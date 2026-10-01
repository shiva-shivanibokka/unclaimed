# simulator

A web stand-in for Alexa+ (the Alexa+ add-on tools are partner-only): an Echo Show-style page with push-to-talk (browser speech recognition and speech synthesis), and a **Strands agent on Amazon Bedrock** as the Alexa+ brain, calling the Unclaimed MCP server over Streamable HTTP the way Alexa+ calls an add-on.

- `simulator/agent.py`: the agent (model from `SIMULATOR_MODEL_ID`, MCP server at `MCP_URL`); instructions in `simulator/prompt.md` (how to talk and run the tools; no program rules: those come from the tools)
- `simulator/app.py`: FastAPI. `GET /` the page, `POST /api/turn` one spoken turn. Stateless: the conversation lives in the browser and comes back with each turn; nothing is stored. Public, so every turn is rate limited per client and per day (`TURNS_PER_IP_PER_HOUR`, `TURNS_PER_DAY`), and the history sent back is size-checked and limited to text and tool turns.
- `simulator/static/`: the page (voice needs Chrome or Edge; typing works everywhere).

## Run locally

The engine and MCP server must be running (see their READMEs). AWS credentials with Bedrock access (e.g. `AWS_PROFILE`).

```bash
uv sync
MCP_URL=http://localhost:8080/mcp uv run uvicorn simulator.app:app --port 8090   # open http://localhost:8090
```

Each turn reports its time (model vs tools) on the page and in the log; logs never include what was said.
