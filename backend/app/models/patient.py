"""患者数据访问与**归属可见性解析**（阶段 1 / `设计.md` 3.3、3.5.5，`开发计划.md` M12/M18）。

本模块承载本系统最关键的一条业务规则：**"当前谁负责这个患者"**。

**2026-10-05 起归属简化为两层**（`temporary_assignment` 已彻底删除，迁移 009）：

| 场景 | `assigned_therapist_id` | 可见归属 |
|---|---|---|
| 有归属 | 张三 | 张三（**恒等于原归属**） |
| 放弃归属 / 管理员批量排空 | NULL | NULL |

也就是说 `visible_therapist_id` 现在**直接就是** `patient.assigned_therapist_id`，
`v_patient_visibility` 不再做任何解析。原先的"临时释放 → 可见归属变 NULL →
他人临时认领"三层语义随临时指派一并删除：

- 它唯一的自动来源是"单日请假"，而请假已随排期功能下线（迁移 008）；
- 它从来没有 API/CLI 登记入口（`/temp-release`、`/temp-claim` 从未实现）；
- 2026-10-03 改成"**全科白板**"后，任何治疗师都能查看/记录任何在院患者，
  所以临时指派**不改变任何权限**，只影响 `scope=mine` 的筛选与排序分组。

> 2026-10-05：`visibility_state` 列也已删除（迁移 010）—— 它在 009 之后恒为
> `'assigned'`，没有任何真实消费者，留着只会诱使后来人写出基于它的判断。

实现要点：
1. 用 `v_patient_visibility` 视图统一计算，**不要**在路由或前端各写一遍；
2. 视图定义必须与迁移 010 完全一致（`scripts/check_docs_consistency.py` 会逐字比对）。
"""

from __future__ import annotations

import sqlite3
from typing import Any, Literal

from app.models.base import Conflict, NotFound, row_to_dict

STATUS_IN_HOSPITAL = "in_hospital"
STATUS_DISCHARGED = "discharged"
STATUS_PAUSED = "paused"
# 2026-10-05（迁移 013）：治疗师提交出院小结后进入"待出院"，等管理员确认或满 7 天自动出院
#（用户：「填完小结即待出院」+「1 周后自动出院」）。
STATUS_PENDING_DISCHARGE = "pending_discharge"
PATIENT_STATUSES = (
    STATUS_IN_HOSPITAL,
    STATUS_DISCHARGED,
    STATUS_PAUSED,
    STATUS_PENDING_DISCHARGE,
)

# "白板"上默认可见的状态（2026-10-03 全科白板决策）：
# 在院与暂停都属于"当前在科室里的患者"；已出院默认隐藏，需要时用 status 筛选显式查。
#
# ★ `pending_discharge` **刻意不在**这里：患者已经填完出院小结、等着办手续，
#   不该再出现在治疗师白板上（也就不会再被误记新记录）。管理员仍可用 scope=all 查看。
ACTIVE_STATUSES = (STATUS_IN_HOSPITAL, STATUS_PAUSED)

# 可用的数据范围（D10）。
#
# 2026-10-03 起新增 `dept`（科室级白板）：治疗师默认范围，含义是"科室当前在院/暂停的患者"，
# 不再按归属隔离。原有取值保留：
#   - `mine`/`unassigned` 仍用于**筛选**（归属是我 / 归属为空）；
#   - `visible` 保留为 `dept` 的同义兼容值（旧客户端仍能用）；
#   - `all` 仍是**管理员专属**的全表范围（含已出院）。
#
# 2026-10-05：`temp` **已从患者列表的范围白名单里删除**（`temporary_assignment` 已删，
# 迁移 009）。「时间轴 / 记录列表」（`api/v1/records.py`）的 `scope=temp` 也已按用户决定
# 一并删除（现在只有 `mine` / `visible`）。
#
# ⚠ 两件事**不要混淆**：
#   * `scope=temp`（数据范围筛选）—— 已全部删除；
#   * `is_temporary`（记录级标记，"记录人 ≠ 该患者当时的归属人"）—— **仍然保留**，
#     由 `treatment_model.temporary_expr()` 查询时推导，PDF、患者每日汇总与后台记录列表
#     三个消费方都还在用它。它与 `temporary_assignment` 从来没有依赖关系。
Scope = Literal["mine", "unassigned", "all", "visible", "dept"]

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

# ★ 2026-10-05：归属的**治疗师姓名**（客户端要显示"张三"而不是"治疗师 #2"）。
#
# 用相关子查询而**不是**再 JOIN 一次 `user`：这条 SQL 已经 JOIN 了两张视图，
# 再加一个 LEFT JOIN 会让"每个患者恰好一行"这个前提更难看出来（子查询天然不会
# 放大行数）。而且 `get_patient` 的单条查询也能直接用同一个片段。
_ASSIGNED_THERAPIST_NAME_SQL = (
    "(SELECT u.name FROM user u WHERE u.id = p.assigned_therapist_id)"
    " AS assigned_therapist_name"
)
_VISIBILITY_COLUMNS = "v.visible_therapist_id"

# --------------------------------------------------------------------------- #
# 可见性视图：全系统唯一的归属解析实现
# --------------------------------------------------------------------------- #
# 2026-10-05（迁移 009）：临时指派删除后，归属只剩两层 ——
# 可见归属**直接等于** `patient.assigned_therapist_id`（没有中间解析）。
#
# 2026-10-05（迁移 010）：`visibility_state` 列也删掉了。它在 009 之后恒为 'assigned'，
# 是个"看起来有意义、实际恒定"的字段 —— 留着会诱使后来人写出基于它的判断。
# 删除前复查确认它**没有任何真实消费者**：安卓本地库那列早已随 schemaVersion 4 删除、
# 后台只是可选类型字段、后端只有 `PatientOut` 声明过它。
#
# ⚠ 这段 SQL 必须与 `app/db/migrations/010_drop_visibility_state.sql` 里的
#   CREATE VIEW 逐字一致（`scripts/check_docs_consistency.py` 会比对两者）。
VISIBILITY_VIEW_SQL = """
CREATE VIEW v_patient_visibility AS
SELECT p.inpatient_no,
       p.assigned_therapist_id,
       p.assigned_therapist_id AS visible_therapist_id
FROM patient p
"""


def visibility_from(scope: Scope, user_id: int) -> tuple[str, list[Any]]:
    """返回 ``(SQL 片段, 参数)``，供拼接到 ``FROM v_patient_visibility v`` 之后。

    各范围语义：

    - ``dept``      **科室级白板（治疗师默认，2026-10-03 起）**：科室当前在院/暂停的患者，
                    不按归属隔离。一个上午里 PT/OT/言语/吞咽可能各给同一患者做一次，
                    所以"别人的患者"必须可见。
    - ``visible``   ``dept`` 的同义兼容值（旧客户端仍在用）。
    - ``mine``      可见归属是我 —— 因为可见归属恒等于原归属，等价于"归属是我"。
    - ``unassigned`` 无人负责（归属为 NULL）。
    - ``all``       不加限制（**仅管理员**，路由层负责拦截；含已出院）。

    > ``temp`` 在 2026-10-05 随 `temporary_assignment` 删除（迁移 009）：
    > 它只影响筛选，而"临时把患者从甲转给乙"在全科白板下不改变任何权限，
    > 用 `assigned_therapist_id` 直接表达即可。`api/v1/records.py` 的 `scope=temp`
    > 也已按用户决定一并删除 —— 那是**另一件事**（记录级的"临时治疗"筛选），
    > 详情见本模块顶部注释。
    """
    if scope == "mine":
        return "WHERE v.visible_therapist_id = ?", [user_id]
    if scope == "unassigned":
        return "WHERE v.visible_therapist_id IS NULL", []
    if scope == "all":
        return "", []
    if scope in ("dept", "visible"):
        # 注意用 `p.status` 而不是 `v.status`：视图 v_patient_visibility 没有输出 status 列，
        # 而 list_patients 的 joins 里本来就 JOIN 了 patient p。
        placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
        return f"WHERE p.status IN ({placeholders})", list(ACTIVE_STATUSES)
    raise Conflict(f"未知的数据范围：{scope}", details={"scope": scope})


# 注：这里原有 `covers_patient()`（原名 `can_schedule`）做"该治疗师当前是否有权开展/记录
# 这个患者"的单体判断；它唯一的生产调用方是已删除的 `api/v1/schedule.py`，故 2026-10-05
# 按死代码删除。归属语义本身没消失，现在只由 `v_patient_visibility` 视图 +
# `visibility_from()` 的 scope 条件表达（`mine` ≡ 可见归属是我，`unassigned` ≡ 可见归属为空）。


# --------------------------------------------------------------------------- #
# 查询
# --------------------------------------------------------------------------- #
def get_patient(conn: sqlite3.Connection, inpatient_no: str) -> dict[str, Any] | None:
    return row_to_dict(
        conn.execute(
            f"SELECT {_PATIENT_COLUMNS}, {_VISIBILITY_COLUMNS},"
            f" {_ASSIGNED_THERAPIST_NAME_SQL}"
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
        " LEFT JOIN v_patient_last_treated l"
        "   ON l.patient_no = p.inpatient_no AND l.therapist_id = ?"
    )
    # JOIN 里带了一个占位参数（我的 user_id），要排在其他参数之前。
    join_params: list[Any] = [user_id if user_id is not None else -1]
    total = int(
        conn.execute(
            f"SELECT COUNT(*) FROM patient p"
            f" JOIN v_patient_visibility v ON v.inpatient_no = p.inpatient_no"
            f" {where_sql}",
            params,
        ).fetchone()[0]
    )

    # 排序（设计.md 3.4.3 "我的患者优先"，2026-10-05 起改用实际治疗排序）：
    #   组 0 = 可见归属是我；组 1 = 无人负责；组 2 = 其他治疗师
    #   组内按"我最近一次已提交治疗这个患者的日期"**降序**（越近越靠前），
    #   从没被我治过的排最后（COALESCE 到极小日期）。
    #
    #   为什么是"最近治疗的"而不是"下一个排期的"：本系统不做排班，
    #   治疗师打开列表是为了**接着记今天做过的患者**，所以"我刚治过谁"才是正确依据。
    order_params: list[Any] = []
    if user_id is None:
        order_sql = "ORDER BY p.inpatient_no"
    else:
        # 组内按"我最近一次已提交治疗"降序；同一天不再区分上午/下午 ——
        # 迁移 011 删掉了 `session_period`，`v_patient_last_treated` 只剩 last_date
        #（旧代码这里还 ORDER BY l.last_period_rank，那一列已不存在，会直接报
        # "no such column: l.last_period_rank"）。
        order_sql = (
            "ORDER BY CASE WHEN v.visible_therapist_id = ? THEN 0"
            " WHEN v.visible_therapist_id IS NULL THEN 1 ELSE 2 END,"
            " COALESCE(l.last_date, '0000-01-01') DESC,"
            " p.inpatient_no"
        )
        order_params.append(user_id)

    rows = conn.execute(
        f"SELECT {_PATIENT_COLUMNS}, {_VISIBILITY_COLUMNS},"
        f" {_ASSIGNED_THERAPIST_NAME_SQL} {joins} {where_sql}"
        f" {order_sql} LIMIT ? OFFSET ?",
        (*join_params, *params, *order_params, limit, offset),
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
    # 2026-10-05：这里原有 `visibility_state == 'temp_released'` 的分支
    #（提示"该患者处于单日假临时释放中，请使用临时认领"，并带一个临时认领的 hint）。
    # 临时指派整体删除（迁移 009/010）后该状态已不存在，分支不可达故删除；
    # 相应的提示文案与 hint 也一并消失 —— 不再存在"临时认领"这条路。
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
    """批量排空：把该治疗师名下患者**正式清空**（`设计.md` 3.5.3）。

    返回被排空的住院编号列表。注意**不自动恢复**，撤销需管理员手动调整。

    > 原名来自"多日假"（请假功能已于 2026-10-05 下线），排空本身仍是管理员会用到的
    > 归属操作，故保留；`change_type` 继续写 `multi_day_release` 以保持历史数据可读。
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


# --------------------------------------------------------------------------- #
# 出院流程（2026-10-05 用户要求）
# --------------------------------------------------------------------------- #
def mark_pending_discharge(
    conn: sqlite3.Connection, inpatient_no: str, *, operator_user_id: int | None = None
) -> dict[str, Any]:
    """在院/暂停 → 待出院。

    ⚠ **权限口径的用户决定**：发起出院**任何治疗师都能做**（不是 AdminUser），
    因为治疗师才是填出院小结的人；管理员的专用改状态接口 `PUT /patients/{no}`
    保持不动，仍可改回任何状态。真正落地出院仍需管理员确认（或满 7 天自动出院）。
    """
    patient = get_patient_or_raise(conn, inpatient_no)
    if patient["status"] == STATUS_PENDING_DISCHARGE:
        return patient
    if patient["status"] == STATUS_DISCHARGED:
        raise Conflict(
            "该患者已出院", details={"inpatient_no": inpatient_no, "status": patient["status"]}
        )
    return update_patient(conn, inpatient_no, status=STATUS_PENDING_DISCHARGE)


def confirm_discharge(conn: sqlite3.Connection, inpatient_no: str) -> dict[str, Any]:
    """待出院 → 已出院（**管理员**确认）。"""
    patient = get_patient_or_raise(conn, inpatient_no)
    if patient["status"] != STATUS_PENDING_DISCHARGE:
        raise Conflict(
            "只有待出院的患者可以确认出院",
            details={"inpatient_no": inpatient_no, "status": patient["status"]},
        )
    return update_patient(conn, inpatient_no, status=STATUS_DISCHARGED)


def cancel_pending_discharge(conn: sqlite3.Connection, inpatient_no: str) -> dict[str, Any]:
    """取消待出院 → 回在院（**管理员**纠正误操作）。"""
    patient = get_patient_or_raise(conn, inpatient_no)
    if patient["status"] != STATUS_PENDING_DISCHARGE:
        raise Conflict(
            "只有待出院的患者可以取消待出院",
            details={"inpatient_no": inpatient_no, "status": patient["status"]},
        )
    return update_patient(conn, inpatient_no, status=STATUS_IN_HOSPITAL)


def pending_discharge_since(conn: sqlite3.Connection, inpatient_no: str) -> str | None:
    """该患者"进入待出院"的时刻（用于「满 7 天自动出院」）。

    真源是**出院小结的提交时间**（`treatment_record.submitted_at`）：
    那是患者进入待出院状态的业务时刻，且是可追溯的文书时间戳，
    不在 `patient` 上另存一个"何时变的状态"（存了就会与文书不一致）。
    万一找不到出院小结（例如管理员直接 `PUT` 改的状态），退回 `patient.updated_at`。
    """
    row = conn.execute(
        "SELECT MAX(submitted_at) AS at FROM treatment_record"
        " WHERE patient_no = ? AND kind = 'discharge' AND status IN ('submitted', 'locked')",
        (inpatient_no,),
    ).fetchone()
    if row is not None and row["at"]:
        return str(row["at"])
    fallback = conn.execute(
        "SELECT updated_at FROM patient WHERE inpatient_no = ?", (inpatient_no,)
    ).fetchone()
    return str(fallback["updated_at"]) if fallback is not None else None


def auto_discharge_pending(
    conn: sqlite3.Connection, *, days: int = 7, now: str | None = None, dry_run: bool = False
) -> list[str]:
    """待出院满 `days` 天的患者自动出院（用户明确要求「1 周后自动出院」「真的自动」）。

    比较用**UTC ISO 字符串**（与库层时间戳同格式，可直接字典序比较）；
    时钟可由 `now` 注入，便于测试与补跑。返回被（或将被）自动出院的住院编号。
    """
    from datetime import UTC, datetime, timedelta

    stamp = now or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    cutoff = (datetime.fromisoformat(stamp.replace("Z", "+00:00")) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )[:-3] + "Z"

    rows = conn.execute(
        "SELECT inpatient_no FROM patient WHERE status = ? ORDER BY inpatient_no",
        (STATUS_PENDING_DISCHARGE,),
    ).fetchall()
    discharged: list[str] = []
    for row in rows:
        inpatient_no = str(row["inpatient_no"])
        since = pending_discharge_since(conn, inpatient_no)
        if since is None or since > cutoff:
            continue
        discharged.append(inpatient_no)
        if not dry_run:
            update_patient(conn, inpatient_no, status=STATUS_DISCHARGED)
    return discharged


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
    "ACTIVE_STATUSES",
    "PATIENT_STATUSES",
    "SELECT_COLUMN_NAMES",
    "STATUS_DISCHARGED",
    "STATUS_IN_HOSPITAL",
    "STATUS_PAUSED",
    "STATUS_PENDING_DISCHARGE",
    "Scope",
    "VISIBILITY_VIEW_SQL",
    "assign_patient",
    "assignment_history",
    "auto_discharge_pending",
    "cancel_pending_discharge",
    "claim_patient",
    "confirm_discharge",
    "create_patient",
    "get_patient",
    "get_patient_or_raise",
    "list_patients",
    "mark_pending_discharge",
    "pending_discharge_since",
    "release_all_for_therapist",
    "release_patient",
    "update_patient",
    "visibility_from",
]
