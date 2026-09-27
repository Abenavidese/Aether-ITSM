"""
Query understanding (Fase 14.4): what to actually search for.

A chat follow-up ("¿y el de Admin?", "ya probé eso, ¿qué más hago?") means
nothing on its own; searched raw, it retrieves whatever is closest to
"Admin" or "hago". A follow-up is detected by cheap rules, and turned into a
standalone query by one of:
- "concat": previous user message + this one. Deterministic, no model call;
- "llm":    the nano model rewrites it as one standalone question. Its output
            is only accepted if every content word already appears in the
            conversation (a rewrite may rephrase, never add facts — a small
            model inventing "VPN" into a printer question would send the search
            to the wrong document); otherwise "concat" is used.
Which one is the default is decided by the eval (docs/PLAN_IMPLEMENTACION.txt,
Fase 14.4), not by taste.

The keyword side always keeps the user's literal terms: rewriting is for the
embedding, exact words are for BM25.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Callable

from .text import extract_entities, query_terms

logger = logging.getLogger(__name__)

_CONNECTOR = re.compile(
    r"^\s*[¿¡]?\s*(y|e|and|what about|how about|también|tambien|entonces|pero|but|ya|ok|vale|"
    r"y si|y qué|y que|what if)\b", re.IGNORECASE)
_ANAPHORA = re.compile(r"\b(eso|esto|ese|esa|lo mismo|ahí|alli|allí|that|this|it|same|those|them)\b",
                       re.IGNORECASE)
_MAX_FOLLOW_UP_TERMS = 4
_MAX_REWRITE_CHARS = 300

Rewriter = Callable[[list[str], str], str]   # (previous user messages, query) -> standalone query


@dataclass
class QueryPlan:
    original: str
    semantic: str                 # what gets embedded (and read by the reranker)
    terms: list[str]              # keyword side
    entities: list[str]
    rewritten: bool = False
    mode: str = "off"
    notes: list[str] = field(default_factory=list)


def is_follow_up(query: str, history: list[str]) -> bool:
    if not history or not any(h.strip() for h in history):
        return False
    if extract_entities(query):
        return False              # "¿y ERR_VPN_812?" is self-contained enough
    terms = query_terms(query)
    if _CONNECTOR.match(query) or _ANAPHORA.search(query):
        return True
    return len(terms) <= _MAX_FOLLOW_UP_TERMS - 1


def _rewrite_is_grounded(rewrite: str, history: list[str], query: str) -> bool:
    allowed = set(query_terms(" ".join(history + [query]), limit=500))
    new_terms = [t for t in query_terms(rewrite, limit=500) if t not in allowed]
    # Tolerate inflection ("contratistas" for "contratista"): shared 5-char prefix.
    return all(any(t[:5] == a[:5] for a in allowed) for t in new_terms if len(t) > 3) and \
        not [t for t in new_terms if len(t) <= 3 and not t.isdigit()]


def plan_query(query: str, history: list[str] | None = None, *, mode: str = "concat",
               rewriter: Rewriter | None = None) -> QueryPlan:
    history = [h for h in (history or []) if h and h.strip()]
    plan = QueryPlan(original=query, semantic=query, terms=query_terms(query), entities=extract_entities(query),
                     mode="off")
    if mode == "off" or not is_follow_up(query, history):
        return plan

    previous = history[-1]
    plan.rewritten, plan.mode = True, "concat"
    plan.semantic = f"{previous} {query}"
    if mode == "llm" and rewriter is not None:
        try:
            candidate = " ".join(rewriter(history[-3:], query).split())[:_MAX_REWRITE_CHARS]
            if candidate and _rewrite_is_grounded(candidate, history[-3:], query):
                plan.semantic, plan.mode = candidate, "llm"
            else:
                plan.notes.append("llm rewrite rejected (not grounded in the conversation)")
        except Exception as e:
            plan.notes.append(f"llm rewrite failed: {type(e).__name__}")
            logger.warning("Query rewrite failed, using concat: %s", e)
    # Keyword side: the user's own words first, then the previous message's.
    seen = dict.fromkeys(plan.terms)
    for term in query_terms(previous):
        seen.setdefault(term, None)
    plan.terms = list(seen)[:24]
    plan.entities = plan.entities or extract_entities(previous)
    return plan


def llm_rewriter(llm) -> Rewriter:
    """A Rewriter over a LangChain chat model (the nano one)."""
    def rewrite(history: list[str], query: str) -> str:
        conversation = "\n".join(f"- {h}" for h in history)
        prompt = (
            "Rewrite the user's LAST message as one standalone search query, in the same language, "
            "using only information from the conversation. Do not answer it, do not add anything new. "
            "Reply with the query only.\n\n"
            f"Previous user messages:\n{conversation}\n\nLast message: {query}\n\nStandalone query:"
        )
        reply = llm.invoke(prompt)
        return str(getattr(reply, "content", "") or "")
    return rewrite
