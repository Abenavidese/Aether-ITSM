"""
The ONLY object in Aether that talks to a hosting platform's API (Render
today). Its whole job is to make "the agent can read logs but never change
anything" a property of the code, not of the credential:

A Render API key has FULL access to every workspace of the user that
created it — Render has no read-only key scope. So read-only can't be
delegated to the platform; it's enforced here, in independent layers:

1. GET only. There is no post/put/patch/delete method to call, and the
   internal request path refuses any other verb before touching the network.
2. Path allow-list. Every request path must fully match one of the
   provider's patterns (e.g. GET /v1/logs, GET /v1/services/srv-...). A
   restart/redeploy/env-var endpoint simply cannot be expressed.
3. No redirects followed, so an allowed URL can't bounce somewhere else.
4. The token never leaves this object: it isn't logged, and errors are
   re-raised without request headers.

This is deliberately NOT an MCP tool: the LLM can't call it or choose its
parameters. Service ids come only from the tenant's validated settings
(src/tenant/router.py) and are picked by deterministic server code.
"""
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ReadOnlyViolation(Exception):
    """A request that would not be a read of an allow-listed path."""


class PlatformAPIError(Exception):
    """The platform answered with an error. Never carries credentials."""

    def __init__(self, status_code: int | None, message: str):
        super().__init__(message)
        self.status_code = status_code


class ReadOnlyHttpClient:
    def __init__(self, base_url: str, token: str, allowed_paths: list[re.Pattern],
                 timeout: float = 10.0, transport: httpx.AsyncBaseTransport | None = None):
        self._base_url = base_url.rstrip("/")
        self.__token = token
        self._allowed_paths = list(allowed_paths)
        self._timeout = timeout
        self._transport = transport  # injectable for tests (httpx.MockTransport)

    def __repr__(self) -> str:  # never let the token end up in a log line
        return f"ReadOnlyHttpClient({self._base_url!r})"

    def _check_path(self, path: str) -> None:
        if any(ch in path for ch in "?#%\\") or ".." in path:
            raise ReadOnlyViolation(f"Refusing suspicious path {path!r}")
        if not any(p.fullmatch(path) for p in self._allowed_paths):
            raise ReadOnlyViolation(f"Path {path!r} is not in the read-only allow-list")

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", path, params)

    async def _request(self, method: str, path: str, params: dict[str, Any] | None) -> Any:
        if method != "GET":
            raise ReadOnlyViolation(f"Method {method} is not allowed: this client is read-only")
        self._check_path(path)

        async with httpx.AsyncClient(
            base_url=self._base_url, timeout=self._timeout,
            follow_redirects=False, transport=self._transport,
        ) as client:
            try:
                response = await client.request(
                    method, path, params=params,
                    headers={"Authorization": f"Bearer {self.__token}", "Accept": "application/json"},
                )
            except httpx.HTTPError as e:
                # str(e) of an httpx error doesn't include headers, but keep
                # only the exception type + URL path to be certain.
                raise PlatformAPIError(None, f"{type(e).__name__} calling {path}") from None

        if response.status_code != 200:
            raise PlatformAPIError(response.status_code, f"GET {path} returned {response.status_code}")
        return response.json()
