from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import Dict, Any
from langchain_core.messages import HumanMessage

from src.agent.graph import agent_app

router = APIRouter()

class TicketPayload(BaseModel):
    ticket_id: str
    summary: str
    description: str
    user_id: str

class ApprovalPayload(BaseModel):
    approved: bool
    approver_id: str

def run_agent_background(payload: TicketPayload):
    """Background task to execute the LangGraph agent."""
    print(f"[BACKGROUND] Starting agent for ticket {payload.ticket_id}")
    
    # Initialize the state for the graph
    initial_state = {
        "messages": [HumanMessage(content=f"Title: {payload.summary}\n\nDescription: {payload.description}")],
        "ticket_id": payload.ticket_id,
        "user_context": {"email": payload.user_id},
        "assessed_risk": 4, # Default to 4 (escalate) until classified
        "intent": "unknown"
    }
    
    # We use the ticket_id as the thread_id for SQLite checkpointer
    config = {"configurable": {"thread_id": payload.ticket_id}}
    
    try:
        # Stream the graph execution
        for step in agent_app.stream(initial_state, config=config):
            # Print state updates for debugging
            for node_name, state_update in step.items():
                print(f"--- Node '{node_name}' finished ---")
                
        print(f"[BACKGROUND] Graph execution finished or paused for {payload.ticket_id}")
        
    except Exception as e:
        print(f"[BACKGROUND ERROR] Failed executing graph: {e}")

@router.post("/webhook/ticket", status_code=202)
async def receive_ticket_webhook(payload: TicketPayload, background_tasks: BackgroundTasks):
    """
    Receives a ticket from ITSM (Jira/ServiceNow).
    Returns 202 Accepted immediately to avoid ITSM timeouts.
    Executes LangGraph in the background.
    """
    background_tasks.add_task(run_agent_background, payload)
    
    return {
        "status": "Accepted",
        "message": "Aether is reviewing the ticket.",
        "ticket_id": payload.ticket_id
    }

@router.post("/approve/{thread_id}")
async def approve_ticket(thread_id: str, payload: ApprovalPayload):
    """
    Endpoint for IT Agents to approve a Risk Level 3 ticket.
    Resumes the paused LangGraph thread.
    """
    config = {"configurable": {"thread_id": thread_id}}
    
    # Check if the thread exists and is paused
    state = agent_app.get_state(config)
    if not state or not state.next:
        raise HTTPException(status_code=404, detail="Thread not found or not waiting for approval.")
    
    print(f"[API] Resuming paused thread {thread_id} with approval: {payload.approved}")
    
    # If approved, we inject a message into the state and resume the graph
    # For now, we simply re-invoke with None to continue from the interrupt
    if payload.approved:
        try:
            # We would normally inject the human's response into the state here.
            for step in agent_app.stream(None, config=config):
                print(f"--- Node finished during resumption ---")
            return {"status": "Resumed", "message": "Ticket execution resumed."}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        return {"status": "Rejected", "message": "Execution cancelled by human."}
