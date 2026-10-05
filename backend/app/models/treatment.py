"""治疗记录数据访问与状态机（阶段 3 / `设计.md` 3.7、`开发计划.md` M10/M11/M17）。

记录结构：**主项目 + 子项目（复选）+ 参数 + 患者反应 + 备注 + 时长**
（明细行 `record_item` 每条对应一个"主项目下的一个子项目"）。

状态机：

    draft（草稿）──submit──> submitted（已提交）──lock──> locked（已锁定）

- **草稿**：任意修改，**不留痕、不计 `edit_count`**（治疗师在写的时候不该产生审计噪声）。
- **已提交**：实质修改由**库层触发器**写 `audit_log` 并累加 `edit_count`（`002_triggers.sql`）。
  这是刻意的分工——留痕不能只依赖应用代码自觉。
- **已锁定**：治疗师不可再改；管理员可改（仍留痕）。

两层快照（防字典改名影响历史）：
- `record_item.sub_item_name_snapshot`：子项目名称
- `record_item.params_snapshot_json`：参数名与选项**当时的**文本
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.core import jsonutil
from app.models.base import Conflict, Forbidden, Invalid, NotFound, row_to_dict

STATUS_DRAFT = "draft"
STATUS_SUBMITTED = "submitted"
STATUS_LOCKED = "locked"
STATUSES = (STATUS_DRAFT, STATUS_SUBMITTED, STATUS_LOCKED)

# 允许被修改的状态（草稿与已提交都可改；已锁定只有管理员能改）
EDITABLE_BY_OWNER = (STATUS_DRAFT, STATUS_SUBMITTED)
PERIODS = ("am", "pm")

# 查询列。
# 2026-10-05：`appointment_id` 与 `is_temporary` 两个存储列随排期功能下线一并删除。
# `appointment_id` 彻底没有意义（排期没了）；`is_temporary` 改为**查询时推导**，
# 因为它是"记录人 ≠ 该患者**当时**的归属人"这个事实的函数，不该单独存一份
# （存了就会与事实不一致）。推导 SQL 见 `temporary_expr()`。
RECORD_COLUMNS = (
    "id, patient_no, therapist_id,"
    " record_date, session_period, seq_no, duration_min, patient_response_json, note,"
    " status, edit_count, locked_at, created_at, submitted_at, updated_at, revision"
)
ITEM_COLUMNS = (
    "id, record_id, main_item_id, sub_item_id, sub_item_name_snapshot, params_json,"
    " params_snapshot_json, sort, revision, created_at, updated_at"
)


def temporary_expr(alias: str = "") -> str:
    """生成「是否临时治疗」的 SQL 表达式（`AS is_temporary`）。

    语义：**记录人不是该患者在当时（记录创建时刻）的归属治疗师**。

    为什么要在查询时重建而不能"看当前归属"：治疗师会换、患者会转手，
    用当前归属去判断历史记录，等于"回头把旧账按今天的归属重算" ——
    那些本来正常的记录会突然变成"临时"，已经计过的统计也会变。
    `patient_assignment_history` 每次归属变更都留了痕（谁→谁、何时），
    所以"当时是谁"是可以准确回溯的。

    `original_therapist_id` 这个存储列已被删除：它只在"从排期进入"那条路径上
    被赋值，排期下线后永远不会再写入（历史数据里也恒为 NULL）。
    留一个永远不写的列比删掉它更危险 —— 后来的人会以为它有值。

    归零安全：拿不到历史（该患者从未有过归属变更记录，或历史早于记录时间）
    时视为**非临时**，与"患者当时无人负责"的事实一致（谁做都算正常）。
    """
    p = f"{alias}." if alias else ""
    return (
        " CASE WHEN ("
        "   SELECT h.to_therapist_id FROM patient_assignment_history h"
        f"   WHERE h.patient_no = {p}patient_no"
        f"     AND h.created_at <= {p}created_at"
        "   ORDER BY h.created_at DESC, h.id DESC LIMIT 1"
        f" ) IS NOT NULL AND ("
        "   SELECT h.to_therapist_id FROM patient_assignment_history h"
        f"   WHERE h.patient_no = {p}patient_no"
        f"     AND h.created_at <= {p}created_at"
        "   ORDER BY h.created_at DESC, h.id DESC LIMIT 1"
        f" ) <> {p}therapist_id"
        " THEN 1 ELSE 0 END AS is_temporary"
    )


# --------------------------------------------------------------------------- #
# 查询
# --------------------------------------------------------------------------- #
def get_record(conn: sqlite3.Connection, record_id: int) -> dict[str, Any] | None:
    """取单条记录，附带患者姓名与治疗师姓名、以及明细行。"""
    row = conn.execute(
        "SELECT r.id, r.patient_no, r.therapist_id,"
        f"{temporary_expr('r')},"
        " r.record_date, r.session_period, r.seq_no, r.duration_min,"
        " r.patient_response_json, r.note, r.status, r.edit_count, r.locked_at, r.created_at,"
        " r.submitted_at, r.updated_at, r.revision,"
        " p.name AS patient_name, u.name AS therapist_name"
        " FROM treatment_record r"
        " JOIN patient p ON p.inpatient_no = r.patient_no"
        " JOIN user u ON u.id = r.therapist_id"
        " WHERE r.id = ?",
        (record_id,),
    ).fetchone()
    data = row_to_dict(row)
    if data is None:
        return None
    data["patient_response"] = jsonutil.loads(data.pop("patient_response_json", None), None)
    data["items"] = list_items(conn, record_id)
    return data


def get_record_or_raise(conn: sqlite3.Connection, record_id: int) -> dict[str, Any]:
    record = get_record(conn, record_id)
    if record is None:
        raise NotFound("治疗记录不存在", details={"record_id": record_id})
    return record


def list_items(conn: sqlite3.Connection, record_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT {ITEM_COLUMNS} FROM record_item WHERE record_id = ? ORDER BY sort, id", (record_id,)
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        data["params"] = jsonutil.loads(data.pop("params_json", None), {}) or {}
        data["params_snapshot"] = jsonutil.loads(data.pop("params_snapshot_json", None), None)
        items.append(data)
    return items


def list_records(
    conn: sqlite3.Connection,
    *,
    patient_no: str | None = None,
    therapist_id: int | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    patient_nos: list[str] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """列出记录。``patient_nos`` 用于"按可见患者过滤"（D10 的数据级权限由调用方算好）。"""
    where: list[str] = []
    params: list[Any] = []
    if patient_no:
        where.append("r.patient_no = ?")
        params.append(patient_no)
    if therapist_id is not None:
        where.append("r.therapist_id = ?")
        params.append(therapist_id)
    if status:
        where.append("r.status = ?")
        params.append(status)
    if date_from:
        where.append("r.record_date >= ?")
        params.append(date_from)
    if date_to:
        where.append("r.record_date <= ?")
        params.append(date_to)
    if patient_nos is not None:
        if not patient_nos:
            return [], 0  # 调用方没有可见患者时直接短路，避免拼出 IN ()
        where.append(f"r.patient_no IN ({', '.join('?' for _ in patient_nos)})")
        params.extend(patient_nos)

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    base = (
        "FROM treatment_record r"
        " JOIN patient p ON p.inpatient_no = r.patient_no"
        " JOIN user u ON u.id = r.therapist_id"
        f" {clause}"
    )
    total = int(conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0])
    rows = conn.execute(
        "SELECT r.id, r.patient_no, r.therapist_id,"
        f"{temporary_expr('r')},"
        " r.record_date, r.session_period, r.seq_no, r.duration_min,"
        " r.note, r.status, r.edit_count, r.locked_at, r.created_at, r.submitted_at, r.revision,"
        " p.name AS patient_name, u.name AS therapist_name,"
        " (SELECT COUNT(*) FROM record_item ri WHERE ri.record_id = r.id) AS item_count"
        f" {base}"
        " ORDER BY r.record_date DESC, r.id DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return [dict(r) for r in rows], total


def next_seq_no(conn: sqlite3.Connection, patient_no: str) -> int:
    """该患者第几次治疗（只统计非草稿记录）。

    **必须在同一事务内调用并写入**，否则并发创建会跳号（M10）。
    """
    row = conn.execute(
        "SELECT COUNT(*) FROM treatment_record WHERE patient_no = ? AND status <> ?",
        (patient_no, STATUS_DRAFT),
    ).fetchone()
    return int(row[0]) + 1


def last_params_for_sub_item(
    conn: sqlite3.Connection, patient_no: str, sub_item_id: int
) -> dict[str, Any] | None:
    """该患者在该子项目上**最近一次**记录用过的参数（F3.7 的"上次值"）。

    用 `json_extract` 直接从 JSON 列取，避免把参数抽成关系表
    （参数集合是动态的，关系化会让字典改动变成 schema 改动）。
    """
    row = conn.execute(
        "SELECT json_extract(ri.params_json, '$') AS params"
        " FROM record_item ri JOIN treatment_record r ON r.id = ri.record_id"
        " WHERE r.patient_no = ? AND ri.sub_item_id = ?"
        "   AND r.status IN (?, ?) AND ri.params_json IS NOT NULL"
        " ORDER BY r.record_date DESC, r.id DESC, ri.sort LIMIT 1",
        (patient_no, sub_item_id, STATUS_SUBMITTED, STATUS_LOCKED),
    ).fetchone()
    if row is None or row["params"] is None:
        return None
    return jsonutil.loads(row["params"], None)


# --------------------------------------------------------------------------- #
# 写入
# --------------------------------------------------------------------------- #
def _assert_editable(record: dict[str, Any], *, user_id: int, is_admin: bool) -> None:
    if record["status"] != STATUS_LOCKED:
        return
    if not is_admin:
        raise Forbidden(
            "该记录已锁定，治疗师不能再修改",
            code="RECORD_LOCKED",
            details={"record_id": record["id"]},
        )
    if int(record["therapist_id"]) != user_id:
        # 管理员可以改，但记下来源，审计里能看出是谁动的
        return


def create_record(
    conn: sqlite3.Connection,
    *,
    patient_no: str,
    therapist_id: int,
    record_date: str,
    session_period: str | None = None,
    duration_min: int | None = None,
    patient_response: Any = None,
    note: str | None = None,
    status: str = STATUS_DRAFT,
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if status not in STATUSES:
        raise Invalid(f"记录状态非法：{status}", details={"status": status})
    if session_period is not None and session_period not in PERIODS:
        raise Invalid("session_period 只能是 am / pm", details={"session_period": session_period})
    if duration_min is not None and duration_min < 0:
        raise Invalid("时长不能为负", details={"duration_min": duration_min})

    exists = conn.execute("SELECT 1 FROM patient WHERE inpatient_no = ?", (patient_no,)).fetchone()
    if exists is None:
        raise NotFound("患者不存在", details={"inpatient_no": patient_no})

    seq_no = next_seq_no(conn, patient_no) if status != STATUS_DRAFT else None
    submitted_at = None
    # 直接以 submitted 建库（如离线同步补录）也要算作已提交
    if status in (STATUS_SUBMITTED, STATUS_LOCKED):
        from app.core.clock import utc_timestamp_now

        submitted_at = utc_timestamp_now()

    cur = conn.execute(
        "INSERT INTO treatment_record"
        " (patient_no, therapist_id,"
        "  record_date, session_period, seq_no, duration_min, patient_response_json, note,"
        "  status, submitted_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            patient_no, therapist_id,
            record_date, session_period, seq_no, duration_min,
            jsonutil.dumps(patient_response), note, status, submitted_at,
        ),
    )
    record_id = int(cur.lastrowid)
    if items:
        _replace_items(conn, record_id, items)
    return get_record_or_raise(conn, record_id)


def update_record(
    conn: sqlite3.Connection,
    record_id: int,
    *,
    user_id: int,
    is_admin: bool,
    record_date: str | None = None,
    session_period: str | None = None,
    duration_min: int | None = None,
    patient_response: Any = None,
    note: str | None = None,
    items: list[dict[str, Any]] | None = None,
    clear_patient_response: bool = False,
) -> dict[str, Any]:
    """修改记录。留痕与 `edit_count` 由库层触发器负责（status <> 'draft' 时生效）。"""
    record = get_record_or_raise(conn, record_id)
    _assert_editable(record, user_id=user_id, is_admin=is_admin)

    if session_period is not None and session_period not in PERIODS:
        raise Invalid("session_period 只能是 am / pm", details={"session_period": session_period})
    if duration_min is not None and duration_min < 0:
        raise Invalid("时长不能为负", details={"duration_min": duration_min})

    sets: list[str] = []
    params: list[Any] = []
    if record_date is not None:
        sets.append("record_date = ?")
        params.append(record_date)
    if session_period is not None:
        sets.append("session_period = ?")
        params.append(session_period)
    if duration_min is not None:
        sets.append("duration_min = ?")
        params.append(duration_min)
    if note is not None:
        sets.append("note = ?")
        params.append(note)
    if patient_response is not None or clear_patient_response:
        sets.append("patient_response_json = ?")
        params.append(None if clear_patient_response else jsonutil.dumps(patient_response))

    if sets:
        # 推进 revision：离线客户端靠它判断手上的副本是否过期。
        # 不推进的话，客户端永远以为自己的版本是最新的（阶段 4 实测缺陷，
        # 与排期的 update_appointment 保持一致）。
        sets.append("revision = revision + 1")
        conn.execute(
            f"UPDATE treatment_record SET {', '.join(sets)} WHERE id = ?", (*params, record_id)
        )
    if items is not None:
        _replace_items(conn, record_id, items)
    return get_record_or_raise(conn, record_id)


def _replace_items(conn: sqlite3.Connection, record_id: int, items: list[dict[str, Any]]) -> None:
    """整体替换明细行。

    明细行数量少（一次治疗几个子项目），整体替换比逐行 diff 更简单可靠；
    快照在写入时生成，因此字典后续改名不会影响已有记录。
    """
    conn.execute("DELETE FROM record_item WHERE record_id = ?", (record_id,))
    for index, item in enumerate(items):
        conn.execute(
            "INSERT INTO record_item"
            " (record_id, main_item_id, sub_item_id, sub_item_name_snapshot, params_json,"
            "  params_snapshot_json, sort)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record_id,
                item["main_item_id"],
                item["sub_item_id"],
                item.get("sub_item_name_snapshot"),
                jsonutil.dumps(item.get("params")),
                jsonutil.dumps(item.get("params_snapshot")),
                item.get("sort", index * 10),
            ),
        )


def submit_record(conn: sqlite3.Connection, record_id: int, *, user_id: int) -> dict[str, Any]:
    """draft → submitted。"""
    from app.core.clock import utc_timestamp_now

    record = get_record_or_raise(conn, record_id)
    if int(record["therapist_id"]) != user_id:
        raise Forbidden("只能提交自己的记录", details={"record_id": record_id})
    if record["status"] == STATUS_SUBMITTED:
        raise Conflict("该记录已提交", details={"record_id": record_id})
    if record["status"] == STATUS_LOCKED:
        raise Conflict("该记录已锁定", details={"record_id": record_id})

    # 提交时补算序次（草稿阶段没有序号），并**推进 revision**：
    # 离线客户端靠 revision 判断自己手上的副本是否过期；状态变了却不推进版本，
    # 客户端会一直以为自己的草稿版是最新的（阶段 4 的实测缺陷）。
    seq_no = record["seq_no"] or next_seq_no(conn, str(record["patient_no"]))
    conn.execute(
        "UPDATE treatment_record SET status = ?, submitted_at = ?, seq_no = ?, revision = revision + 1"
        " WHERE id = ?",
        (STATUS_SUBMITTED, utc_timestamp_now(), seq_no, record_id),
    )
    return get_record_or_raise(conn, record_id)


def lock_record(conn: sqlite3.Connection, record_id: int) -> dict[str, Any]:
    """submitted → locked（管理员操作）。"""
    from app.core.clock import utc_timestamp_now

    record = get_record_or_raise(conn, record_id)
    if record["status"] == STATUS_LOCKED:
        raise Conflict("该记录已锁定", details={"record_id": record_id})
    if record["status"] == STATUS_DRAFT:
        raise Conflict("草稿不能直接锁定，请先提交", details={"record_id": record_id})
    conn.execute(
        "UPDATE treatment_record SET status = ?, locked_at = ?, revision = revision + 1 WHERE id = ?",
        (STATUS_LOCKED, utc_timestamp_now(), record_id),
    )
    return get_record_or_raise(conn, record_id)


def delete_draft(conn: sqlite3.Connection, record_id: int, *, user_id: int) -> None:
    """只允许删除自己的草稿——已提交的记录是医疗文书，不能删。"""
    record = get_record_or_raise(conn, record_id)
    if int(record["therapist_id"]) != user_id:
        raise Forbidden("只能删除自己的记录", details={"record_id": record_id})
    if record["status"] != STATUS_DRAFT:
        raise Conflict(
            "只有草稿可以删除；已提交的记录是医疗文书，请用修改留痕",
            details={"record_id": record_id, "status": record["status"]},
        )
    conn.execute("DELETE FROM record_item WHERE record_id = ?", (record_id,))
    conn.execute("DELETE FROM treatment_record WHERE id = ?", (record_id,))


__all__ = [
    "EDITABLE_BY_OWNER",
    "ITEM_COLUMNS",
    "PERIODS",
    "RECORD_COLUMNS",
    "STATUSES",
    "STATUS_DRAFT",
    "STATUS_LOCKED",
    "STATUS_SUBMITTED",
    "create_record",
    "delete_draft",
    "get_record",
    "get_record_or_raise",
    "last_params_for_sub_item",
    "list_items",
    "list_records",
    "lock_record",
    "next_seq_no",
    "submit_record",
    "update_record",
]
