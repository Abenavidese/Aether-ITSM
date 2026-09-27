"""
Retrieval metrics for the RAG eval (Fase 14.0). Pure: ranked hits in, numbers
out — unit-tested in CI (tests/test_rag_eval.py).

A query's relevant units are (file, section) targets. A retrieved passage
counts as relevant when its file matches and its section matches the
target's (accent/case-insensitive, either containing the other — a chunker
may title a section "Error ERR_VPN_809" or just "ERR_VPN_809").

Everything is measured on what would reach the model (after the relevance
gate), because that is what the answer is built from; `candidate_hit@k`
measures the ranking alone (before the gate) to tell a ranking problem from
a gating problem.
"""
import math
import unicodedata
from dataclasses import asdict, dataclass, field


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.casefold().replace('"', " ").split())


@dataclass(frozen=True)
class Hit:
    file: str
    section: str
    tenant_id: str
    score: float | None = None


@dataclass
class QueryResult:
    case_id: str
    category: str
    targets: list[dict]
    passages: list[Hit] = field(default_factory=list)     # after the gate: what the model sees
    candidates: list[Hit] = field(default_factory=list)   # ranked, before the gate
    latency_ms: float = 0.0
    context_chars: int = 0
    error: str | None = None

    @property
    def answerable(self) -> bool:
        return bool(self.targets)

    def to_dict(self) -> dict:
        return asdict(self)


def section_matches(hit: Hit, target: dict) -> bool:
    if hit.file != target["file"]:
        return False
    hit_section, target_section = _norm(hit.section), _norm(target["section"])
    return bool(hit_section) and (target_section in hit_section or hit_section in target_section)


def _matched_target(hit: Hit, targets: list[dict]) -> int | None:
    for i, target in enumerate(targets):
        if section_matches(hit, target):
            return i
    return None


def hit_at(hits: list[Hit], targets: list[dict], k: int) -> bool:
    return any(_matched_target(h, targets) is not None for h in hits[:k])


def doc_hit_at(hits: list[Hit], targets: list[dict], k: int) -> bool:
    files = {t["file"] for t in targets}
    return any(h.file in files for h in hits[:k])


def reciprocal_rank(hits: list[Hit], targets: list[dict], k: int = 10) -> float:
    for rank, h in enumerate(hits[:k], start=1):
        if _matched_target(h, targets) is not None:
            return 1.0 / rank
    return 0.0


def ndcg_at(hits: list[Hit], targets: list[dict], k: int = 5) -> float:
    """Binary relevance; each target is credited once (a second chunk of the
    same section is not a second relevant result)."""
    credited: set[int] = set()
    dcg = 0.0
    for rank, h in enumerate(hits[:k], start=1):
        t = _matched_target(h, targets)
        if t is not None and t not in credited:
            credited.add(t)
            dcg += 1.0 / math.log2(rank + 1)
    ideal = sum(1.0 / math.log2(r + 1) for r in range(1, min(len(targets), k) + 1))
    return dcg / ideal if ideal else 0.0


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return round(ordered[idx], 1)


def _mean(values) -> float:
    values = list(values)
    return round(sum(values) / len(values), 3) if values else 0.0


def summarize(results: list[QueryResult], own_tenant: str) -> dict:
    ok = [r for r in results if r.error is None]
    answerable = [r for r in ok if r.answerable]
    unanswerable = [r for r in ok if not r.answerable]
    summary = {
        "queries": len(results),
        "errors": len(results) - len(ok),
        "hit@1": _mean(hit_at(r.passages, r.targets, 1) for r in answerable),
        "hit@3": _mean(hit_at(r.passages, r.targets, 3) for r in answerable),
        "hit@5": _mean(hit_at(r.passages, r.targets, 5) for r in answerable),
        "doc_hit@5": _mean(doc_hit_at(r.passages, r.targets, 5) for r in answerable),
        "mrr@10": _mean(reciprocal_rank(r.passages, r.targets) for r in answerable),
        "ndcg@5": _mean(ndcg_at(r.passages, r.targets) for r in answerable),
        "candidate_hit@10": _mean(hit_at(r.candidates, r.targets, 10) for r in answerable),
        "false_empty_rate": _mean(not r.passages for r in answerable),
        "no_answer_accuracy": _mean(not r.passages for r in unanswerable),
        "tenant_leaks": sum(1 for r in ok for h in r.passages + r.candidates if h.tenant_id != own_tenant),
        "avg_passages": _mean(len(r.passages) for r in ok),
        "avg_context_chars": round(_mean(r.context_chars for r in ok)),
        "latency_p50_ms": _pct([r.latency_ms for r in ok], 0.5),
        "latency_p95_ms": _pct([r.latency_ms for r in ok], 0.95),
    }
    by_category: dict[str, list[QueryResult]] = {}
    for r in answerable:
        by_category.setdefault(r.category, []).append(r)
    summary["hit@5_by_category"] = {
        cat: _mean(hit_at(r.passages, r.targets, 5) for r in rs) for cat, rs in sorted(by_category.items())
    }
    return summary


# Metrics where lower is better; everything else in `summary` is higher-is-better.
LOWER_IS_BETTER = {"errors", "false_empty_rate", "tenant_leaks", "latency_p50_ms", "latency_p95_ms"}


def check_thresholds(summary: dict, thresholds: dict[str, float]) -> list[str]:
    """`hit@5=0.8` -> must be >= 0.8; `tenant_leaks_max=0` -> must be <= 0."""
    failures = []
    for key, bound in thresholds.items():
        metric = key.removesuffix("_max")
        value = summary.get(metric)
        if value is None:
            failures.append(f"{metric}: not in this report")
        elif key.endswith("_max") or metric in LOWER_IS_BETTER:
            if value > bound:
                failures.append(f"{metric}={value} > {bound}")
        elif value < bound:
            failures.append(f"{metric}={value} < {bound}")
    return failures
