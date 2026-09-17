"""
Single source of truth for how the auth cookie is set and cleared.

Every issuer (login, onboarding, ...) must use the exact same flags, or the
cookie one endpoint just wrote can be silently rejected/dropped when read
back under different Secure/SameSite semantics.
"""
from fastapi import Response
from src.config import get_settings

ACCESS_TOKEN_COOKIE = "access_token"


def set_auth_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=24 * 60 * 60,  # 24 hours
    )


def clear_auth_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(ACCESS_TOKEN_COOKIE, secure=settings.cookie_secure, samesite="lax")
