# simulator

A web stand-in for Alexa+ (the Alexa+ add-on tools are partner-only): an Echo Show-style page where you talk with Alexa live. **Amazon Nova 2 Sonic** on Bedrock, a speech-to-speech model run by a **Strands BidiAgent**, hears you and answers out loud in one stream, calling the Unclaimed MCP server over Streamable HTTP the way Alexa+ calls an add-on. There's no speech-to-text, text model and text-to-speech chain, so Alexa starts answering a couple of seconds after you finish, and you can cut in while she talks.

It is hands-free after one tap (browsers allow the mic and sound only after one). After some quiet the conversation rests: a live conversation costs by the minute. The device then waits for the wake word ("Alexa" or "Hey Alexa") and carries on where it left off. The wake word is spotted by the browser's speech recognition, which in Chrome and Edge sends the audio to the browser maker's speech service while the conversation rests; nothing is kept by Unclaimed either way.

- `simulator/live.py`: the live conversation (WebSocket `/api/live`; the protocol is in its docstring). The device keeps the household draft for the open conversation and fills in each tool's `household` argument, so the model never copies it and the MCP server stays stateless. Also: the device's `go_back`, and the limits (open at once and minutes per day, in all and per client; conversations per client per hour; length; silence; microphone audio no faster than real time).
- `simulator/agent.py`: the client to the MCP server and its screens, and Alexa's instructions: `simulator/voice.md` (who Alexa is, how to speak; shared with the research baselines) and `simulator/prompt.md` (how to run the screening with our tools; no program rules: those come from the tools). Also the text pipeline (`turn`: a Strands agent on a Bedrock text model, one turn at a time), which the research evaluations use.
- `simulator/defaults.env`: the settings (models, voice, limits), defined once; the environment overrides them.
- `simulator/app.py`: FastAPI. `GET /` the page, `GET /api/screens` the MCP server's screens, and the live WebSocket.
- `simulator/static/`: the page. It streams the microphone (16 kHz PCM, from an AudioWorklet) and plays Alexa's voice (24 kHz PCM) as it arrives, and hosts the MCP App screens. Voice works in current browsers; the wake word needs Chrome or Edge, and typing works everywhere.

## Run locally

The engine and MCP server must be running (see their READMEs). Python 3.12+. AWS credentials with Bedrock access to Nova 2 Sonic, in a region that has it (e.g. `AWS_PROFILE` and `AWS_REGION=us-east-1`).

```bash
uv sync
MCP_URL=http://localhost:8080/mcp uv run uvicorn simulator.app:app --port 8090   # open http://localhost:8090
```

The page shows how long Alexa took to start answering. The log has each tool call's time and each conversation's length and tokens, never what was said.
