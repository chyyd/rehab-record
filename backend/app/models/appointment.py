"""排期数据访问与**三类冲突检测**（阶段 2 / `设计.md` 3.4、`开发计划.md` M07、S1）。

排期单位是 **`(日期, 上午|下午)`**，不是具体时间点（Q1）。

三条冲突规则（M07）：

| 序号 | 规则 | 由谁保证 |
|---|---|---|
| 1 | 治疗师半日 = 一台 | 库层唯一索引 `ux_appt_therapist_slot` + 本模块预检 |
| 2 | 患者半日 = 一名治疗师 | 库层唯一索引 `ux_appt_patient_slot` + 本模块预检（Q2：**不允许**同时段多人） |
| 3 | 休息 / 已生效请假占用 | 本模块（`rest_block` 与 `leave_record` 是配置，不适合用唯一索引表达） |

**为什么要预检**：唯一索引只能给出"约束冲突"这种模糊错误，
而治疗师端需要知道"到底和谁撞了"，才能提示到具体那一台。索引是最后防线，预检负责给出可读信息。
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from app.core.worktime import normalize_period
from app.models.base import Conflict, Invalid, NotFound, row_to_dict

# 占用半日格子的排期状态（取消与改期不占）
ACTIVE_STATUSES = ("planned", "arrived", "in_progress", "done")
BLOCKING_STATUSES = ("planned", "arrived", "in_progress")
INACTIVE_STATUSES = ("cancelled", "rescheduled")
ALL_STATUSES = (*ACTIVE_STATUSES, "cancelled", "no_show", "rescheduled")

SELECT_COLUMNS = (
    "id, patient_no, therapist_id, date, period, start_time, end_time, slot_label,"
    " status, note, created_at, updated_at, revision"
)

# 一个治疗师能被正确排班的前提：该半日没有生效中的请假
_LEAVE_HIT_SQL = """
SELECT 1 FROM leave_record lr
WHERE lr.therapist_id = ?
  AND lr.status = 'active'
  AND lr.start_date <= ?
  AND lr.end_date >= ?
  AND (
        lr.leave_type = 'multi_day'
     OR lr.leave_type = 'full_day'
     OR (lr.leave_type = 'half_day_am' AND ? = 'am')
     OR (lr.leave_type = 'half_day_pm' AND ? = 'pm')
  )
LIMIT 1
"""

# 休息块命中：周固定（按 weekday）或指定日期
_REST_HIT_SQL = """
SELECT 1 FROM rest_block rb
WHERE rb.therapist_id = ?
  AND rb.period = ?
  AND (
        (rb.scope = 'weekly' AND rb.weekday = ?)
     OR (rb.scope = 'date'   AND rb.specific_date = ?)
  )
LIMIT 1
"""


# --------------------------------------------------------------------------- #
# 查询
# --------------------------------------------------------------------------- #
def get_appointment(conn: sqlite3.Connection, appointment_id: int) -> dict[str, Any] | None:
    """取单条排期，**附带患者姓名与治疗师姓名**。

    这里就把姓名 JOIN 出来（而不是只在列表接口里做），是为了让"创建/修改"返回的
    对象与"列表"返回的对象结构完全一致 —— 前端拿到的 DTO 不该因为走了哪个接口而不同。
    """
    return row_to_dict(
        conn.execute(
            "SELECT a.id, a.patient_no, a.therapist_id, a.date, a.period, a.start_time, a.end_time,"
            " a.slot_label, a.status, a.note, a.created_at, a.updated_at, a.revision,"
            " p.name AS patient_name, u.name AS therapist_name"
            " FROM appointment a"
            " JOIN patient p ON p.inpatient_no = a.patient_no"
            " JOIN user u ON u.id = a.therapist_id"
            " WHERE a.id = ?",
            (appointment_id,),
        ).fetchone()
    )


def get_appointment_or_raise(conn: sqlite3.Connection, appointment_id: int) -> dict[str, Any]:
    row = get_appointment(conn, appointment_id)
    if row is None:
        raise NotFound("排期不存在", details={"appointment_id": appointment_id})
    return row


def list_appointments(
    conn: sqlite3.Connection,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    therapist_id: int | None = None,
    patient_no: str | None = None,
    include_inactive: bool = False,
) -> list[dict[str, Any]]:
    """按条件列出排期，返回时带上患者姓名与治疗师姓名（前端直接可渲染）。"""
    where: list[str] = []
    params: list[Any] = []
    if date_from:
        where.append("a.date >= ?")
        params.append(date_from)
    if date_to:
        where.append("a.date <= ?")
        params.append(date_to)
    if therapist_id is not None:
        where.append("a.therapist_id = ?")
        params.append(therapist_id)
    if patient_no is not None:
        where.append("a.patient_no = ?")
        params.append(patient_no)
    if not include_inactive:
        placeholders = ", ".join("?" for _ in INACTIVE_STATUSES)
        where.append(f"a.status NOT IN ({placeholders})")
        params.extend(INACTIVE_STATUSES)

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    rows = conn.execute(
        "SELECT a.id, a.patient_no, a.therapist_id, a.date, a.period, a.start_time, a.end_time,"
        " a.slot_label, a.status, a.note, a.created_at, a.updated_at, a.revision,"
        " p.name AS patient_name, u.name AS therapist_name"
        " FROM appointment a"
        " JOIN patient p ON p.inpatient_no = a.patient_no"
        " JOIN user u ON u.id = a.therapist_id"
        f" {clause}"
        " ORDER BY a.date, CASE a.period WHEN 'am' THEN 0 ELSE 1 END,"
        " COALESCE(a.start_time, ''), a.id",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def occupied_slots(
    conn: sqlite3.Connection, *, date_from: str, date_to: str, therapist_id: int | None = None
) -> list[dict[str, Any]]:
    """已被占用的半日格（不含取消/改期），供可排性计算与冲突提示。"""
    where = ["a.date >= ?", "a.date <= ?"]
    params: list[Any] = [date_from, date_to]
    placeholders = ", ".join("?" for _ in INACTIVE_STATUSES)
    where.append(f"a.status NOT IN ({placeholders})")
    params.extend(INACTIVE_STATUSES)
    if therapist_id is not None:
        where.append("a.therapist_id = ?")
        params.append(therapist_id)

    rows = conn.execute(
        "SELECT a.therapist_id, a.patient_no, a.date, a.period, a.status, p.name AS patient_name"
        " FROM appointment a JOIN patient p ON p.inpatient_no = a.patient_no"
        f" WHERE {' AND '.join(where)}",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def rest_blocks_for(
    conn: sqlite3.Connection, therapist_id: int, *, date_from: str, date_to: str
) -> list[dict[str, Any]]:
    """该治疗师在日期范围内的休息块（周固定 + 指定日期都返回，由调用方匹配）。"""
    rows = conn.execute(
        "SELECT id, scope, weekday, specific_date, period, note FROM rest_block"
        " WHERE therapist_id = ?"
        "   AND (scope = 'weekly' OR (scope = 'date' AND specific_date BETWEEN ? AND ?))",
        (therapist_id, date_from, date_to),
    ).fetchall()
    return [dict(r) for r in rows]


def leaves_for(
    conn: sqlite3.Connection, therapist_id: int, *, date_from: str, date_to: str
) -> list[dict[str, Any]]:
    """该治疗师与日期范围有交集的生效请假。"""
    rows = conn.execute(
        "SELECT id, start_date, end_date, leave_type, period, reason FROM leave_record"
        " WHERE therapist_id = ? AND status = 'active'"
        "   AND start_date <= ? AND end_date >= ?",
        (therapist_id, date_to, date_from),
    ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# 冲突检测
# --------------------------------------------------------------------------- #
def _therapist_leave_hit(conn: sqlite3.Connection, therapist_id: int, day: str, period: str) -> bool:
    return conn.execute(_LEAVE_HIT_SQL, (therapist_id, day, day, period, period)).fetchone() is not None


def _rest_hit(conn: sqlite3.Connection, therapist_id: int, day: str, period: str) -> bool:
    weekday = date.fromisoformat(day).weekday()
    return conn.execute(_REST_HIT_SQL, (therapist_id, period, weekday, day)).fetchone() is not None


def detect_conflicts(
    conn: sqlite3.Connection,
    *,
    patient_no: str,
    therapist_id: int,
    day: str,
    period: str,
    exclude_appointment_id: int | None = None,
) -> list[dict[str, Any]]:
    """返回该半日格子的全部冲突（空列表表示可排）。

    规则 1/2 用查询预检（可给出"和谁撞了"），库层唯一索引仍是最后防线。
    """
    period = normalize_period(period)
    if period not in ("am", "pm"):
        raise Invalid("排期的半日只能是 am / pm（全天是请假专用）", details={"period": period})

    conflicts: list[dict[str, Any]] = []
    exclude = "" if exclude_appointment_id is None else " AND id <> ?"
    base_params: tuple[Any, ...] = () if exclude_appointment_id is None else (exclude_appointment_id,)
    status_placeholders = ", ".join("?" for _ in INACTIVE_STATUSES)

    # 规则 1：治疗师半日已被占
    row = conn.execute(
        f"SELECT id, patient_no FROM appointment WHERE therapist_id = ? AND date = ? AND period = ?"
        f" AND status NOT IN ({status_placeholders}){exclude}",
        (therapist_id, day, period, *INACTIVE_STATUSES, *base_params),
    ).fetchone()
    if row is not None:
        conflicts.append(
            {
                "rule": "therapist_slot_taken",
                "message": f"该治疗师 {day} {'上午' if period == 'am' else '下午'} 已有一台排期",
                "appointment_id": row["id"],
                "patient_no": row["patient_no"],
            }
        )

    # 规则 2：患者半日已被其他治疗师占用（Q2：不允许同一患者同时段多人）
    row = conn.execute(
        f"SELECT id, therapist_id FROM appointment WHERE patient_no = ? AND date = ? AND period = ?"
        f" AND status NOT IN ({status_placeholders}){exclude}",
        (patient_no, day, period, *INACTIVE_STATUSES, *base_params),
    ).fetchone()
    if row is not None:
        conflicts.append(
            {
                "rule": "patient_slot_taken",
                "message": f"该患者 {day} {'上午' if period == 'am' else '下午'} 已由其他治疗师排期",
                "appointment_id": row["id"],
                "therapist_id": row["therapist_id"],
            }
        )

    # 规则 3：休息 / 已生效请假
    if _rest_hit(conn, therapist_id, day, period):
        conflicts.append(
            {
                "rule": "rest_block",
                "message": f"该治疗师 {day} {'上午' if period == 'am' else '下午'} 为休息时段",
            }
        )
    if _therapist_leave_hit(conn, therapist_id, day, period):
        conflicts.append(
            {
                "rule": "on_leave",
                "message": f"该治疗师 {day} {'上午' if period == 'am' else '下午'} 处于请假状态",
            }
        )
    return conflicts


def availability(
    conn: sqlite3.Connection,
    *,
    therapist_id: int,
    date_from: str,
    date_to: str,
    patient_no: str | None = None,
) -> list[dict[str, Any]]:
    """逐半日给出"能不能排 / 为什么不能"，供排期页直接把格子置灰。

    返回每项：``{date, period, available, reasons: [...]}``
    """
    if date_from > date_to:
        raise Invalid("起始日期不能晚于结束日期", details={"date_from": date_from, "date_to": date_to})

    occupied = occupied_slots(conn, date_from=date_from, date_to=date_to, therapist_id=therapist_id)
    occupied_by_slot = {(r["date"], r["period"]): r for r in occupied}
    patient_occupied: dict[tuple[str, str], dict[str, Any]] = {}
    if patient_no:
        for r in occupied_slots(conn, date_from=date_from, date_to=date_to):
            if r["patient_no"] == patient_no:
                patient_occupied[(r["date"], r["period"])] = r

    rests = rest_blocks_for(conn, therapist_id, date_from=date_from, date_to=date_to)
    leaves = leaves_for(conn, therapist_id, date_from=date_from, date_to=date_to)

    def rest_hit(day: str, period: str) -> bool:
        weekday = date.fromisoformat(day).weekday()
        for rb in rests:
            if rb["period"] != period:
                continue
            if rb["scope"] == "weekly" and rb["weekday"] == weekday:
                return True
            if rb["scope"] == "date" and rb["specific_date"] == day:
                return True
        return False

    def leave_hit(day: str, period: str) -> bool:
        for lv in leaves:
            if not (lv["start_date"] <= day <= lv["end_date"]):
                continue
            if lv["leave_type"] in ("full_day", "multi_day"):
                return True
            if lv["leave_type"] == "half_day_am" and period == "am":
                return True
            if lv["leave_type"] == "half_day_pm" and period == "pm":
                return True
        return False

    out: list[dict[str, Any]] = []
    for day in _date_range(date_from, date_to):
        for period in ("am", "pm"):
            reasons: list[str] = []
            taken = occupied_by_slot.get((day, period))
            if taken is not None:
                reasons.append("therapist_slot_taken")
            pat = patient_occupied.get((day, period))
            if pat is not None:
                reasons.append("patient_slot_taken")
            if rest_hit(day, period):
                reasons.append("rest_block")
            if leave_hit(day, period):
                reasons.append("on_leave")
            out.append(
                {
                    "date": day,
                    "period": period,
                    "available": not reasons,
                    "reasons": reasons,
                    "patient_no": taken["patient_no"] if taken else None,
                    "patient_name": taken["patient_name"] if taken else None,
                    "status": taken["status"] if taken else None,
                }
            )
    return out


def _date_range(start: str, end: str) -> list[str]:
    from datetime import timedelta

    first, last = date.fromisoformat(start), date.fromisoformat(end)
    days: list[str] = []
    cursor = first
    while cursor <= last:
        days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return days


# --------------------------------------------------------------------------- #
# 写入
# --------------------------------------------------------------------------- #
def create_appointment(
    conn: sqlite3.Connection,
    *,
    patient_no: str,
    therapist_id: int,
    day: str,
    period: str,
    start_time: str | None = None,
    end_time: str | None = None,
    slot_label: str | None = None,
    note: str | None = None,
    status: str = "planned",
) -> dict[str, Any]:
    period = normalize_period(period)
    if status not in ALL_STATUSES:
        raise Invalid(f"排期状态非法：{status}", details={"status": status})
    _validate_planned_times(day, period, start_time, end_time)

    # 先确认患者存在：否则外键失败会被下面的 IntegrityError 兜底逻辑
    # 误报成"半日被占用"，把调用方引向完全错误的方向
    exists = conn.execute("SELECT 1 FROM patient WHERE inpatient_no = ?", (patient_no,)).fetchone()
    if exists is None:
        raise NotFound("患者不存在", details={"inpatient_no": patient_no})

    conflicts = detect_conflicts(
        conn, patient_no=patient_no, therapist_id=therapist_id, day=day, period=period
    )
    if conflicts:
        # 409：可预期的业务冲突，而不是参数错误
        raise Conflict("该半日无法排期", details={"conflicts": conflicts})

    try:
        cur = conn.execute(
            "INSERT INTO appointment"
            " (patient_no, therapist_id, date, period, start_time, end_time, slot_label, status, note)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (patient_no, therapist_id, day, period, start_time, end_time, slot_label, status, note),
        )
    except sqlite3.IntegrityError as exc:
        # 预检通过但索引拒绝：并发写入或预检遗漏，仍然要给出可读信息
        raise Conflict("该半日已被占用（并发冲突）", details={"reason": str(exc)}) from exc
    return get_appointment_or_raise(conn, int(cur.lastrowid))


def update_appointment(
    conn: sqlite3.Connection,
    appointment_id: int,
    *,
    patient_no: str | None = None,
    therapist_id: int | None = None,
    day: str | None = None,
    period: str | None = None,
    status: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    current = get_appointment_or_raise(conn, appointment_id)
    target_patient = patient_no or current["patient_no"]
    target_therapist = therapist_id or current["therapist_id"]
    target_day = day or current["date"]
    target_period = normalize_period(period) if period else current["period"]
    target_status = status or current["status"]
    if target_status not in ALL_STATUSES:
        raise Invalid(f"排期状态非法：{target_status}", details={"status": target_status})

    _validate_planned_times(
        target_day,
        target_period,
        start_time if start_time is not None else current["start_time"],
        end_time if end_time is not None else current["end_time"],
    )

    # 只有仍然占用格子时才需要查冲突；改成 cancelled/rescheduled 就是让出格子
    if target_status not in INACTIVE_STATUSES:
        conflicts = detect_conflicts(
            conn,
            patient_no=target_patient,
            therapist_id=target_therapist,
            day=target_day,
            period=target_period,
            exclude_appointment_id=appointment_id,
        )
        if conflicts:
            raise Conflict("该半日无法排期", details={"conflicts": conflicts})

    sets = ["patient_no = ?", "therapist_id = ?", "date = ?", "period = ?", "status = ?",
            "revision = revision + 1"]
    params: list[Any] = [target_patient, target_therapist, target_day, target_period, target_status]
    for column, value in (("start_time", start_time), ("end_time", end_time), ("note", note)):
        if value is not None:
            sets.append(f"{column} = ?")
            params.append(value)

    try:
        conn.execute(f"UPDATE appointment SET {', '.join(sets)} WHERE id = ?", (*params, appointment_id))
    except sqlite3.IntegrityError as exc:
        raise Conflict("该半日已被占用（并发冲突）", details={"reason": str(exc)}) from exc
    return get_appointment_or_raise(conn, appointment_id)


def cancel_appointment(conn: sqlite3.Connection, appointment_id: int) -> dict[str, Any]:
    """取消排期 = 软删除，让出半日格子。"""
    return update_appointment(conn, appointment_id, status="cancelled")


def _validate_planned_times(
    day: str, period: str, start_time: str | None, end_time: str | None
) -> None:
    """校验可选的"计划时间"。

    这两个字段不参与冲突判定（S1），但既然填了就要合理：
    必须落在所属半日的作息区间内，且结束晚于开始。
    """
    if start_time is None and end_time is None:
        return
    from app.core.worktime import parse_hm, period_interval

    lo, hi = period_interval(period)
    if start_time is not None:
        st = parse_hm(start_time)
        if not (lo <= st <= hi):
            raise Invalid(
                f"计划开始时间 {start_time} 不在{'上午' if period == 'am' else '下午'}作息区间内",
                details={"period": period, "range": [lo.strftime("%H:%M"), hi.strftime("%H:%M")]},
            )
    if end_time is not None:
        et = parse_hm(end_time)
        if not (lo <= et <= hi):
            raise Invalid(
                f"计划结束时间 {end_time} 不在{'上午' if period == 'am' else '下午'}作息区间内",
                details={"period": period, "range": [lo.strftime("%H:%M"), hi.strftime("%H:%M")]},
            )
    if start_time is not None and end_time is not None and parse_hm(end_time) <= parse_hm(start_time):
        raise Invalid("计划结束时间必须晚于开始时间", details={"start_time": start_time, "end_time": end_time})


__all__ = [
    "ACTIVE_STATUSES",
    "ALL_STATUSES",
    "BLOCKING_STATUSES",
    "INACTIVE_STATUSES",
    "availability",
    "cancel_appointment",
    "create_appointment",
    "detect_conflicts",
    "get_appointment",
    "get_appointment_or_raise",
    "leaves_for",
    "list_appointments",
    "occupied_slots",
    "rest_blocks_for",
    "update_appointment",
]
