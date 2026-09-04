# Ops & Policy Runbook

## 1. Startup Commands (Local Dev)
To spin up the Aether environment:

1. **Activate Virtual Environment:**
   ```bash
   # Windows
   .\.venv\Scripts\Activate.ps1
   ```
2. **Start FastAPI Backend:**
   ```bash
   uvicorn src.main:app --reload --port 8000
   ```
3. **Expose Webhook (Optional):**
   ```bash
   ngrok http 8000
   ```

## 2. Debugging Common Errors

### 2.1 LLM Parsing Error
**Symptom:** Graph loops infinitely or crashes with `pydantic.ValidationError`.
**Fix:** Check `docs/specs/prompts_and_models.md`. Ensure Nebius Token Factory is receiving the `response_format={ "type": "json_object" }` flag in the OpenAI SDK call.

### 2.2 OpenShell Policy Block
**Symptom:** Tool execution returns "Permission Denied" or "Network Unreachable".
**Fix:** The MCP tool is attempting to access an IP outside the whitelist. Check the mock server IP and add it to the OpenShell configuration manifest.

### 2.3 Ticket State Lost (Human Approval Timeout)
**Symptom:** Approving a Level 3 ticket returns a 404 Thread Not Found.
**Fix:** The SQLite database is corrupt or locked. Delete `checkpoints.sqlite` and restart the Uvicorn server.

## 3. How to Modify Risk Policies safely
Do NOT try to prompt the LLM to change risk logic. Risk logic is hardcoded in `src/agent/nodes.py`.
To mandate that "Software Installs" become Level 3 (require approval), modify the `RISK_MAPPING` dictionary in Python.
