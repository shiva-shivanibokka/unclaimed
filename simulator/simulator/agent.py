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
from strands.models import BedrockModel
from strands.models.model import CacheConfig
from strands.tools.mcp import MCPClient

MODEL_ID = os.environ.get("SIMULATOR_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
REGION = os.environ.get("AWS_REGION", "us-east-1")
MCP_URL = os.environ.get("MCP_URL", "http://localhost:8080/mcp")
SYSTEM_PROMPT = (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")

_lock = threading.Lock()
_mcp: MCPClient | None = None
_tools: list | None = None


def _connect() -> list:
    """The MCP server's tools, from one long-lived client (reconnects after a failure)."""
    global _mcp, _tools
    with _lock:
        if _tools is None:
            if _mcp is not None:
                try:
                    _mcp.stop(None, None, None)
                except Exception:
                    pass
            _mcp = MCPClient(url=MCP_URL)
            _mcp.start()
            _tools = _mcp.list_tools_sync()
        return _tools


def _reset() -> None:
    global _tools
    with _lock:
        _tools = None


def turn(history: list[dict], text: str) -> dict:
    """One spoken turn: the person's words in, Alexa's reply out, with timings."""
    tools = _connect()
    # Prompt caching: the instructions, tool schemas and earlier turns repeat on every model
    # call, so cached they cost a fraction and return sooner.
    model = BedrockModel(model_id=MODEL_ID, region_name=REGION, cache_config=CacheConfig(strategy="auto"))
    agent = Agent(model=model, messages=history, tools=tools,
                  system_prompt=SYSTEM_PROMPT, callback_handler=None)
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
