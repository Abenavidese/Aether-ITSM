from langgraph.graph import StateGraph, START, END
from src.observability.tracing import traced_node

from .state import AgentState
from .nodes import supervisor_node, policy_agent_node, execution_agent_node, draft_plan_node, escalate_node

def route_from_supervisor(state: AgentState) -> str:
    """Conditional Edge logic routing from Supervisor to specific sub-agents."""
    if state.get("technical_error"):
        return "escalate"
    
    return state.get("next_agent", "escalate")

def route_from_policy(state: AgentState) -> str:
    """Conditional Edge logic routing from Policy Agent to resolution."""
    if state.get("technical_error"):
        return "escalate"

    return state.get("next_agent", "escalate")

def route_from_execution(state: AgentState) -> str:
    """Conditional Edge logic routing from Execution Agent.

    Execution can fail after Supervisor/Policy already routed here, setting
    technical_error + next_agent="escalate" in its except block — without
    this check that signal was written to state but never read, so the
    graph fell straight through to END and no human was ever notified.
    """
    if state.get("technical_error") or state.get("action_refused"):
        return "escalate"
    if state.get("next_agent") == "policy":
        return "policy"  # risk raised by the proposed tool: compliance check first

    return "end"

def route_from_draft_plan(state: AgentState) -> str:
    """Conditional Edge logic routing from the paused Draft Plan node.

    This edge is only ever evaluated on resume (interrupt_after pauses the
    graph right after draft_plan runs, before this router is consulted).
    approve_ticket sets `human_approved` via aupdate_state right before
    resuming, so by the time we get here the human's decision is already
    in state:
      - approved  -> actually execute the plan (it used to dead-end at END,
        meaning "approval" never ran anything)
      - rejected  -> escalate to a human queue instead of silently leaving
        the thread paused forever
    """
    if state.get("technical_error"):
        return "escalate"
    if state.get("human_approved") is False:
        return "escalate"

    return "execution"

def get_workflow() -> StateGraph:
    """Builds and returns the uncompiled StateGraph for Aether ITSM Multi-Agent Swarm."""
    workflow = StateGraph(AgentState)
    
    # Add Async Swarm Nodes
    # Each node is timed into the run's trace (src/observability/tracing.py).
    for name, node in (
        ("supervisor", supervisor_node), ("policy", policy_agent_node), ("execution", execution_agent_node),
        ("draft_plan", draft_plan_node), ("escalate", escalate_node),
    ):
        workflow.add_node(name, traced_node(name, node))
    
    # START -> Supervisor
    workflow.add_edge(START, "supervisor")
    
    # Routing from Supervisor
    workflow.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "execution": "execution",
            "policy": "policy",
            "escalate": "escalate"
        }
    )
    
    # Routing from Policy Agent
    workflow.add_conditional_edges(
        "policy",
        route_from_policy,
        {
            "execution": "execution",
            "draft_plan": "draft_plan",
            "escalate": "escalate"
        }
    )
    
    # Routing from Execution Agent (may fail and need to escalate instead of ending)
    workflow.add_conditional_edges(
        "execution",
        route_from_execution,
        {
            "escalate": "escalate",
            "policy": "policy",
            "end": END
        }
    )

    # Routing from Draft Plan (paused for human approval, see route_from_draft_plan)
    workflow.add_conditional_edges(
        "draft_plan",
        route_from_draft_plan,
        {
            "escalate": "escalate",
            "execution": "execution"
        }
    )

    # Terminal nodes
    workflow.add_edge("escalate", END)
    
    return workflow
