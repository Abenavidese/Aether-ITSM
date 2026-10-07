# MCP Tooling Registry & Policies

> **Status** (reviewed against the code on 2026-09-26, roadmap 1.3): the MCP *protocol*
> path is **Implemented** — a real MCP server (`src/tools/mcp_server.py`) over stdio, a
> client that reads its live catalog (`src/tools/mcp_client.py`) and a default-deny policy
> in code (`src/tools/tool_policy.py`). The tool *backends* are **simulated**: except
> `check_service_status`, every tool returns a canned JSON result and touches no real
> VPN, MDM, IAM or knowledge system. Wiring them to real systems is **Planned**.

## 1. Concept
The MCP server exposes strict, parameterized functions. The LLM can only *propose* a call
(`tool_name` + `tool_args` in a Pydantic schema); `tool_policy.authorize()` decides in code
whether it runs. The model never executes scripts.

## 2. Tool Inventory

Risk levels and parameters below are the ones enforced by `TOOL_POLICY` in
`src/tools/tool_policy.py` — the source of truth; tools not listed there are refused.

### 2.1 `reset_vpn_session` — risk 2 — backend simulated
- **Parameters:** `user_id` — an *identity* parameter: bound to the ticket's requester by
  code and hidden from the model's catalog, so the agent can't act on someone else's account.
- **Policy:** runs autonomously when the ticket's assessed risk is ≥ 2 and Policy approved.

### 2.2 `provision_standard_software` — risk 2 — backend simulated
- **Parameters:** `user_id` (identity, as above), `software_id`.
- **Policy:** `software_id` must be in `MDM_SOFTWARE_WHITELIST` (validated in code); anything
  else is refused.

### 2.3 `modify_iam_access` — risk 3 — backend simulated
- **Parameters:** `user_id` (identity), `resource_arn`, `access_level`.
- **Policy:** **requires human approval.** `draft_plan` stores the exact validated call;
  after `POST /api/approve/{ticket_id}` that frozen call runs with no LLM involved.

### 2.4 `query_knowledge_base` — risk 0 — backend simulated
- **Parameters:** `query_string`.
- **Note:** returns two fixed sentences. The real knowledge base is the tenant's RAG store
  (`src/rag/`), which the agents query directly in code, not through this tool.

### 2.5 `check_service_status` — risk 0 — **real**
- **Parameters:** `service_url` — must be one of the tenant's configured monitored services;
  public addresses only, no redirects (`src/security/url_guard.py`).

## 3. Security Boundary & Retry Logic
- **Unknown tool or bad arguments — Implemented.** An unregistered tool, a tool riskier than
  the ticket, an argument outside the tool's schema or a failed validator raises
  `ToolPolicyViolation` before any call; the node escalates (or raises the ticket's risk once
  and re-runs Policy, for a tool that simply needs more approval).
- **Retries — Implemented, differently than first specified.** The original doc said
  exactly 1 retry. `src/llm/structured_output.py` allows 2 self-correction retries for
  output that fails schema validation, re-sending the original prompt plus a short error
  summary (never the failed output). After that the node reports `technical_error` and the
  graph escalates.
