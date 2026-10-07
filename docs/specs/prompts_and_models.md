# Model Prompting & Configuration Guide

> **Status** (reviewed against the code on 2026-09-26, roadmap 1.3). The prompts that
> actually run live in the code (`src/agents/ticket_flow/nodes.py`, `src/prompts/concierge.py`,
> `src/agents/runtime/vision.py`); this doc describes their contract, not a copy of them. The
> Nemotron-3 model sizes and the Ultra/Summarizer nodes of the original draft were never
> built — marked below.

## 1. Inference configuration — Implemented

Every model id lives in `src/core/config.py`; switching provider is a `.env` change.

| Role | Used by | Local (Ollama, default) | Hosted (`USE_OLLAMA=False`) |
| :-- | :-- | :-- | :-- |
| nano | Supervisor (risk classification) | `llama3.2:1b` | `NEBIUS_MODEL_NANO` (placeholder id) |
| super | Policy, Execution, Draft Plan, Concierge chat | `llama3.1:8b` | `NEBIUS_MODEL_SUPER` (placeholder id) |
| vision | Reads attached screenshots into text | `qwen2.5vl:3b` | `NEBIUS_MODEL_VISION` (placeholder id) |
| embeddings | RAG | `nomic-embed-text` (with task prefixes) | `NEBIUS_EMBEDDING_MODEL` |

- Hosted: Nebius Token Factory (`https://api.studio.nebius.ai/v1/`) through the OpenAI SDK,
  or OpenAI as a fallback. The Nebius model ids are placeholders until checked against the
  real catalog (**Planned**: a live run on Nebius).
- `temperature=0.0`; hard limits on every call: `LLM_MAX_OUTPUT_TOKENS` (1024), timeout
  (120 s), Ollama `num_ctx` (8192) — added after a runaway generation froze the chat.
- Structured output: `with_structured_output(<Pydantic schema>)` with bounded
  self-correction (`src/llm/structured_output.py`), not a raw "JSON mode" flag.
- The admin sees the active models read-only in Settings; they are platform configuration,
  not a per-tenant choice (the old per-tenant "LLM engine" field did nothing and was removed).

## 2. Classification — Supervisor (nano) — Implemented
Output schema `ClassificationResult`: `intent`, `risk_level` (0-4, a `Literal`, so
out-of-range values fail validation), `tools_required`. The model's risk is only a starting
point: `enforce_risk_floor()` (EN + ES patterns) and the risk of `tools_required` can raise
it, never lower it. A few-shot block was added after the first real eval run.

## 3. Policy / Execution / Draft Plan (super) — Implemented
- Policy: `PolicyCheckResult` (`is_compliant`, `reason`) against the tenant's
  `company_policy` RAG documents.
- Execution / Draft Plan: `ExecutionPlanResult` (`resolution_summary`, `proposed_plan`,
  `tool_name`, `tool_args`). The model proposes; `tool_policy.authorize()` decides. For risk
  3 the validated call is frozen into the plan and runs only after human approval.
- Every text the model reads from outside (RAG chunks, repo files, logs, tool output,
  screenshot readings) is fenced as `<untrusted_data>` with a data-not-instructions rule.

## 4. Vision (screenshot reading) — Implemented
One call per attached image: visible error text verbatim + a 1-3 sentence description,
redacted, capped at `VISION_MAX_CHARS`, fenced as untrusted data. See `src/agents/runtime/vision.py`.

## 5. Analysis node (Nemotron Ultra) — Planned, not built
Escalations use the same "super" model; there is no Ultra model or separate analysis node.
Escalation summaries plus the automatic diagnosis (platform logs → `file:line`) go into the
GitHub issue.

## 6. Summarizer node — Not built (superseded)
History is kept inside the context window by `src/llm/context_budget.py` (newest turns
first, system prompt always kept) instead of an LLM summarizer. See ADR-004 §4.
