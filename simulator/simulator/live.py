"""Alexa's live voice: Amazon Nova 2 Sonic, a speech-to-speech model on Bedrock, hears the
person and answers out loud in one stream (no speech-to-text, text model and text-to-speech
in a row), calling the Unclaimed MCP server's tools as it goes. A Strands BidiAgent runs it;
the page streams the microphone in over a WebSocket and plays the voice that comes back.

The device keeps the household draft for the open conversation, as Alexa+ keeps a
conversation's context: each tool's `household` argument is filled in here from the last
result, so the model never has to copy it, and the MCP server stays stateless. The page gets
the draft too, so a conversation that rested after a silence can carry on after "Alexa";
nothing is kept here once the connection closes.

Public and free for judges, so conversations are limited (Nova Sonic bills by the audio
token): open at once (in all, and per client), started per client per hour, minutes per day
(in all, and per client), length, and silence; microphone audio may not arrive faster than
real time, nor typed words more than once a second.

The WebSocket protocol (`/api/live`):
  page -> here   first a JSON {"start": {"household"?, "said"?, "screens"?}} (said: the
                 conversation so far as [{"role", "text"}], to carry on; screens: how many
                 the page can go back through); then binary frames of microphone audio
                 (16-bit PCM, mono, 16 kHz), JSON {"text": ...} for typed words, and
                 {"screens": n} when the page's own back button is used.
  here -> page   binary frames of Alexa's voice (16-bit PCM, mono, 24 kHz), and JSON events:
                 heard / said {text, final} (transcripts), interrupted (stop playing: the
                 person cut in), screen {call} (an MCP App to show), household {household},
                 back (the device's back), usage {in, out} (tokens so far, once a turn), end
                 {reason, message?} (then the connection closes).
"""

import asyncio
import base64
import json
import logging
import threading
import time
from collections import defaultdict, deque

from fastapi import WebSocket, WebSocketDisconnect
from strands.experimental.bidi import BidiAgent
from strands.experimental.bidi.models.bedrock import BedrockNovaSonicModel
from strands.experimental.bidi.types.media import AudioDelta
from strands.tools.tools import PythonAgentTool

from . import agent
from .settings import setting

log = logging.getLogger("unclaimed.simulator")

SONIC_MODEL_ID = setting("SONIC_MODEL_ID")
SONIC_VOICE = setting("SONIC_VOICE")
AT_ONCE = int(setting("LIVE_AT_ONCE"))
PER_IP_AT_ONCE = int(setting("LIVE_PER_IP_AT_ONCE"))
PER_IP_PER_HOUR = int(setting("LIVE_PER_IP_PER_HOUR"))
MINUTES_PER_DAY = int(setting("LIVE_MINUTES_PER_DAY"))
PER_IP_MINUTES_PER_DAY = int(setting("LIVE_PER_IP_MINUTES_PER_DAY"))
MAX_MINUTES = int(setting("LIVE_MAX_MINUTES"))
QUIET_SECONDS = int(setting("LIVE_QUIET_SECONDS"))
IN_RATE, OUT_RATE = 16000, 24000
MAX_FRAME = 32_000  # bytes of audio per frame: 1 s at 16 kHz; the page sends 32 ms
MAX_TEXT = 600
MAX_SAID = 40  # transcript lines carried into a resumed conversation
MAX_START_BYTES = 64_000
START_SECONDS = 20  # the page's start message and the model's connection
AUDIO_PACE = 1.25  # microphone audio may run this much faster than real time (network jitter)

# Only what's specific to this device, first so it frames the rest; who Alexa is and how the
# screening runs are shared with the text pipeline (agent.SYSTEM_PROMPT's files).
DEVICE = """Most important, on this device:
- You're speaking out loud: keep each turn to one or two short sentences, about 25 words, then stop and listen. Never read out a question's clarifiers or option lists; use them only if the person seems unsure.
- Never ask them to confirm or repeat what they've said, and never ask about the details in a question's definition (before taxes, before housing help): take their words as the answer, call `answer` right away, and ask the next question. Anything they already told you, even before you asked, is answered: record it and don't ask it.
- Results, every time (also after checking the maybes), even when there are many: say how many programs they likely qualify for, name at most two with their amounts, then the maybes in a few words, and ask one question. The screen lists the rest. Never add amounts up or estimate a total.
- When they say yes to checking the maybes, call `check_programs` right away with the ids of the programs whose status is "maybe", and ask the question it returns.
- Never say the same thing twice: if you've already told them their results, don't repeat them; answer what they just asked.
- The device keeps the household draft: the tools don't take it, so just call them with the new information.
- If a tool returns an error, fix the call and try again; if it fails again, say sorry, something went wrong, and ask them to try again in a little while. Never talk about tools.
- A plan: one sentence with the first way to apply and one thing to have ready, then offer the next program; the screen and its code have the rest.
- When they ask to go back (to the results or the previous screen), call `go_back` and say only "Sure." Don't repeat what you said before.
"""

_lock = threading.Lock()
_open: dict[str, int] = defaultdict(int)  # open conversations, per client
_hits: dict[str, deque] = defaultdict(deque)  # conversations started in the last hour, per client
_day = {"date": time.strftime("%Y-%m-%d"), "all": 0.0, "by_ip": defaultdict(float)}  # seconds talked today

END = {  # why a conversation ended, said to the person (none: the page explains it)
    "limit": "That's all the time the demo has for today. Please try again tomorrow.",
    "error": "Alexa lost the connection. Tap the mic to try again.",
}


def _today() -> None:
    if _day["date"] != time.strftime("%Y-%m-%d"):
        _day.update(date=time.strftime("%Y-%m-%d"), all=0.0, by_ip=defaultdict(float))


def admit(ip: str) -> str | None:
    """None if a new conversation may start, else why not (said to the person)."""
    now = time.time()
    with _lock:
        _today()
        if _day["all"] >= MINUTES_PER_DAY * 60 or _day["by_ip"][ip] >= PER_IP_MINUTES_PER_DAY * 60:
            return END["limit"]
        if sum(_open.values()) >= AT_ONCE:
            return "Alexa is busy with other visitors. Please try again in a minute."
        if _open[ip] >= PER_IP_AT_ONCE:
            return "Alexa is already talking with you in another tab."
        for stale in [k for k, h in _hits.items() if h[-1] < now - 3600]:
            del _hits[stale]
        hits = _hits[ip]
        while hits and hits[0] < now - 3600:
            hits.popleft()
        if len(hits) >= PER_IP_PER_HOUR:
            return "That's a lot of conversations for one hour. Please try again a bit later."
        hits.append(now)
        _open[ip] += 1
    return None


def _release(ip: str) -> None:
    with _lock:
        _open[ip] -= 1
        if not _open[ip]:
            del _open[ip]


def _spend(ip: str, seconds: float) -> bool:
    """Count conversation time against the day; False once the day's minutes (everyone's, or
    this client's) are used."""
    with _lock:
        _today()
        _day["all"] += seconds
        _day["by_ip"][ip] += seconds
        return _day["all"] < MINUTES_PER_DAY * 60 and _day["by_ip"][ip] < PER_IP_MINUTES_PER_DAY * 60


class Conversation:
    """One open conversation: the household draft, and the events for the page."""

    def __init__(self, household: dict | None):
        self.household = household
        self.events: asyncio.Queue = asyncio.Queue()
        self.screens = 0  # screens on the page's back stack

    def tools(self) -> list:
        """The MCP server's tools as the model sees them (without `household`), plus the
        device's back."""
        try:
            listed = agent._connect()
        except Exception:
            agent._reset()  # reconnect on the next conversation
            raise
        return [self._wrap(agent._client(), t) for t in listed] + [self._back()]

    def _wrap(self, client, mcp_tool) -> PythonAgentTool:
        spec = json.loads(json.dumps(mcp_tool.tool_spec))
        schema = spec["inputSchema"]["json"]
        takes_household = "household" in schema.get("properties", {})
        if takes_household:
            del schema["properties"]["household"]
            schema["required"] = [r for r in schema.get("required", []) if r != "household"]
            if "$ref" not in json.dumps(schema):
                schema.pop("$defs", None)  # only the household's schema used them
        uri = agent.ui_uri(mcp_tool)
        name = mcp_tool.tool_name

        async def run(tool_use, **_):
            args = dict(tool_use["input"])
            if takes_household:
                if self.household is None:
                    return _error(tool_use, "No screening yet: call start_screening first.")
                args["household"] = self.household
            t = time.monotonic()
            result = await client.call_tool_async(tool_use_id=tool_use["toolUseId"], name=name, arguments=args)
            log.info("live tool=%s status=%s ms=%d", name, result["status"], (time.monotonic() - t) * 1000)
            data = dict(result.get("structuredContent") or {})
            if result["status"] == "error" or not data:
                return {"toolUseId": tool_use["toolUseId"], "status": result["status"], "content": result["content"]}
            if "household" in data:
                self.household = data.pop("household")
                await self.events.put({"type": "household", "household": self.household})
            if uri:
                full = result["structuredContent"]
                self.screens += 1
                await self.events.put({"type": "screen", "call": {
                    "id": tool_use["toolUseId"], "uri": uri, "name": name, "input": args,
                    "result": {"content": [{"type": "text", "text": json.dumps(full)}], "structuredContent": full}}})
            return {"toolUseId": tool_use["toolUseId"], "status": "success", "content": [{"text": json.dumps(data)}]}

        return PythonAgentTool(name, spec, run)

    def _back(self) -> PythonAgentTool:
        async def run(tool_use, **_):
            if not self.screens:
                said = "Nothing to go back to: no screen is showing yet."
            else:
                self.screens -= 1
                await self.events.put({"type": "back"})
                said = "The previous screen is showing." if self.screens else "The screen is cleared."
            return {"toolUseId": tool_use["toolUseId"], "status": "success", "content": [{"text": said}]}

        spec = {"name": "go_back", "description": "Show the previous screen (e.g. from a plan back to the results).",
                "inputSchema": {"json": {"type": "object", "properties": {}}}}
        return PythonAgentTool("go_back", spec, run)


def _error(tool_use, text: str) -> dict:
    return {"toolUseId": tool_use["toolUseId"], "status": "error", "content": [{"text": text}]}


def _history(said) -> list[dict]:
    """The conversation so far, as text turns (a resumed conversation's context): starting
    with the person, one turn per speaker in a row."""
    turns = []
    for s in (said or [])[-MAX_SAID:] if isinstance(said, list) else []:
        if not (isinstance(s, dict) and s.get("role") in ("user", "assistant") and isinstance(s.get("text"), str)):
            continue
        if not turns and s["role"] == "assistant":
            continue
        if turns and turns[-1]["role"] == s["role"]:
            turns[-1]["content"][0]["text"] += " " + s["text"][:MAX_TEXT]
        else:
            turns.append({"role": s["role"], "content": [{"text": s["text"][:MAX_TEXT]}]})
    return turns


def make_agent(conversation: Conversation, said) -> BidiAgent:
    model = BedrockNovaSonicModel(model_id=SONIC_MODEL_ID, region=agent.REGION or "us-east-1", voice=SONIC_VOICE,
                                  audio={"input": {"sample_rate": IN_RATE}, "output": {"sample_rate": OUT_RATE}})
    return BidiAgent(model=model, tools=conversation.tools(), system_prompt=DEVICE + "\n" + agent.SYSTEM_PROMPT,
                     messages=_history(said))


async def serve(ws: WebSocket, ip: str) -> None:
    await ws.accept()
    refused = admit(ip)
    if refused:
        await ws.send_json({"type": "end", "reason": "limit", "message": refused})
        return await ws.close()
    try:
        await _converse(ws, ip)
    finally:
        _release(ip)


async def _start(ws: WebSocket, held: dict) -> Conversation:
    """The page's start message, then the model's connection (held, so it's closed even if
    starting fails or takes too long)."""
    first = await ws.receive_text()
    if len(first) > MAX_START_BYTES:
        raise ValueError("start too large")
    start = json.loads(first)["start"]
    household = start.get("household")
    conversation = Conversation(household if isinstance(household, dict) else None)
    conversation.screens = _count(start.get("screens"))
    held["bidi"] = await asyncio.to_thread(make_agent, conversation, start.get("said"))
    await held["bidi"].start()
    return conversation


def _count(n) -> int:
    return min(max(n, 0), 100) if isinstance(n, int) and not isinstance(n, bool) else 0


async def _converse(ws: WebSocket, ip: str) -> None:
    started, usage, held, reason = time.monotonic(), {}, {}, "closed"
    try:
        try:
            conversation = await asyncio.wait_for(_start(ws, held), START_SECONDS)
        except WebSocketDisconnect:
            return
        except Exception as e:  # a bad start message, or the model or MCP server didn't answer in time
            log.error("live start failed: %s", type(e).__name__)
            reason = "error"
            return await _end(ws, reason)
        bidi = held["bidi"]
        heard = [time.monotonic()]  # when the person (or Alexa) last made a sound

        async def from_page():
            audio, typed = 0, 0.0  # microphone bytes so far; when words were last typed
            while True:
                m = await ws.receive()
                if m["type"] == "websocket.disconnect":
                    return "closed"
                if m.get("bytes"):
                    # A live microphone sends in real time; faster audio (which Bedrock
                    # bills) is dropped, as are odd or oversized frames.
                    audio += len(m["bytes"])
                    if len(m["bytes"]) <= MAX_FRAME and len(m["bytes"]) % 2 == 0 and \
                            audio <= (time.monotonic() - started + 2) * IN_RATE * 2 * AUDIO_PACE:
                        await bidi.send(AudioDelta(format="pcm", source={"bytes": m["bytes"]}))
                elif m.get("text"):
                    message = json.loads(m["text"])
                    if "screens" in message:  # the page's own back button
                        conversation.screens = _count(message["screens"])
                    text = str(message.get("text", "")).strip()[:MAX_TEXT]
                    if text and time.monotonic() - typed >= 1:  # at most one typed line a second
                        typed = heard[0] = time.monotonic()
                        await bidi.send(text)

        async def from_alexa():
            async for e in bidi.receive():
                kind = e.get("type")
                if kind == "bidi_audio_delta":
                    heard[0] = time.monotonic()
                    await ws.send_bytes(base64.b64decode(e["audio"]))
                elif kind in ("bidi_transcript_delta", "bidi_transcript_stop"):
                    if e["role"] == "user":
                        heard[0] = time.monotonic()
                    final = kind == "bidi_transcript_stop"
                    await ws.send_json({"type": "heard" if e["role"] == "user" else "said",
                                        "text": e["transcript"] if final else e["delta"], "final": final})
                elif kind == "bidi_barge_in":
                    await ws.send_json({"type": "interrupted"})
                elif kind == "bidi_usage":
                    usage.update({"in": e["inputTokens"], "out": e["outputTokens"]})  # cumulative
                elif kind == "bidi_response_stop" and usage:
                    await ws.send_json({"type": "usage", **usage})  # once a turn, for the evaluations
                elif kind == "bidi_connection_stop":
                    return "closed"

        async def to_page():
            while True:
                await ws.send_json(await conversation.events.get())

        async def clock():
            while True:
                await asyncio.sleep(1)
                if not _spend(ip, 1):
                    return "limit"
                if time.monotonic() - started > MAX_MINUTES * 60:
                    return "long"
                if time.monotonic() - heard[0] > QUIET_SECONDS:
                    return "quiet"

        tasks = [asyncio.create_task(c()) for c in (from_page, from_alexa, to_page, clock)]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            task = done.pop()
            failed = task.exception()
            reason = "closed" if isinstance(failed, WebSocketDisconnect) else "error" if failed else task.result()
            if reason == "error":
                log.error("live failed: %s", type(failed).__name__)
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        if reason != "closed":
            await _end(ws, reason)
    finally:
        if "bidi" in held:
            try:
                await held["bidi"].stop()
            except Exception:
                pass
        # Never the conversation itself: how long, why it ended, and the tokens Bedrock billed.
        log.info("live s=%d end=%s tokens_in=%s tokens_out=%s", time.monotonic() - started, reason,
                 usage.get("in"), usage.get("out"))


async def _end(ws: WebSocket, reason: str) -> None:
    try:
        await ws.send_json({"type": "end", "reason": reason, **({"message": END[reason]} if reason in END else {})})
        await ws.close()
    except Exception:
        pass  # the page is already gone
