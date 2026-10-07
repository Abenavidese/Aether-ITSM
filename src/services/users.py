"""A tenant's users: list, create (within the plan's seat limit), delete."""
from sqlalchemy.orm import Session

from src.db.models import Company, SubscriptionPlan, User
from src.security.hashing import get_password_hash

_FREE_PLAN_MAX_USERS = 2


class UserError(Exception):
    pass


class PlanLimitReached(UserError):
    def __init__(self, max_users: int):
        self.max_users = max_users
        super().__init__(f"Plan limit reached. Your current plan allows a maximum of {max_users} users.")


class EmailTaken(UserError):
    def __init__(self):
        super().__init__("Email already registered.")


class CannotDeleteSelf(UserError):
    def __init__(self):
        super().__init__("You cannot delete yourself.")


class UserNotFound(UserError):
    def __init__(self):
        super().__init__("User not found.")


def _to_dict(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "full_name": u.full_name,
        "job_title": u.job_title,
        "role": u.role,
        "created_at": u.created_at.isoformat() if u.created_at else ""
    }


def list_users(db: Session, company_id: str) -> list[dict]:
    return [_to_dict(u) for u in db.query(User).filter(User.company_id == company_id).all()]


def create_user(db: Session, company_id: str, *, email: str, full_name: str, job_title: str | None,
                password: str, role: str) -> dict:
    company = db.query(Company).filter(Company.id == company_id).first()
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == company.plan_id).first()
    # Default to Free limits if no plan is found
    max_users = plan.max_users if plan else _FREE_PLAN_MAX_USERS

    if db.query(User).filter(User.company_id == company_id).count() >= max_users:
        raise PlanLimitReached(max_users)
    if db.query(User).filter(User.email == email).first():
        raise EmailTaken()

    new_user = User(
        email=email,
        full_name=full_name,
        job_title=job_title,
        password_hash=get_password_hash(password),
        role=role,
        company_id=company_id
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return _to_dict(new_user)


def delete_user(db: Session, acting_user: User, user_id: str) -> None:
    if user_id == acting_user.id:
        raise CannotDeleteSelf()
    user = db.query(User).filter(User.id == user_id, User.company_id == acting_user.company_id).first()
    if not user:
        raise UserNotFound()
    db.delete(user)
    db.commit()
