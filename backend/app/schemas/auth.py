import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class UserRegister(BaseModel):
    email: EmailStr = Field(..., description="Email đăng ký của người dùng")
    password: str = Field(..., min_length=6, description="Mật khẩu dài ít nhất 6 ký tự")


class UserLogin(BaseModel):
    email: EmailStr = Field(..., description="Email đăng nhập")
    password: str = Field(..., description="Mật khẩu đăng nhập")


class TokenResponse(BaseModel):
    access_token: str = Field(..., description="Access Token (Hiệu lực 20 phút)")
    refresh_token: str = Field(..., description="Refresh Token (Hiệu lực 7 ngày)")
    token_type: str = Field("bearer", description="Loại token")


class TokenRefreshRequest(BaseModel):
    refresh_token: str = Field(..., description="Refresh Token hợp lệ để lấy Access Token mới")


class UserResponse(BaseModel):
    id: uuid.UUID = Field(..., description="ID định danh")
    email: EmailStr = Field(..., description="Email người dùng")
    is_active: bool = Field(..., description="Trạng thái tài khoản")
    created_at: datetime = Field(..., description="Ngày tạo tài khoản")

    class Config:
        from_attributes = True
