#!/usr/bin/env bash
# Deploy Unclaimed to AWS (us-east-1) with Amazon ECS Express Mode (Fargate + a managed
# load balancer). Two public services:
#   unclaimed-mcp        the MCP server (port 8080), with the engine as a sidecar in the same
#                        task: the engine is reachable only on localhost, never from outside
#   unclaimed-simulator  the Alexa+ simulator (port 8090); the only part allowed to call Bedrock
# Idempotent: creates what's missing, otherwise rolls out new images.
#
# Run from the repo root, in WSL, with AWS credentials (e.g. AWS_PROFILE=alexa-ai-user) and
# Docker running:  bash infra/deploy.sh
set -euo pipefail

REGION=${AWS_REGION:-us-east-1}
export AWS_REGION=$REGION AWS_PAGER=""
AWS=${AWS:-aws}
# Docker: in WSL without Docker Desktop's integration, `docker` is a stub; Windows' docker.exe works.
# SKIP_BUILD=1 reuses the images already pushed for this commit (no Docker needed).
if [ -z "${SKIP_BUILD:-}" ]; then
  # In WSL without Docker Desktop's integration, `docker` is a stub; Windows' docker.exe works.
  if [ -z "${DOCKER:-}" ]; then
    if docker version >/dev/null 2>&1; then DOCKER=docker; else DOCKER=docker.exe; fi
  fi
  $DOCKER version >/dev/null || { echo "Docker isn't running"; exit 1; }
fi
ACCOUNT=$($AWS sts get-caller-identity --query Account --output text)
REGISTRY=$ACCOUNT.dkr.ecr.$REGION.amazonaws.com
TAG=$(git rev-parse --short HEAD)$(git diff --quiet HEAD -- engine mcp-server simulator dictionary || echo -dirty)
CLUSTER=unclaimed
LOGS=/ecs/unclaimed
# Our choices for the public demo, defined once here.
MODEL_ID=${SIMULATOR_MODEL_ID:-us.anthropic.claude-haiku-4-5-20251001-v1:0}
TURNS_PER_IP_PER_HOUR=${TURNS_PER_IP_PER_HOUR:-120}
TURNS_PER_DAY=${TURNS_PER_DAY:-3000}

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
if [ -z "${SKIP_BUILD:-}" ]; then
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
# ECS's own service-linked role (created once per account, on first use of ECS).
$AWS iam get-role --role-name AWSServiceRoleForECS >/dev/null 2>&1 || {
  $AWS iam create-service-linked-role --aws-service-name ecs.amazonaws.com >/dev/null
  sleep 15  # IAM is eventually consistent: new roles take a moment to be usable
}
$AWS logs create-log-group --log-group-name "$LOGS" 2>/dev/null || true
$AWS logs put-retention-policy --log-group-name "$LOGS" --retention-in-days 14
$AWS ecs create-cluster --cluster-name "$CLUSTER" >/dev/null

service_arn() { $AWS ecs list-services --cluster "$CLUSTER" --query "serviceArns[?ends_with(@, '/$1')] | [0]" --output text; }
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
     \"healthCheck\": {\"command\": [\"CMD-SHELL\", \"python -c \\\"import urllib.request,json,sys; sys.exit(0 if json.load(urllib.request.urlopen('http://localhost:8000/health'))['ready'] else 1)\\\"\"],
                      \"interval\": 10, \"timeout\": 5, \"retries\": 3, \"startPeriod\": 120},
     \"logConfiguration\": {\"logDriver\": \"awslogs\", \"options\": {\"awslogs-group\": \"$LOGS\", \"awslogs-region\": \"$REGION\", \"awslogs-stream-prefix\": \"engine\"}}},
    {\"name\": \"Main\", \"image\": \"$REGISTRY/unclaimed-mcp:$TAG\", \"essential\": true,
     \"portMappings\": [{\"containerPort\": 8080, \"name\": \"mcp\", \"protocol\": \"tcp\"}],
     \"environment\": [{\"name\": \"ENGINE_URL\", \"value\": \"http://localhost:8000\"}, {\"name\": \"TRUSTED_PROXIES\", \"value\": \"1\"}],
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
MCP_URL="$(endpoint "$MCP_ARN")/mcp"

say "Simulator"
SIM_CONTAINER="{\"image\": \"$REGISTRY/unclaimed-simulator:$TAG\", \"containerPort\": 8090,
  \"awsLogsConfiguration\": {\"logGroup\": \"$LOGS\", \"logStreamPrefix\": \"simulator\"},
  \"environment\": [{\"name\": \"MCP_URL\", \"value\": \"$MCP_URL\"}, {\"name\": \"SIMULATOR_MODEL_ID\", \"value\": \"$MODEL_ID\"},
                    {\"name\": \"TURNS_PER_IP_PER_HOUR\", \"value\": \"$TURNS_PER_IP_PER_HOUR\"}, {\"name\": \"TURNS_PER_DAY\", \"value\": \"$TURNS_PER_DAY\"}]}"
SIM_ARN=$(service_arn unclaimed-simulator)
if [ "$SIM_ARN" = "None" ]; then
  SIM_ARN=$($AWS ecs create-express-gateway-service --cluster "$CLUSTER" --service-name unclaimed-simulator \
    --execution-role-arn "$EXEC_ROLE" --infrastructure-role-arn "$INFRA_ROLE" --task-role-arn "$SIM_ROLE" \
    --primary-container "$SIM_CONTAINER" --cpu 512 --memory 1024 --health-check-path /health \
    --scaling-target minTaskCount=1,maxTaskCount=1 --query service.serviceArn --output text)
else
  $AWS ecs update-express-gateway-service --service-arn "$SIM_ARN" --primary-container "$SIM_CONTAINER" >/dev/null
fi

say "Done (services take a few minutes to become healthy)"
echo "MCP server: $MCP_URL"
echo "Simulator:  $(endpoint "$SIM_ARN")"
