import json
import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from .state import AgentState, ClassificationResult, ExecutionPlanResult, EscalateResult

# Configuration (Points to Nebius if NEBIUS_API_KEY is set, else defaults to OpenAI for testing)
api_key = os.getenv("NEBIUS_API_KEY", os.getenv("OPENAI_API_KEY", "dummy"))
base_url = "https://api.studio.nebius.ai/v1/" if os.getenv("NEBIUS_API_KEY") else None

# Initialize LLM Models (Using gpt-4o-mini as a proxy for Nemotron Nano if Nebius is not configured yet)
llm_nano = ChatOpenAI(model="gpt-4o-mini", temperature=0.0, api_key=api_key, base_url=base_url)
llm_super = ChatOpenAI(model="gpt-4o", temperature=0.0, api_key=api_key, base_url=base_url)

def classify_node(state: AgentState) -> dict:
    """Node 1: Evaluates ticket and assigns Risk Level."""
    print(f"[NODE] Classifying Ticket: {state.get('ticket_id')}")
    
    # We use LangChain's structured output parser to force JSON
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
    
    # Invoke the LLM
    try:
        result: ClassificationResult = structured_llm.invoke(messages)
        return {
            "intent": result.intent,
            "assessed_risk": result.risk_level,
            "final_resolution": None
        }
    except Exception as e:
        print(f"[ERROR] Classification failed: {e}")
        return {"assessed_risk": 4, "technical_error": True}


def execute_tools_node(state: AgentState) -> dict:
    """Node 2: (Risk 0-2) Connects to MCP Server and executes immediately."""
    print(f"[NODE] Executing Tools for Risk Level {state.get('assessed_risk')}")
    
    # In a real environment, we would use the MCP SDK stdio client here.
    # For now, we simulate the LLM choosing a tool based on the intent.
    # We use Nemotron Super to decide the exact parameters.
    
    structured_llm = llm_super.with_structured_output(ExecutionPlanResult)
    prompt = f"""
    You are the Execution Engine. The ticket is Risk Level {state.get('assessed_risk')}.
    Formulate a tool call and a resolution summary.
    """
    messages = [SystemMessage(content=prompt)] + state["messages"]
    result: ExecutionPlanResult = structured_llm.invoke(messages)
    
    # Simulate execution success
    final_res = f"Action Executed: {result.resolution_summary}"
    
    return {
        "final_resolution": final_res
    }

def draft_plan_node(state: AgentState) -> dict:
    """Node 3: (Risk 3) Drafts a plan and pauses for Human Approval."""
    print("[NODE] Drafting Plan (Risk 3) - Preparing for Human Pause")
    
    structured_llm = llm_super.with_structured_output(ExecutionPlanResult)
    prompt = "You are the Execution Engine. The ticket is Risk 3. Draft a proposed_plan for human review. DO NOT execute."
    messages = [SystemMessage(content=prompt)] + state["messages"]
    result: ExecutionPlanResult = structured_llm.invoke(messages)
    
    return {
        "proposed_plan": result.proposed_plan
    }

def escalate_node(state: AgentState) -> dict:
    """Node 4: (Risk 4) Escalates to Human."""
    print("[NODE] Escalating to Human (Risk 4)")
    return {
        "final_resolution": "Ticket escalated to Tier 3 human engineering due to high risk or technical error."
    }
