from sqlalchemy import Column, String, ForeignKey, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from .database import Base
import uuid

class Company(Base):
    __tablename__ = "companies"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, index=True)
    company_size = Column(String, nullable=True)
    industry = Column(String, nullable=True)
    current_tool = Column(String, nullable=True)
    
    # Integration & Onboarding Settings
    onboarding_completed = Column(String, default="false") # SQLite boolean compatibility
    api_key = Column(String, unique=True, nullable=True) # Kept for legacy/SDK
    webhook_url = Column(String, nullable=True) # Kept for legacy
    github_token = Column(String, nullable=True)
    github_repo = Column(String, nullable=True)
    mcp_server_url = Column(String, nullable=True)
    mcp_auth_token = Column(String, nullable=True)
    llm_engine = Column(String, default="nemotron-nano")
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    users = relationship("User", back_populates="company")

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, index=True)
    full_name = Column(String, nullable=False)
    job_title = Column(String, nullable=True)
    primary_goal = Column(String, nullable=True)
    password_hash = Column(String)
    role = Column(String, default="employee") # superadmin, admin, employee
    company_id = Column(String, ForeignKey("companies.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    company = relationship("Company", back_populates="users")
