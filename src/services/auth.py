"""Sign-up, login and session tokens. No FastAPI here: routers map these errors to HTTP."""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.db import models
from src.security.api_keys import generate_api_key, hash_api_key
from src.security.encryption import encrypt_token
from src.security.hashing import get_password_hash, verify_password
from src.security.jwt import create_access_token


class AuthError(Exception):
    pass


class EmailAlreadyRegistered(AuthError):
    def __init__(self, email: str):
        self.email = email
        super().__init__(f"Email {email} is already registered")


class InvalidCredentials(AuthError):
    def __init__(self):
        super().__init__("Invalid credentials")


@dataclass(frozen=True)
class TenantSignup:
    """What creating a company + its first admin needs (validated by the API schema)."""
    email: str
    password: str
    full_name: str
    company_name: str
    job_title: str | None = None
    primary_goal: str | None = None
    company_size: str | None = None
    industry: str | None = None
    current_tool: str | None = None


def create_tenant_and_user(db: Session, signup: TenantSignup) -> models.User:
    """
    Creates a new company tenant and its initial admin user atomically.
    Raises EmailAlreadyRegistered if the email exists.
    """
    db_user = db.query(models.User).filter(models.User.email == signup.email).first()
    if db_user:
        raise EmailAlreadyRegistered(signup.email)

    # The raw key is never persisted: api_key_hash verifies webhook calls,
    # api_key stores an encrypted copy purely so Settings can redisplay it.
    raw_api_key = generate_api_key()
    db_company = models.Company(
        name=signup.company_name,
        company_size=signup.company_size,
        industry=signup.industry,
        current_tool=signup.current_tool,
        api_key=encrypt_token(raw_api_key),
        api_key_hash=hash_api_key(raw_api_key),
        plan_id="plan_free",  # Every tenant starts on Free; upgrades update this later.
    )
    db.add(db_company)
    db.flush()  # Get company ID without committing transaction

    db_user = models.User(
        email=signup.email,
        full_name=signup.full_name,
        job_title=signup.job_title,
        primary_goal=signup.primary_goal,
        password_hash=get_password_hash(signup.password),
        role="admin",
        company_id=db_company.id
    )
    db.add(db_user)

    # Atomic commit for both
    db.commit()
    db.refresh(db_user)

    return db_user


def authenticate_user(db: Session, email: str, password: str) -> models.User:
    """
    Authenticates a user by email and password.
    Raises InvalidCredentials if authentication fails.
    """
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        raise InvalidCredentials()
    return user


def session_token(user: models.User, onboarding_completed: str | None = None) -> str:
    """JWT carrying the tenant context. Login and onboarding issue the same
    claims (onboarding passes the status it just set before the row reloads)."""
    return create_access_token(data={
        "sub": user.id,
        "email": user.email,
        "role": user.role,
        "tenant_id": user.company_id,
        "onboarding_completed": onboarding_completed if onboarding_completed is not None
        else user.company.onboarding_completed,
    })
