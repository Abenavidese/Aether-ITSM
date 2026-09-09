from pydantic import BaseModel

class Token(BaseModel):
    access_token: str
    token_type: str

class UserLogin(BaseModel):
    email: str
    password: str

class UserCreate(BaseModel):
    email: str
    password: str
    company_name: str
    role: str = "superadmin"

class UserOut(BaseModel):
    id: str
    email: str
    role: str
    company_id: str
