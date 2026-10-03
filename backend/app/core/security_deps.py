"""认证与授权依赖（阶段 1 / `开发计划.md` D10）。

**权限规则的唯一落点。** 路由只声明"需要什么身份"，具体判断在这里做，
避免每个路由各写一遍导致漏判。

约定：
- 未认证 → 401，并带 `WWW-Authenticate: Bearer`（HTTP 规范要求）。
- 已认证但权限不足 → 403。
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core import security
from app.core.config import Settings, get_settings
from app.core.db_dep import get_db
from app.core.errors import ForbiddenError, UnauthorizedError
from app.models import user as user_model
from app.models.user import ROLE_ADMIN, STATUS_ACTIVE

# auto_error=False：自己抛 401，才能保证错误体与 D08 一致
_bearer = HTTPBearer(auto_error=False, scheme_name="BearerToken", description="登录后获得的 access token")

_UNAUTHORIZED_HEADERS = {"WWW-Authenticate": "Bearer"}


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """解析 access token 并取出当前用户。"""
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError(
            "AUTH_REQUIRED", "需要登录", details={"header": "Authorization: Bearer <token>"}
        )

    try:
        decoded = security.decode_token(
            credentials.credentials, expected_type=security.TOKEN_TYPE_ACCESS, settings=settings
        )
    except security.TokenError as exc:
        raise UnauthorizedError(exc.code, exc.message) from exc

    user = user_model.get_by_id(conn, decoded.user_id)
    if user is None:
        raise UnauthorizedError("USER_NOT_FOUND", "用户不存在或已被删除")
    if user["status"] != STATUS_ACTIVE:
        # 账号被停用后，已发放的 token 也要立刻失效
        raise UnauthorizedError("ACCOUNT_DISABLED", "账号已停用，请联系管理员")
    return user


CurrentUser = Annotated[dict[str, Any], Depends(get_current_user)]


def require_admin(user: CurrentUser) -> dict[str, Any]:
    if user["role"] != ROLE_ADMIN:
        raise ForbiddenError("ADMIN_REQUIRED", "该操作仅管理员可用")
    return user


AdminUser = Annotated[dict[str, Any], Depends(require_admin)]


def is_admin(user: dict[str, Any]) -> bool:
    return user.get("role") == ROLE_ADMIN


__all__ = [
    "AdminUser",
    "CurrentUser",
    "get_current_user",
    "is_admin",
    "require_admin",
]
