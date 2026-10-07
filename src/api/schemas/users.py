from typing import Optional

from pydantic import BaseModel, ConfigDict


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str
    job_title: Optional[str] = None
    role: str
    created_at: str


class CreateUserPayload(BaseModel):
    email: str
    full_name: str
    job_title: Optional[str] = None
    password: str
    role: str = "employee"
