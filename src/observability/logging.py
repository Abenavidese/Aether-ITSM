"""
Correlated logging (roadmap 2.4).

Every log line carries request_id (one per HTTP request, echoed back in the
X-Request-ID header, or taken from the caller's header when it is a sane
value) and trace_id (the agent run it belongs to, see tracing.py). With
LOG_FORMAT=json each line is one JSON object, ready for any log backend;
the default text format keeps local output readable.
"""
import json
import logging
import re
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .tracing import current_trace

_request_id: ContextVar[str] = ContextVar("aether_request_id", default="-")
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

_TEXT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - [req=%(request_id)s trace=%(trace_id)s] %(message)s"


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        trace = current_trace()
        record.trace_id = trace.trace_id if trace else "-"
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "trace_id": getattr(record, "trace_id", "-"),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(log_format: str = "text", level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(ContextFilter())
    handler.setFormatter(JsonFormatter() if log_format == "json" else logging.Formatter(_TEXT_FORMAT))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _SAFE_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex[:16]
        token = _request_id.set(request_id)
        try:
            response = await call_next(request)
        finally:
            _request_id.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response
