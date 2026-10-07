"""Node 2: Compliance — checks the request against the tenant's company policy."""
import logging

from src.agents.runtime.messages import latest_text
from src.llm.context_budget import build_prompt
from src.llm.structured_output import invoke_structured
from src.prompts.ticket_flow import policy_prompt

from ..state import AgentState, PolicyCheckResult
from . import common

logger = logging.getLogger(__name__)


async def policy_agent_node(state: AgentState) -> dict:
    """Checks the user's request against Company Policy."""
    logger.info("Policy Agent evaluating compliance for Risk Level %s", state.get('assessed_risk'))

    _, llm_super = common.get_llms()

    user_query = latest_text(state["messages"])
    tenant_id = state.get("user_context", {}).get("tenant_id")

    rag_context = ""
    if tenant_id and user_query:
        # Policy agent specifically queries the company_policy RAG
        rag_context = await common.retrieve(tenant_id, user_query, "company_policy")

    messages = build_prompt(policy_prompt(state.get('intent'), rag_context), state["messages"])

    try:
        result: PolicyCheckResult = await invoke_structured(llm_super, PolicyCheckResult, messages)

        # Route based on compliance and risk
        if not result.is_compliant:
            next_ag = "escalate"
        else:
            if state.get("assessed_risk") == 3:
                next_ag = "draft_plan"
            else:
                next_ag = "execution"

        return {
            "compliance_passed": result.is_compliant,
            "compliance_notes": result.reason,
            "next_agent": next_ag
        }
    except Exception as e:
        logger.error("Policy Agent failed: %s", e, exc_info=True)
        return {"compliance_passed": False, "compliance_notes": "Policy check failed due to technical error.", "next_agent": "escalate", "technical_error": True}
