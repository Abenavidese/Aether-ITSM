# Ops & Policy Runbook

> Reviewed against the code on 2026-09-26 (roadmap 1.3). The OpenShell section of the
> original draft described a sandbox that doesn't exist; it is marked **Planned**.

## 1. Startup (local dev)

```bash
python -m venv .venv && .venv/Scripts/activate      # Windows (Linux/macOS: source .venv/bin/activate)
pip install -r requirements-dev.txt
cp .env.example .env && python gen_key.py           # then set JWT_SECRET_KEY and SUPERADMIN_PASSWORD
ollama pull llama3.2:1b && ollama pull llama3.1:8b && ollama pull nomic-embed-text && ollama pull qwen2.5vl:3b

python -m src.db.migrate                            # apply schema migrations (Alembic)
uvicorn src.main:app --reload --port 8000           # API (+ embedded queue worker)
cd frontend && npm install && npm run dev           # web app on :5173
```

Or everything in containers: `docker compose up --build` → http://localhost:8080 (see README).

- **Windows + Postgres checkpointer:** psycopg async can't run on the ProactorEventLoop;
  start uvicorn with `--reload` (or `--loop asyncio:SelectorEventLoop`).
- **Production worker:** set `JOBS_EMBEDDED_WORKER=False` and run `python -m src.jobs.worker`.
- **Webhook from outside (optional):** `ngrok http 8000`.

## 2. Checks

```bash
ruff check . && mypy && pytest -q                    # what CI runs (plus Postgres + frontend jobs)
python -m evals.run --suite all --fail-under unsafe_actions_max=0   # real models, ~5 min
python scripts/redteam_ollama.py                    # attacks against the real local models
```

## 3. Debugging common errors

### 3.1 Structured output keeps failing
**Symptom:** a node escalates with `technical_error`; logs show "failed schema validation".
**Fix:** check the model is the configured one (`ollama list`) and that the prompt fits the
window (context budget warnings in the log). The hosted path uses `with_structured_output`;
no manual `response_format` flag is involved.

### 3.2 Ollama "freezes"
Usually a runaway generation, not a hang: look for a growing `n_gen` / "context shift" in
`%LOCALAPPDATA%/Ollama/server.log`. The per-call limits in `get_llms()` bound it.

### 3.3 Approving a Level 3 ticket returns 404
**Cause:** the thread isn't waiting for approval (already resumed/finished), belongs to
another tenant, or the checkpointer backend changed since it paused (threads are not
migrated between SQLite and Postgres). Check `GET /api/tenant/tickets/{id}` and the job row.

### 3.4 Schema errors after pulling new code
Run `python -m src.db.migrate`. A database created before Alembic is adopted automatically
(stamped at the revision its schema matches); an unrecognized schema is refused with an
explicit message instead of guessed at.

### 3.5 OpenShell policy block — Planned
There is no OpenShell sandbox yet (see `docs/security_guardrails.md` §3.1); a tool can't be
blocked by it today.

## 4. Modifying risk policies safely
Do not prompt the LLM to change risk logic — it lives in code:
- Minimum risk by ticket wording: `src/agent/risk_policy.py` (`enforce_risk_floor`).
- Risk, parameters and validators per tool: `TOOL_POLICY` in `src/agent/tool_policy.py`.
  To make software installs require approval, set `provision_standard_software` to risk 3.
Add a test in `tests/security/` and re-run the evals after any change.
