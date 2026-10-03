"""请假数据访问与**释放/排空副作用**（阶段 2 / `设计.md` 3.5、`开发计划.md` M08/M09）。

**Q6 定稿：没有审批流。** 治疗师直接请假，管理员可以代录，**登记即生效**。
因此本模块不做任何 `pending` 状态流转——`leave_record.status` 只有 `active` / `cancelled`。

请假的两类副作用：

| 假别 | 副作用 | 是否改原归属 |
|---|---|---|
| 半天 / 全天（单日） | **临时释放**：建 `temporary_assignment`，可见归属变 NULL | **不改**（3.5.2） |
| 多日（≥2 天） | **正式排空**：`assigned_therapist_id = NULL` | **改**，且不自动恢复（3.5.3） |

撤销（cancel）时的回滚：

- 单日假：关掉未过期的 `temporary_assignment`（`closed_reason='leave_cancelled'`）。
- 多日假：只回收**尚未被认领**的患者归属；已被他人认领的不动，并在返回值里列出，让前端提示。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.core.clock import utc_timestamp_now
from app.core.worktime import LEAVE_PERIODS, normalize_period
from app.models.base import Conflict, Invalid, NotFound, row_to_dict

# `_record_assignment` 是归属历史的唯一写入口，请假释放也必须经过它
from app.models.patient import _record_assignment

LEAVE_TYPES = ("half_day_am", "half_day_pm", "full_day", "multi_day")
SINGLE_DAY_TYPES = ("half_day_am", "half_day_pm", "full_day")
SOURCES = ("therapist_self", "admin_entry")
STATUS_ACTIVE = "active"
STATUS_CANCELLED = "cancelled"

SELECT_COLUMNS = (
    "id, therapist_id, start_date, end_date, leave_type, period, source, status, reason,"
    " created_by, recorded_at, applied_at, cancelled_at, cancel_reason, released_at, created_at"
)


def get_leave(conn: sqlite3.Connection, leave_id: int) -> dict[str, Any] | None:
    """取单条请假，**附带治疗师姓名与代录人姓名**。

    与列表接口保持同一结构，避免"创建返回的字段比列表少"这种不一致。
    """
    return row_to_dict(
        conn.execute(
            "SELECT lr.id, lr.therapist_id, lr.start_date, lr.end_date, lr.leave_type, lr.period,"
            " lr.source, lr.status, lr.reason, lr.created_by, lr.recorded_at, lr.applied_at,"
            " lr.cancelled_at, lr.cancel_reason, lr.created_at,"
            " u.name AS therapist_name, c.name AS created_by_name"
            " FROM leave_record lr"
            " JOIN user u ON u.id = lr.therapist_id"
            " LEFT JOIN user c ON c.id = lr.created_by"
            " WHERE lr.id = ?",
            (leave_id,),
        ).fetchone()
    )


def get_leave_or_raise(conn: sqlite3.Connection, leave_id: int) -> dict[str, Any]:
    row = get_leave(conn, leave_id)
    if row is None:
        raise NotFound("请假记录不存在", details={"leave_id": leave_id})
    return row


def list_leaves(
    conn: sqlite3.Connection,
    *,
    therapist_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if therapist_id is not None:
        where.append("lr.therapist_id = ?")
        params.append(therapist_id)
    if status:
        where.append("lr.status = ?")
        params.append(status)
    if date_from:
        where.append("lr.end_date >= ?")
        params.append(date_from)
    if date_to:
        where.append("lr.start_date <= ?")
        params.append(date_to)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    rows = conn.execute(
        "SELECT lr.id, lr.therapist_id, lr.start_date, lr.end_date, lr.leave_type, lr.period,"
        " lr.source, lr.status, lr.reason, lr.created_by, lr.recorded_at, lr.applied_at,"
        " lr.cancelled_at, lr.cancel_reason, lr.created_at,"
        " u.name AS therapist_name, c.name AS created_by_name"
        " FROM leave_record lr"
        " JOIN user u ON u.id = lr.therapist_id"
        " LEFT JOIN user c ON c.id = lr.created_by"
        f" {clause}"
        " ORDER BY lr.start_date DESC, lr.id DESC",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def is_on_leave(
    conn: sqlite3.Connection, therapist_id: int, day: str, period: str
) -> dict[str, Any] | None:
    """该治疗师在指定半日是否处于生效请假中（供排期页置灰与冲突提示）。"""
    period = normalize_period(period)
    row = conn.execute(
        "SELECT id, leave_type, start_date, end_date, period FROM leave_record"
        " WHERE therapist_id = ? AND status = 'active'"
        "   AND start_date <= ? AND end_date >= ?"
        "   AND ( leave_type IN ('full_day', 'multi_day')"
        "      OR (leave_type = 'half_day_am' AND ? = 'am')"
        "      OR (leave_type = 'half_day_pm' AND ? = 'pm') )"
        " LIMIT 1",
        (therapist_id, day, day, period, period),
    ).fetchone()
    return row_to_dict(row)


# --------------------------------------------------------------------------- #
# 创建请假（登记即生效）
# --------------------------------------------------------------------------- #
def _normalize_period_for(leave_type: str, period: str | None) -> str:
    if leave_type == "half_day_am":
        return "am"
    if leave_type == "half_day_pm":
        return "pm"
    if leave_type == "full_day":
        return "full"
    # 多日假没有"半天"概念，但库里 period 允许 am/pm/full；统一存 full 表示整天
    if period is None:
        return "full"
    normalized = normalize_period(period)
    return normalized if normalized in LEAVE_PERIODS else "full"


def _validate(leave_type: str, start_date: str, end_date: str) -> None:
    from datetime import date as _date

    if leave_type not in LEAVE_TYPES:
        raise Invalid(f"请假类型必须是 {'/'.join(LEAVE_TYPES)} 之一", details={"leave_type": leave_type})
    try:
        start = _date.fromisoformat(start_date)
        end = _date.fromisoformat(end_date)
    except ValueError as exc:
        raise Invalid("日期必须是 YYYY-MM-DD", details={"start": start_date, "end": end_date}) from exc
    if end < start:
        raise Invalid("结束日期不能早于开始日期", details={"start": start_date, "end": end_date})

    span = (end - start).days + 1
    if leave_type == "multi_day" and span < 2:
        raise Invalid(
            "多日假至少 2 天；单日请用 half_day_am / half_day_pm / full_day",
            details={"span_days": span},
        )
    if leave_type in SINGLE_DAY_TYPES and span != 1:
        raise Invalid(
            "半天假/全天假只能请一天；跨天请用 multi_day",
            details={"span_days": span},
        )


def create_leave(
    conn: sqlite3.Connection,
    *,
    therapist_id: int,
    leave_type: str,
    start_date: str,
    end_date: str,
    operator_user_id: int,
    source: str = "therapist_self",
    period: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """登记请假（**立即生效**）并执行释放或排空副作用。"""
    _validate(leave_type, start_date, end_date)
    if source not in SOURCES:
        raise Invalid(f"请假来源必须是 {'/'.join(SOURCES)} 之一", details={"source": source})

    overlapping = conn.execute(
        "SELECT id FROM leave_record WHERE therapist_id = ? AND status = 'active'"
        "   AND start_date <= ? AND end_date >= ?",
        (therapist_id, end_date, start_date),
    ).fetchone()
    if overlapping is not None:
        raise Conflict("该时间段已有生效中的请假", details={"leave_id": overlapping["id"]})

    normalized_period = _normalize_period_for(leave_type, period)
    now = utc_timestamp_now()
    cur = conn.execute(
        "INSERT INTO leave_record"
        " (therapist_id, start_date, end_date, leave_type, period, source, status, reason,"
        "  created_by, applied_at, released_at)"
        " VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)",
        (
            therapist_id, start_date, end_date, leave_type, normalized_period,
            source, reason, operator_user_id, now, now,
        ),
    )
    leave_id = int(cur.lastrowid)

    if leave_type == "multi_day":
        _apply_multi_day_release(conn, therapist_id=therapist_id, operator_user_id=operator_user_id)
    else:
        _apply_single_day_release(
            conn,
            therapist_id=therapist_id,
            day=start_date,
            period=normalized_period,
            operator_user_id=operator_user_id,
        )
    return get_leave_or_raise(conn, leave_id)


def _apply_single_day_release(
    conn: sqlite3.Connection, *, therapist_id: int, day: str, period: str, operator_user_id: int
) -> list[str]:
    """单日假：为名下患者建临时释放记录。**不改原归属。**"""
    from app.core.clock import period_expiry

    expires_at = period_expiry(_date_of(day), period)
    rows = conn.execute(
        "SELECT inpatient_no FROM patient WHERE assigned_therapist_id = ?", (therapist_id,)
    ).fetchall()
    released: list[str] = []
    for row in rows:
        patient_no = str(row["inpatient_no"])
        try:
            conn.execute(
                "INSERT INTO temporary_assignment"
                " (patient_no, original_therapist_id, temporary_therapist_id, date, period, status,"
                "  expires_at, released_at)"
                " VALUES (?, ?, NULL, ?, ?, 'open', ?, ?)",
                (patient_no, therapist_id, day, period, expires_at, utc_timestamp_now()),
            )
        except sqlite3.IntegrityError:
            # 该患者该半日已有未关闭的临时指派（重复请假等）——跳过而不是整体失败
            continue
        _record_assignment(
            conn, patient_no, therapist_id, None, "temp_release", operator_user_id=operator_user_id
        )
        released.append(patient_no)
    return released


def _apply_multi_day_release(
    conn: sqlite3.Connection, *, therapist_id: int, operator_user_id: int
) -> list[str]:
    """多日假：**正式排空**归属（不可自动恢复）。"""
    from app.models.patient import release_all_for_therapist

    return release_all_for_therapist(conn, therapist_id, operator_user_id)


def _date_of(day: str):
    from datetime import date as _date

    return _date.fromisoformat(day)


# --------------------------------------------------------------------------- #
# 撤销（回滚副作用）
# --------------------------------------------------------------------------- #
def cancel_leave(
    conn: sqlite3.Connection,
    leave_id: int,
    *,
    operator_user_id: int,
    cancel_reason: str | None = None,
) -> dict[str, Any]:
    """撤销请假并回滚副作用。

    多日假**不强制收回已被他人认领的患者**（3.5.3"不自动恢复"），
    只在返回值 `not_restored` 里列出，由前端提示管理员手动处理。
    """
    leave = get_leave_or_raise(conn, leave_id)
    if leave["status"] == STATUS_CANCELLED:
        raise Conflict("该请假已撤销", details={"leave_id": leave_id})

    now = utc_timestamp_now()
    conn.execute(
        "UPDATE leave_record SET status = 'cancelled', cancelled_at = ?, cancel_reason = ? WHERE id = ?",
        (now, cancel_reason, leave_id),
    )

    restored: list[str] = []
    not_restored: list[str] = []
    therapist_id = int(leave["therapist_id"])

    # 关掉该治疗师在请假期间开出的临时释放
    conn.execute(
        "UPDATE temporary_assignment SET status = 'closed', closed_at = ?, closed_reason = 'leave_cancelled'"
        " WHERE original_therapist_id = ? AND status = 'open'"
        "   AND date BETWEEN ? AND ?",
        (now, therapist_id, leave["start_date"], leave["end_date"]),
    )

    if leave["leave_type"] == "multi_day":
        # 找出本次排空涉及的患者。
        # 注意**不能**只看"最后一条历史是否为 multi_day_release"：
        # 患者被他人认领后会新增一条 claim 记录，那样就漏掉了"已被认领"的情况。
        # 正确做法：取所有被本治疗师排空过的患者，再按当前归属判断。
        rows = conn.execute(
            "SELECT DISTINCT h.patient_no FROM patient_assignment_history h"
            " WHERE h.change_type = 'multi_day_release' AND h.from_therapist_id = ?",
            (therapist_id,),
        ).fetchall()
        for row in rows:
            patient_no = str(row["patient_no"])
            current = conn.execute(
                "SELECT assigned_therapist_id FROM patient WHERE inpatient_no = ?", (patient_no,)
            ).fetchone()
            if current is None:
                continue  # 患者已删除
            if current["assigned_therapist_id"] is None:
                _record_assignment(
                    conn, patient_no, None, therapist_id, "admin_assign", operator_user_id=operator_user_id
                )
                conn.execute(
                    "UPDATE patient SET assigned_therapist_id = ?, revision = revision + 1"
                    " WHERE inpatient_no = ?",
                    (therapist_id, patient_no),
                )
                restored.append(patient_no)
            elif int(current["assigned_therapist_id"]) == therapist_id:
                # 已经回到原治疗师名下（例如管理员手动恢复过），无需处理
                continue
            else:
                not_restored.append(patient_no)

    result = get_leave_or_raise(conn, leave_id)
    result["restored"] = restored
    result["not_restored"] = not_restored
    return result


# --------------------------------------------------------------------------- #
# 到期清理（定时任务调用；判定本身在读时也已兜底）
# --------------------------------------------------------------------------- #
def close_expired_temporary_assignments(conn: sqlite3.Connection) -> int:
    """把已过期的临时指派置为 closed，返回处理条数。

    **这只是清理，不是判定依据**：`v_patient_visibility` 视图在读取时也检查 `expires_at`，
    所以即使这个任务漏跑，归属显示依然正确（`开发计划.md` R8）。
    """
    cur = conn.execute(
        "UPDATE temporary_assignment SET status = 'closed', closed_at = ?, closed_reason = 'expired'"
        " WHERE status = 'open' AND expires_at IS NOT NULL AND expires_at <= ?",
        (utc_timestamp_now(), utc_timestamp_now()),
    )
    return int(cur.rowcount or 0)

__all__ = [
    "LEAVE_TYPES",
    "SELECT_COLUMNS",
    "SINGLE_DAY_TYPES",
    "SOURCES",
    "STATUS_ACTIVE",
    "STATUS_CANCELLED",
    "cancel_leave",
    "close_expired_temporary_assignments",
    "create_leave",
    "get_leave",
    "get_leave_or_raise",
    "is_on_leave",
    "list_leaves",
]
