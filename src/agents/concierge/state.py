"""Concierge chat: the model's structured output and the graph state."""
import operator
from typing import Annotated, Optional, Sequence, TypedDict

from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field


class ConciergeResult(BaseModel):
    """Output schema for the Concierge chat node (Fase 5)."""
    response_text: str = Field(description="The reply to show the user for this turn (intro/summary sentence).")
    # Lists go in their own field: under JSON-constrained decoding a small
    # model avoids newlines inside a string and closes response_text right
    # at "here's what each file does:" — the list itself was silently lost.
    details: list[str] = Field(
        default_factory=list,
        description="One entry per item when the answer is a list (per file, step, or finding). "
                    "Put list items HERE, not inside response_text.",
    )
    resolved: bool = Field(
        description="True if response_text fully answers the request and no Ticket is needed."
    )
    # Fase 14.5: found live — under JSON-constrained decoding the 8B model
    # cited inline "[n]" in 1 of 4 grounded answers; a field of its own is
    # what it reliably fills. Validated against the real passages by code.
    cited_passages: list[int] = Field(
        default_factory=list,
        description="Numbers [n] of the knowledge base passages your answer is based on. Empty if the "
                    "answer doesn't come from a knowledge base passage.",
    )
    # Restricted at runtime by tool_policy (see CONCIERGE_RISK_CEILING
    # in concierge.py) — the Concierge must never dispatch a risky MCP tool
    # directly; anything beyond a quick lookup/healthcheck goes through a
    # real Ticket and the full Supervisor -> Policy -> Execution swarm.
    tool_name: Optional[str] = Field(default=None, description="Exact name of a safe MCP tool to call, or null.")
    tool_args: dict = Field(default_factory=dict, description="Arguments for tool_name.")


class ConciergeState(TypedDict):
    """State for the lightweight Concierge chat graph (Fase 5) — a single
    node, no risk routing. Message history lives entirely in the checkpointer
    (Fase 5.5 decision: no separate SQL transcript table for the MVP)."""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    user_context: dict
    resolved: Optional[bool]
    final_response: Optional[str]
    # Fase 10.7: deterministic service diagnosis from this turn (verdict,
    # code locations, redacted errors), attached to the Ticket — and so to
    # the GitHub issue — when the turn escalates.
    diagnosis_report: Optional[str]
    # Fase 14.5: knowledge-base passages the answer actually cites (validated
    # by src/rag/citations.py), shown to the user as the answer's sources.
    sources: Optional[list]
