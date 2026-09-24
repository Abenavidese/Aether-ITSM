import logging
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

MAX_STRUCTURED_RETRIES = 2
_MAX_ERROR_CHARS = 300


def _summarize_error(error) -> str:
    """First line of the parsing error, capped — enough for the model to
    know what to fix, never a copy of its own (possibly huge) raw output."""
    text = str(error).strip().splitlines()[0] if error else "unknown error"
    return text[:_MAX_ERROR_CHARS] + ("…" if len(text) > _MAX_ERROR_CHARS else "")


async def invoke_structured(llm, schema, messages: list, max_retries: int = MAX_STRUCTURED_RETRIES):
    """
    Invokes an LLM for structured output, self-correcting up to `max_retries`
    times when the model (notably a local Ollama model) returns JSON that
    fails schema validation instead of raising immediately.

    Uses include_raw=True so a failed parse comes back as data
    ({"parsed": None, "parsing_error": ...}) rather than an exception,
    which lets us feed the error back to the model and ask it to fix its
    own output before giving up. Callers should still wrap this in a
    try/except to fall back to a safe default (e.g. escalate) once all
    attempts are exhausted.
    """
    structured_llm = llm.with_structured_output(schema, include_raw=True)
    current_messages = list(messages)
    last_error = None

    for attempt in range(max_retries + 1):
        raw_result = await structured_llm.ainvoke(current_messages)
        parsed = raw_result.get("parsed")
        if parsed is not None:
            return parsed

        last_error = raw_result.get("parsing_error")
        error_summary = _summarize_error(last_error)
        logger.warning(
            "Structured output for %s failed schema validation (attempt %d/%d): %s",
            schema.__name__, attempt + 1, max_retries + 1, error_summary
        )
        # Always retry from the ORIGINAL messages plus a short correction —
        # never append the failed output or the full parsing error: the
        # error embeds the model's whole raw output, and a degenerate
        # generation fed back that way once produced a 41,878-token prompt
        # that Ollama truncated from the start (losing the system prompt),
        # which made the next attempt degenerate too.
        current_messages = list(messages) + [
            HumanMessage(content=(
                f"Your previous response was not valid JSON for the '{schema.__name__}' "
                f"schema. Error: {error_summary}. Respond again with ONLY a short JSON "
                "object matching every required field of the schema."
            ))
        ]

    raise ValueError(
        f"Structured output for {schema.__name__} failed after {max_retries + 1} attempts: {last_error}"
    )
