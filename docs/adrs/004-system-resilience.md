# ADR-004: System Resilience & Technical Fallbacks

## Status
Accepted

## Context
Enterprise ITSM integrations have strict SLAs. A failure in the AI agent or a timeout in the API layer can result in infinite webhook retries, duplicate tickets, or silent failures where a user is left waiting indefinitely.

## Decisions

### 1. Asynchronous Webhook Processing
**Problem:** ITSM platforms (ServiceNow, Jira) expect webhook responses within 3-10 seconds. LangGraph LLM cycles can take 15-45 seconds.
**Decision:** The FastAPI webhook endpoint will immediately return `202 Accepted`. The actual LangGraph invocation will be pushed to FastAPI `BackgroundTasks` (or Celery/Redis for Phase 3). The agent will asynchronously update the ITSM ticket via API when it finishes.

### 2. State Persistence (Checkpointer)
**Problem:** LangGraph requires persistent memory to execute the "Assist-and-Gate" (Level 3) pause mechanism. If the server restarts while waiting for human approval, the state is lost.
**Decision:** We will use `SqliteSaver` for the MVP Hackathon phase to persist LangGraph thread states locally. For the production SaaS (Phase 3), this will be migrated to `AsyncPostgresSaver`.

### 3. Technical Error Routing
**Problem:** The LLM API (Nebius) may experience temporary downtime, or the LLM may fail to produce a valid JSON schema after multiple retries.
**Decision:** The LangGraph definition will include a global `Error Edge`. If a node throws an unhandled exception or parsing fails repeatedly, the graph routes directly to the `escalate_node` (Level 4), appending a system note: *"Technical failure in Aether. Manual intervention required."*

### 4. Context Window Management
**Problem:** Appending the entire ticket history (which may contain dozens of comments) to every LLM prompt will consume excessive Nebius Token Factory credits and increase latency.
**Decision:** We will implement a `SummarizerNode` using Nemotron-Nano. If the `messages` array exceeds 2000 tokens, Nano will compress the historical context into a dense summary before passing the state to Nemotron-Super for execution.

## Consequences
- Development complexity increases slightly due to background task handling.
- We require a local SQLite database file for the MVP, meaning the container must have a persistent volume.
- System reliability and cost-efficiency are significantly increased, fulfilling Enterprise-grade requirements.
