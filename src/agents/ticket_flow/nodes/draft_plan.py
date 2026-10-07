"""Node 4: Draft Plan — proposes a risk-3 action and pauses for human approval."""
import logging

from langchain_core.runnables import RunnableConfig

from src.llm.context_budget import build_prompt
from src.llm.structured_output import invoke_structured
from src.prompts.ticket_flow import draft_plan_prompt
from src.tools.mcp_client import MCPToolClient
from src.tools.tool_policy import ToolPolicyViolation, allowed_tools, authorize, identity_params

from ..state import AgentState, ExecutionPlanResult
from . import common

logger = logging.getLogger(__name__)


async def draft_plan_node(state: AgentState, config: RunnableConfig) -> dict:
    """
    Drafts a plan and pauses for Human Approval (Async).

    The plan carries a STRUCTURED action (planned_action), validated now as
    if approved, and its exact form is appended to the text the admin reads
    — so what the human approves is literally what execution will run.
    """
    logger.info("Execution Agent drafting plan (Risk 3) - Preparing for Human Pause")

    _, llm_super = common.get_llms()
    mcp_client: MCPToolClient = config["configurable"]["mcp_client"]
    ctx_if_approved = common.tool_context(state, await common.monitored_services(state), human_approved=True)
    prompt = draft_plan_prompt(
        mcp_client.prompt_catalog(only=allowed_tools(ctx_if_approved), hidden_params=identity_params())
    )
    messages = build_prompt(prompt, state["messages"])

    try:
        result: ExecutionPlanResult = await invoke_structured(llm_super, ExecutionPlanResult, messages)
    except Exception as e:
        logger.error("Draft plan failed: %s", e, exc_info=True)
        return {"proposed_plan": "Failed to draft plan due to technical error.", "next_agent": "escalate", "technical_error": True}

    plan_text = result.proposed_plan or result.resolution_summary
    planned_action = None
    if result.tool_name:
        try:
            call = authorize(result.tool_name, result.tool_args, ctx_if_approved)
            planned_action = call.to_dict()
            plan_text += f"\n\nExact action that will run on approval: {call.describe()}"
        except ToolPolicyViolation as e:
            logger.warning("Draft plan proposed a refused action for ticket %s: %s", state.get("ticket_id"), e)
            plan_text += f"\n\nNo automated action (proposed call refused by policy: {e.reason}). Approval hands it to an engineer."
    else:
        plan_text += "\n\nNo automated action: approval hands it to an engineer."
    return {"proposed_plan": plan_text, "planned_action": planned_action}
