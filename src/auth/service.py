from sqlalchemy.orm import Session
from src.db import models
from src.security.hashing import get_password_hash, verify_password
from src.auth.schemas import UserCreate
from src.auth.exceptions import EmailAlreadyRegistered, InvalidCredentials

def create_tenant_and_user(db: Session, user: UserCreate) -> models.User:
    """
    Creates a new company tenant and the initial superadmin user atomically.
    Raises EmailAlreadyRegistered if the email exists.
    """
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise EmailAlreadyRegistered(user.email)
        
    # Create Company
    db_company = models.Company(
        name=user.company_name,
        company_size=user.company_size,
        industry=user.industry,
        current_tool=user.current_tool
    )
    db.add(db_company)
    db.flush() # Get company ID without committing transaction
    
    # Create User
    hashed_pwd = get_password_hash(user.password)
    db_user = models.User(
        email=user.email,
        full_name=user.full_name,
        job_title=user.job_title,
        primary_goal=user.primary_goal,
        password_hash=hashed_pwd,
        role=user.role,
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
