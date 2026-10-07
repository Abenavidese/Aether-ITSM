"""Node 1: Supervisor — classifies the ticket, assigns the risk level and routes it."""
import logging

from src.agents.runtime.messages import latest_text
from src.llm.context_budget import build_prompt
from src.llm.structured_output import invoke_structured
from src.prompts.ticket_flow import supervisor_prompt
from src.tools.tool_policy import risk_of_tools

from ..risk_policy import enforce_risk_floor
from ..state import AgentState, ClassificationResult
from . import common

logger = logging.getLogger(__name__)


async def supervisor_node(state: AgentState) -> dict:
    """Evaluates the ticket, assigns a risk level, and routes to the next sub-agent."""
    logger.info("Supervisor Agent analyzing Ticket: %s", state.get('ticket_id'))

    llm_nano, _ = common.get_llms()
    messages = build_prompt(supervisor_prompt(state.get('ticket_id'), state.get('user_context', {})),
                            state["messages"])

    try:
        result: ClassificationResult = await invoke_structured(llm_nano, ClassificationResult, messages)

        ticket_text = latest_text(state["messages"])
        assessed_risk, floor_reason = enforce_risk_floor(ticket_text, result.risk_level)
        # Second floor source: if the classifier itself says the ticket needs
        # a risk-3 tool, the ticket is at least risk 3, whatever number it gave.
        tools_floor = risk_of_tools(result.tools_required)
        if tools_floor > assessed_risk:
            assessed_risk, floor_reason = tools_floor, f"requires tools {result.tools_required}"
        if floor_reason:
            logger.warning(
                "Risk floor enforced for ticket %s: model classified risk %d, forcing %d (%s)",
                state.get('ticket_id'), result.risk_level, assessed_risk, floor_reason
            )

        # Swarm Routing Logic
        next_ag = "escalate"
        if assessed_risk == 0:
            next_ag = "execution"  # Safe to execute directly (no policy check needed for FAQs)
        elif assessed_risk in [1, 2, 3]:
            next_ag = "policy"     # Must pass compliance check

        return {
            "intent": result.intent,
            "assessed_risk": assessed_risk,
            "next_agent": next_ag,
            "final_resolution": None
        }
    except Exception as e:
        logger.error("Supervisor failed: %s", e, exc_info=True)
        return {"assessed_risk": 4, "next_agent": "escalate", "technical_error": True}
