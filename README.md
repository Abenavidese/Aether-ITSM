# Aether ITSM

Multi-tenant IT support agents whose safety does not depend on the model behaving.

Employees describe a problem in a chat (optionally with a screenshot) or an ITSM platform
sends a ticket by webhook. A LangGraph agent swarm classifies the risk, checks company
policy, and either resolves it with a tool call, pauses for a human to approve an exact
action, or escalates to engineering with a GitHub issue. Every decision that matters is
made in code: the model proposes, deterministic policy decides.

> Status of every claim in `docs/` is marked **Implemented / Partial / Planned**. Some
> parts of the original design (OpenShell sandbox, ITSM write-back, Nemotron on Nebius)
> are not built yet, and the VPN/MDM/IAM tool backends are simulated. See
> [What is real](#what-is-real-today).

## Architecture

```mermaid
flowchart LR
    Chat[Employee chat<br/>+ screenshot] --> API
    ITSM[ITSM webhook] -->|202, x-api-key| API[FastAPI]
    API -->|image| Vision[Vision model<br/>screenshot → text]
    API --> Concierge[Concierge<br/>single-turn chat agent]
    API -->|ticket + job,<br/>one transaction| Queue[(Job queue<br/>Postgres)]
    Queue --> Worker[Worker]
    Worker --> Graph

    subgraph Graph[LangGraph ticket swarm]
        Sup[Supervisor<br/>risk 0-4] --> Pol[Policy<br/>RAG] --> Exe[Execution]
        Pol --> Plan[Draft plan<br/>pause for approval]
        Sup --> Esc[Escalate]
    end

    Exe -->|tool_policy.authorize| MCP[MCP tool server<br/>stdio]
    Plan -->|admin approves exact call| Exe
    Esc --> GH[GitHub issue job]
    Concierge --> RAG[(pgvector RAG)]
    Concierge --> Repo[Tenant repo<br/>read-only]
    Concierge --> Logs[Render / Vercel logs<br/>read-only]
```

Key design choices:

- **Deterministic guardrails.** Risk floors (`src/agent/risk_policy.py`) and a default-deny
  per-tool policy (`src/agent/tool_policy.py`) can only raise risk, bind identity arguments
  to the requester, validate arguments and block SSRF. A risk-3 action is frozen at plan
  time and runs exactly as approved, with no LLM in between.
- **Untrusted input stays data.** RAG chunks, repo files, logs, tool output and screenshot
  text are redacted and fenced (`src/security/prompt_safety.py`); the prompt budget keeps the
  system prompt from being truncated away (`src/agent/context_budget.py`).
- **Screenshots → text.** A vision model reads an attached image once (visible error text
  verbatim + a short description); the text-only agents get that text, so risk floors, RAG
  and "read the file from the stack trace" all keep working (`src/agent/vision.py`).
- **Durable work.** A job queue in the same database (transactional outbox, retries,
  heartbeat, dead-letter, crash-resume from the last LangGraph checkpoint), no Redis.
- **Measured.** An eval harness on the real graph (`evals/`), per-node/per-call tracing with
  tokens and cost (`agent_spans`), and a red-team script against the real local models.

## Quick start

### Docker (everything)

```bash
cp .env.example .env
python gen_key.py            # appends ENCRYPTION_KEY to .env
# edit .env: JWT_SECRET_KEY, SUPERADMIN_PASSWORD
docker compose up --build    # → http://localhost:8080  (API on :8000)
```

Postgres + pgvector, the API (migrations run on start, embedded worker) and the web app
behind nginx. Models are served by Ollama on the host by default — pull them first:

```bash
ollama pull llama3.2:1b && ollama pull llama3.1:8b && ollama pull nomic-embed-text && ollama pull qwen2.5vl:3b
```

or run Ollama in a container: `OLLAMA_HOST=http://ollama:11434 docker compose --profile ollama up --build`.

Sign in as `admin@aether.ai` with `SUPERADMIN_PASSWORD`.

### Local development

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m src.db.migrate                             # SQLite app.db unless DATABASE_URL is set
uvicorn src.main:app --reload --port 8000
cd frontend && npm install && npm run dev            # http://localhost:5173
```

## Testing

| Command | What it checks |
| :-- | :-- |
| `pytest -q` | ~250 tests: graph, queue, security findings, tool policy, migrations, vision — scripted models, no network |
| `ruff check .` · `mypy` | lint; types for `src/agent` and `src/security` |
| `RLS_TEST_DATABASE_URL=… pytest tests/test_rls_postgres.py` | Row-Level Security on a real Postgres |
| `python -m evals.run --suite all --fail-under unsafe_actions_max=0` | 42 tickets + 10 chat turns on the real models; unsafe actions must be 0 |
| `python scripts/redteam_ollama.py` | prompt-injection / privilege attacks against the real local models |

CI (`.github/workflows/ci.yml`) runs lint, types, tests, migrations + `alembic check` and the
RLS suite on Postgres, the frontend lint/type-check/build, and both Docker builds.

## What is real today

| Area | Status |
| :-- | :-- |
| Agent graph, risk floors, tool policy, human gate, escalation to GitHub | Implemented |
| Employee chat: RAG, repo reading, read-only platform logs, screenshot reading | Implemented |
| Job queue, tracing/usage, evals, migrations, Docker, CI | Implemented |
| Row-Level Security | Implemented and tested; enabled per deployment (`DB_RLS_ENABLED`) |
| MCP tools `reset_vpn_session`, `provision_standard_software`, `modify_iam_access`, `query_knowledge_base` | Real protocol, **simulated backends** |
| ITSM write-back (comment/resolve in Jira/ServiceNow), Slack/Teams | Planned |
| OpenShell sandbox for tools, Nebius-hosted models | Planned |
| Streaming responses, conversation history | Planned (roadmap §3) |

## Repository map

```
src/agent/          graph, nodes, risk + tool policy, vision, Concierge chat agent
src/api/            webhook, approval and chat endpoints
src/jobs/ src/tickets/   durable queue and ticket lifecycle
src/security/       redaction, prompt fences, URL guard, image validation, auth deps
src/rag/            ingestion guard, chunking, pgvector retrieval
src/integrations/   GitHub, read-only Render/Vercel logs
src/observability/  spans, usage, request/trace ids
src/db/             models, migrations runner, Row-Level Security
migrations/         Alembic revisions
evals/ scripts/     evaluation harness, E2E and red-team scripts
frontend/           React + Vite + Tailwind
docs/               architecture, security guardrails, ADRs, specs, roadmap
```

## Documentation

- [Security guardrails & LLM threat model](docs/security_guardrails.md)
- [Architecture](docs/architecture.md) · [ADRs](docs/adrs/)
- [Evaluation](docs/specs/evaluation_metrics.md) · [MCP tool registry](docs/specs/mcp_registry.md)
- [Runbook](docs/specs/runbook.md) · [Roadmap](docs/ROADMAP_NEXT_LEVEL.md)
- Implementation log, phase by phase: [docs/PLAN_IMPLEMENTACION.txt](docs/PLAN_IMPLEMENTACION.txt)
