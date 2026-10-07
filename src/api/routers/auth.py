from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from src.api.deps import get_current_user
from src.api.schemas.auth import UserCreate, UserLogin, UserOut
from src.db.database import get_db
from src.db.models import User
from src.security.cookies import clear_auth_cookie, set_auth_cookie
from src.security.limiter import limiter
from src.services import auth as service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut)
@limiter.limit("5/minute")
def register(request: Request, user: UserCreate, db: Session = Depends(get_db)):
    try:
        return service.create_tenant_and_user(db, user.to_signup())
    except service.EmailAlreadyRegistered:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email is already registered.") from None


@router.post("/login")
@limiter.limit("5/minute")
def login(request: Request, user_credentials: UserLogin, response: Response, db: Session = Depends(get_db)):
    try:
        user = service.authenticate_user(db, user_credentials.email, user_credentials.password)
    except service.InvalidCredentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials") from None

    set_auth_cookie(response, service.session_token(user))
    return {"status": "success", "message": "Logged in successfully"}


@router.post("/logout")
def logout(response: Response):
    clear_auth_cookie(response)
    return {"status": "success", "message": "Logged out successfully"}


@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "sub": current_user.id,
        "email": current_user.email,
        "role": current_user.role,
        "tenant_id": current_user.company_id,
        "onboarding_completed": current_user.company.onboarding_completed
    }
