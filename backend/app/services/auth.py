"""认证业务逻辑（阶段 1 / `设计.md` 3.1、5.5；`开发计划.md` D01、M02）。

职责：登录、刷新、注销，以及在 `auth_session` 里维护 refresh token 的生命周期。

设计要点
--------
1. **登录失败信息不区分"工号不存在"与"密码错误"**，统一返回同一句话，
   避免把工号变成可枚举的信息。
2. **账号停用一律拒绝登录**，即使密码正确。
3. 刷新采用**轮换**：旧 refresh token 立即作废、换发新的。
   这样令牌一旦被窃取并使用，合法用户的下次刷新就会失败，暴露异常。
4. 只存 refresh token 的**哈希**（`hash_token`），数据库泄露也无法直接冒充。
5. 密码哈希参数过期时顺手升级（`needs_rehash`），用户无感知。
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core import security
from app.core.config import Settings, get_settings
from app.models import user as user_model
from app.models.base import Forbidden, NotFound
from app.models.user import STATUS_ACTIVE

GENERIC_LOGIN_FAILURE = "工号或密码不正确"


class AuthResult(dict):
    """登录/刷新的返回结果（access_token / refresh_token / expires_in / user）。"""


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _issue_tokens(
    conn: sqlite3.Connection, user: dict[str, Any], settings: Settings
) -> tuple[str, str]:
    access = security.create_access_token(int(user["id"]), settings)
    refresh, jti = security.create_refresh_token(int(user["id"]), settings)
    expires_at = (
        datetime.now(UTC) + timedelta(seconds=settings.refresh_token_ttl_seconds)
    ).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    conn.execute(
        "INSERT INTO auth_session (user_id, refresh_token_hash, expires_at, device_info)"
        " VALUES (?, ?, ?, ?)",
        (user["id"], security.hash_token(refresh), expires_at, jti),
    )
    return access, refresh


def login(
    conn: sqlite3.Connection,
    *,
    employee_no: str,
    password: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    cfg = settings or get_settings()
    record = user_model.get_auth_record(conn, employee_no)

    # 统一的失败出口：不透露是工号不存在还是密码错误
    if record is None or not security.verify_password(password, record.get("password_hash")):
        raise Forbidden(GENERIC_LOGIN_FAILURE, code="INVALID_CREDENTIALS")

    if record["status"] != STATUS_ACTIVE:
        raise Forbidden("账号已停用，请联系管理员", code="ACCOUNT_DISABLED")

    # 密码哈希参数落后了就顺手升级（argon2 参数调整或从 scrypt 迁到 argon2）
    if security.needs_rehash(record.get("password_hash")):
        conn.execute(
            "UPDATE user SET password_hash = ? WHERE id = ?",
            (security.hash_password(password), record["id"]),
        )

    user = user_model.get_by_id_or_raise(conn, int(record["id"]))
    access, refresh = _issue_tokens(conn, user, cfg)
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": cfg.access_token_ttl_seconds,
        "user": user,
    }


def refresh(
    conn: sqlite3.Connection, *, refresh_token: str, settings: Settings | None = None
) -> dict[str, Any]:
    """用 refresh token 换新的一对令牌（轮换旧令牌）。"""
    cfg = settings or get_settings()
    try:
        decoded = security.decode_token(
            refresh_token, expected_type=security.TOKEN_TYPE_REFRESH, settings=cfg
        )
    except security.TokenError as exc:
        raise Forbidden(exc.message, code=exc.code) from exc

    token_hash = security.hash_token(refresh_token)
    session = conn.execute(
        "SELECT id, user_id, expires_at, revoked_at FROM auth_session WHERE refresh_token_hash = ?",
        (token_hash,),
    ).fetchone()
    if session is None:
        # 轮换后旧令牌再次出现：可能是重放，直接拒绝
        raise Forbidden("登录凭证已失效，请重新登录", code="REFRESH_NOT_FOUND")
    if session["revoked_at"] is not None:
        raise Forbidden("登录凭证已失效，请重新登录", code="REFRESH_REVOKED")
    if str(session["expires_at"]) <= _now_iso():
        raise Forbidden("登录已过期，请重新登录", code="REFRESH_EXPIRED")
    if int(session["user_id"]) != decoded.user_id:
        raise Forbidden("登录凭证无效", code="REFRESH_MISMATCH")

    user = user_model.get_by_id(conn, decoded.user_id)
    if user is None:
        raise NotFound("用户不存在")
    if user["status"] != STATUS_ACTIVE:
        raise Forbidden("账号已停用，请联系管理员", code="ACCOUNT_DISABLED")

    # 轮换：旧 session 作废，发放新的
    conn.execute("UPDATE auth_session SET revoked_at = ? WHERE id = ?", (_now_iso(), session["id"]))
    access, new_refresh = _issue_tokens(conn, user, cfg)
    return {
        "access_token": access,
        "refresh_token": new_refresh,
        "token_type": "bearer",
        "expires_in": cfg.access_token_ttl_seconds,
        "user": user,
    }


def logout(conn: sqlite3.Connection, *, refresh_token: str | None = None, user_id: int | None = None) -> int:
    """注销：吊销指定 refresh token；未给 token 时吊销该用户全部会话。

    返回被吊销的会话数。
    """
    now = _now_iso()
    if refresh_token:
        cur = conn.execute(
            "UPDATE auth_session SET revoked_at = ? WHERE refresh_token_hash = ? AND revoked_at IS NULL",
            (now, security.hash_token(refresh_token)),
        )
        return int(cur.rowcount or 0)
    if user_id is not None:
        cur = conn.execute(
            "UPDATE auth_session SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
            (now, user_id),
        )
        return int(cur.rowcount or 0)
    return 0


def revoke_all_sessions(conn: sqlite3.Connection, user_id: int) -> int:
    """管理员踢下线 / 用户改密码后调用。"""
    return logout(conn, user_id=user_id)


__all__ = [
    "GENERIC_LOGIN_FAILURE",
    "login",
    "logout",
    "refresh",
    "revoke_all_sessions",
]
