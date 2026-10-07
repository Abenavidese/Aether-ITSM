"""How a ticket's graph is compiled, addressed and inspected — shared by the queue
worker, the approval endpoint, the trace API and the evals."""
from .graph import get_workflow


def ticket_graph(checkpointer):
    return get_workflow().compile(checkpointer=checkpointer, interrupt_after=["draft_plan"])


def ticket_thread_config(tenant_id: str, external_id: str, mcp_client) -> dict:
    # Namespaced by tenant so ticket IDs can never collide or be resumed across
    # companies (see resume_after_approval for the matching check). mcp_client
    # rides along in `configurable` so nodes get it injected, never as a global.
    return {"configurable": {"thread_id": f"{tenant_id}:{external_id}", "mcp_client": mcp_client}}


def ticket_trace_id(external_id: str) -> str:
    # One trace per ticket: the first run and the post-approval resume append
    # to the same trace, so GET /tenant/tickets/{id}/trace shows the whole path.
    return f"ticket:{external_id}"


def awaiting_approval(snapshot) -> bool:
    values = snapshot.values or {}
    return bool(snapshot.next) and values.get("proposed_plan") is not None and values.get("human_approved") is None
