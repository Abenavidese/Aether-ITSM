from sqlalchemy import Column, String, ForeignKey, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from .database import Base
import uuid

def generate_uuid():
    return str(uuid.uuid4())

class Company(Base):
    __tablename__ = "companies"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, index=True)
    company_size = Column(String, nullable=True)
    industry = Column(String, nullable=True)
    current_tool = Column(String, nullable=True)
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
