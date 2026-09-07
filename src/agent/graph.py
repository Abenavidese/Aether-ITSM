from langgraph.graph import StateGraph, START, END
from .state import AgentState
from .nodes import classify_node, execute_tools_node, draft_plan_node, escalate_node

def route_ticket(state: AgentState) -> str:
    """Conditional Edge logic based on Risk Level."""
    risk = state.get("assessed_risk", 4)
    
    if state.get("technical_error"):
        return "escalate"
    if risk <= 2:
        return "execute"
    elif risk == 3:
        return "draft_plan"
    else:
        return "escalate"

def get_workflow() -> StateGraph:
    """Builds and returns the uncompiled StateGraph for Aether ITSM."""
    workflow = StateGraph(AgentState)
    
    # Add Async Nodes
    workflow.add_node("classify", classify_node)
    workflow.add_node("execute_tools", execute_tools_node)
    workflow.add_node("draft_plan", draft_plan_node)
    workflow.add_node("escalate", escalate_node)
    
    # Add Edges
    workflow.add_edge(START, "classify")
    
    # Add Conditional Edges
    workflow.add_conditional_edges(
        "classify",
        route_ticket,
        {
            "execute": "execute_tools",
            "draft_plan": "draft_plan",
            "escalate": "escalate"
        }
    )
    
    # Terminal nodes
    workflow.add_edge("execute_tools", END)
    workflow.add_edge("draft_plan", END)
    workflow.add_edge("escalate", END)
    
    return workflow
