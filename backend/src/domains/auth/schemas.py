from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, ConfigDict

class UserCreateReq(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    is_super_admin: bool = False

class UserLoginReq(BaseModel):
    email: EmailStr
    password: str

class UserRes(BaseModel):
    id: str
    email: EmailStr
    is_active: bool
    is_super_admin: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class TokenRes(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRes
