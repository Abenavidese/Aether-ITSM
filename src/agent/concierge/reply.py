"""
Turns the model's structured result (and tool outputs) into the text the
employee reads — built by code from known fields, never raw JSON.
"""
import json
import re

from src.agent.state import ConciergeResult

# Schema-ish junk a small model sometimes emits as a list item
# ("tool_used_check_service_status:false,").
_JUNK_DETAIL = re.compile(r"^[\w.-]+\s*:\s*(true|false|null|none|\d+)?\s*,?$", re.IGNORECASE)


def _compose_reply(result: ConciergeResult) -> str:
    items = [d.strip() for d in result.details if d and d.strip() and not _JUNK_DETAIL.match(d.strip())]
    if not items:
        return result.response_text
    return result.response_text.rstrip() + "\n\n" + "\n".join(f"- {item.lstrip('-• ')}" for item in items)


def _format_tool_output(tool_name: str, raw: str) -> str:
    """
    What the employee sees from a tool call: a sentence built by code from
    known fields — never the tool's raw JSON (it used to be appended as-is,
    internal fields and all).
    """
    try:
        data = json.loads(raw)
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    if tool_name == "check_service_status":
        if data.get("status") != "success":
            return "⚠️ No pude verificar el estado de ese servicio."
        state = "disponible" if data.get("available") else "NO disponible"
        code = f" (HTTP {data['http_status']})" if isinstance(data.get("http_status"), int) else ""
        return f"🔎 Estado de {data.get('service_url')}: {state}{code}"
    if tool_name == "query_knowledge_base":
        results = [r for r in data.get("results") or [] if isinstance(r, str)]
        return "\n".join(f"- {r}" for r in results)[:1500]
    return ""
