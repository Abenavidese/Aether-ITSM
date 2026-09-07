import asyncio
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from src.agent.graph import get_workflow

router = APIRouter()

class TicketPayload(BaseModel):
    ticket_id: str
    summary: str
    description: str
    user_id: str

class ApprovalPayload(BaseModel):
    approved: bool
    approver_id: str

async def run_agent_background(payload: TicketPayload):
    """Async background task to execute the LangGraph agent."""
    print(f"[BACKGROUND] Starting ASYNC agent for ticket {payload.ticket_id}")
    
    initial_state = {
        "messages": [HumanMessage(content=f"Title: {payload.summary}\n\nDescription: {payload.description}")],
        "ticket_id": payload.ticket_id,
        "user_context": {"email": payload.user_id},
        "assessed_risk": 4, 
        "intent": "unknown"
    }
    
    config = {"configurable": {"thread_id": payload.ticket_id}}
    
    try:
        # ASYNC SQLITE SAVER for concurrency
        async with AsyncSqliteSaver.from_conn_string("checkpoints.db") as memory:
            # Compile the graph with the checkpointer at runtime
            app = get_workflow().compile(
                checkpointer=memory,
                interrupt_after=["draft_plan"]
            )
            
            # ASYNC STREAMING
            async for step in app.astream(initial_state, config=config):
                for node_name, state_update in step.items():
                    print(f"--- Node '{node_name}' finished (ASYNC) ---")
                    
            print(f"[BACKGROUND] Graph execution finished or paused for {payload.ticket_id}")
            
    except Exception as e:
        print(f"[BACKGROUND ERROR] Failed executing graph: {e}")

@router.post("/webhook/ticket", status_code=202)
async def receive_ticket_webhook(payload: TicketPayload, background_tasks: BackgroundTasks):
    """
    Receives a ticket from ITSM.
    Uses FastAPI BackgroundTasks which will schedule our async function in the event loop.
    """
    background_tasks.add_task(run_agent_background, payload)
    
    return {
        "status": "Accepted",
        "message": "Aether is reviewing the ticket asynchronously.",
        "ticket_id": payload.ticket_id
    }

@router.post("/approve/{thread_id}")
async def approve_ticket(thread_id: str, payload: ApprovalPayload):
    """
    Endpoint for IT Agents to approve a Risk Level 3 ticket.
    """
    config = {"configurable": {"thread_id": thread_id}}
    
    async with AsyncSqliteSaver.from_conn_string("checkpoints.db") as memory:
        app = get_workflow().compile(
            checkpointer=memory,
            interrupt_after=["draft_plan"]
        )
        
        # Check state asynchronously
        state = await app.aget_state(config)
        if not state or not state.next:
            raise HTTPException(status_code=404, detail="Thread not found or not waiting for approval.")
        
        print(f"[API] Resuming paused thread {thread_id} with approval: {payload.approved}")
        
        if payload.approved:
            try:
                async for step in app.astream(None, config=config):
                    print(f"--- Node finished during resumption (ASYNC) ---")
                return {"status": "Resumed", "message": "Ticket execution resumed."}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        else:
            return {"status": "Rejected", "message": "Execution cancelled by human."}
