"""
The investigation supervisor (Fase 16.4/16.5): one small structured-output
call that picks read-only checks from a closed menu. It never answers the
user and never produces a parameter that reaches a reader unvalidated
(plan.py). Any failure — model down, timeout, wrong schema — degrades to the
deterministic floor, i.e. exactly the pre-Fase 16 behavior.
"""
import asyncio
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm.structured_output import invoke_structured
from src.prompts.concierge_supervisor import conversation_block, follow_up_prompt, investigation_plan_prompt

from .plan import FollowUpPlan, InvestigationPlan

logger = logging.getLogger(__name__)

# The supervisor must be cheap: a turn that waits longer than this for it
# just runs the floor.
SUPERVISOR_TIMEOUT_SECONDS = 20.0

# Greetings, thanks and acknowledgements never need a check (Fase 16.8):
# skipping the model there keeps small talk as fast as before.
_TRIVIAL = re.compile(
    r"^\W*(hola|hi|hello|hey|buen[oa]s( d[ií]as| tardes| noches)?|gracias|muchas gracias|thanks|thank you|ok(ay)?"
    r"|vale|perfecto|genial|listo|de acuerdo|entendido|great|cool|bye|adi[oó]s|chao)\b[\w\s,!.¡¿?]{0,25}$",
    re.IGNORECASE,
)


def is_trivial(message: str) -> bool:
    return len(message) <= 60 and bool(_TRIVIAL.match(message.strip()))


async def propose_investigations(llm, user_messages: list[str], services: list[str],
                                 repo_connected: bool) -> InvestigationPlan | None:
    """None = no proposal (the floor alone runs)."""
    messages = [SystemMessage(content=investigation_plan_prompt(services, repo_connected)),
                HumanMessage(content="Conversation (latest message last):\n" + conversation_block(user_messages))]
    return await _invoke(llm, InvestigationPlan, messages, "plan")


async def propose_follow_up(llm, evidence: str, candidates: list[str], can_search: bool) -> FollowUpPlan | None:
    messages = [SystemMessage(content=follow_up_prompt(evidence, candidates, can_search)),
                HumanMessage(content="Decide the follow-up now.")]
    return await _invoke(llm, FollowUpPlan, messages, "follow-up")


async def _invoke(llm, schema, messages: list, what: str):
    if llm is None:
        return None
    try:
        result = await asyncio.wait_for(invoke_structured(llm, schema, messages, max_retries=1),
                                        timeout=SUPERVISOR_TIMEOUT_SECONDS)
    except Exception as e:
        logger.warning("Concierge supervisor %s failed (%s) — using the deterministic floor", what,
                       type(e).__name__)
        return None
    if not isinstance(result, schema):
        logger.warning("Concierge supervisor %s returned %s, not %s — ignored", what, type(result).__name__,
                       schema.__name__)
        return None
    return result
