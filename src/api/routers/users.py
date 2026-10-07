"""A tenant's users (admins only)."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.deps import get_current_user, require_admin
from src.api.schemas.users import CreateUserPayload, UserResponse
from src.db.database import get_db
from src.db.models import User
from src.services import users as service

router = APIRouter(prefix="/tenant/users", tags=["tenant_users"])

_STATUS = {service.PlanLimitReached: 402, service.EmailTaken: 400, service.CannotDeleteSelf: 400,
           service.UserNotFound: 404}


def _http(error: service.UserError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(type(error), 400), detail=str(error))


@router.get("", response_model=List[UserResponse])
def get_tenant_users(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    return service.list_users(db, current_user.company_id)


@router.post("", response_model=UserResponse)
def create_tenant_user(payload: CreateUserPayload, db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    try:
        return service.create_user(db, current_user.company_id, email=payload.email, full_name=payload.full_name,
                                   job_title=payload.job_title, password=payload.password, role=payload.role)
    except service.UserError as e:
        raise _http(e) from None


@router.delete("/{user_id}")
def delete_tenant_user(user_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    try:
        service.delete_user(db, current_user, user_id)
    except service.UserError as e:
        raise _http(e) from None
    return {"status": "success", "message": "User deleted."}
