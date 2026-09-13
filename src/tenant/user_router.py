from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from src.db.database import get_db
from src.db.models import User, Company, SubscriptionPlan
from src.security.deps import get_current_user
from src.auth.service import get_password_hash

router = APIRouter(prefix="/tenant/users", tags=["tenant_users"])

class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    job_title: Optional[str] = None
    role: str
    created_at: str

    class Config:
        from_attributes = True

class CreateUserPayload(BaseModel):
    email: str
    full_name: str
    job_title: Optional[str] = None
    password: str
    role: str = "employee"

@router.get("", response_model=List[UserResponse])
def get_tenant_users(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in ["superadmin", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized.")
        
    users = db.query(User).filter(User.company_id == current_user.company_id).all()
    
    result = []
    for u in users:
        result.append({
            "id": u.id,
            "email": u.email,
            "full_name": u.full_name,
            "job_title": u.job_title,
            "role": u.role,
            "created_at": u.created_at.isoformat() if u.created_at else ""
        })
    return result

@router.post("", response_model=UserResponse)
def create_tenant_user(payload: CreateUserPayload, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in ["superadmin", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized.")
        
    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == company.plan_id).first()
    
    if not plan:
        # Default to Free limits if no plan is found
        max_users = 2
    else:
        max_users = plan.max_users
        
    current_user_count = db.query(User).filter(User.company_id == current_user.company_id).count()
    
    if current_user_count >= max_users:
        raise HTTPException(status_code=402, detail=f"Plan limit reached. Your current plan allows a maximum of {max_users} users.")
        
    # Check if email exists
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered.")
        
    new_user = User(
        email=payload.email,
        full_name=payload.full_name,
        job_title=payload.job_title,
        password_hash=get_password_hash(payload.password),
        role=payload.role,
        company_id=current_user.company_id
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return {
        "id": new_user.id,
        "email": new_user.email,
        "full_name": new_user.full_name,
        "job_title": new_user.job_title,
        "role": new_user.role,
        "created_at": new_user.created_at.isoformat() if new_user.created_at else ""
    }

@router.delete("/{user_id}")
def delete_tenant_user(user_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in ["superadmin", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized.")
        
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot delete yourself.")
        
    user_to_delete = db.query(User).filter(User.id == user_id, User.company_id == current_user.company_id).first()
    if not user_to_delete:
        raise HTTPException(status_code=404, detail="User not found.")
        
    db.delete(user_to_delete)
    db.commit()
    
    return {"status": "success", "message": "User deleted."}
