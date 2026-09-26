"""
Error responses that never leak internals (Fase 11.10).

Returning the exception text itself as the HTTP detail sent internals to the
client: SQL fragments, file paths, library internals, sometimes a URL with a
token in it. Instead the
client gets a stable message plus a short reference id, and the full
exception goes to the server log under that same id.
"""
import logging
import uuid

from fastapi import HTTPException


def internal_error(logger: logging.Logger, public_message: str, exc: BaseException | None = None,
                   status_code: int = 500) -> HTTPException:
    reference = uuid.uuid4().hex[:12]
    logger.error("%s [ref=%s]", public_message, reference, exc_info=exc)
    return HTTPException(status_code=status_code, detail=f"{public_message} (ref: {reference})")
