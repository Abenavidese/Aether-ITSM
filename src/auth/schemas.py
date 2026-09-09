from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict, Field, field_validator
import re

class Token(BaseModel):
    access_token: str
    token_type: str

class UserLogin(BaseModel):
    email: str
    password: str

class UserCreate(BaseModel):
    email: str = Field(..., max_length=150)
    password: str = Field(..., min_length=8, max_length=100)
    
    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not re.match(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&._-])[A-Za-z\d@$!%*?&._-]+$", v):
            raise ValueError("Password must contain at least 1 uppercase, 1 lowercase, 1 number, and 1 symbol.")
        return v
        
    full_name: str = Field(..., max_length=100)
    job_title: str | None = Field(default=None, max_length=100)
    primary_goal: str | None = Field(default=None, max_length=200)
    
    company_name: str = Field(..., max_length=150)
    company_size: str | None = Field(default=None, max_length=50)
    industry: str | None = Field(default=None, max_length=100)
    current_tool: str | None = Field(default=None, max_length=100)
    
    role: str = Field(default="superadmin", pattern=r"^(superadmin|user)$")

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    role: str
    company_id: str
