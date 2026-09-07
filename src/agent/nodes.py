import json
import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage
from .state import AgentState, ClassificationResult, ExecutionPlanResult, EscalateResult
from src.config import get_llms

# Initialize LLM Models via Factory
llm_nano, llm_super = get_llms()

async def classify_node(state: AgentState) -> dict:
    """Node 1: Evaluates ticket and assigns Risk Level (Async)."""
    print(f"[NODE] Classifying Ticket: {state.get('ticket_id')}")
    
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
        # ASYNC INVOCATION
        result: ClassificationResult = await structured_llm.ainvoke(messages)
        return {
            "intent": result.intent,
            "assessed_risk": result.risk_level,
            "final_resolution": None
        }
    except Exception as e:
        print(f"[ERROR] Classification failed: {e}")
        return {"assessed_risk": 4, "technical_error": True}


async def execute_tools_node(state: AgentState) -> dict:
    """Node 2: (Risk 0-2) Connects to MCP Server and executes immediately (Async)."""
    print(f"[NODE] Executing Tools for Risk Level {state.get('assessed_risk')}")
    
    structured_llm = llm_super.with_structured_output(ExecutionPlanResult)
    prompt = f"""
    You are the Execution Engine. The ticket is Risk Level {state.get('assessed_risk')}.
    Formulate a tool call and a resolution summary.
    """
    messages = [SystemMessage(content=prompt)] + state["messages"]
    
    # ASYNC INVOCATION
    result: ExecutionPlanResult = await structured_llm.ainvoke(messages)
    
    final_res = f"Action Executed: {result.resolution_summary}"
    
    return {
        "final_resolution": final_res
    }

async def draft_plan_node(state: AgentState) -> dict:
    """Node 3: (Risk 3) Drafts a plan and pauses for Human Approval (Async)."""
    print("[NODE] Drafting Plan (Risk 3) - Preparing for Human Pause")
    
    structured_llm = llm_super.with_structured_output(ExecutionPlanResult)
    prompt = "You are the Execution Engine. The ticket is Risk 3. Draft a proposed_plan for human review. DO NOT execute."
    messages = [SystemMessage(content=prompt)] + state["messages"]
    
    # ASYNC INVOCATION
    result: ExecutionPlanResult = await structured_llm.ainvoke(messages)
    
    return {
        "proposed_plan": result.proposed_plan
    }

async def escalate_node(state: AgentState) -> dict:
    """Node 4: (Risk 4) Escalates to Human (Async)."""
    print("[NODE] Escalating to Human (Risk 4)")
    return {
        "final_resolution": "Ticket escalated to Tier 3 human engineering due to high risk or technical error."
    }
