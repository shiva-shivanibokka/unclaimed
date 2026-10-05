#!/usr/bin/env bash
# Deploy Unclaimed to AWS (us-east-1) with Amazon ECS Express Mode (Fargate + a managed
# load balancer). Two public services:
#   unclaimed-mcp        the MCP server, with the engine as a sidecar in the same
#                        task: the engine is reachable only on localhost, never from outside
#   unclaimed-simulator  the Alexa+ simulator; the only part allowed to call Bedrock
# Idempotent: creates what's missing, otherwise rolls out new images.
#
# Run from the repo root, in WSL, with AWS credentials (e.g. AWS_PROFILE=alexa-ai-user) and
# Docker running:  bash infra/deploy.sh
set -euo pipefail

REGION=${AWS_REGION:-us-east-1}
export AWS_REGION=$REGION AWS_PAGER=""
AWS=${AWS:-aws}
# SKIP_BUILD=1 reuses the images already pushed (no Docker needed).
if [ -z "${SKIP_BUILD:-}" ]; then
  # In WSL without Docker Desktop's integration, `docker` is a stub; Windows' docker.exe works.
  if [ -z "${DOCKER:-}" ]; then
    if docker version >/dev/null 2>&1; then DOCKER=docker; else DOCKER=docker.exe; fi
  fi
  $DOCKER version >/dev/null || { echo "Docker isn't running"; exit 1; }
fi
ACCOUNT=$($AWS sts get-caller-identity --query Account --output text)
REGISTRY=$ACCOUNT.dkr.ecr.$REGION.amazonaws.com
# Images are named by the last commit that changed what's in them, so an infra-only commit
# reuses the images already pushed. Uncommitted changes (new files too) make it "-dirty".
APP="engine mcp-server simulator dictionary plans .dockerignore"
TAG=$(git log -1 --format=%h -- $APP)$([ -z "$(git status --porcelain -- $APP)" ] || echo -dirty)
CLUSTER=unclaimed
LOGS=/ecs/unclaimed
# Ports the containers listen on (each image's default; the engine's is overridden to localhost).
ENGINE_PORT=8000 MCP_PORT=8080 SIM_PORT=8090
# The simulator's settings (model, limits): its defaults file, unless set in the environment.
SIM_SETTINGS=simulator/simulator/defaults.env
SIM_ENV=""
while IFS='=' read -r k v; do
  case "$k" in ''|\#*) continue ;; esac
  v=${!k:-$v}
  printf -v "$k" '%s' "$v"
  SIM_ENV="$SIM_ENV, {\"name\": \"$k\", \"value\": \"$v\"}"
done < "$SIM_SETTINGS"
MODEL_ID=$SIMULATOR_MODEL_ID

say() { printf '\n== %s\n' "$*"; }

say "ECR repositories and images ($TAG)"
[ -n "${SKIP_BUILD:-}" ] || $AWS ecr get-login-password | $DOCKER login --username AWS --password-stdin "$REGISTRY" >/dev/null
for name in engine mcp simulator; do
  repo=unclaimed-$name
  $AWS ecr describe-repositories --repository-names "$repo" >/dev/null 2>&1 ||
    $AWS ecr create-repository --repository-name "$repo" --image-scanning-configuration scanOnPush=true >/dev/null
  # Keep the last 5 images (storage costs money; older ones aren't needed to roll back a demo).
  $AWS ecr put-lifecycle-policy --repository-name "$repo" --lifecycle-policy-text \
    '{"rules":[{"rulePriority":1,"selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":5},"action":{"type":"expire"}}]}' >/dev/null
done
if [ -n "${SKIP_BUILD:-}" ]; then
  for name in engine mcp simulator; do
    $AWS ecr describe-images --repository-name "unclaimed-$name" --image-ids imageTag="$TAG" >/dev/null 2>&1 ||
      { echo "unclaimed-$name:$TAG isn't in ECR: build it (run without SKIP_BUILD)"; exit 1; }
  done
else
  $DOCKER build --platform linux/amd64 -f engine/Dockerfile -t "$REGISTRY/unclaimed-engine:$TAG" .
  $DOCKER build --platform linux/amd64 -t "$REGISTRY/unclaimed-mcp:$TAG" mcp-server
  $DOCKER build --platform linux/amd64 -t "$REGISTRY/unclaimed-simulator:$TAG" simulator
  for name in engine mcp simulator; do $DOCKER push "$REGISTRY/unclaimed-$name:$TAG" >/dev/null; done
fi

say "IAM roles"
role() {  # role NAME SERVICE_PRINCIPAL [MANAGED_POLICY_ARN]
  if ! $AWS iam get-role --role-name "$1" >/dev/null 2>&1; then
    $AWS iam create-role --role-name "$1" --assume-role-policy-document \
      "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Principal\":{\"Service\":\"$2\"},\"Action\":\"sts:AssumeRole\"}]}" >/dev/null
  fi
  [ -n "${3:-}" ] && $AWS iam attach-role-policy --role-name "$1" --policy-arn "$3"
  $AWS iam get-role --role-name "$1" --query Role.Arn --output text
}
EXEC_ROLE=$(role ecsTaskExecutionRole ecs-tasks.amazonaws.com arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy)
INFRA_ROLE=$(role ecsInfrastructureRoleForExpressServices ecs.amazonaws.com arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices)
SIM_ROLE=$(role unclaimed-simulator-task ecs-tasks.amazonaws.com)
# The simulator may call only the one model it uses (a US cross-region inference profile
# routes to the model in several US regions).
MODEL_NAME=${MODEL_ID#us.}
$AWS iam put-role-policy --role-name unclaimed-simulator-task --policy-name bedrock-invoke --policy-document "{
  \"Version\": \"2012-10-17\",
  \"Statement\": [{\"Effect\": \"Allow\", \"Action\": [\"bedrock:InvokeModel\", \"bedrock:InvokeModelWithResponseStream\"],
    \"Resource\": [\"arn:aws:bedrock:$REGION:$ACCOUNT:inference-profile/$MODEL_ID\", \"arn:aws:bedrock:*::foundation-model/$MODEL_NAME\"]}]
}"
# Alexa's voice (Amazon Polly; speech synthesis has no resource to scope to).
$AWS iam put-role-policy --role-name unclaimed-simulator-task --policy-name polly-speak --policy-document \
  '{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "polly:SynthesizeSpeech", "Resource": "*"}]}'
# Service-linked roles ECS, the load balancer and autoscaling need (once per account).
# Created up front: if Express Mode creates them itself, its first load balancer can race
# the new role and fail (seen on this account's first deploy).
created=""
for svc in ecs:AWSServiceRoleForECS elasticloadbalancing:AWSServiceRoleForElasticLoadBalancing            ecs.application-autoscaling:AWSServiceRoleForApplicationAutoScaling_ECSService; do
  $AWS iam get-role --role-name "${svc#*:}" >/dev/null 2>&1 ||
    { $AWS iam create-service-linked-role --aws-service-name "${svc%%:*}.amazonaws.com" >/dev/null; created=1; }
done
[ -n "$created" ] && sleep 20  # IAM is eventually consistent: new roles take a moment to be usable
$AWS logs create-log-group --log-group-name "$LOGS" 2>/dev/null || true
$AWS logs put-retention-policy --log-group-name "$LOGS" --retention-in-days 14
$AWS ecs create-cluster --cluster-name "$CLUSTER" >/dev/null

service_arn() { $AWS ecs list-services --cluster "$CLUSTER" --query "serviceArns[?ends_with(@, '/$1')] | [0]" --output text; }
# Express Mode rolls a release back when its error-rate alarm fires, and that alarm counts
# the "not found" answers internet scanners get on any public URL (it rolled back a healthy
# release on Oct 1). Only that trigger is turned off: failed health checks still roll back.
no_alarm_rollback() {
  local alarm
  alarm=$($AWS ecs describe-services --cluster "$CLUSTER" --services "$1"     --query 'services[0].deploymentConfiguration.alarms.alarmNames[0]' --output text)
  [ "$alarm" != "None" ] || return 0  # a brand-new service may not have it yet: next deploy
  $AWS ecs update-service --cluster "$CLUSTER" --service "$1"     --deployment-configuration "alarms={alarmNames=[$alarm],enable=false,rollback=false}" >/dev/null
}
endpoint() {  # https URL of a service (AWS returns the host, sometimes with a scheme)
  local host
  host=$($AWS ecs describe-express-gateway-service --service-arn "$1" \
    --query 'service.activeConfigurations[0].ingressPaths[0].endpoint' --output text)
  echo "https://${host#https://}"
}

say "MCP server + engine (one task: the engine is a localhost-only sidecar)"
TASKDEF=$($AWS ecs register-task-definition --family unclaimed-mcp --requires-compatibilities FARGATE \
  --network-mode awsvpc --cpu 1024 --memory 3072 --execution-role-arn "$EXEC_ROLE" \
  --container-definitions "[
    {\"name\": \"engine\", \"image\": \"$REGISTRY/unclaimed-engine:$TAG\", \"essential\": true,
     \"environment\": [{\"name\": \"UVICORN_HOST\", \"value\": \"127.0.0.1\"}, {\"name\": \"UVICORN_PORT\", \"value\": \"$ENGINE_PORT\"}],
     \"healthCheck\": {\"command\": [\"CMD-SHELL\", \"python -c \\\"import urllib.request,json,sys; sys.exit(0 if json.load(urllib.request.urlopen('http://127.0.0.1:$ENGINE_PORT/health'))['ready'] else 1)\\\"\"],
                      \"interval\": 10, \"timeout\": 5, \"retries\": 3, \"startPeriod\": 120},
     \"logConfiguration\": {\"logDriver\": \"awslogs\", \"options\": {\"awslogs-group\": \"$LOGS\", \"awslogs-region\": \"$REGION\", \"awslogs-stream-prefix\": \"engine\"}}},
    {\"name\": \"Main\", \"image\": \"$REGISTRY/unclaimed-mcp:$TAG\", \"essential\": true,
     \"portMappings\": [{\"containerPort\": $MCP_PORT, \"name\": \"mcp\", \"protocol\": \"tcp\"}],
     \"environment\": [{\"name\": \"ENGINE_URL\", \"value\": \"http://127.0.0.1:$ENGINE_PORT\"}, {\"name\": \"PORT\", \"value\": \"$MCP_PORT\"}, {\"name\": \"TRUSTED_PROXIES\", \"value\": \"1\"}],
     \"dependsOn\": [{\"containerName\": \"engine\", \"condition\": \"HEALTHY\"}],
     \"logConfiguration\": {\"logDriver\": \"awslogs\", \"options\": {\"awslogs-group\": \"$LOGS\", \"awslogs-region\": \"$REGION\", \"awslogs-stream-prefix\": \"mcp\"}}}
  ]" --query taskDefinition.taskDefinitionArn --output text)
MCP_ARN=$(service_arn unclaimed-mcp)
if [ "$MCP_ARN" = "None" ]; then
  MCP_ARN=$($AWS ecs create-express-gateway-service --cluster "$CLUSTER" --service-name unclaimed-mcp \
    --infrastructure-role-arn "$INFRA_ROLE" --task-definition-arn "$TASKDEF" --health-check-path /health \
    --scaling-target minTaskCount=1,maxTaskCount=2 --query service.serviceArn --output text)
else
  $AWS ecs update-express-gateway-service --service-arn "$MCP_ARN" --task-definition-arn "$TASKDEF" >/dev/null
fi
no_alarm_rollback unclaimed-mcp
MCP_URL="$(endpoint "$MCP_ARN")/mcp"

say "Simulator"
SIM_CONTAINER="{\"image\": \"$REGISTRY/unclaimed-simulator:$TAG\", \"containerPort\": $SIM_PORT,
  \"awsLogsConfiguration\": {\"logGroup\": \"$LOGS\", \"logStreamPrefix\": \"simulator\"},
  \"environment\": [{\"name\": \"MCP_URL\", \"value\": \"$MCP_URL\"}$SIM_ENV]}"
SIM_ARN=$(service_arn unclaimed-simulator)
if [ "$SIM_ARN" = "None" ]; then
  SIM_ARN=$($AWS ecs create-express-gateway-service --cluster "$CLUSTER" --service-name unclaimed-simulator \
    --execution-role-arn "$EXEC_ROLE" --infrastructure-role-arn "$INFRA_ROLE" --task-role-arn "$SIM_ROLE" \
    --primary-container "$SIM_CONTAINER" --cpu 512 --memory 1024 --health-check-path /health \
    --scaling-target minTaskCount=1,maxTaskCount=1 --query service.serviceArn --output text)
else
  $AWS ecs update-express-gateway-service --service-arn "$SIM_ARN" --primary-container "$SIM_CONTAINER" >/dev/null
fi

no_alarm_rollback unclaimed-simulator

say "Done (services take a few minutes to become healthy)"
echo "MCP server: $MCP_URL"
echo "Simulator:  $(endpoint "$SIM_ARN")"
