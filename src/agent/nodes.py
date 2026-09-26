import json
import logging
from langchain_core.runnables import RunnableConfig
from .context_budget import build_prompt
from .mcp_client import MCPToolClient
from .risk_policy import enforce_risk_floor
from .state import AgentState, ClassificationResult, ExecutionPlanResult, PolicyCheckResult
from .structured_output import invoke_structured as _invoke_structured
from .tool_policy import (
    AuthorizedToolCall, ToolCallContext, ToolPolicyViolation, allowed_tools, authorize, identity_params, normalize_url,
    risk_of_tools,
)
from src.config import get_llms
from src.integrations.monitoring import get_monitored_services
from src.rag.service import retrieve_context
from src.security.prompt_safety import UNTRUSTED_DATA_POLICY, untrusted_block

logger = logging.getLogger(__name__)


def _tool_context(state: AgentState, *, human_approved: bool | None = None) -> ToolCallContext:
    """Authorization context built from state/config only — never from LLM output."""
    user_context = state.get("user_context", {})
    tenant_id = user_context.get("tenant_id")
    services = get_monitored_services(tenant_id) if tenant_id else []
    return ToolCallContext(
        requester=user_context.get("email"),
        assessed_risk=state.get("assessed_risk", 4),
        human_approved=state.get("human_approved") is True if human_approved is None else human_approved,
        allowed_service_urls=frozenset(normalize_url(s["url"]) for s in services),
    )


async def supervisor_node(state: AgentState) -> dict:
    """Node 1: Supervisor - Evaluates ticket, assigns Risk Level, and routes to next sub-agent."""
    logger.info("Supervisor Agent analyzing Ticket: %s", state.get('ticket_id'))

    llm_nano, _ = get_llms()

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

    messages = build_prompt(prompt, state["messages"])

    try:
        result: ClassificationResult = await _invoke_structured(llm_nano, ClassificationResult, messages)

        ticket_text = state["messages"][-1].content if state["messages"] else ""
        if not isinstance(ticket_text, str):
            ticket_text = json.dumps(ticket_text)
        assessed_risk, floor_reason = enforce_risk_floor(ticket_text, result.risk_level)
        # Second floor source: if the classifier itself says the ticket needs
        # a risk-3 tool, the ticket is at least risk 3, whatever number it gave.
        tools_floor = risk_of_tools(result.tools_required)
        if tools_floor > assessed_risk:
            assessed_risk, floor_reason = tools_floor, f"requires tools {result.tools_required}"
        if floor_reason:
            logger.warning(
                "Risk floor enforced for ticket %s: model classified risk %d, forcing %d (%s)",
                state.get('ticket_id'), result.risk_level, assessed_risk, floor_reason
            )

        # Swarm Routing Logic
        next_ag = "escalate"
        if assessed_risk == 0:
            next_ag = "execution"  # Safe to execute directly (no policy check needed for FAQs)
        elif assessed_risk in [1, 2, 3]:
            next_ag = "policy"     # Must pass compliance check

        return {
            "intent": result.intent,
            "assessed_risk": assessed_risk,
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
    {UNTRUSTED_DATA_POLICY}

    Company Policy Context:
    {untrusted_block("company_policy", rag_context) or "No specific company policy context found. Assume standard safe IT practices."}

    Evaluate if this request is compliant.
    """

    messages = build_prompt(prompt, state["messages"])

    try:
        result: PolicyCheckResult = await _invoke_structured(llm_super, PolicyCheckResult, messages)

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


async def _run_tool(mcp_client: MCPToolClient, call: AuthorizedToolCall, ticket_id) -> str:
    output = await mcp_client.call_tool(call.name, call.args)
    logger.info("MCP tool '%s' executed for ticket %s", call.name, ticket_id)
    return output


async def _execute_approved_plan(state: AgentState, mcp_client: MCPToolClient) -> dict:
    """
    Runs EXACTLY the action a human approved — no LLM involved (Fase 11.2).
    Asking the model again after approval (the previous behavior) meant the
    call that ran could differ from the one the admin saw.
    """
    action = state.get("planned_action")
    if not action:
        return {"action_refused": "the approved plan has no automated action; an engineer must carry it out"}
    try:
        call = authorize(action.get("tool_name"), action.get("tool_args"), _tool_context(state))
    except ToolPolicyViolation as e:
        logger.warning("Approved action refused at execution time for ticket %s: %s", state.get("ticket_id"), e)
        return {"action_refused": e.reason}
    tool_output = await _run_tool(mcp_client, call, state.get("ticket_id"))
    return {"final_resolution": f"Action Executed (human-approved): {call.describe()}\nTool result: {tool_output}"}


async def execution_agent_node(state: AgentState, config: RunnableConfig) -> dict:
    """Node 3: Execution - Formulates a resolution and, if the ticket requires
    a real-world action, dispatches it to the FastMCP tool server (see
    src/agent/mcp_client.py). The mcp_client is injected via LangGraph's own
    `configurable` mechanism (same pattern already used for thread_id) rather
    than a module-level global, so it stays swappable/mockable per run.

    The model only PROPOSES a tool call; tool_policy.authorize decides.
    """
    logger.info("Execution Agent running for Ticket: %s", state.get('ticket_id'))

    mcp_client: MCPToolClient = config["configurable"]["mcp_client"]
    if state.get("human_approved") is True:
        try:
            return await _execute_approved_plan(state, mcp_client)
        except Exception as e:
            logger.error("Approved plan execution failed: %s", e, exc_info=True)
            return {"final_resolution": "Execution failed — escalating.", "next_agent": "escalate", "technical_error": True}

    _, llm_super = get_llms()
    user_query = state["messages"][-1].content if state["messages"] else ""
    tenant_id = state.get("user_context", {}).get("tenant_id")

    rag_context = ""
    ai_feedback = ""
    if tenant_id and user_query:
        # Execution agent queries technical docs (or company policy if risk 0)
        source = "company_policy" if state.get('assessed_risk') == 0 else "technical_repo"
        rag_context = retrieve_context(tenant_id, user_query, source_type=source)
        ai_feedback = retrieve_context(tenant_id, user_query, source_type="ai_feedback", top_k=2)

    ctx = _tool_context(state)
    monitored_services = get_monitored_services(tenant_id) if tenant_id else []
    services_note = ""
    if monitored_services:
        services_list = "\n".join(f"- {s['name']}: {s['url']}" for s in monitored_services)
        services_note = f"""
    Monitored services for this tenant (use check_service_status against the
    matching URL BEFORE assuming a "can't connect / can't log in" report is a
    user-side problem):
    {services_list}
    """

    prompt = f"""
    You are the Execution Agent.
    The ticket is Risk Level {state.get('assessed_risk')}.
    Formulate a tool call and a resolution summary.
    {UNTRUSTED_DATA_POLICY}

    Compliance Check Notes:
    {untrusted_block("compliance_notes", state.get('compliance_notes') or '') or "N/A"}

    Knowledge Base Context:
    {untrusted_block("knowledge_base", rag_context) or "No specific context found."}

    Previous Admin Feedback on similar issues (LEARN FROM THIS):
    {untrusted_block("admin_feedback", ai_feedback) or "No previous feedback found."}
    {services_note}
    Available tools (call exactly one if the ticket requires a real action;
    leave tool_name null for a purely informational answer). Tools always act
    on the requesting user's own account (never pass who it is for):
    {mcp_client.prompt_catalog(only=allowed_tools(ctx), hidden_params=identity_params())}
    If you set tool_name, tool_args must match that tool's parameters exactly.
    """
    messages = build_prompt(prompt, state["messages"])

    try:
        result: ExecutionPlanResult = await _invoke_structured(llm_super, ExecutionPlanResult, messages)

        tool_output = None
        if result.tool_name:
            try:
                call = authorize(result.tool_name, result.tool_args, ctx)
            except ToolPolicyViolation as e:
                logger.warning("Tool call refused for ticket %s: %s", state.get('ticket_id'), e)
                return {"action_refused": e.reason}
            tool_output = await _run_tool(mcp_client, call, state.get('ticket_id'))

        final_res = f"Action Executed: {result.resolution_summary}"
        if tool_output:
            final_res += f"\nTool result: {tool_output}"

        return {"final_resolution": final_res}
    except Exception as e:
        logger.error("Execution Agent failed: %s", e, exc_info=True)
        return {"final_resolution": "Execution failed — escalating.", "next_agent": "escalate", "technical_error": True}


async def draft_plan_node(state: AgentState, config: RunnableConfig) -> dict:
    """
    Node 4: Drafts a plan and pauses for Human Approval (Async).

    The plan carries a STRUCTURED action (planned_action), validated now as
    if approved, and its exact form is appended to the text the admin reads
    — so what the human approves is literally what execution will run.
    """
    logger.info("Execution Agent drafting plan (Risk 3) - Preparing for Human Pause")

    _, llm_super = get_llms()
    mcp_client: MCPToolClient = config["configurable"]["mcp_client"]
    ctx_if_approved = _tool_context(state, human_approved=True)
    prompt = f"""
    You are the Execution Agent. The ticket is Risk 3 and has passed Compliance.
    Draft a proposed_plan for human review. DO NOT execute.
    If an available tool can carry out the plan, also set tool_name and
    tool_args: that exact call is what will run if a human approves.
    Tools always act on the requesting user's own account (never pass who it is for).
    {UNTRUSTED_DATA_POLICY}
    Available tools:
    {mcp_client.prompt_catalog(only=allowed_tools(ctx_if_approved), hidden_params=identity_params())}
    """
    messages = build_prompt(prompt, state["messages"])

    try:
        result: ExecutionPlanResult = await _invoke_structured(llm_super, ExecutionPlanResult, messages)
    except Exception as e:
        logger.error("Draft plan failed: %s", e, exc_info=True)
        return {"proposed_plan": "Failed to draft plan due to technical error.", "next_agent": "escalate", "technical_error": True}

    plan_text = result.proposed_plan or result.resolution_summary
    planned_action = None
    if result.tool_name:
        try:
            call = authorize(result.tool_name, result.tool_args, ctx_if_approved)
            planned_action = call.to_dict()
            plan_text += f"\n\nExact action that will run on approval: {call.describe()}"
        except ToolPolicyViolation as e:
            logger.warning("Draft plan proposed a refused action for ticket %s: %s", state.get("ticket_id"), e)
            plan_text += f"\n\nNo automated action (proposed call refused by policy: {e.reason}). Approval hands it to an engineer."
    else:
        plan_text += "\n\nNo automated action: approval hands it to an engineer."
    return {"proposed_plan": plan_text, "planned_action": planned_action}


async def escalate_node(state: AgentState) -> dict:
    """Node 5: Escalates to Human."""
    logger.info("Escalating to Human (Risk 4 or Non-Compliant)")

    reason = "high risk or technical error"
    if state.get("compliance_passed") is False:
        reason = f"Company Policy Violation: {state.get('compliance_notes')}"
    elif state.get("human_approved") is False:
        reason = "the proposed plan was rejected by the human reviewer"
    elif state.get("action_refused"):
        reason = f"the automated action was not allowed ({state.get('action_refused')})"

    return {
        "final_resolution": f"Ticket escalated to Tier 3 human engineering due to: {reason}."
    }
