# infra

AWS deployment (us-east-1) with **Amazon ECS Express Mode** (Fargate behind a managed load balancer; App Runner no longer takes new customers). `deploy.sh` is the whole setup, idempotent: it creates what's missing and otherwise rolls out new images.

| Service | What runs | Public? |
|---|---|---|
| `unclaimed-mcp` | the MCP server (`Main`) with the engine as a sidecar in the same task, listening on localhost only | the MCP endpoint is public (Alexa+ needs it); the engine is not reachable from outside |
| `unclaimed-simulator` | the Alexa+ simulator (port 8090) | public, rate limited; the only part allowed to call Bedrock, and only the one model it uses |

Also created: ECR repositories (scan on push, last 5 images kept), IAM roles (task execution, Express infrastructure, the simulator's Bedrock-only task role, and the service-linked roles for ECS, load balancing and autoscaling), CloudWatch logs (`/ecs/unclaimed`, 14 days). No sign-in, no database, nothing about the person stored.

```bash
AWS_PROFILE=alexa-ai-user bash infra/deploy.sh               # build, push, deploy (Docker running)
AWS_PROFILE=alexa-ai-user SKIP_BUILD=1 bash infra/deploy.sh  # redeploy the images already pushed (named by the last commit that changed the app)
```

The simulator's settings (model, limits) come from `simulator/simulator/defaults.env`; any of them can be overridden in the environment when deploying.

Cost: both services always run one task (the engine's cold start is seconds long), plus the load balancer; Bedrock is pay per use, capped by the simulator's daily token budget. The `unclaimed-monthly-25` budget emails at 50/80/100% of $25 of real spend.
