import logging
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

MAX_STRUCTURED_RETRIES = 2


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
        logger.warning(
            "Structured output for %s failed schema validation (attempt %d/%d): %s",
            schema.__name__, attempt + 1, max_retries + 1, last_error
        )
        current_messages = current_messages + [
            HumanMessage(content=(
                f"Your previous response was not valid JSON for the '{schema.__name__}' "
                f"schema. Error: {last_error}. Respond again with ONLY a JSON object "
                "matching every required field of the schema."
            ))
        ]

    raise ValueError(
        f"Structured output for {schema.__name__} failed after {max_retries + 1} attempts: {last_error}"
    )
