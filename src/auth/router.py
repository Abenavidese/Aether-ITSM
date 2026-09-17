from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from sqlalchemy.orm import Session
from src.db.database import get_db
from src.db.models import User
from src.auth import schemas, service
from src.auth.exceptions import EmailAlreadyRegistered, InvalidCredentials
from src.security.jwt import create_access_token
from src.security.deps import get_current_user
from src.security.limiter import limiter
from src.security.cookies import set_auth_cookie, clear_auth_cookie

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", response_model=schemas.UserOut)
@limiter.limit("5/minute")
def register(request: Request, user: schemas.UserCreate, db: Session = Depends(get_db)):
    try:
        return service.create_tenant_and_user(db, user)
    except EmailAlreadyRegistered as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.post("/login")
@limiter.limit("5/minute")
def login(request: Request, user_credentials: schemas.UserLogin, response: Response, db: Session = Depends(get_db)):
    try:
        user = service.authenticate_user(db, user_credentials.email, user_credentials.password)
    except InvalidCredentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        
    # Inject Tenant Context into JWT
    token_data = {
        "sub": user.id,
        "email": user.email,
        "role": user.role,
        "tenant_id": user.company_id,
        "onboarding_completed": user.company.onboarding_completed
    }
    
    access_token = create_access_token(data=token_data)
    set_auth_cookie(response, access_token)

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
