import operator
from typing import Annotated, Sequence, TypedDict, Optional
from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field

# ---------------------------------------------------------
# Pydantic Schemas for LLM Structured Output (JSON Mode)
# ---------------------------------------------------------

class ClassificationResult(BaseModel):
    """Output schema for the Nemotron Nano Classification Node."""
    intent: str = Field(description="The core intent of the ticket, e.g., 'vpn_reset', 'software_install', 'db_issue'")
    risk_level: int = Field(description="Assessed risk level from 0 to 4 based on policy.")
    tools_required: list[str] = Field(description="List of MCP tools that might be needed.")

class ExecutionPlanResult(BaseModel):
    """Output schema for the Nemotron Super Execution/Planning Node."""
    resolution_summary: str = Field(description="A brief summary of what the agent decided or did.")
    proposed_plan: Optional[str] = Field(default=None, description="The human-readable plan proposed for Risk Level 3 tickets.")


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
