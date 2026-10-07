"""FastAPI dependencies shared by every router: who is calling, may they, and their DB session."""
from typing import Generator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from src.db.database import get_db
from src.db.models import User
from src.db.tenant_scope import tenant_session
from src.security.jwt import decode_access_token

ADMIN_ROLES = ("superadmin", "admin")


def require_admin(user: User, detail: str = "Not authorized.") -> None:
    if user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def get_current_user(request: Request, db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = request.cookies.get("access_token")
    if not token:
        # Fallback for API clients using Authorization header
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

    if not token:
        raise credentials_exception

    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception

    user_id = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception

    return user


def get_tenant_db(current_user=Depends(get_current_user)) -> Generator[Session, None, None]:
    """A session scoped to the caller's tenant (Row-Level Security, roadmap 2.5)."""
    with tenant_session(current_user.company_id) as db:
        yield db
