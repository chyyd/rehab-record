"""患者数据访问与**归属可见性解析**（阶段 1 / `设计.md` 3.3、3.5.5，`开发计划.md` M09/M12/M18）。

本模块承载本系统最关键的一条业务规则：**"当前谁负责这个患者"**。

原归属（`patient.assigned_therapist_id`）与可见归属（`visible_therapist`）是两件事：

| 场景 | `assigned_therapist_id` | 可见归属 |
|---|---|---|
| 正常 | 张三 | 张三 |
| 单日假临时释放（未被认领） | 张三 | **NULL**（谁都不负责，别人可临时认领） |
| 单日假被李四临时认领 | 张三（**不变**） | 李四 |
| 多日假正式排空 | NULL | NULL |

实现要点：
1. 用 `v_patient_visibility` 视图统一计算，**不要**在路由或前端各写一遍；
2. 判定"临时指派是否仍有效"采用**读时兜底**——同时看 `status='open'` 与 `expires_at`。
   这样即使定时清理任务漏跑（服务重启等），归属显示也不会错（`开发计划.md` R8）。
"""

from __future__ import annotations

import sqlite3
from typing import Any, Literal

from app.models.base import Conflict, NotFound, row_to_dict

STATUS_IN_HOSPITAL = "in_hospital"
STATUS_DISCHARGED = "discharged"
STATUS_PAUSED = "paused"
PATIENT_STATUSES = (STATUS_IN_HOSPITAL, STATUS_DISCHARGED, STATUS_PAUSED)

# "白板"上默认可见的状态（2026-10-03 全科白板决策）：
# 在院与暂停都属于"当前在科室里的患者"；已出院默认隐藏，需要时用 status 筛选显式查。
ACTIVE_STATUSES = (STATUS_IN_HOSPITAL, STATUS_PAUSED)

# 可用的数据范围（D10）。
#
# 2026-10-03 起新增 `dept`（科室级白板）：治疗师默认范围，含义是"科室当前在院/暂停的患者"，
# 不再按归属隔离。原有取值保留：
#   - `mine`/`unassigned`/`temp` 仍用于**筛选**（我的患者、未分配、临时相关）；
#   - `visible` 保留为 `dept` 的同义兼容值（旧客户端仍能用）；
#   - `all` 仍是**管理员专属**的全表范围（含已出院）。
Scope = Literal["mine", "unassigned", "temp", "all", "visible", "dept"]

SELECT_COLUMN_NAMES = (
    "inpatient_no",
    "name",
    "diagnosis",
    "admin_note",
    "assigned_therapist_id",
    "status",
    "created_at",
    "updated_at",
    "revision",
)

# 带表别名的列清单，供 JOIN 查询使用
_PATIENT_COLUMNS = ", ".join(f"p.{name}" for name in SELECT_COLUMN_NAMES)
_VISIBILITY_COLUMNS = (
    "v.visible_therapist_id, v.visibility_state, v.temp_assignment_id,"
    " v.temp_therapist_id, v.temp_original_therapist_id"
)

# --------------------------------------------------------------------------- #
# 可见性视图：全系统唯一的归属解析实现
# --------------------------------------------------------------------------- #
# 取每个患者「当前有效」的临时指派：
#   - status = 'open'
#   - expires_at 为空（不设过期）或未过期   ← 读时兜底，不依赖定时任务
# 若同一患者有多条（正常情况下唯一索引会拦住），取 id 最大的一条。
VISIBILITY_VIEW_SQL = """
CREATE VIEW v_patient_visibility AS
WITH active_temp AS (
    SELECT ta.*
    FROM temporary_assignment ta
    WHERE ta.status = 'open'
      AND (ta.expires_at IS NULL OR ta.expires_at > strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
),
picked_temp AS (
    SELECT * FROM active_temp t
    WHERE t.id = (SELECT MAX(x.id) FROM active_temp x WHERE x.patient_no = t.patient_no)
)
SELECT p.inpatient_no,
       p.assigned_therapist_id,
       pt.id                     AS temp_assignment_id,
       pt.temporary_therapist_id AS temp_therapist_id,
       pt.original_therapist_id  AS temp_original_therapist_id,
       pt.date                   AS temp_date,
       pt.period                 AS temp_period,
       pt.expires_at             AS temp_expires_at,
       CASE
           WHEN pt.id IS NULL THEN p.assigned_therapist_id
           WHEN pt.temporary_therapist_id IS NOT NULL THEN pt.temporary_therapist_id
           ELSE NULL
       END AS visible_therapist_id,
       CASE
           WHEN pt.id IS NULL THEN 'assigned'
           WHEN pt.temporary_therapist_id IS NOT NULL THEN 'temp_claimed'
           ELSE 'temp_released'
       END AS visibility_state
FROM patient p
LEFT JOIN picked_temp pt ON pt.patient_no = p.inpatient_no
"""


def visibility_from(scope: Scope, user_id: int) -> tuple[str, list[Any]]:
    """返回 ``(SQL 片段, 参数)``，供拼接到 ``FROM v_patient_visibility v`` 之后。

    各范围语义：

    - ``dept``      **科室级白板（治疗师默认，2026-10-03 起）**：科室当前在院/暂停的患者，
                    不按归属隔离。一个上午里 PT/OT/言语/吞咽可能各给同一患者做一次，
                    所以"别人的患者"必须可见且可排期。
    - ``visible``   ``dept`` 的同义兼容值（旧客户端仍在用）。
    - ``mine``      可见归属是我（含临时认领我的患者）—— 仍可作为**筛选**使用。
    - ``unassigned`` 无人负责（原归属为空，或正处于临时释放中且未被认领）。
    - ``temp``      与我有关的临时指派（我请假的或我临时认领的）。
    - ``all``       不加限制（**仅管理员**，路由层负责拦截；含已出院）。
    """
    if scope == "mine":
        return "WHERE v.visible_therapist_id = ?", [user_id]
    if scope == "unassigned":
        return "WHERE v.visible_therapist_id IS NULL", []
    if scope == "temp":
        return (
            "WHERE v.temp_assignment_id IS NOT NULL"
            " AND (v.temp_therapist_id = ? OR v.temp_original_therapist_id = ?)",
            [user_id, user_id],
        )
    if scope == "all":
        return "", []
    if scope in ("dept", "visible"):
        # 注意用 `p.status` 而不是 `v.status`：视图 v_patient_visibility 没有输出 status 列，
        # 而 list_patients 的 joins 里本来就 JOIN 了 patient p。
        placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
        return f"WHERE p.status IN ({placeholders})", list(ACTIVE_STATUSES)
    raise Conflict(f"未知的数据范围：{scope}", details={"scope": scope})


def can_schedule(conn: sqlite3.Connection, patient_no: str, therapist_id: int) -> bool:
    """治疗师能否给该患者排期（Q3：只能排"我的 / 未分配 / 临时认领"的患者）。

    注意用的是**可见归属**：单日假临时释放期间，原归属者反而不能排、临时认领者可以排。
    """
    row = conn.execute(
        "SELECT visible_therapist_id FROM v_patient_visibility WHERE inpatient_no = ?", (patient_no,)
    ).fetchone()
    if row is None:
        raise NotFound("患者不存在", details={"inpatient_no": patient_no})
    visible = row["visible_therapist_id"]
    return visible is None or int(visible) == therapist_id


# --------------------------------------------------------------------------- #
# 查询
# --------------------------------------------------------------------------- #
def get_patient(conn: sqlite3.Connection, inpatient_no: str) -> dict[str, Any] | None:
    return row_to_dict(
        conn.execute(
            f"SELECT {_PATIENT_COLUMNS}, {_VISIBILITY_COLUMNS}"
            " FROM patient p JOIN v_patient_visibility v ON v.inpatient_no = p.inpatient_no"
            " WHERE p.inpatient_no = ?",
            (inpatient_no,),
        ).fetchone()
    )


def get_patient_or_raise(conn: sqlite3.Connection, inpatient_no: str) -> dict[str, Any]:
    patient = get_patient(conn, inpatient_no)
    if patient is None:
        raise NotFound("患者不存在", details={"inpatient_no": inpatient_no})
    return patient


def list_patients(
    conn: sqlite3.Connection,
    *,
    scope: Scope = "dept",
    user_id: int | None = None,
    status: str | None = None,
    keyword: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """按数据范围列出患者。

    默认 `dept`（科室白板：在院 + 暂停），与 `api/v1/patients.py::_resolve_scope`
    里治疗师的默认值保持一致 —— 两处默认值不同会让"直接调模型层"的代码拿到与接口不同的范围。

    ``scope='all'`` 需要调用方（路由层）先确认是管理员——本函数不做权限判断。
    """
    if scope != "all" and user_id is None:
        raise Conflict("非全局范围查询必须提供 user_id")

    scope_sql, params = visibility_from(scope, user_id if user_id is not None else 0)

    extra: list[str] = []
    if status:
        extra.append("p.status = ?")
        params.append(status)
    if keyword:
        extra.append("(p.name LIKE ? OR p.inpatient_no LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])

    # 条件拼装：scope 条件 + 附加筛选。
    # 注意 SQL 子句顺序必须是 FROM ... JOIN ... WHERE ... ORDER BY ... LIMIT，
    # 不能把 WHERE 塞进 FROM 片段里（否则 WHERE 后面再跟 LEFT JOIN 会语法错误）。
    conditions: list[str] = []
    if scope_sql:
        conditions.append(scope_sql.removeprefix("WHERE ").strip())
    conditions.extend(extra)
    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    joins = (
        "FROM patient p"
        " JOIN v_patient_visibility v ON v.inpatient_no = p.inpatient_no"
        " LEFT JOIN v_patient_next_appointment n ON n.patient_no = p.inpatient_no"
    )
    total = int(conn.execute(f"SELECT COUNT(*) {joins} {where_sql}", params).fetchone()[0])

    # 排序（设计.md 3.4.3 "我的患者优先"）：
    #   组 0 = 可见归属是我；组 1 = 无人负责；组 2 = 其他治疗师
    #   组内按最近一次有效排期的日期与半日升序（无排期排最后）
    order_params: list[Any] = []
    if user_id is None:
        order_sql = "ORDER BY p.inpatient_no"
    else:
        order_sql = (
            "ORDER BY CASE WHEN v.visible_therapist_id = ? THEN 0"
            " WHEN v.visible_therapist_id IS NULL THEN 1 ELSE 2 END,"
            " COALESCE(n.next_date, '9999-12-31'), COALESCE(n.next_period_rank, 9), p.inpatient_no"
        )
        order_params.append(user_id)

    rows = conn.execute(
        f"SELECT {_PATIENT_COLUMNS}, {_VISIBILITY_COLUMNS} {joins} {where_sql}"
        f" {order_sql} LIMIT ? OFFSET ?",
        (*params, *order_params, limit, offset),
    ).fetchall()
    return [dict(r) for r in rows], total


# --------------------------------------------------------------------------- #
# 写入
# --------------------------------------------------------------------------- #
def create_patient(
    conn: sqlite3.Connection,
    *,
    inpatient_no: str,
    name: str,
    diagnosis: str | None = None,
    admin_note: str | None = None,
    assigned_therapist_id: int | None = None,
    status: str = STATUS_IN_HOSPITAL,
) -> dict[str, Any]:
    if status not in PATIENT_STATUSES:
        raise Conflict(f"患者状态必须是 {'/'.join(PATIENT_STATUSES)} 之一", details={"status": status})
    if get_patient(conn, inpatient_no) is not None:
        raise Conflict("住院编号已存在", details={"inpatient_no": inpatient_no})

    conn.execute(
        "INSERT INTO patient (inpatient_no, name, diagnosis, admin_note, assigned_therapist_id, status)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (inpatient_no, name, diagnosis, admin_note, assigned_therapist_id, status),
    )
    if assigned_therapist_id is not None:
        _record_assignment(conn, inpatient_no, None, assigned_therapist_id, "admin_assign")
    return get_patient_or_raise(conn, inpatient_no)


def update_patient(
    conn: sqlite3.Connection,
    inpatient_no: str,
    *,
    name: str | None = None,
    diagnosis: str | None = None,
    admin_note: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    get_patient_or_raise(conn, inpatient_no)
    if status is not None and status not in PATIENT_STATUSES:
        raise Conflict(f"患者状态必须是 {'/'.join(PATIENT_STATUSES)} 之一", details={"status": status})

    sets: list[str] = []
    params: list[Any] = []
    for column, value in (
        ("name", name),
        ("diagnosis", diagnosis),
        ("admin_note", admin_note),
        ("status", status),
    ):
        if value is not None:
            sets.append(f"{column} = ?")
            params.append(value)
    if sets:
        sets.append("revision = revision + 1")
        conn.execute(f"UPDATE patient SET {', '.join(sets)} WHERE inpatient_no = ?", (*params, inpatient_no))
    return get_patient_or_raise(conn, inpatient_no)


def _record_assignment(
    conn: sqlite3.Connection,
    patient_no: str,
    from_therapist_id: int | None,
    to_therapist_id: int | None,
    change_type: str,
    operator_user_id: int | None = None,
    effective_date: str | None = None,
) -> None:
    """写归属历史（M12）。所有归属变更都必须经过这里。"""
    conn.execute(
        "INSERT INTO patient_assignment_history"
        " (patient_no, from_therapist_id, to_therapist_id, change_type, operator_user_id, effective_date)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (patient_no, from_therapist_id, to_therapist_id, change_type, operator_user_id, effective_date),
    )


def claim_patient(conn: sqlite3.Connection, inpatient_no: str, therapist_id: int) -> dict[str, Any]:
    """治疗师认领未分配患者（正式归属变更）。"""
    patient = get_patient_or_raise(conn, inpatient_no)
    if patient["visible_therapist_id"] is not None:
        raise Conflict(
            "该患者当前已有负责治疗师，不能认领",
            details={"visible_therapist_id": patient["visible_therapist_id"]},
        )
    if patient["visibility_state"] == "temp_released":
        # 处于单日假临时释放中：应走临时认领，而不是改原归属
        raise Conflict(
            "该患者处于单日假临时释放中，请使用临时认领",
            details={"hint": "temp-claim"},
        )
    _record_assignment(conn, inpatient_no, None, therapist_id, "claim", operator_user_id=therapist_id)
    conn.execute(
        "UPDATE patient SET assigned_therapist_id = ?, revision = revision + 1 WHERE inpatient_no = ?",
        (therapist_id, inpatient_no),
    )
    return get_patient_or_raise(conn, inpatient_no)


def release_patient(conn: sqlite3.Connection, inpatient_no: str, operator_user_id: int) -> dict[str, Any]:
    """放弃归属（回到未分配）。治疗师只能放弃自己的，管理员可释放任意患者。"""
    patient = get_patient_or_raise(conn, inpatient_no)
    previous = patient["assigned_therapist_id"]
    if previous is None:
        raise Conflict("该患者本来就未分配", details={"inpatient_no": inpatient_no})
    _record_assignment(conn, inpatient_no, previous, None, "admin_release", operator_user_id=operator_user_id)
    conn.execute(
        "UPDATE patient SET assigned_therapist_id = NULL, revision = revision + 1 WHERE inpatient_no = ?",
        (inpatient_no,),
    )
    return get_patient_or_raise(conn, inpatient_no)


def assign_patient(
    conn: sqlite3.Connection, inpatient_no: str, therapist_id: int | None, operator_user_id: int
) -> dict[str, Any]:
    """管理员指定/清除归属。"""
    patient = get_patient_or_raise(conn, inpatient_no)
    previous = patient["assigned_therapist_id"]
    if previous == therapist_id:
        return patient
    _record_assignment(
        conn, inpatient_no, previous, therapist_id, "admin_assign", operator_user_id=operator_user_id
    )
    conn.execute(
        "UPDATE patient SET assigned_therapist_id = ?, revision = revision + 1 WHERE inpatient_no = ?",
        (therapist_id, inpatient_no),
    )
    return get_patient_or_raise(conn, inpatient_no)


def release_all_for_therapist(
    conn: sqlite3.Connection, therapist_id: int, operator_user_id: int
) -> list[str]:
    """多日假：把该治疗师名下患者**正式排空**（`设计.md` 3.5.3）。

    返回被排空的住院编号列表。注意**不自动恢复**，撤销需管理员手动调整。
    """
    rows = conn.execute(
        "SELECT inpatient_no FROM patient WHERE assigned_therapist_id = ?", (therapist_id,)
    ).fetchall()
    numbers = [str(r["inpatient_no"]) for r in rows]
    for no in numbers:
        _record_assignment(conn, no, therapist_id, None, "multi_day_release", operator_user_id=operator_user_id)
    if numbers:
        conn.execute(
            "UPDATE patient SET assigned_therapist_id = NULL, revision = revision + 1"
            " WHERE assigned_therapist_id = ?",
            (therapist_id,),
        )
    return numbers


def assignment_history(conn: sqlite3.Connection, inpatient_no: str) -> list[dict[str, Any]]:
    get_patient_or_raise(conn, inpatient_no)
    rows = conn.execute(
        "SELECT h.*, f.name AS from_name, t.name AS to_name, o.name AS operator_name"
        " FROM patient_assignment_history h"
        " LEFT JOIN user f ON f.id = h.from_therapist_id"
        " LEFT JOIN user t ON t.id = h.to_therapist_id"
        " LEFT JOIN user o ON o.id = h.operator_user_id"
        " WHERE h.patient_no = ? ORDER BY h.id",
        (inpatient_no,),
    ).fetchall()
    return [dict(r) for r in rows]


__all__ = [
    "PATIENT_STATUSES",
    "SELECT_COLUMN_NAMES",
    "STATUS_DISCHARGED",
    "STATUS_IN_HOSPITAL",
    "STATUS_PAUSED",
    "Scope",
    "VISIBILITY_VIEW_SQL",
    "assign_patient",
    "assignment_history",
    "can_schedule",
    "claim_patient",
    "create_patient",
    "get_patient",
    "get_patient_or_raise",
    "list_patients",
    "release_all_for_therapist",
    "release_patient",
    "update_patient",
    "visibility_from",
]
