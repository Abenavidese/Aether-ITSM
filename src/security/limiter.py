from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from src.security.cookies import ACCESS_TOKEN_COOKIE
from src.security.jwt import decode_access_token

limiter = Limiter(key_func=get_remote_address)


def user_or_ip_key(request: Request) -> str:
    """
    Rate-limit key for authenticated endpoints that call the LLM (Fase 11.6):
    per user, not per IP — a whole office behind one NAT shares an IP, and a
    single user must not be able to burn the tenant's LLM budget. Falls back
    to the IP when there is no valid session (the endpoint then 401s anyway).
    """
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    auth = request.headers.get("Authorization", "")
    if not token and auth.startswith("Bearer "):
        token = auth.split(" ", 1)[1]
    payload = decode_access_token(token) if token else None
    if payload and payload.get("sub"):
        return f"user:{payload['sub']}"
    return get_remote_address(request)
