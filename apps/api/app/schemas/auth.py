from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)
    organization_id: str = Field(min_length=36, max_length=36)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=32)
    organization_id: str = Field(min_length=36, max_length=36)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=32)
    organization_id: str = Field(min_length=36, max_length=36)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str
