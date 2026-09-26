"""
MCP client: the one place in the codebase that knows how to talk to the
FastMCP tool server (src/tools/mcp_server.py) over stdio.

Design notes:
- Long-lived, one per app process. Spawning a fresh stdio subprocess per
  ticket/node call would be wasteful and slow; the connection is opened once
  in FastAPI's lifespan (see src/main.py) and reused for every request,
  mirroring how the LangGraph checkpointer is already managed there.
- The tool catalog (name, description, args) is read from the live server at
  connect time via list_tools() — never hand-duplicated into a prompt
  string, so adding a tool to mcp_server.py doesn't require touching this
  file or the agent prompts.
- call_tool() refuses any name that isn't in that live catalog. This is the
  enforcement point for the "Strict Schema Validation" rule in
  docs/security_guardrails.md: an LLM hallucinating an unregistered tool
  name fails loudly here instead of silently doing something unintended.
"""
import json
import logging
import os
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
MCP_SERVER_MODULE = "src.tools.mcp_server"


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    description: str
    input_schema: dict


class MCPToolClient:
    """Thin async wrapper around an MCP ClientSession with a cached tool registry."""

    def __init__(self):
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._tools: dict[str, ToolDescriptor] = {}

    async def connect(self) -> None:
        self._exit_stack = AsyncExitStack()
        params = StdioServerParameters(
            # sys.executable, not a bare "python" — guarantees the subprocess
            # uses this exact venv (mcp/fastmcp installed) regardless of PATH.
            command=sys.executable,
            args=["-m", MCP_SERVER_MODULE],
            cwd=PROJECT_ROOT,
        )
        read, write = await self._exit_stack.enter_async_context(stdio_client(params))
        self._session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()

        listed = await self._session.list_tools()
        self._tools = {
            t.name: ToolDescriptor(
                name=t.name,
                description=t.description or "",
                input_schema=t.input_schema or {},
            )
            for t in listed.tools
        }
        logger.info("MCP client connected — %d tools available: %s", len(self._tools), list(self._tools))

    async def close(self) -> None:
        if self._exit_stack:
            await self._exit_stack.aclose()
        self._exit_stack = None
        self._session = None
        self._tools = {}

    @property
    def tools(self) -> dict[str, ToolDescriptor]:
        return self._tools

    def prompt_catalog(self, only: Iterable[str] | None = None,
                       hidden_params: Mapping[str, Iterable[str]] | None = None) -> str:
        """
        Human-readable tool listing for the agent prompt, derived live — see
        module docstring. `only` narrows it to the tools the caller is
        allowed to use (tool_policy.allowed_tools): a risk-1 ticket's prompt
        shouldn't even mention modify_iam_access. `hidden_params` drops
        parameters the model must not choose (tool_policy.identity_params).
        """
        wanted = set(only) if only is not None else None
        hidden = {name: set(params) for name, params in (hidden_params or {}).items()}
        tools = [t for t in self._tools.values() if wanted is None or t.name in wanted]
        if not tools:
            return "No tools available."
        lines = []
        for t in tools:
            props = (t.input_schema or {}).get("properties", {})
            args = ", ".join(p for p in props if p not in hidden.get(t.name, set()))
            lines.append(f"- {t.name}({args}): {t.description}")
        return "\n".join(lines)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        if name not in self._tools:
            raise ValueError(f"Unregistered MCP tool requested: '{name}'. Known tools: {list(self._tools)}")
        if self._session is None:
            raise RuntimeError("MCP client is not connected.")

        result = await self._session.call_tool(name, arguments)
        if result.is_error:
            raise RuntimeError(f"MCP tool '{name}' returned an error: {result.content}")

        # mcp_server.py's tools each return a single JSON string in a text block.
        text_parts = [c.text for c in result.content if getattr(c, "type", None) == "text"]
        return "\n".join(text_parts) if text_parts else json.dumps({"status": "success"})
