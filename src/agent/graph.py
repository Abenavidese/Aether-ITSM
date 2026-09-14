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
    
    # Terminal nodes
    workflow.add_edge("execution", END)
    workflow.add_edge("draft_plan", END)
    workflow.add_edge("escalate", END)
    
    return workflow
