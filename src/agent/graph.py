from langgraph.graph import StateGraph, START, END
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
    if state.get("technical_error"):
        return "escalate"

    return "end"

def get_workflow() -> StateGraph:
    """Builds and returns the uncompiled StateGraph for Aether ITSM Multi-Agent Swarm."""
    workflow = StateGraph(AgentState)
    
    # Add Async Swarm Nodes
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("policy", policy_agent_node)
    workflow.add_node("execution", execution_agent_node)
    workflow.add_node("draft_plan", draft_plan_node)
    workflow.add_node("escalate", escalate_node)
    
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
            "end": END
        }
    )

    # Terminal nodes
    workflow.add_edge("draft_plan", END)
    workflow.add_edge("escalate", END)
    
    return workflow
