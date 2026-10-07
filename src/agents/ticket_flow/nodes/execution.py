"""Node 3: Execution — resolves the ticket and, if it needs a real action, proposes one tool call."""
import asyncio
import logging

from langchain_core.runnables import RunnableConfig

from src.agents.runtime.messages import latest_text
from src.llm.context_budget import build_prompt
from src.llm.structured_output import invoke_structured
from src.prompts.ticket_flow import execution_prompt
from src.tools.mcp_client import MCPToolClient
from src.tools.tool_policy import ToolPolicyViolation, authorize, identity_params, proposable_tools, required_risk

from ..state import AgentState, ExecutionPlanResult
from . import common

logger = logging.getLogger(__name__)


async def _execute_approved_plan(state: AgentState, mcp_client: MCPToolClient) -> dict:
    """
    Runs EXACTLY the action a human approved — no LLM involved (Fase 11.2).
    Asking the model again after approval (the previous behavior) meant the
    call that ran could differ from the one the admin saw.
    """
    action = state.get("planned_action")
    if not action:
        return {"action_refused": "the approved plan has no automated action; an engineer must carry it out"}
    try:
        call = authorize(action.get("tool_name"), action.get("tool_args"),
                         common.tool_context(state, await common.monitored_services(state)))
    except ToolPolicyViolation as e:
        logger.warning("Approved action refused at execution time for ticket %s: %s", state.get("ticket_id"), e)
        return {"action_refused": e.reason}
    tool_output = await common.run_tool(mcp_client, call, state.get("ticket_id"))
    return {"final_resolution": f"Action Executed (human-approved): {call.describe()}\nTool result: {tool_output}"}


async def execution_agent_node(state: AgentState, config: RunnableConfig) -> dict:
    """Formulates a resolution and, if the ticket requires a real-world action,
    dispatches it to the MCP tool server (src/tools/mcp_client.py). The
    mcp_client is injected via LangGraph's own `configurable` mechanism (same
    pattern already used for thread_id) rather than a module-level global, so
    it stays swappable/mockable per run.

    The model only PROPOSES a tool call; tool_policy.authorize decides.
    """
    logger.info("Execution Agent running for Ticket: %s", state.get('ticket_id'))

    mcp_client: MCPToolClient = config["configurable"]["mcp_client"]
    if state.get("human_approved") is True:
        try:
            return await _execute_approved_plan(state, mcp_client)
        except Exception as e:
            logger.error("Approved plan execution failed: %s", e, exc_info=True)
            return {"final_resolution": "Execution failed — escalating.", "next_agent": "escalate", "technical_error": True}

    _, llm_super = common.get_llms()
    user_query = latest_text(state["messages"])
    tenant_id = state.get("user_context", {}).get("tenant_id")

    rag_context = ""
    ai_feedback = ""
    if tenant_id and user_query:
        # Execution agent queries technical docs (or company policy if risk 0)
        source = "company_policy" if state.get('assessed_risk') == 0 else "technical_repo"
        rag_context, ai_feedback = await asyncio.gather(
            common.retrieve(tenant_id, user_query, source),
            common.retrieve(tenant_id, user_query, "ai_feedback", top_k=2),
        )

    monitored_services = await common.monitored_services(state)
    ctx = common.tool_context(state, monitored_services)
    prompt = execution_prompt(
        state.get('assessed_risk'), state.get('compliance_notes') or '', rag_context, ai_feedback,
        monitored_services, mcp_client.prompt_catalog(only=proposable_tools(), hidden_params=identity_params()),
    )
    messages = build_prompt(prompt, state["messages"])

    try:
        result: ExecutionPlanResult = await invoke_structured(llm_super, ExecutionPlanResult, messages)

        tool_output = None
        if result.tool_name:
            needed = required_risk(result.tool_name)
            if needed is not None and needed > ctx.assessed_risk and not state.get("risk_rerouted"):
                # The model says this ticket needs a riskier action than the
                # classifier thought. Risk only ever goes UP: re-route through
                # Policy (and, for risk 3, draft_plan + human approval) instead
                # of refusing outright. Once per ticket, so it can't loop.
                logger.info("Ticket %s: proposed %s needs risk %d > %d — re-routing through policy",
                            state.get('ticket_id'), result.tool_name, needed, ctx.assessed_risk)
                return {"assessed_risk": needed, "next_agent": "policy", "risk_rerouted": True}
            try:
                call = authorize(result.tool_name, result.tool_args, ctx)
            except ToolPolicyViolation as e:
                logger.warning("Tool call refused for ticket %s: %s", state.get('ticket_id'), e)
                return {"action_refused": e.reason}
            tool_output = await common.run_tool(mcp_client, call, state.get('ticket_id'))

        final_res = f"Action Executed: {result.resolution_summary}"
        if tool_output:
            final_res += f"\nTool result: {tool_output}"

        return {"final_resolution": final_res}
    except Exception as e:
        logger.error("Execution Agent failed: %s", e, exc_info=True)
        return {"final_resolution": "Execution failed — escalating.", "next_agent": "escalate", "technical_error": True}
