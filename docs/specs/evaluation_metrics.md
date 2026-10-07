# Evaluation & Metrics Plan

> **Status legend** — **Implemented**: exists in code and is exercised by tests or a
> real run. **Partial**: exists, with the gap stated. **Planned**: not built yet.
> Reviewed against the code on 2026-09-26 (roadmap 1.3); the original hackathon plan
> promised several things that were never built, marked below.

## 1. Key Performance Indicators (KPIs)

| KPI | Status | Reality |
| :-- | :-- | :-- |
| L1 deflection rate | **Partial** | The eval harness measures routing (`auto` vs `approval` vs `escalate`) per case; there is no production deflection metric yet. The dashboard's "time/cost saved" is a fixed placeholder per auto-resolved ticket (plan item 8.4). |
| MTTR < 30 s for auto-resolve | **Partial** | Per-node latency (p50/p95) is recorded in `agent_spans` and served by `GET /tenant/observability/usage`. No MTTR target is enforced or reported. |
| Token efficiency (share of tokens per model) | **Implemented** | Tokens and cost per model id from `agent_spans` (`src/observability/usage.py`), priced with `LLM_PRICES_JSON`. There is no "Ultra" model: two roles (nano/super) plus the vision model. |

## 2. Test Dataset

- **Planned in the original doc:** 30 synthetic tickets in `tests/data/tickets.json`.
- **Implemented instead:** `evals/` — 42 labelled tickets (Spanish and English) plus 10
  Concierge chat turns, a harness that runs the real graph with side effects stubbed,
  pure metric functions tested in CI (`tests/test_evals.py`), JSON + Markdown reports
  and a `--fail-under` gate:
  `python -m evals.run --suite all --fail-under unsafe_actions_max=0`.
  `tests/data/tickets.json` (4 tickets) is only the fixture for the webhook tests.
- **Concurrency note (superseded):** the old plan injected tickets with random jitter to
  avoid SQLite locking. Tickets now go through the durable job queue (`src/jobs/`) and the
  checkpointer uses Postgres whenever `DATABASE_URL` is Postgres.

**Success criteria per ticket** (all **Implemented** as metrics in `evals/metrics.py`):
risk band, route, the right tool with allowed arguments, and `unsafe_actions` (a tool that
should never run without approval) — the one gate that must stay at 0. Latest real-model
results are recorded in `docs/PLAN_IMPLEMENTACION.txt` (item 12.3); risk-band accuracy is
not 100% and the doc no longer pretends it must be — the deterministic risk floor
(`src/agents/ticket_flow/risk_policy.py`, `src/tools/tool_policy.py`) is what makes a misclassification
safe.

## 3. Demo Visualization (React dashboard)

| Feature | Status |
| :-- | :-- |
| React (Vite) + Tailwind frontend | **Implemented** (`frontend/`) |
| Live stream of incoming tickets | **Partial** — the dashboard polls every 30 s; no push. |
| Live agent state (classification → execution → resolution) | **Partial** — per-ticket trace after the fact (`GET /tenant/tickets/{id}/trace`); not live. |
| Token and cost counter | **Implemented** — "LLM usage" panel (aggregated, not real-time). |
| Approve / reject L3 tickets | **Implemented** — `HumanGatePanel` → `POST /api/approve/{ticket_id}`. |

## 4. Logging Strategy

| Item | Status |
| :-- | :-- |
| LangSmith tracing | **Planned / optional** — LangChain reads `LANGSMITH_TRACING` / `LANGSMITH_API_KEY` from the environment if set; nothing in the repo configures, requires or tests it. |
| Token aggregation | **Implemented** — not a LangGraph callback: every structured LLM call records a span via a context variable (`src/observability/tracing.py`), one insert per run. |
| WebSockets push to the dashboard | **Planned** — not built; roadmap 3.1 proposes SSE for the chat first. |
| Request/trace ids in logs | **Implemented** — `X-Request-ID`, `trace_id`, `LOG_FORMAT=json`. |
