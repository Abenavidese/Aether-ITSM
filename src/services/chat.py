"""
One employee chat turn (Fase 5): run the Concierge and, when it can't resolve
the request, open a real Ticket that goes through the full ticket flow.
"""
import asyncio
import uuid

from langchain_core.messages import HumanMessage

from src.agents.concierge import get_concierge_workflow
from src.agents.runtime.vision import describe_attachment
from src.db.models import User
from src.observability.tracing import trace_scope
from src.services import tickets


async def run_chat_turn(checkpointer, mcp_client, user: User, message: str, image_base64: str | None) -> dict:
    """
    One LangGraph thread per employee (not per ticket) so multi-turn context
    persists across messages; history lives only in the checkpointer (Fase 5.5
    decision — no separate SQL transcript table).
    """
    config = {"configurable": {"thread_id": f"chat:{user.id}", "mcp_client": mcp_client}}
    concierge_app = get_concierge_workflow().compile(checkpointer=checkpointer)

    # An attached screenshot is read once by the vision model and travels as
    # text (src/agents/runtime/vision.py): the chat model is text-only, and the
    # multi-MB image never enters the checkpointed history.
    message_text = await describe_attachment(message, image_base64)
    initial_state = {
        "messages": [HumanMessage(content=message_text)],
        "user_context": {
            "email": user.email, "tenant_id": user.company_id,
            # role gates raw platform-log lines (Fase 10.6); user_id is
            # recorded in the log access audit (Fase 10.9).
            "role": user.role, "user_id": user.id,
        },
        "diagnosis_report": None,
        "sources": None,  # a previous turn's sources must not carry over
    }
    async with trace_scope(f"chat:{uuid.uuid4().hex}", "chat", user.company_id):
        async for _ in concierge_app.astream(initial_state, config=config):
            pass

    values = (await concierge_app.aget_state(config)).values
    reply = values.get("final_response", "")
    # Only the passages the answer cites (validated, Fase 14.5) — never raw retrieval output.
    sources = values.get("sources") or []
    if values.get("resolved", True):
        return {"reply": reply, "status": "resolved", "sources": sources}

    # Fase 5.3: the Concierge couldn't resolve it — create a real Ticket and
    # run it through the full flow (via the queue), same as a webhook ticket.
    description = message_text
    if values.get("diagnosis_report"):
        # Evidence travels with the ticket, so the engineer (and the GitHub
        # issue built from this description on escalation) starts from the
        # real verdict and failing code location, not just "it's broken".
        description = f"{message_text}\n\n--- Diagnóstico automático (Aether) ---\n{values['diagnosis_report']}"
    external_id = await asyncio.to_thread(
        tickets.open_chat_ticket, user.id, f"chat-{uuid.uuid4().hex[:10]}", message[:120], description,
    )
    if external_id is None:
        return {
            "reply": f"{reply}\n\n(Your organization has reached its monthly ticket limit — please contact an admin.)",
            "status": "resolved", "sources": sources,
        }
    return {"reply": reply, "status": "investigating", "ticket_external_id": external_id, "sources": sources}
