"""
Keeps every prompt inside the model's context window (Fase 11.6).

Why this is a SECURITY control and not just a performance one: when a
prompt is longer than num_ctx, Ollama silently truncates it FROM THE START
— the first thing lost is the system prompt, i.e. every rule the agent
follows (grounding, read-only servers, untrusted-data policy). A chat
thread only grows (history lives in the checkpointer), so without a budget
a long enough conversation — or a user padding it on purpose — ends up
talking to a model with no instructions at all.

build_prompt() always keeps the system prompt and the latest message, then
adds history newest-first while it fits. Token counts are estimated at ~3
chars/token, conservative for both prose and code.
"""
import json
import logging
from typing import Sequence

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage

from src.config import get_settings

logger = logging.getLogger(__name__)

_CHARS_PER_TOKEN = 3
_SAFETY_MARGIN_TOKENS = 256
_IMAGE_TOKENS = 800  # rough cost of an attached image part


def estimate_tokens(message_or_text) -> int:
    content = getattr(message_or_text, "content", message_or_text)
    if isinstance(content, str):
        return len(content) // _CHARS_PER_TOKEN + 4
    tokens = 4
    for part in content or []:
        if isinstance(part, dict) and part.get("type") == "image_url":
            tokens += _IMAGE_TOKENS
        else:
            tokens += len(json.dumps(part, ensure_ascii=False)) // _CHARS_PER_TOKEN
    return tokens


def history_budget(system_prompt: str) -> int:
    settings = get_settings()
    return (
        settings.llm_context_window_tokens
        - settings.llm_max_output_tokens
        - _SAFETY_MARGIN_TOKENS
        - estimate_tokens(system_prompt)
    )


def fit_history(history: Sequence[BaseMessage], budget: int) -> list[BaseMessage]:
    """Newest messages that fit `budget`; the latest one is always kept."""
    if not history:
        return []
    kept = [history[-1]]
    used = estimate_tokens(history[-1])
    for message in reversed(history[:-1]):
        cost = estimate_tokens(message)
        if used + cost > budget:
            break
        kept.append(message)
        used += cost
    kept.reverse()
    # A window starting on an assistant turn reads as the model talking to itself.
    while len(kept) > 1 and isinstance(kept[0], AIMessage):
        kept.pop(0)
    return kept


def build_prompt(system_prompt: str, history: Sequence[BaseMessage]) -> list[BaseMessage]:
    budget = history_budget(system_prompt)
    if budget <= 0:
        logger.error("System prompt alone exceeds the context window (%d tokens over) — "
                     "the model would lose instructions; review the context budgets", -budget)
    window = fit_history(history, max(budget, 0))
    if len(window) < len(history):
        logger.info("Prompt history trimmed from %d to %d messages to fit the context window",
                    len(history), len(window))
    return [SystemMessage(content=system_prompt)] + window
