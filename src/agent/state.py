import operator
from typing import Annotated, Literal, Sequence, TypedDict, Optional
from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field

# ---------------------------------------------------------
# Pydantic Schemas for LLM Structured Output (JSON Mode)
# ---------------------------------------------------------

class ClassificationResult(BaseModel):
    """Output schema for the Nemotron Nano Classification Node."""
    intent: str = Field(description="The core intent of the ticket, e.g., 'vpn_reset', 'software_install', 'db_issue'")
    # Literal (not int) so the schema itself rejects out-of-range values the
    # model might hallucinate, instead of silently producing an unroutable state.
    risk_level: Literal[0, 1, 2, 3, 4] = Field(description="Assessed risk level from 0 to 4 based on policy.")
    # Optional with a default: a local model omitting this non-critical field
    # shouldn't fail validation for the whole (correctly classified) result.
    tools_required: list[str] = Field(default_factory=list, description="List of MCP tools that might be needed.")

class ExecutionPlanResult(BaseModel):
    """Output schema for the Nemotron Super Execution/Planning Node."""
    resolution_summary: str = Field(description="A brief summary of what the agent decided or did.")
    proposed_plan: Optional[str] = Field(default=None, description="The human-readable plan proposed for Risk Level 3 tickets.")
    # Deterministic, Pydantic-validated tool dispatch (see docs/security_guardrails.md
    # "Strict Schema Validation") instead of free-form agentic tool-calling.
    # None means "no real-world action needed" (e.g. a pure informational answer).
    tool_name: Optional[str] = Field(
        default=None, description="Exact name of the MCP tool to invoke, or null if none is needed."
    )
    tool_args: dict = Field(
        default_factory=dict, description="Arguments for tool_name, matching that tool's parameters exactly."
    )

class PolicyCheckResult(BaseModel):
    """Output schema for the Compliance/Policy Agent."""
    is_compliant: bool = Field(description="True if the user's request complies with company policy.")
    reason: str = Field(description="Explanation of why the request is compliant or not.")


class ConciergeResult(BaseModel):
    """Output schema for the Concierge chat node (Fase 5)."""
    response_text: str = Field(description="The reply to show the user for this turn.")
    resolved: bool = Field(
        description="True if response_text fully answers the request and no Ticket is needed."
    )
    # Restricted at runtime to a safe allow-list (see CONCIERGE_ALLOWED_TOOLS
    # in concierge.py) — the Concierge must never dispatch a risky MCP tool
    # directly; anything beyond a quick lookup/healthcheck goes through a
    # real Ticket and the full Supervisor -> Policy -> Execution swarm.
    tool_name: Optional[str] = Field(default=None, description="Exact name of a safe MCP tool to call, or null.")
    tool_args: dict = Field(default_factory=dict, description="Arguments for tool_name.")


# ---------------------------------------------------------
# LangGraph Agent State
# ---------------------------------------------------------

class AgentState(TypedDict):
    """The state passed between nodes in the LangGraph state machine."""
    # The history of the conversation, using operator.add to append new messages
    messages: Annotated[Sequence[BaseMessage], operator.add]
    
    # Core ticket metadata
    ticket_id: str
    company_id: str
    user_context: dict
    
    # State tracking variables populated by nodes
    assessed_risk: int
    intent: str
    proposed_plan: Optional[str]
    human_approved: bool
    final_resolution: Optional[str]
    technical_error: bool
    
    # Swarm/Hierarchical Routing Fields
    next_agent: Optional[str]
    compliance_passed: Optional[bool]
    compliance_notes: Optional[str]


class ConciergeState(TypedDict):
    """State for the lightweight Concierge chat graph (Fase 5) — a single
    node, no risk routing. Message history lives entirely in the checkpointer
    (Fase 5.5 decision: no separate SQL transcript table for the MVP)."""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    user_context: dict
    resolved: Optional[bool]
    final_response: Optional[str]
