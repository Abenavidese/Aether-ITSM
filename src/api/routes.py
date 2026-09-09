import logging
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from src.agent.graph import get_workflow

logger = logging.getLogger(__name__)
router = APIRouter()

class TicketPayload(BaseModel):
    ticket_id: str
    summary: str
    description: str
    user_id: str

class ApprovalPayload(BaseModel):
    approved: bool
    approver_id: str

async def run_agent_background(payload: TicketPayload, checkpointer):
    """Async background task to execute the LangGraph agent."""
    logger.info("Starting ASYNC agent for ticket %s", payload.ticket_id)
    
    initial_state = {
        "messages": [HumanMessage(content=f"Title: {payload.summary}\n\nDescription: {payload.description}")],
        "ticket_id": payload.ticket_id,
        "user_context": {"email": payload.user_id},
        "assessed_risk": 4, 
        "intent": "unknown"
    }
    
    config = {"configurable": {"thread_id": payload.ticket_id}}
    
    try:
        app = get_workflow().compile(
            checkpointer=checkpointer,
            interrupt_after=["draft_plan"]
        )
        
        # ASYNC STREAMING
        async for step in app.astream(initial_state, config=config):
            for node_name, state_update in step.items():
                logger.info("--- Node '%s' finished (ASYNC) ---", node_name)
                
        logger.info("Graph execution finished or paused for %s", payload.ticket_id)
            
    except Exception as e:
        logger.error("Failed executing graph: %s", e, exc_info=True)

@router.post("/webhook/ticket", status_code=202)
async def receive_ticket_webhook(payload: TicketPayload, background_tasks: BackgroundTasks, request: Request):
    """
    Receives a ticket from ITSM.
    Uses FastAPI BackgroundTasks which will schedule our async function in the event loop.
    """
    checkpointer = request.app.state.checkpointer
    background_tasks.add_task(run_agent_background, payload, checkpointer)
    
    return {
        "status": "Accepted",
        "message": "Aether is reviewing the ticket asynchronously.",
        "ticket_id": payload.ticket_id
    }

@router.post("/approve/{thread_id}")
async def approve_ticket(thread_id: str, payload: ApprovalPayload, request: Request):
    """
    Endpoint for IT Agents to approve a Risk Level 3 ticket.
    """
    config = {"configurable": {"thread_id": thread_id}}
    checkpointer = request.app.state.checkpointer
    
    app = get_workflow().compile(
        checkpointer=checkpointer,
        interrupt_after=["draft_plan"]
    )
    
    # Check state asynchronously
    state = await app.aget_state(config)
    if not state or not state.next:
        raise HTTPException(status_code=404, detail="Thread not found or not waiting for approval.")
    
    logger.info("Resuming paused thread %s with approval: %s", thread_id, payload.approved)
    
    if payload.approved:
        try:
            async for step in app.astream(None, config=config):
                logger.info("--- Node finished during resumption (ASYNC) ---")
            return {"status": "Resumed", "message": "Ticket execution resumed."}
        except Exception as e:
            logger.error("Resumption failed: %s", e, exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error during resumption.")
    else:
        return {"status": "Rejected", "message": "Execution cancelled by human."}
