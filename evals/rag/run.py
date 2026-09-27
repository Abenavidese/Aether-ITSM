"""
RAG retrieval eval (Fase 14.0).

    .venv/Scripts/python.exe -m evals.rag.run --database-url postgresql://...@localhost:55432/aether
    .venv/Scripts/python.exe -m evals.rag.run --system legacy --database-url ...
    .venv/Scripts/python.exe -m evals.rag.run --fail-under hit@5=0.8 --fail-under tenant_leaks_max=0

Indexes evals/rag/corpus (two tenants) into a DISPOSABLE Postgres with
pgvector — never point it at a shared database: the store's tables for the
eval tenants are wiped first. Embeddings come from the configured provider
(.env), so the same command compares embedding models. Writes
evals/reports/<stamp>-rag-<system>.json and .md; exits 1 on a violated
--fail-under threshold.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from .corpus import MAIN_TENANT, load_corpus, load_dataset
from .metrics import QueryResult, check_thresholds, summarize

REPORTS = Path(__file__).resolve().parents[1] / "reports"


def _parse_thresholds(items: list[str]) -> dict[str, float]:
    return {k.strip(): float(v) for k, _, v in (i.partition("=") for i in items)}


def build_system(name: str, database_url: str, options: dict):
    if name == "legacy":
        from .systems import LegacySystem
        return LegacySystem(database_url)
    from .systems import CurrentSystem
    return CurrentSystem(database_url, **options)


def run_cases(system, cases: list[dict], progress=print) -> list[QueryResult]:
    results = []
    for i, case in enumerate(cases, start=1):
        result = QueryResult(case["id"], case["category"], case["targets"])
        try:
            outcome = system.search(MAIN_TENANT, case["query"], case.get("history", []))
            result.passages, result.candidates = outcome.passages, outcome.candidates
            result.context_chars, result.latency_ms = outcome.context_chars, round(outcome.latency_ms, 1)
        except Exception as e:  # one broken case must not hide the rest
            result.error = f"{type(e).__name__}: {e}"
        results.append(result)
        if progress:
            progress(f"[{i}/{len(cases)}] {case['id']}: {len(result.passages)} passages"
                     + (f" ERROR {result.error}" if result.error else ""))
    return results


def render_markdown(report: dict) -> str:
    lines = [f"# RAG eval — {report['system']}", "", f"- Date: {report['created_at']}",
             f"- Embeddings: `{report['embedding_model']}`", f"- Options: `{json.dumps(report['options'])}`",
             "", "## Summary", "", "| metric | value |", "|---|---|"]
    lines += [f"| {k} | {json.dumps(v, ensure_ascii=False)} |" for k, v in report["summary"].items()]
    if report.get("threshold_failures") is not None:
        lines += ["", "## Thresholds", ""]
        lines += [f"- ❌ {f}" for f in report["threshold_failures"]] or ["- ✅ all thresholds met"]
    lines += ["", "## Misses (answerable queries without the target in the top 5)", "",
              "| case | category | top passages |", "|---|---|---|"]
    from .metrics import Hit, hit_at
    for raw in report["results"]:
        if not raw["targets"]:
            continue
        passages = [Hit(**h) for h in raw["passages"]]
        if not hit_at(passages, raw["targets"], 5):
            top = "; ".join(f"{h.file}#{h.section}" for h in passages[:3]) or "(empty)"
            lines.append(f"| {raw['case_id']} | {raw['category']} | {top} |")
    return "\n".join(lines) + "\n"


def _embedding_model() -> str:
    from src.rag.embeddings import embedding_model_id
    return embedding_model_id()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the RAG retrieval eval")
    parser.add_argument("--system", choices=["current", "legacy"], default="current")
    parser.add_argument("--database-url", default=os.environ.get("RAG_EVAL_DATABASE_URL"),
                        help="disposable Postgres with pgvector (or RAG_EVAL_DATABASE_URL)")
    parser.add_argument("--option", action="append", default=[], metavar="KEY=VALUE",
                        help="system option, e.g. reranker=none or rewrite=off (repeatable)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--fail-under", action="append", default=[], metavar="METRIC=VALUE")
    parser.add_argument("--no-index", action="store_true", help="reuse what a previous run indexed")
    parser.add_argument("--out", default=str(REPORTS))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if not args.database_url:
        parser.error("--database-url (or RAG_EVAL_DATABASE_URL) is required: a disposable Postgres")

    # Before anything imports src.*: settings and the engine are built from
    # the environment once, and they must point at the eval database.
    os.environ["DATABASE_URL"] = args.database_url
    os.environ["DB_RLS_ENABLED"] = "False"
    options = dict(o.split("=", 1) for o in args.option)
    system = build_system(args.system, args.database_url, options)
    if not args.no_index:
        system.index(load_corpus())
    cases = load_dataset()[:args.limit]
    results = run_cases(system, cases, progress=None if args.quiet else print)

    summary = summarize(results, MAIN_TENANT)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = {"system": args.system, "created_at": stamp, "embedding_model": _embedding_model(),
              "options": options, "summary": summary, "results": [r.to_dict() for r in results]}
    thresholds = _parse_thresholds(args.fail_under)
    if thresholds:
        report["threshold_failures"] = check_thresholds(summary, thresholds)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    suffix = "-".join([args.system] + [f"{k}_{v}" for k, v in sorted(options.items())])
    suffix = re.sub(r"[^\w.=-]+", "_", suffix)[:120]   # model ids contain "/"
    base = out / f"{stamp}-rag-{suffix}"
    base.with_suffix(".json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    base.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"-> {base}.md")
    sys.exit(1 if report.get("threshold_failures") else 0)


if __name__ == "__main__":
    main()
