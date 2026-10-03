"""用户管理接口（阶段 1 / `开发计划.md` 4.1）。管理员专属。"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import Depends, Response, status

from app.api.pagination import Page, page_params
from app.api.router import ApiRouter
from app.core.db_dep import get_db
from app.core.errors import ForbiddenError, NotFoundError
from app.core.security_deps import AdminUser, CurrentUser
from app.models import user as user_model
from app.models.base import Conflict
from app.models.user import ROLE_ADMIN, STATUS_ACTIVE
from app.schemas.auth import (
    ResetPasswordRequest,
    UserCreateRequest,
    UserListOut,
    UserOut,
    UserUpdateRequest,
)
from app.services.audit import write_audit

router = ApiRouter(prefix="/users", tags=["用户管理"])


def _guard_last_admin(conn: sqlite3.Connection, target: dict[str, Any], *, new_role: str | None,
                      new_status: str | None) -> None:
    """不许把最后一个在用管理员降级或停用——否则没人能管理系统了。"""
    if target["role"] != ROLE_ADMIN or target["status"] != STATUS_ACTIVE:
        return
    losing_admin = (new_role is not None and new_role != ROLE_ADMIN) or (
        new_status is not None and new_status != STATUS_ACTIVE
    )
    if losing_admin and user_model.count_active_admins(conn) <= 1:
        raise Conflict(
            "系统必须保留至少一名在用管理员",
            details={"user_id": target["id"]},
        )


@router.get("", response_model=UserListOut, summary="用户列表")
def list_users(
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    page: Annotated[Page, Depends(page_params)],
    role: str | None = None,
    status_filter: str | None = None,
    keyword: str | None = None,
) -> dict[str, Any]:
    items, total = user_model.list_users(
        conn,
        role=role,
        status=status_filter,
        keyword=keyword,
        limit=page.limit,
        offset=page.offset,
    )
    return {"items": items, "total": total, "page": page.page, "page_size": page.page_size}


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED, summary="新建用户")
def create_user(
    payload: UserCreateRequest,
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    user = user_model.create_user(
        conn,
        employee_no=payload.employee_no,
        name=payload.name,
        role=payload.role,
        password=payload.password,
        phone=payload.phone,
    )
    write_audit(conn, user_id=int(admin["id"]), action="create", target_type="user",
                target_id=str(user["id"]), after=user)
    return user


@router.get("/{user_id}", response_model=UserOut, summary="用户详情")
def get_user(
    user_id: int,
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    user = user_model.get_by_id(conn, user_id)
    if user is None:
        raise NotFoundError("USER_NOT_FOUND", "用户不存在", details={"user_id": user_id})
    return user


@router.put("/{user_id}", response_model=UserOut, summary="修改用户")
def update_user(
    user_id: int,
    payload: UserUpdateRequest,
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    before = user_model.get_by_id(conn, user_id)
    if before is None:
        raise NotFoundError("USER_NOT_FOUND", "用户不存在", details={"user_id": user_id})
    _guard_last_admin(conn, before, new_role=payload.role, new_status=payload.status)

    after = user_model.update_user(
        conn, user_id, name=payload.name, phone=payload.phone, role=payload.role, status=payload.status
    )
    # 停用账号要立刻踢掉其现有会话，否则旧 token 还能用到过期
    if payload.status is not None and payload.status != STATUS_ACTIVE:
        from app.services import auth as auth_service

        auth_service.revoke_all_sessions(conn, user_id)

    write_audit(conn, user_id=int(admin["id"]), action="update", target_type="user",
                target_id=str(user_id), before=before, after=after)
    return after


@router.post(
    "/{user_id}/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="重置密码",
)
def reset_password(
    user_id: int,
    payload: ResetPasswordRequest,
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> Response:
    if user_model.get_by_id(conn, user_id) is None:
        raise NotFoundError("USER_NOT_FOUND", "用户不存在", details={"user_id": user_id})
    # 管理员给自己重置也一样：会吊销全部会话，需要重新登录
    user_model.set_password(conn, user_id, payload.new_password)
    write_audit(conn, user_id=int(admin["id"]), action="reset_password", target_type="user",
                target_id=str(user_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{user_id}/sessions", summary="该用户的活跃会话")
def list_sessions(
    user_id: int,
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    """用于"谁在哪台设备上还登着"，以及排查令牌问题。"""
    rows = conn.execute(
        "SELECT id, device_info, created_at, expires_at, revoked_at FROM auth_session"
        " WHERE user_id = ? ORDER BY id DESC LIMIT 50",
        (user_id,),
    ).fetchall()
    return {"items": [dict(r) for r in rows]}


@router.delete(
    "/{user_id}/sessions",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="踢下线",
)
def revoke_sessions(
    user_id: int,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> Response:
    """管理员可踢任何人；治疗师只能踢自己（用于"我的设备"页面）。"""
    if user["id"] != user_id and user["role"] != ROLE_ADMIN:
        raise ForbiddenError("FORBIDDEN", "只能操作自己的会话")

    from app.services import auth as auth_service

    auth_service.revoke_all_sessions(conn, user_id)
    write_audit(conn, user_id=int(user["id"]), action="revoke_sessions", target_type="user",
                target_id=str(user_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
