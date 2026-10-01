# infra

AWS deployment (us-east-1) with **Amazon ECS Express Mode** (Fargate behind a managed load balancer; App Runner no longer takes new customers). `deploy.sh` is the whole setup, idempotent: it creates what's missing and otherwise rolls out new images.

| Service | What runs | Public? |
|---|---|---|
| `unclaimed-mcp` | the MCP server (`Main`, port 8080) with the engine as a sidecar in the same task (localhost:8000 only) | the MCP endpoint is public (Alexa+ needs it); the engine is not reachable from outside |
| `unclaimed-simulator` | the Alexa+ simulator (port 8090) | public, rate limited; the only part allowed to call Bedrock, and only the one model it uses |

Also created: ECR repositories (scan on push, last 5 images kept), IAM roles (task execution, Express infrastructure, the simulator's Bedrock-only task role, ECS's service-linked role), CloudWatch logs (`/ecs/unclaimed`, 14 days). No sign-in, no database, nothing about the person stored.

```bash
AWS_PROFILE=alexa-ai-user bash infra/deploy.sh               # build, push, deploy (Docker running)
AWS_PROFILE=alexa-ai-user SKIP_BUILD=1 bash infra/deploy.sh  # redeploy the images already pushed for this commit
```

Settings (environment, defaults in `deploy.sh`): `SIMULATOR_MODEL_ID`, `TURNS_PER_IP_PER_HOUR`, `TURNS_PER_DAY`.

Cost: both services always run one task (the engine's cold start is seconds long), plus the load balancer; Bedrock is pay per use, capped by the simulator's daily turn limit. The `unclaimed-monthly-25` budget emails at 50/80/100% of $25 of real spend.
