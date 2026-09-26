"""
Read side of the agent traces (roadmap 2.4): tokens and cost per model,
latency percentiles per node, and one ticket's full path. Aggregation is
done in Python over the period's spans — fine for one tenant-month of
traffic; a SQL percentile (percentile_cont) is the next step at scale.
"""
import json
import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from src.config import get_settings
from src.db.tenant_scope import tenant_session
from src.db.models import AgentSpan

logger = logging.getLogger(__name__)


def _prices() -> dict[str, tuple[float, float]]:
    try:
        raw = json.loads(get_settings().llm_prices_json or "{}")
        return {model: (float(p[0]), float(p[1])) for model, p in raw.items()}
    except (ValueError, TypeError, IndexError, AttributeError):
        logger.warning("LLM_PRICES_JSON is not valid {model: [in, out]} JSON; costs reported as 0")
        return {}


def percentile(values: list[int], pct: float) -> int:
    """Nearest-rank percentile (no interpolation): an actually observed value."""
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[max(math.ceil(pct / 100 * len(ordered)) - 1, 0)]


def usage_summary(tenant_id: str, days: int = 30) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with tenant_session(tenant_id) as db:
        spans = db.query(AgentSpan).filter(AgentSpan.tenant_id == tenant_id, AgentSpan.started_at >= since).all()

    prices = _prices()
    models: dict[str, dict] = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
    by_source: dict[str, dict] = defaultdict(lambda: {"runs": set(), "input_tokens": 0, "output_tokens": 0})
    node_durations: dict[str, list[int]] = defaultdict(list)
    node_errors: dict[str, int] = defaultdict(int)

    for s in spans:
        if s.kind == "llm":
            m = models[s.model or "unknown"]
            m["calls"] += 1
            m["input_tokens"] += s.input_tokens or 0
            m["output_tokens"] += s.output_tokens or 0
            price_in, price_out = prices.get(s.model or "", (0.0, 0.0))
            m["cost_usd"] += ((s.input_tokens or 0) * price_in + (s.output_tokens or 0) * price_out) / 1_000_000
            src = by_source[s.source]
            src["input_tokens"] += s.input_tokens or 0
            src["output_tokens"] += s.output_tokens or 0
        by_source[s.source]["runs"].add(s.trace_id)
        if s.kind == "node":
            node_durations[s.name].append(s.duration_ms)
            node_errors[s.name] += s.status != "ok"

    by_model = [{"model": name, **{k: round(v, 6) if k == "cost_usd" else v for k, v in data.items()}}
                for name, data in sorted(models.items())]
    return {
        "period_days": days,
        "totals": {
            "llm_calls": sum(m["calls"] for m in by_model),
            "input_tokens": sum(m["input_tokens"] for m in by_model),
            "output_tokens": sum(m["output_tokens"] for m in by_model),
            "cost_usd": round(sum(m["cost_usd"] for m in by_model), 6),
            "priced": bool(prices),
        },
        "by_model": by_model,
        "by_source": [{"source": k, "runs": len(v["runs"]), "input_tokens": v["input_tokens"],
                       "output_tokens": v["output_tokens"]} for k, v in sorted(by_source.items())],
        "nodes": [
            {"node": name, "count": len(d), "p50_ms": percentile(d, 50), "p95_ms": percentile(d, 95),
             "error_rate": round(node_errors[name] / len(d), 3)}
            for name, d in sorted(node_durations.items())
        ],
    }


def ticket_trace(tenant_id: str, trace_id: str) -> list[dict]:
    with tenant_session(tenant_id) as db:
        spans = (db.query(AgentSpan)
                 .filter(AgentSpan.tenant_id == tenant_id, AgentSpan.trace_id == trace_id)
                 .order_by(AgentSpan.started_at).all())
        return [{
            "kind": s.kind, "name": s.name, "model": s.model, "status": s.status, "duration_ms": s.duration_ms,
            "input_tokens": s.input_tokens, "output_tokens": s.output_tokens,
            "started_at": s.started_at.isoformat() if s.started_at else None,
        } for s in spans]
