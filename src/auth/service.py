from sqlalchemy.orm import Session
from src.db import models
from src.security.hashing import get_password_hash
from src.auth.schemas import UserCreate
from fastapi import HTTPException

def create_tenant_and_user(db: Session, user: UserCreate):
    # Check if user exists
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
        
    # Create Company
    db_company = models.Company(
        name=user.company_name,
        company_size=user.company_size,
        industry=user.industry,
        current_tool=user.current_tool
    )
    db.add(db_company)
    db.commit()
    db.refresh(db_company)
    
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
    db.commit()
    db.refresh(db_user)
    
    return db_user
