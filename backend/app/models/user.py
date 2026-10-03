"""用户数据访问（阶段 1）。

只放数据访问与最基础的约束，业务规则（谁能改谁）放在 services 层。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.core import security
from app.models.base import Conflict, NotFound, row_to_dict

ROLE_THERAPIST = "therapist"
ROLE_ADMIN = "admin"
ROLES = (ROLE_THERAPIST, ROLE_ADMIN)

STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"
STATUSES = (STATUS_ACTIVE, STATUS_DISABLED)

# 对外输出时必须剔除的字段
SECRET_FIELDS = ("password_hash",)

SELECT_COLUMNS = "id, employee_no, name, phone, role, status, created_at, updated_at"


def get_by_id(conn: sqlite3.Connection, user_id: int) -> dict[str, Any] | None:
    return row_to_dict(conn.execute(f"SELECT {SELECT_COLUMNS} FROM user WHERE id = ?", (user_id,)).fetchone())


def get_by_id_or_raise(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    user = get_by_id(conn, user_id)
    if user is None:
        raise NotFound("用户不存在", details={"user_id": user_id})
    return user


def get_by_employee_no(conn: sqlite3.Connection, employee_no: str) -> dict[str, Any] | None:
    return row_to_dict(
        conn.execute(f"SELECT {SELECT_COLUMNS} FROM user WHERE employee_no = ?", (employee_no,)).fetchone()
    )


def get_auth_record(conn: sqlite3.Connection, employee_no: str) -> dict[str, Any] | None:
    """登录用：额外取出 `password_hash`。**不要**把它返回给客户端。"""
    return row_to_dict(
        conn.execute(
            "SELECT id, employee_no, name, role, status, password_hash FROM user WHERE employee_no = ?",
            (employee_no,),
        ).fetchone()
    )


def list_users(
    conn: sqlite3.Connection,
    *,
    role: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    where: list[str] = []
    params: list[Any] = []
    if role:
        where.append("role = ?")
        params.append(role)
    if status:
        where.append("status = ?")
        params.append(status)
    if keyword:
        where.append("(name LIKE ? OR employee_no LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    total = int(conn.execute(f"SELECT COUNT(*) FROM user {clause}", params).fetchone()[0])
    rows = conn.execute(
        f"SELECT {SELECT_COLUMNS} FROM user {clause} ORDER BY employee_no LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return [dict(r) for r in rows], total


def create_user(
    conn: sqlite3.Connection,
    *,
    employee_no: str,
    name: str,
    role: str,
    password: str | None = None,
    phone: str | None = None,
) -> dict[str, Any]:
    if role not in ROLES:
        raise Conflict(f"角色必须是 {'/'.join(ROLES)} 之一", details={"role": role})
    if get_by_employee_no(conn, employee_no) is not None:
        raise Conflict("工号已存在", details={"employee_no": employee_no})

    password_hash = security.hash_password(password) if password else None
    cur = conn.execute(
        "INSERT INTO user (employee_no, name, role, phone, password_hash, status) VALUES (?, ?, ?, ?, ?, ?)",
        (employee_no, name, role, phone, password_hash, STATUS_ACTIVE),
    )
    return get_by_id_or_raise(conn, int(cur.lastrowid))


def update_user(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    name: str | None = None,
    phone: str | None = None,
    role: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    get_by_id_or_raise(conn, user_id)
    if role is not None and role not in ROLES:
        raise Conflict(f"角色必须是 {'/'.join(ROLES)} 之一", details={"role": role})
    if status is not None and status not in STATUSES:
        raise Conflict(f"状态必须是 {'/'.join(STATUSES)} 之一", details={"status": status})

    sets: list[str] = []
    params: list[Any] = []
    for column, value in (("name", name), ("phone", phone), ("role", role), ("status", status)):
        if value is not None:
            sets.append(f"{column} = ?")
            params.append(value)
    if sets:
        conn.execute(f"UPDATE user SET {', '.join(sets)} WHERE id = ?", (*params, user_id))
    return get_by_id_or_raise(conn, user_id)


def set_password(conn: sqlite3.Connection, user_id: int, password: str) -> None:
    get_by_id_or_raise(conn, user_id)
    conn.execute("UPDATE user SET password_hash = ? WHERE id = ?", (security.hash_password(password), user_id))
    # 改密码后所有已发放的 refresh token 立即失效（防止旧令牌继续用）
    conn.execute(
        "UPDATE auth_session SET revoked_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')"
        " WHERE user_id = ? AND revoked_at IS NULL",
        (user_id,),
    )


def count_active_admins(conn: sqlite3.Connection) -> int:
    """用于"不许把最后一个管理员降级/停用"这类保护。"""
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM user WHERE role = ? AND status = ?", (ROLE_ADMIN, STATUS_ACTIVE)
        ).fetchone()[0]
    )


__all__ = [
    "ROLES",
    "ROLE_ADMIN",
    "ROLE_THERAPIST",
    "SECRET_FIELDS",
    "SELECT_COLUMNS",
    "STATUSES",
    "STATUS_ACTIVE",
    "STATUS_DISABLED",
    "count_active_admins",
    "create_user",
    "get_auth_record",
    "get_by_employee_no",
    "get_by_id",
    "get_by_id_or_raise",
    "list_users",
    "set_password",
    "update_user",
]
