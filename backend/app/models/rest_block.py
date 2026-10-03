"""休息块数据访问（阶段 2 / `设计.md` 3.5.1、`开发计划.md` M07）。

粒度是**半日**，不是小时：

- ``scope='weekly'``：每周固定某天的某个半日休息（如周三下午业务学习）
- ``scope='date'``：指定日期的某个半日休息

库层已有唯一索引与 CHECK 保证自洽性（`weekly` 必须有 `weekday` 且无日期，反之亦然），
本模块在此之上给出**可读的错误信息**，避免把 `IntegrityError` 直接抛给客户端。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.core.worktime import normalize_period
from app.models.base import Conflict, Invalid, NotFound, row_to_dict

SCOPES = ("weekly", "date")
SELECT_COLUMNS = "id, therapist_id, scope, weekday, specific_date, period, note, created_at"


def get_rest_block(conn: sqlite3.Connection, block_id: int) -> dict[str, Any] | None:
    return row_to_dict(
        conn.execute(f"SELECT {SELECT_COLUMNS} FROM rest_block WHERE id = ?", (block_id,)).fetchone()
    )


def get_rest_block_or_raise(conn: sqlite3.Connection, block_id: int) -> dict[str, Any]:
    row = get_rest_block(conn, block_id)
    if row is None:
        raise NotFound("休息块不存在", details={"rest_block_id": block_id})
    return row


def list_rest_blocks(conn: sqlite3.Connection, therapist_id: int | None = None) -> list[dict[str, Any]]:
    if therapist_id is None:
        rows = conn.execute(
            f"SELECT {SELECT_COLUMNS} FROM rest_block ORDER BY therapist_id, scope, weekday, specific_date"
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {SELECT_COLUMNS} FROM rest_block WHERE therapist_id = ?"
            " ORDER BY scope, weekday, specific_date",
            (therapist_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _validate(scope: str, weekday: int | None, specific_date: str | None) -> None:
    if scope not in SCOPES:
        raise Invalid(f"休息块类型必须是 {'/'.join(SCOPES)} 之一", details={"scope": scope})
    if scope == "weekly":
        if weekday is None:
            raise Invalid("每周固定休息必须指定 weekday（0=周一 … 6=周日）", details={"scope": scope})
        if specific_date is not None:
            raise Invalid("每周固定休息不能同时指定具体日期", details={"specific_date": specific_date})
        if not 0 <= int(weekday) <= 6:
            raise Invalid("weekday 必须在 0–6 之间（0=周一）", details={"weekday": weekday})
    else:
        if specific_date is None:
            raise Invalid("指定日期休息必须提供 specific_date", details={"scope": scope})
        if weekday is not None:
            raise Invalid("指定日期休息不能同时指定 weekday", details={"weekday": weekday})
        try:
            from datetime import date as _date

            _date.fromisoformat(specific_date)
        except ValueError as exc:
            raise Invalid("specific_date 必须是 YYYY-MM-DD", details={"specific_date": specific_date}) from exc


def create_rest_block(
    conn: sqlite3.Connection,
    *,
    therapist_id: int,
    scope: str,
    period: str,
    weekday: int | None = None,
    specific_date: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    _validate(scope, weekday, specific_date)
    period = normalize_period(period)
    if period not in ("am", "pm"):
        raise Invalid("休息块只支持半天（am / pm）；整天不排班不需要休息块", details={"period": period})

    try:
        cur = conn.execute(
            "INSERT INTO rest_block (therapist_id, scope, weekday, specific_date, period, note)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (therapist_id, scope, weekday, specific_date, period, note),
        )
    except sqlite3.IntegrityError as exc:
        raise Conflict("该半日已存在休息块", details={"reason": str(exc)}) from exc
    return get_rest_block_or_raise(conn, int(cur.lastrowid))


def update_rest_block(
    conn: sqlite3.Connection,
    block_id: int,
    *,
    scope: str | None = None,
    weekday: int | None = None,
    specific_date: str | None = None,
    period: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    current = get_rest_block_or_raise(conn, block_id)
    target_scope = scope or current["scope"]
    # 切换 scope 时清掉互斥字段，避免带上旧值触发 CHECK
    if scope is not None and scope != current["scope"]:
        if scope == "weekly":
            weekday, specific_date = (current["weekday"] if weekday is None else weekday), None
        else:
            weekday, specific_date = None, (current["specific_date"] if specific_date is None else specific_date)
    else:
        weekday = current["weekday"] if weekday is None else weekday
        specific_date = current["specific_date"] if specific_date is None else specific_date

    _validate(target_scope, weekday, specific_date)
    target_period = normalize_period(period) if period else current["period"]

    try:
        conn.execute(
            "UPDATE rest_block SET scope = ?, weekday = ?, specific_date = ?, period = ?,"
            " note = COALESCE(?, note) WHERE id = ?",
            (target_scope, weekday, specific_date, target_period, note, block_id),
        )
    except sqlite3.IntegrityError as exc:
        raise Conflict("该半日已存在休息块", details={"reason": str(exc)}) from exc
    return get_rest_block_or_raise(conn, block_id)


def delete_rest_block(conn: sqlite3.Connection, block_id: int) -> None:
    get_rest_block_or_raise(conn, block_id)
    conn.execute("DELETE FROM rest_block WHERE id = ?", (block_id,))


__all__ = [
    "SCOPES",
    "SELECT_COLUMNS",
    "create_rest_block",
    "delete_rest_block",
    "get_rest_block",
    "get_rest_block_or_raise",
    "list_rest_blocks",
    "update_rest_block",
]
