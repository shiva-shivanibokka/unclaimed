"""The simulated Alexa+ brain: a Strands agent on Amazon Bedrock that calls the Unclaimed MCP
server over Streamable HTTP, the way Alexa+ calls an add-on's MCP server.

Stateless like Alexa+'s side of an add-on: the conversation lives in the browser and comes
back with every turn; nothing is kept here.
"""

import os
import threading
import time
from pathlib import Path

from strands import Agent
from strands.hooks import BeforeModelCallEvent
from strands.models import BedrockModel
from strands.models.model import CacheConfig
from strands.tools.mcp import MCPClient

from .settings import setting

MODEL_ID = setting("SIMULATOR_MODEL_ID")
REGION = os.environ.get("AWS_REGION")  # None: the AWS profile's region (ECS sets AWS_REGION)
MCP_URL = os.environ.get("MCP_URL", "http://localhost:8080/mcp")
# Caps on one turn's Bedrock use. A spoken reply is a few sentences, but a tool call carries
# the household draft; a turn is normally a tool call or two and a reply.
MAX_TOKENS = 4096
MAX_MODEL_CALLS_PER_TURN = 6
# voice.md: who Alexa is and how to speak (shared with the research baselines, eval/e3.py);
# prompt.md: how to run the screening with our tools.
VOICE = (Path(__file__).parent / "voice.md").read_text(encoding="utf-8")
SYSTEM_PROMPT = VOICE + "\n" + (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")

_lock = threading.Lock()
_mcp: MCPClient | None = None


def _client() -> MCPClient:
    """One long-lived client to the MCP server (reconnects after a failure)."""
    global _mcp
    with _lock:
        if _mcp is None:
            _mcp = MCPClient(url=MCP_URL)
            _mcp.start()
        return _mcp


def _connect() -> list:
    """The MCP server's tools, listed fresh for every turn: a deploy of the MCP server can
    change them while this service keeps running."""
    return _client().list_tools_sync()


def screens() -> dict:
    """Which tools show a screen, and each screen's HTML, as the MCP server declares them
    (tool `_meta.ui.resourceUri`, read with resources/read). Read on every page load, for
    the same reason as the tools. The browser hosts them."""
    try:
        client = _client()
        uris = {t.tool_name: ((t.mcp_tool.meta or {}).get("ui") or {}).get("resourceUri") for t in _connect()}
        uris = {name: uri for name, uri in uris.items() if uri}
        html = {}
        for uri in set(uris.values()):
            content = client.read_resource_sync(uri).contents[0]
            html[uri] = {"html": content.text, "meta": (content.meta or {}).get("ui", {})}
    except Exception:
        _reset()  # reconnect on the next call
        raise
    return {"tools": uris, "screens": html}


def _reset() -> None:
    global _mcp
    with _lock:
        if _mcp is not None:
            try:
                _mcp.stop(None, None, None)
            except Exception:
                pass
        _mcp = None


def turn(history: list[dict], text: str, *, model_id: str = MODEL_ID, tools: list | None = None,
         system_prompt: str = SYSTEM_PROMPT) -> dict:
    """One spoken turn: the person's words in, Alexa's reply out, with timings. By default
    Alexa uses our MCP server; the research baselines (eval/e3.py) pass their own tools."""
    tools = _connect() if tools is None else tools
    # Prompt caching: the instructions, tool schemas and earlier turns repeat on every model
    # call, so cached they cost a fraction and return sooner.
    model = BedrockModel(model_id=model_id, region_name=REGION, max_tokens=MAX_TOKENS,
                         cache_config=CacheConfig(strategy="auto"))
    agent = Agent(model=model, messages=history, tools=tools,
                  system_prompt=system_prompt, callback_handler=None)
    calls = 0

    def limit(event: BeforeModelCallEvent) -> None:
        nonlocal calls
        calls += 1
        if calls > MAX_MODEL_CALLS_PER_TURN:
            event.cancel = "Too many steps for one turn."
    agent.add_hook(limit, BeforeModelCallEvent)
    t = time.perf_counter()
    try:
        result = agent(text)
    except Exception:
        _reset()  # e.g. the MCP connection dropped: reconnect on the next turn
        raise
    total = (time.perf_counter() - t) * 1000
    m = result.metrics
    tool_ms = sum(tm.total_time for tm in m.tool_metrics.values()) * 1000
    return {
        "reply": str(result).strip(),
        "messages": agent.messages,
        "timing": {"total_ms": round(total), "tools_ms": round(tool_ms), "model_ms": round(total - tool_ms),
                   "model_calls": m.cycle_count},
        "tokens": {"input": m.accumulated_usage["inputTokens"], "output": m.accumulated_usage["outputTokens"],
                   "cache_read": m.accumulated_usage.get("cacheReadInputTokens", 0),
                   "cache_write": m.accumulated_usage.get("cacheWriteInputTokens", 0)},
    }
