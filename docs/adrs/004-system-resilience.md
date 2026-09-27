# ADR-004: System Resilience & Technical Fallbacks

## Status
Accepted — partially superseded. Each decision below carries its implementation status,
reviewed against the code on 2026-09-26 (roadmap 1.3).

## Context
Enterprise ITSM integrations have strict SLAs. A failure in the AI agent or a timeout in the API layer can result in infinite webhook retries, duplicate tickets, or silent failures where a user is left waiting indefinitely.

## Decisions

### 1. Asynchronous Webhook Processing — Implemented (mechanism superseded); ITSM callback Planned
**Problem:** ITSM platforms (ServiceNow, Jira) expect webhook responses within 3-10 seconds. LangGraph LLM cycles can take 15-45 seconds.

**Original decision:** return `202 Accepted` and run the graph in FastAPI `BackgroundTasks`, then update the ITSM ticket via API when finished.

**What exists:**
- `202 Accepted` immediately — **Implemented** (`POST /api/webhook/ticket`).
- `BackgroundTasks` was **replaced** by a durable job queue in the same database
  (`src/jobs/`, roadmap 2.2): the ticket and its job are written in one transaction,
  retries with backoff, crash-resume from the last checkpoint, dead-letter → escalated
  ticket. `BackgroundTasks` lost every in-flight ticket on restart.
- Duplicate webhooks — **Implemented**: `(tenant_id, external_id)` is unique; a
  re-delivered ticket is acknowledged and not reprocessed.
- Updating the ITSM ticket when the agent finishes — **Planned** (roadmap 3.6: signed
  callback to the tenant's ITSM). Today the result is visible in Aether's dashboard and,
  on escalation, in a GitHub issue.

### 2. State Persistence (Checkpointer) — Implemented
`src/agent/checkpointer.py` picks `AsyncPostgresSaver` when `DATABASE_URL` is Postgres and
`AsyncSqliteSaver` otherwise (`CHECKPOINT_BACKEND=auto|sqlite|postgres`), so paused L3
threads survive restarts and several workers can share them.

### 3. Technical Error Routing — Implemented
There is no single global "error edge"; each node catches its own failure and sets
`technical_error`, and every routing function (`src/agent/graph.py`) sends
`technical_error` to `escalate`. A structured-output call that still fails validation after
its retries (`src/agent/structured_output.py`) raises into that same path. A job that keeps
failing is dead-lettered and its ticket escalated (`run_ticket_dead`).

### 4. Context Window Management — Implemented differently (no SummarizerNode)
**Original decision:** a `SummarizerNode` (Nano) compressing history above 2000 tokens —
**not built**.

**What exists:** `src/agent/context_budget.py` keeps every prompt inside the model's window:
the system prompt and the latest message always stay, history is added newest-first while
it fits (older turns are dropped, not summarized). This is also a security control: Ollama
truncates an oversized prompt from the start, i.e. it would drop the system prompt first.
Attached images are read once into text (`src/agent/vision.py`) instead of travelling in
every prompt. Summarizing dropped history remains a possible improvement (**Planned**, not
scheduled).

## Consequences
- The queue adds a worker process (embedded in the API for dev, `python -m src.jobs.worker`
  in production) instead of background-task complexity.
- No local SQLite file is required in production: Postgres holds tickets, jobs and
  checkpoints.
