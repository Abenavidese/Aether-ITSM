from sqlalchemy import Column, String, ForeignKey, DateTime, Integer, Float
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from .database import Base
import uuid

class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"
    
    id = Column(String, primary_key=True)
    name = Column(String) # Free, Pro, Enterprise
    price_usd = Column(Float, default=0.0)
    
    max_users = Column(Integer, default=2)
    max_tickets_per_month = Column(Integer, default=100)
    max_ai_resolutions_per_month = Column(Integer, default=50)


class Company(Base):
    __tablename__ = "companies"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, index=True)
    company_size = Column(String, nullable=True)
    industry = Column(String, nullable=True)
    current_tool = Column(String, nullable=True)
    
    # Integration & Onboarding Settings
    onboarding_completed = Column(String, default="false") # SQLite boolean compatibility
    api_key = Column(String, unique=True, nullable=True)  # Fernet-encrypted — decrypted only for display in Settings
    api_key_hash = Column(String, unique=True, nullable=True, index=True)  # SHA-256 — used to verify webhook calls
    webhook_url = Column(String, nullable=True) # Kept for legacy
    github_token = Column(String, nullable=True)
    github_repo = Column(String, nullable=True)
    mcp_server_url = Column(String, nullable=True)
    mcp_auth_token = Column(String, nullable=True)
    llm_engine = Column(String, default="nemotron-nano")
    
    plan_id = Column(String, ForeignKey("subscription_plans.id"), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    plan = relationship("SubscriptionPlan")
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
    tickets = relationship("Ticket", back_populates="user")


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("companies.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    
    title = Column(String, nullable=False)
    description = Column(String, nullable=False)
    
    # Classification
    urgency = Column(String, default="medium") # low, medium, high, critical
    category = Column(String, default="general") # software, hardware, access, network, general
    
    # Tracking
    status = Column(String, default="open") # open, resolved, escalated_github, pending_human
    resolution_path = Column(String, nullable=True) # autonomous, human, github
    
    # Deep Metrics & ROI
    estimated_time_saved_minutes = Column(Integer, default=0)
    cost_saved_usd = Column(Float, default=0.0)
    ai_confidence_score = Column(Float, nullable=True)
    
    # External Links
    github_issue_url = Column(String, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    company = relationship("Company")
    user = relationship("User", back_populates="tickets")
