import sqlite3
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

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

def build_graph():
    """Builds and compiles the StateGraph for Aether ITSM."""
    
    # Initialize the graph with our state schema
    workflow = StateGraph(AgentState)
    
    # Add Nodes
    workflow.add_node("classify", classify_node)
    workflow.add_node("execute_tools", execute_tools_node)
    workflow.add_node("draft_plan", draft_plan_node)
    workflow.add_node("escalate", escalate_node)
    
    # Add Edges
    workflow.add_edge(START, "classify")
    
    # Add Conditional Edges from the classify node
    workflow.add_conditional_edges(
        "classify",
        route_ticket,
        {
            "execute": "execute_tools",
            "draft_plan": "draft_plan",
            "escalate": "escalate"
        }
    )
    
    # All terminal nodes end the graph
    workflow.add_edge("execute_tools", END)
    workflow.add_edge("draft_plan", END)  # Pauses here (interrupt_before not set yet, handled at API layer)
    workflow.add_edge("escalate", END)
    
    # Configure SQLite Checkpointer for State Persistence
    # This allows us to pause at Risk 3 and resume later
    conn = sqlite3.connect("checkpoints.db", check_same_thread=False)
    memory = SqliteSaver(conn)
    
    # Compile the graph
    # We set an interrupt AFTER draft_plan so the API can wait for human approval
    app = workflow.compile(
        checkpointer=memory,
        interrupt_after=["draft_plan"]
    )
    
    return app

# Singleton instance of the graph
agent_app = build_graph()
