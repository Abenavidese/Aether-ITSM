# MCP Tooling Registry & Policies

## 1. Concept
The Model Context Protocol (MCP) servers expose strict, parameterized functions. The LLM can only request these functions; it cannot execute raw scripts.

## 2. Tool Inventory

### 2.1 `reset_vpn_session`
- **Description:** Terminates active VPN sessions for a specific user to fix hung connections.
- **Expected Parameters:**
  - `user_id` (string): The corporate email or ID.
- **Default Risk Level:** 2 (Low / Reversible)
- **Allowed Environments:** Dev, Prod.
- **Policy Rule:** Fully autonomous execution allowed.

### 2.2 `provision_standard_software`
- **Description:** Adds a user to an AD group that triggers an automated MDM (Mobile Device Management) software install.
- **Expected Parameters:**
  - `user_id` (string): The corporate email.
  - `software_id` (string): Standardized ID (e.g., `pkg_office365`, `pkg_docker`).
- **Default Risk Level:** 2 (Low / Reversible)
- **Allowed Environments:** Dev, Prod.
- **Policy Rule:** Fully autonomous execution allowed ONLY if `software_id` is in the whitelist.

### 2.3 `modify_iam_access`
- **Description:** Modifies cloud or directory access policies.
- **Expected Parameters:**
  - `user_id` (string): The corporate email.
  - `resource_arn` (string): The resource identifier.
  - `access_level` (string): e.g., `ReadOnly`, `Admin`.
- **Default Risk Level:** 3 (High)
- **Allowed Environments:** Dev, Prod.
- **Policy Rule:** **REQUIRES HUMAN APPROVAL.** The LLM may only draft the parameters. Execution is paused until webhook confirmation.

### 2.4 `query_knowledge_base`
- **Description:** Performs a semantic search over internal Tier 1 support documentation.
- **Expected Parameters:**
  - `query_string` (string): The search query.
- **Default Risk Level:** 0 (Read-Only)
- **Allowed Environments:** All.
- **Policy Rule:** Fully autonomous. Never requires approval.

## 3. Security Boundary & Retry Logic
If the LLM generates a tool call for a tool not in this registry, or attempts to pass parameters that violate the JSON schema, the `Pydantic` validator in the FastAPI backend will throw a `ValidationError`.

**Retry Policy:** 
- The agent is permitted exactly **1 internal retry**. The error message is fed back to the LLM (e.g., *"JSON schema invalid, please correct the 'user_id' field"*).
- If the LLM fails on the second attempt, the Graph immediately routes to the `Error Edge` and escalates the ticket to Risk Level 4, abandoning automated resolution.
