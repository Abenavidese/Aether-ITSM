import json
import logging
from langchain_core.messages import SystemMessage
from .state import AgentState, ClassificationResult, ExecutionPlanResult
from src.config import get_llms

logger = logging.getLogger(__name__)

async def classify_node(state: AgentState) -> dict:
    """Node 1: Evaluates ticket and assigns Risk Level (Async)."""
    logger.info("Classifying Ticket: %s", state.get('ticket_id'))
    
    # Lazy init to avoid instantiation at import time
    llm_nano, _ = get_llms()
    structured_llm = llm_nano.with_structured_output(ClassificationResult)
    
    prompt = f"""
    You are the Classification Engine for Aether ITSM.
    Analyze the user's IT support ticket.
    Ticket ID: {state.get('ticket_id')}
    Context: {json.dumps(state.get('user_context', {}))}
    
    Assign a risk_level:
    0 = Generic Question / FAQ (Can be solved by Knowledge Base)
    1-2 = Low Risk Action (e.g. Reset VPN, Install standard software)
    3 = High Risk Action (e.g. Modify IAM, Admin access) - Requires Human Approval
    4 = Escalate (Technical error, vague request, or dangerous)
    """
    
    messages = [SystemMessage(content=prompt)] + state["messages"]
    
    try:
        result: ClassificationResult = await structured_llm.ainvoke(messages)
        return {
            "intent": result.intent,
            "assessed_risk": result.risk_level,
            "final_resolution": None
        }
    except Exception as e:
        logger.error("Classification failed: %s", e, exc_info=True)
        return {"assessed_risk": 4, "technical_error": True}


async def execute_tools_node(state: AgentState) -> dict:
    """Node 2: (Risk 0-2) Connects to MCP Server and executes immediately (Async)."""
    logger.info("Executing Tools for Risk Level %s", state.get('assessed_risk'))
    
    _, llm_super = get_llms()
    structured_llm = llm_super.with_structured_output(ExecutionPlanResult)
    prompt = f"""
    You are the Execution Engine. The ticket is Risk Level {state.get('assessed_risk')}.
    Formulate a tool call and a resolution summary.
    """
    messages = [SystemMessage(content=prompt)] + state["messages"]
    
    try:
        result: ExecutionPlanResult = await structured_llm.ainvoke(messages)
        final_res = f"Action Executed: {result.resolution_summary}"
        return {"final_resolution": final_res}
    except Exception as e:
        logger.error("Tool execution failed: %s", e, exc_info=True)
        return {"final_resolution": "Execution failed — escalating.", "technical_error": True}

async def draft_plan_node(state: AgentState) -> dict:
    """Node 3: (Risk 3) Drafts a plan and pauses for Human Approval (Async)."""
    logger.info("Drafting Plan (Risk 3) - Preparing for Human Pause")
    
    _, llm_super = get_llms()
    structured_llm = llm_super.with_structured_output(ExecutionPlanResult)
    prompt = "You are the Execution Engine. The ticket is Risk 3. Draft a proposed_plan for human review. DO NOT execute."
    messages = [SystemMessage(content=prompt)] + state["messages"]
    
    try:
        result: ExecutionPlanResult = await structured_llm.ainvoke(messages)
        return {"proposed_plan": result.proposed_plan}
    except Exception as e:
        logger.error("Draft plan failed: %s", e, exc_info=True)
        return {"proposed_plan": "Failed to draft plan due to technical error.", "technical_error": True}

async def escalate_node(state: AgentState) -> dict:
    """Node 4: (Risk 4) Escalates to Human (Async)."""
    logger.info("Escalating to Human (Risk 4)")
    return {
        "final_resolution": "Ticket escalated to Tier 3 human engineering due to high risk or technical error."
    }
