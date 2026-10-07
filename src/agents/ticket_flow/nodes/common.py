"""
What every ticket-flow node shares: the LLMs, tenant data lookups and the
authorization context. Nodes call these through this module (common.get_llms(),
...) so there is one place to inject fakes in tests.
"""
import asyncio
import logging

from src.integrations.monitoring import get_monitored_services
from src.llm.factory import get_llms  # noqa: F401 — looked up as common.get_llms by every node
from src.rag.service import retrieve_context
from src.tools.mcp_client import MCPToolClient
from src.tools.tool_policy import AuthorizedToolCall, ToolCallContext
from src.utils.urls import normalize_url

from ..state import AgentState

logger = logging.getLogger(__name__)


async def monitored_services(state: AgentState) -> list[dict]:
    # DB lookup off the event loop (roadmap 2.1).
    tenant_id = state.get("user_context", {}).get("tenant_id")
    return await asyncio.to_thread(get_monitored_services, tenant_id) if tenant_id else []


async def retrieve(tenant_id: str, query: str, source_type: str, top_k: int | None = None) -> str:
    # Embedding + search + rerank is blocking I/O/CPU: run it in a worker thread.
    # Numbered passages ([1]..[n]) with document/section (Fase 14.5).
    return await asyncio.to_thread(retrieve_context, tenant_id, query, source_type=source_type, top_k=top_k)


def tool_context(state: AgentState, services: list[dict], *, human_approved: bool | None = None) -> ToolCallContext:
    """Authorization context built from state/config only — never from LLM output."""
    user_context = state.get("user_context", {})
    return ToolCallContext(
        requester=user_context.get("email"),
        assessed_risk=state.get("assessed_risk", 4),
        human_approved=state.get("human_approved") is True if human_approved is None else human_approved,
        allowed_service_urls=frozenset(normalize_url(s["url"]) for s in services),
    )


async def run_tool(mcp_client: MCPToolClient, call: AuthorizedToolCall, ticket_id) -> str:
    output = await mcp_client.call_tool(call.name, call.args)
    logger.info("MCP tool '%s' executed for ticket %s", call.name, ticket_id)
    return output
