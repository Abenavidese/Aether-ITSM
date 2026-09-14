import json
import logging
from langchain_core.messages import SystemMessage
from .state import AgentState, ClassificationResult, ExecutionPlanResult, PolicyCheckResult
from src.config import get_llms
from src.rag.service import retrieve_context

logger = logging.getLogger(__name__)

async def supervisor_node(state: AgentState) -> dict:
    """Node 1: Supervisor - Evaluates ticket, assigns Risk Level, and routes to next sub-agent."""
    logger.info("Supervisor Agent analyzing Ticket: %s", state.get('ticket_id'))
    
    llm_nano, _ = get_llms()
    structured_llm = llm_nano.with_structured_output(ClassificationResult)
    
    prompt = f"""
    You are the Supervisor Agent for Aether ITSM.
    Analyze the user's IT support ticket and route it.
    Ticket ID: {state.get('ticket_id')}
    Context: {json.dumps(state.get('user_context', {}))}
    
    Assign a risk_level:
    0 = Generic Question / FAQ (Can be solved simply by asking Execution Agent to read docs)
    1-2 = Low Risk Action (e.g. Reset VPN, Install standard software)
    3 = High Risk Action (e.g. Modify IAM, Admin access)
    4 = Escalate (Technical error, vague request, or dangerous)
    """
    
    messages = [SystemMessage(content=prompt)] + state["messages"]
    
    try:
        result: ClassificationResult = await structured_llm.ainvoke(messages)
        
        # Swarm Routing Logic
        next_ag = "escalate"
        if result.risk_level == 0:
            next_ag = "execution"  # Safe to execute directly (no policy check needed for FAQs)
        elif result.risk_level in [1, 2, 3]:
            next_ag = "policy"     # Must pass compliance check
        
        return {
            "intent": result.intent,
            "assessed_risk": result.risk_level,
            "next_agent": next_ag,
            "final_resolution": None
        }
    except Exception as e:
        logger.error("Supervisor failed: %s", e, exc_info=True)
        return {"assessed_risk": 4, "next_agent": "escalate", "technical_error": True}


async def policy_agent_node(state: AgentState) -> dict:
    """Node 2: Compliance - Checks the user's request against Company Policy."""
    logger.info("Policy Agent evaluating compliance for Risk Level %s", state.get('assessed_risk'))
    
    _, llm_super = get_llms()
    structured_llm = llm_super.with_structured_output(PolicyCheckResult)
    
    user_query = state["messages"][-1].content if state["messages"] else ""
    tenant_id = state.get("user_context", {}).get("tenant_id")
    
    rag_context = ""
    if tenant_id and user_query:
        # Policy agent specifically queries the company_policy RAG
        rag_context = retrieve_context(tenant_id, user_query, source_type="company_policy")
        
    prompt = f"""
    You are the Compliance & Security Agent.
    The user wants to perform an action (Intent: {state.get('intent')}).
    Check if this action violates any Company Policies.
    
    Company Policy Context:
    {rag_context if rag_context else "No specific company policy context found. Assume standard safe IT practices."}
    
    Evaluate if this request is compliant.
    """
    
    messages = [SystemMessage(content=prompt)] + state["messages"]
    
    try:
        result: PolicyCheckResult = await structured_llm.ainvoke(messages)
        
        # Route based on compliance and risk
        if not result.is_compliant:
            next_ag = "escalate"
        else:
            if state.get("assessed_risk") == 3:
                next_ag = "draft_plan"
            else:
                next_ag = "execution"
                
        return {
            "compliance_passed": result.is_compliant,
            "compliance_notes": result.reason,
            "next_agent": next_ag
        }
    except Exception as e:
        logger.error("Policy Agent failed: %s", e, exc_info=True)
        return {"compliance_passed": False, "compliance_notes": "Policy check failed due to technical error.", "next_agent": "escalate", "technical_error": True}


async def execution_agent_node(state: AgentState) -> dict:
    """Node 3: Execution - Formulates tools/resolution using Technical Docs."""
    logger.info("Execution Agent running for Ticket: %s", state.get('ticket_id'))
    
    _, llm_super = get_llms()
    structured_llm = llm_super.with_structured_output(ExecutionPlanResult)
    user_query = state["messages"][-1].content if state["messages"] else ""
    tenant_id = state.get("user_context", {}).get("tenant_id")
    
    rag_context = ""
    ai_feedback = ""
    if tenant_id and user_query:
        # Execution agent queries technical docs (or company policy if risk 0)
        source = "company_policy" if state.get('assessed_risk') == 0 else "technical_repo"
        rag_context = retrieve_context(tenant_id, user_query, source_type=source)
        ai_feedback = retrieve_context(tenant_id, user_query, source_type="ai_feedback", top_k=2)
        
    prompt = f"""
    You are the Execution Agent. 
    The ticket is Risk Level {state.get('assessed_risk')}.
    Compliance Check Notes: {state.get('compliance_notes', 'N/A')}
    Formulate a tool call and a resolution summary.
    
    Knowledge Base Context:
    {rag_context if rag_context else "No specific context found."}
    
    Previous Admin Feedback on similar issues (LEARN FROM THIS):
    {ai_feedback if ai_feedback else "No previous feedback found."}
    """
    messages = [SystemMessage(content=prompt)] + state["messages"]
    
    try:
        result: ExecutionPlanResult = await structured_llm.ainvoke(messages)
        final_res = f"Action Executed: {result.resolution_summary}"
        return {"final_resolution": final_res}
    except Exception as e:
        logger.error("Execution Agent failed: %s", e, exc_info=True)
        return {"final_resolution": "Execution failed — escalating.", "next_agent": "escalate", "technical_error": True}


async def draft_plan_node(state: AgentState) -> dict:
    """Node 4: Drafts a plan and pauses for Human Approval (Async)."""
    logger.info("Execution Agent drafting plan (Risk 3) - Preparing for Human Pause")
    
    _, llm_super = get_llms()
    structured_llm = llm_super.with_structured_output(ExecutionPlanResult)
    prompt = "You are the Execution Agent. The ticket is Risk 3 and has passed Compliance. Draft a proposed_plan for human review. DO NOT execute."
    messages = [SystemMessage(content=prompt)] + state["messages"]
    
    try:
        result: ExecutionPlanResult = await structured_llm.ainvoke(messages)
        return {"proposed_plan": result.proposed_plan}
    except Exception as e:
        logger.error("Draft plan failed: %s", e, exc_info=True)
        return {"proposed_plan": "Failed to draft plan due to technical error.", "next_agent": "escalate", "technical_error": True}


async def escalate_node(state: AgentState) -> dict:
    """Node 5: Escalates to Human."""
    logger.info("Escalating to Human (Risk 4 or Non-Compliant)")
    
    reason = "high risk or technical error"
    if state.get("compliance_passed") is False:
        reason = f"Company Policy Violation: {state.get('compliance_notes')}"
        
    return {
        "final_resolution": f"Ticket escalated to Tier 3 human engineering due to: {reason}."
    }
