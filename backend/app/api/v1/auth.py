"""认证接口（阶段 1 / `开发计划.md` 4.1）。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /auth/login | 工号 + 密码登录，返回 access/refresh |
| POST | /auth/refresh | 刷新 access token（轮换 refresh） |
| POST | /auth/logout | 吊销 refresh token |
| GET | /auth/me | 当前用户与角色 |
| PUT | /auth/password | 修改自己的密码（改后所有会话失效） |
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import Depends, Query, Request, Response, status

from app.api.router import ApiRouter
from app.core import security
from app.core.config import Settings, get_settings
from app.core.db_dep import get_db
from app.core.errors import BadRequestError
from app.core.security_deps import CurrentUser
from app.models import user as user_model
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    TokenPair,
    UserOut,
)
from app.services import auth as auth_service
from app.services.audit import write_audit

router = ApiRouter(prefix="/auth", tags=["认证"])


# --------------------------------------------------------------------------- #
# refresh token 的 httpOnly Cookie（管理后台 Web 用；安卓端仍用响应体）
# --------------------------------------------------------------------------- #
def _set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    """把 refresh token 写进 httpOnly Cookie。

    **为什么必须 httpOnly**：管理后台是浏览器里的 JS，若 refresh token 存进
    localStorage，一次 XSS 就能把长期凭证偷走（它有效期 90 天）。
    放进 httpOnly Cookie 后 JS 读不到，同时浏览器会自动随请求带上。

    路径限定为 `/api/v1/auth`，使这个凭证只在刷新与登出时才会被发送 ——
    不必在每次业务请求里携带长期凭证，缩小暴露面。
    """
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        max_age=settings.refresh_token_ttl_seconds,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
    )


def _token_from(request: Request, settings: Settings) -> str | None:
    """从 Cookie 取 refresh token（Web 路径）。"""
    return request.cookies.get(settings.refresh_cookie_name)


def _client_info(request: Request) -> str:
    """记录设备信息，便于管理员在会话列表里辨认（M02）。"""
    ua = request.headers.get("user-agent", "")
    host = request.client.host if request.client else ""
    return f"{host} {ua}".strip()[:200]


@router.post("/login", response_model=LoginResponse, summary="登录")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """登录。

    同时以两种方式交付 refresh token，按客户端类型选择：

    - **响应体**里的 `refresh_token`（安卓端继续用，行为不变）；
    - **httpOnly Cookie**（管理后台 Web 用，JS 读不到，避免 XSS 窃取长期凭证）。

    两者是同一个 token，客户端挑一种即可，不会产生两个会话。
    """
    result = auth_service.login(
        conn, employee_no=payload.employee_no, password=payload.password, settings=settings
    )
    # 补记设备信息，便于管理员在会话列表里辨认来源（M02）
    conn.execute(
        "UPDATE auth_session SET device_info = ? WHERE refresh_token_hash = ?",
        (_client_info(request), security.hash_token(result["refresh_token"])),
    )
    write_audit(
        conn,
        user_id=result["user"]["id"],
        action="login",
        target_type="user",
        target_id=str(result["user"]["id"]),
        after={"employee_no": payload.employee_no},
    )
    _set_refresh_cookie(response, result["refresh_token"], settings)
    return result


@router.post("/refresh", response_model=TokenPair, summary="刷新令牌")
def refresh(
    payload: RefreshRequest,
    request: Request,
    response: Response,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """刷新 access token（轮换 refresh）。

    refresh token 的取用顺序：**Cookie 优先，其次请求体**。
    - 管理后台走 Cookie，浏览器自动携带，JS 不需要也不应该持有它；
    - 安卓端继续在请求体里传（保持既有协议不变）。
    """
    token = _token_from(request, settings) or payload.refresh_token
    if not token:
        raise BadRequestError(
            "MISSING_REFRESH_TOKEN", "缺少 refresh token（Cookie 与请求体都没有）"
        )
    result = auth_service.refresh(conn, refresh_token=token, settings=settings)
    _set_refresh_cookie(response, result["refresh_token"], settings)
    return result


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="退出登录",
)
def logout(
    user: CurrentUser,
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    refresh_token: str | None = Query(
        default=None,
        description="要吊销的 refresh token。不传则吊销当前用户的全部会话（用于'退出所有设备'）",
    ),
) -> Response:
    """注销。

    204 响应不能带 body（FastAPI 会断言失败），因此：
    - refresh token 走查询参数或 httpOnly Cookie，而不是请求体；
    - 显式声明 ``response_class=Response``，避免 FastAPI 从类型注解推断出响应模型。

    取用顺序：**查询参数优先，其次 Cookie**。不传时吊销全部会话 ——
    治疗师共用设备时，"退出登录"期望的是彻底退出。

    无论走哪条路径都会**清掉 Cookie**，否则浏览器里会残留一份已吊销的凭证。
    """
    token = refresh_token or _token_from(request, settings)
    if token:
        revoked = auth_service.logout(conn, refresh_token=token)
        if revoked == 0:
            # token 已失效或不属于任何人：仍然吊销该用户全部会话，保证"退出"语义
            auth_service.logout(conn, user_id=int(user["id"]))
    else:
        auth_service.logout(conn, user_id=int(user["id"]))
    write_audit(conn, user_id=int(user["id"]), action="logout", target_type="user",
                target_id=str(user["id"]))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response, settings)
    return response


@router.get("/me", response_model=UserOut, summary="当前用户")
def me(user: CurrentUser) -> dict[str, Any]:
    return user


@router.put(
    "/password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="修改自己的密码",
)
def change_password(
    payload: ChangePasswordRequest,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> Response:
    record = user_model.get_auth_record(conn, user["employee_no"])
    if record is None or not security.verify_password(payload.old_password, record.get("password_hash")):
        raise BadRequestError("OLD_PASSWORD_WRONG", "原密码不正确")
    if payload.old_password == payload.new_password:
        raise BadRequestError("PASSWORD_UNCHANGED", "新密码不能与原密码相同")

    # set_password 内部会吊销该用户所有会话，强迫重新登录
    user_model.set_password(conn, int(user["id"]), payload.new_password)
    write_audit(conn, user_id=int(user["id"]), action="change_password", target_type="user",
                target_id=str(user["id"]))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
