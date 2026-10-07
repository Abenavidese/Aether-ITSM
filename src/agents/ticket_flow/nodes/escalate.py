"""Node 5: Escalate — hands the ticket to a human engineer, with the reason."""
import logging

from ..state import AgentState

logger = logging.getLogger(__name__)


async def escalate_node(state: AgentState) -> dict:
    """Escalates to Human."""
    logger.info("Escalating to Human (Risk 4 or Non-Compliant)")

    reason = "high risk or technical error"
    if state.get("compliance_passed") is False:
        reason = f"Company Policy Violation: {state.get('compliance_notes')}"
    elif state.get("human_approved") is False:
        reason = "the proposed plan was rejected by the human reviewer"
    elif state.get("action_refused"):
        reason = f"the automated action was not allowed ({state.get('action_refused')})"

    return {
        "final_resolution": f"Ticket escalated to Tier 3 human engineering due to: {reason}."
    }
