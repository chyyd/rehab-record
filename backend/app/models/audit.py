"""审计日志查询（阶段 5 / `设计.md` 3.11、6.2）。

**只读**：审计日志由库层触发器与 `services/audit.write_audit` 写入，
不提供任何修改或删除接口 —— 能改的审计日志就不是审计日志了。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.core import jsonutil

COLUMNS = "id, user_id, action, target_type, target_id, before_json, after_json, created_at"


def list_audit_logs(
    conn: sqlite3.Connection,
    *,
    user_id: int | None = None,
    action: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """按人、按对象、按时间范围查询（6.2 后台的"审计日志"模块）。"""
    where: list[str] = []
    params: list[Any] = []
    if user_id is not None:
        where.append("a.user_id = ?")
        params.append(user_id)
    if action:
        where.append("a.action = ?")
        params.append(action)
    if target_type:
        where.append("a.target_type = ?")
        params.append(target_type)
    if target_id:
        where.append("a.target_id = ?")
        params.append(str(target_id))
    if date_from:
        # created_at 是 ISO8601 UTC（带 Z），字符串比较即时间比较
        where.append("a.created_at >= ?")
        params.append(date_from)
    if date_to:
        where.append("a.created_at <= ?")
        params.append(date_to)

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    base = f"FROM audit_log a LEFT JOIN user u ON u.id = a.user_id {clause}"
    total = int(conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0])
    rows = conn.execute(
        "SELECT a.id, a.user_id, a.action, a.target_type, a.target_id, a.before_json,"
        " a.after_json, a.created_at, u.name AS user_name, u.employee_no"
        f" {base} ORDER BY a.id DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["before"] = jsonutil.loads(item.pop("before_json", None), None)
        item["after"] = jsonutil.loads(item.pop("after_json", None), None)
        out.append(item)
    return out, total


def distinct_actions(conn: sqlite3.Connection) -> list[str]:
    """日志里出现过的动作类型，供后台做筛选下拉。"""
    rows = conn.execute("SELECT DISTINCT action FROM audit_log ORDER BY action").fetchall()
    return [str(r["action"]) for r in rows]


def distinct_target_types(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT target_type FROM audit_log ORDER BY target_type").fetchall()
    return [str(r["target_type"]) for r in rows]


__all__ = ["COLUMNS", "distinct_actions", "distinct_target_types", "list_audit_logs"]
