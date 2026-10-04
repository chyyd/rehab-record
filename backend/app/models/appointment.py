"""排期数据访问与**两类冲突检测**（阶段 2 / `设计.md` 3.4、`开发计划.md` M07）。

排期单位是 **`(日期, 上午|下午)`**，不是具体时间点（Q1）。

## 2026-10-03 起的冲突模型（重大变更，见 `CHANGELOG.md`）

科室确认真实工作流：**一个上午里不同治疗师可能给同一患者做多次治疗，一次最多 1 小时**；
且本系统**只做记录**（今天做了哪些治疗、每次治疗干了什么），**不做时间合规判定**
（时间合规由另一个患者签字系统负责）。

因此「半日格子互斥」不再是正确的模型：迁移 `006_open_scheduling.sql` 删除了
`ux_appt_therapist_slot` 与 `ux_appt_patient_slot` 两条唯一索引。

现在只剩两条硬冲突，且都在本模块判定（休息与请假是配置，不适合用唯一索引表达）：

| 序号 | 规则 | 说明 |
|---|---|---|
| 1 | **休息块命中** | 该治疗师该半日为休息时段（`rest_block`） |
| 2 | **该治疗师该半日处于生效请假** | `leave_record` 且 `status='active'` |

一个半日格子**可以容纳多台排期**（不同治疗师、甚至同一治疗师的多台）。
`availability()` 不再返回"不可排"，但仍会回传该格子已有的排期清单与人数，供客户端展示。

> 保留但**不参与任何约束**：`start_time` / `end_time`。本系统不采集也不校验具体时间。
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
    therapist_id: int,
    day: str,
    period: str,
) -> list[dict[str, Any]]:
    """返回该半日的冲突（空列表表示可排）。

    2026-10-03 起只剩两类：**休息块** 与 **该治疗师处于生效请假**。
    "治疗师半日已占用""患者半日已被他人排期"两条规则随 Q2/S1 一并取消
    —— 半日格子不再互斥，一个患者一个上午被多个治疗师各排一台是正常业务。
    见模块文档与迁移 `006_open_scheduling.sql`。
    """
    period = normalize_period(period)
    if period not in ("am", "pm"):
        raise Invalid("排期的半日只能是 am / pm（全天是请假专用）", details={"period": period})

    conflicts: list[dict[str, Any]] = []

    # 规则 1：休息块
    if _rest_hit(conn, therapist_id, day, period):
        conflicts.append(
            {
                "rule": "rest_block",
                "message": f"该治疗师 {day} {'上午' if period == 'am' else '下午'} 为休息时段",
            }
        )

    # 规则 2：生效请假
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
    """逐半日给出"这个格子能不能排 / 为什么不能 / 里面已经有什么"。

    2026-10-03 起半日格子**不再互斥**：
    - ``available`` 只受 **休息块** 与 **该治疗师生效请假** 影响；
    - 已经排在格子里的治疗（含该治疗师多台、以及其它治疗师给同一患者排的）会出现在
      ``appointments`` / ``appointment_count`` / ``patients`` 里，**但不会让格子变灰**；
    - 传 ``patient_no`` 时额外回传 ``patient_appointments``（该患者在这些半日的排期），
      供客户端展示"这个患者本半日还有谁在做"，同样不参与可排性判定。

    返回每项：``{date, period, available, reasons, appointments,
    appointment_count, patients, patient_appointments}``。
    """
    if date_from > date_to:
        raise Invalid("起始日期不能晚于结束日期", details={"date_from": date_from, "date_to": date_to})

    # 该治疗师在这些半日的全部排期（含多台）
    mine = occupied_slots(conn, date_from=date_from, date_to=date_to, therapist_id=therapist_id)
    mine_by_slot: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in mine:
        mine_by_slot.setdefault((r["date"], r["period"]), []).append(r)

    # 指定患者在这些半日的全部排期（可能由多个治疗师排）
    patient_by_slot: dict[tuple[str, str], list[dict[str, Any]]] = {}
    if patient_no:
        patient_rows = conn.execute(
            "SELECT a.id, a.therapist_id, a.patient_no, a.date, a.period, a.status,"
            "       u.name AS therapist_name"
            " FROM appointment a LEFT JOIN user u ON u.id = a.therapist_id"
            " WHERE a.patient_no = ? AND a.date >= ? AND a.date <= ?"
            f"   AND a.status NOT IN ({', '.join('?' for _ in INACTIVE_STATUSES)})",
            (patient_no, date_from, date_to, *INACTIVE_STATUSES),
        ).fetchall()
        for r in patient_rows:
            patient_by_slot.setdefault((r["date"], r["period"]), []).append(dict(r))

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
            if rest_hit(day, period):
                reasons.append("rest_block")
            if leave_hit(day, period):
                reasons.append("on_leave")

            slot_appointments = mine_by_slot.get((day, period), [])
            out.append(
                {
                    "date": day,
                    "period": period,
                    "available": not reasons,
                    "reasons": reasons,
                    "appointments": slot_appointments,
                    "appointment_count": len(slot_appointments),
                    "patients": [
                        {"patient_no": a["patient_no"], "patient_name": a["patient_name"]}
                        for a in slot_appointments
                    ],
                    "patient_appointments": patient_by_slot.get((day, period), []),
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
        conn, therapist_id=therapist_id, day=day, period=period
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
        # 半日格子已不再互斥，唯一的库层约束是 client_uuid 幂等键；
        # 走到这里说明同步推送的幂等键冲突或其它完整性错误，据实回报。
        raise Conflict("排期写入冲突", details={"reason": str(exc)}) from exc
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

    # 只有仍然占用格子时才需要查冲突；改成 cancelled/rescheduled 即视为不再占用
    if target_status not in INACTIVE_STATUSES:
        conflicts = detect_conflicts(
            conn,
            therapist_id=target_therapist,
            day=target_day,
            period=target_period,
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
        raise Conflict("排期写入冲突", details={"reason": str(exc)}) from exc
    return get_appointment_or_raise(conn, appointment_id)


def cancel_appointment(conn: sqlite3.Connection, appointment_id: int) -> dict[str, Any]:
    """取消排期 = 软删除（状态改为 cancelled，不再计入占用与汇总）。"""
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
