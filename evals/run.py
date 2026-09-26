"""
Eval runner (roadmap 2.3).

    .venv/Scripts/python.exe -m evals.run --suite all
    .venv/Scripts/python.exe -m evals.run --suite tickets --limit 10 \
        --fail-under route_accuracy=0.8 --fail-under unsafe_actions_max=0

Uses the models configured in .env (USE_OLLAMA / NEBIUS_*), the real MCP
tool server (simulated actions) and writes evals/reports/<stamp>-<suite>.json
and .md. Exits 1 when a --fail-under threshold is violated, so the same
command gates a nightly job or a model/prompt change.
"""
import argparse
import asyncio
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.agent.mcp_client import MCPToolClient
from src.config import get_settings

from .harness import load_cases, run_chat_case, run_ticket_case
from .metrics import chat_checks, check_thresholds, route_ok, summarize_chats, summarize_tickets, tool_ok, unsafe_calls

ROOT = Path(__file__).resolve().parent
DATASETS = {"tickets": ROOT / "datasets" / "tickets.jsonl", "concierge": ROOT / "datasets" / "concierge.jsonl"}


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              cwd=ROOT, timeout=5).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _models() -> dict:
    s = get_settings()
    if s.use_ollama:
        return {"provider": "ollama", "nano": s.ollama_model_nano, "super": s.ollama_model_super}
    return {"provider": "nebius" if s.nebius_api_key else "openai",
            "nano": s.nebius_model_nano if s.nebius_api_key else s.openai_model_nano,
            "super": s.nebius_model_super if s.nebius_api_key else s.openai_model_super}


async def run_suite(suite: str, mcp_client, limit: int | None = None, progress=print) -> dict:
    cases = load_cases(DATASETS[suite])[:limit]
    runner = run_ticket_case if suite == "tickets" else run_chat_case
    results = []
    for i, case in enumerate(cases, start=1):
        result = await runner(case, mcp_client)
        results.append(result)
        progress(f"[{i}/{len(cases)}] {case['id']}: " + (f"ERROR {result.error}" if result.error else
                 f"{result.latency_ms} ms"))
    summary = summarize_tickets(results) if suite == "tickets" else summarize_chats(results)
    return {"suite": suite, "summary": summary, "results": [r.to_dict() for r in results]}


def _ticket_rows(results: list[dict]) -> list[str]:
    from .metrics import TicketResult
    rows = ["| case | route (expected) | risk | tools | ok |", "|---|---|---|---|---|"]
    for raw in results:
        r = TicketResult(**{**raw, "tool_calls": [tuple(c) for c in raw["tool_calls"]]})
        if r.error:
            rows.append(f"| {r.case_id} | ERROR | | | ❌ {r.error[:60]} |")
            continue
        ok = route_ok(r) and (tool_ok(r) if r.expected.get("route") == "auto" else True) and not unsafe_calls(r)
        tools = ", ".join(name for name, _ in r.tool_calls) or "—"
        rows.append(f"| {r.case_id} | {r.route} ({r.expected.get('route')}) | {r.risk} | {tools} | {'✅' if ok else '❌'} |")
    return rows


def _chat_rows(results: list[dict]) -> list[str]:
    from .metrics import ChatResult
    rows = ["| case | resolved | failed checks |", "|---|---|---|"]
    for raw in results:
        r = ChatResult(**{**raw, "tool_calls": [tuple(c) for c in raw["tool_calls"]]})
        failed = [k for k, ok in chat_checks(r).items() if not ok] if not r.error else ["harness error"]
        rows.append(f"| {r.case_id} | {r.resolved} | {', '.join(failed) or '✅'} |")
    return rows


def render_markdown(report: dict) -> str:
    lines = [f"# Eval report — {report['suite']}", "",
             f"- Date: {report['created_at']}", f"- Commit: `{report['git_sha']}`",
             f"- Models: `{json.dumps(report['models'])}`", "", "## Summary", "", "| metric | value |", "|---|---|"]
    lines += [f"| {k} | {json.dumps(v, ensure_ascii=False)} |" for k, v in report["summary"].items()]
    if report.get("threshold_failures") is not None:
        lines += ["", "## Thresholds", ""]
        lines += [f"- ❌ {f}" for f in report["threshold_failures"]] or ["- ✅ all thresholds met"]
    lines += ["", "## Cases", ""]
    lines += _ticket_rows(report["results"]) if report["suite"] == "tickets" else _chat_rows(report["results"])
    return "\n".join(lines) + "\n"


def _parse_thresholds(items: list[str]) -> dict[str, float]:
    thresholds = {}
    for item in items:
        key, _, value = item.partition("=")
        thresholds[key.strip()] = float(value)
    return thresholds


async def _main(args) -> int:
    thresholds = _parse_thresholds(args.fail_under)
    suites = ["tickets", "concierge"] if args.suite == "all" else [args.suite]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    mcp = MCPToolClient()
    await mcp.connect()
    exit_code = 0
    try:
        for suite in suites:
            report = await run_suite(suite, mcp, args.limit)
            report.update(created_at=stamp, git_sha=_git_sha(), models=_models())
            applicable = {k: v for k, v in thresholds.items() if k.removesuffix("_max") in report["summary"]}
            if thresholds:
                report["threshold_failures"] = check_thresholds(report["summary"], applicable)
                exit_code |= bool(report["threshold_failures"])
            base = out_dir / f"{stamp}-{suite}"
            base.with_suffix(".json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
            base.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
            print(f"\n{suite}: {json.dumps(report['summary'], ensure_ascii=False)}\n-> {base}.md")
    finally:
        await mcp.close()
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Aether LLM evals")
    parser.add_argument("--suite", choices=["tickets", "concierge", "all"], default="all")
    parser.add_argument("--limit", type=int, default=None, help="run only the first N cases of each suite")
    parser.add_argument("--fail-under", action="append", default=[], metavar="METRIC=VALUE",
                        help="e.g. route_accuracy=0.8 or unsafe_actions_max=0 (repeatable)")
    parser.add_argument("--out", default=str(ROOT / "reports"))
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(_main(parser.parse_args())))


if __name__ == "__main__":
    main()
