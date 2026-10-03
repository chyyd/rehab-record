"""认证相关的请求/响应模型（阶段 1）。

刻意与数据库行解耦：请求模型只声明"允许客户端传什么"，
响应模型只声明"对外暴露什么"。`password_hash` 这类字段不在任何响应模型里，
从类型层面就杜绝了误传。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.user import ROLES, STATUSES


class LoginRequest(BaseModel):
    employee_no: str = Field(min_length=1, max_length=64, description="工号")
    password: str = Field(min_length=1, max_length=256, description="密码")


class RefreshRequest(BaseModel):
    """刷新请求。

    `refresh_token` **可为空**：管理后台 Web 走 httpOnly Cookie 携带它，
    浏览器不会把它交给 JS，因此前端拿不到也没必要传。
    安卓端仍在请求体里传（保持既有协议）。服务端取用顺序是 Cookie 优先。
    """

    refresh_token: str | None = Field(
        default=None, description="安卓端在请求体里传；Web 端留空，走 httpOnly Cookie"
    )


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="access token 剩余有效秒数")


class UserOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    employee_no: str
    name: str
    role: str
    status: str
    phone: str | None = None


class LoginResponse(TokenPair):
    user: UserOut


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=256, description="至少 8 位")


class UserCreateRequest(BaseModel):
    employee_no: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    role: str = Field(description=f"{' / '.join(ROLES)}")
    password: str | None = Field(default=None, min_length=8, max_length=256)
    phone: str | None = Field(default=None, max_length=32)


class UserUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    phone: str | None = Field(default=None, max_length=32)
    role: str | None = Field(default=None, description=f"{' / '.join(ROLES)}")
    status: str | None = Field(default=None, description=f"{' / '.join(STATUSES)}")


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=256)


class UserListOut(BaseModel):
    items: list[UserOut]
    total: int
    page: int
    page_size: int


__all__ = [
    "ChangePasswordRequest",
    "LoginRequest",
    "LoginResponse",
    "RefreshRequest",
    "ResetPasswordRequest",
    "TokenPair",
    "UserCreateRequest",
    "UserListOut",
    "UserOut",
    "UserUpdateRequest",
]
