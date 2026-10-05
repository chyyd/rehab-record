"""汇总统计（阶段 5 / `设计.md` 3.8、3.9）。

汇总只统计**已提交与已锁定**的记录：草稿是治疗师还没写完的东西，
把它算进"今天治疗了多少人次"会误导排班与统计。

三种口径：

- ``summarize_date``：某一天全部治疗记录，可按治疗师或患者分组（3.8 按日期汇总）；
- ``summarize_patient_daily``：某患者逐日汇总（3.8 按患者每日汇总）；
- ``patient_overview``：单患者全部记录的汇总与统计（3.9 单患者汇总打印）。

三条查询共享同一段"把记录行转成展示行"的逻辑（`_fetch_rows`），
保证 PDF 与 JSON 汇总**口径一致** —— 两处各写一份 SQL 迟早会跑出不同的数字。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.core import jsonutil
from app.models import treatment as treatment_model
from app.models.base import Invalid

# 计入汇总的记录状态
COUNTED_STATUSES = ("submitted", "locked")


def _params_digest(params: dict[str, Any] | None, snapshot: list[dict[str, Any]] | None) -> str:
    """把参数揉成一行可读摘要，如「体位：坐位；侧别：左；次数：10」。

    优先用快照里的 `param_name`（当时的显示名），没有快照时退回 `param_key`，
    这样字典改名后历史汇总仍显示当时的名字。
    """
    if not params and not snapshot:
        return ""
    labels: dict[str, str] = {}
    units: dict[str, str] = {}
    for entry in snapshot or []:
        key = str(entry.get("param_key") or "")
        if key:
            labels[key] = str(entry.get("param_name") or key)
            if entry.get("unit"):
                units[key] = str(entry["unit"])

    parts: list[str] = []
    for key, value in (params or {}).items():
        if value in (None, "", [], {}):
            continue
        label = labels.get(key, key)
        if isinstance(value, list):
            shown = "、".join(str(v) for v in value)
        elif isinstance(value, bool):
            shown = "是" if value else "否"
        else:
            shown = str(value)
        unit = units.get(key, "")
        parts.append(f"{label}：{shown}{unit}")
    return "；".join(parts)


def _fetch_rows(
    conn: sqlite3.Connection,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    day: str | None = None,
    patient_no: str | None = None,
    therapist_id: int | None = None,
    patient_nos: list[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """取汇总用的原始行。一条记录展开成"每个子项目一行"，便于统计频次与展示参数。"""
    where = [f"r.status IN ({', '.join('?' for _ in COUNTED_STATUSES)})"]
    params: list[Any] = list(COUNTED_STATUSES)

    if day:
        where.append("r.record_date = ?")
        params.append(day)
    if date_from:
        where.append("r.record_date >= ?")
        params.append(date_from)
    if date_to:
        where.append("r.record_date <= ?")
        params.append(date_to)
    if patient_no:
        where.append("r.patient_no = ?")
        params.append(patient_no)
    if therapist_id is not None:
        where.append("r.therapist_id = ?")
        params.append(therapist_id)
    if patient_nos is not None:
        if not patient_nos:
            return []
        where.append(f"r.patient_no IN ({', '.join('?' for _ in patient_nos)})")
        params.extend(patient_nos)

    # 「临时治疗」= 记录人不是该患者**当时**的归属治疗师。
    # 归属人按 patient_assignment_history 回溯到记录创建时刻（见 temporary_expr）。
    sql = (
        "SELECT r.id AS record_id, r.record_date, r.session_period, r.seq_no, r.status,"
        " r.duration_min, r.note, r.patient_response_json,"
        + treatment_model.temporary_expr("r")
        + ","
        " r.patient_no, p.name AS patient_name, p.diagnosis,"
        " r.therapist_id, u.name AS therapist_name,"
        " ri.main_item_id, m.name AS main_item_name, m.sort AS main_sort,"
        " ri.sub_item_id, ri.sub_item_name_snapshot, ri.params_json, ri.params_snapshot_json,"
        " ri.sort AS item_sort"
        " FROM treatment_record r"
        " JOIN patient p ON p.inpatient_no = r.patient_no"
        " JOIN user u ON u.id = r.therapist_id"
        " LEFT JOIN record_item ri ON ri.record_id = r.id"
        " LEFT JOIN main_item m ON m.id = ri.main_item_id"
        f" WHERE {' AND '.join(where)}"
        " ORDER BY r.record_date, r.id, ri.sort"
    )
    if limit is not None:
        sql += f" LIMIT {int(limit)}"

    rows = conn.execute(sql, params).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        data["params"] = jsonutil.loads(data.pop("params_json", None), {}) or {}
        data["params_snapshot"] = jsonutil.loads(data.pop("params_snapshot_json", None), None)
        data["params_digest"] = _params_digest(data["params"], data["params_snapshot"])
        data["patient_response"] = jsonutil.loads(data.pop("patient_response_json", None), None)
        data["response_digest"] = _response_digest(data["patient_response"])
        out.append(data)
    return out


def _response_digest(response: Any) -> str:
    """把患者反应揉成一行，如「无不适 / 疼痛 3 分」。"""
    if not response or not isinstance(response, dict):
        return ""
    parts: list[str] = []
    for tag in response.get("tags") or []:
        parts.append(str(tag.get("label") or tag.get("code") or ""))
    for item in response.get("items") or []:
        label = str(item.get("label") or item.get("code") or "")
        value = item.get("value")
        unit = item.get("unit") or ""
        parts.append(f"{label} {value}{unit}".strip())
    return " / ".join(p for p in parts if p)


def _counter(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        name = row.get(key)
        if name:
            counts[str(name)] = counts.get(str(name), 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    record_ids = {int(r["record_id"]) for r in rows}
    return {
        "record_count": len(record_ids),
        "item_count": len(rows),
        "total_duration_min": sum(int(r["duration_min"] or 0) for r in rows),
        "patient_count": len({str(r["patient_no"]) for r in rows}),
        "main_item_counts": _counter(rows, "main_item_name"),
        "sub_item_counts": _counter(rows, "sub_item_name_snapshot"),
        "therapist_counts": _counter(rows, "therapist_name"),
    }


def summarize_date(
    conn: sqlite3.Connection,
    *,
    day: str,
    group_by: str = "therapist",
    therapist_id: int | None = None,
    patient_nos: list[str] | None = None,
) -> dict[str, Any]:
    """按日期汇总（`设计.md` 3.8）。``group_by`` 为 `therapist` 或 `patient`。"""
    if group_by not in ("therapist", "patient"):
        raise Invalid("group_by 只能是 therapist 或 patient", details={"group_by": group_by})

    rows = _fetch_rows(conn, day=day, therapist_id=therapist_id, patient_nos=patient_nos)
    key = "therapist_name" if group_by == "therapist" else "patient_name"

    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row.get(key) or "（未知）"), []).append(row)

    return {
        "date": day,
        "group_by": group_by,
        "totals": _totals(rows),
        "groups": [
            {"key": name, "totals": _totals(items), "rows": items}
            for name, items in sorted(groups.items())
        ],
    }


def summarize_patient_daily(
    conn: sqlite3.Connection,
    *,
    patient_no: str,
    date_from: str | None = None,
    date_to: str | None = None,
    user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按患者逐日汇总（`设计.md` 3.8 / 3.9）。每天一行，含参数与反应摘要。"""
    from app.models import patient as patient_model

    patient = patient_model.get_patient_or_raise(conn, patient_no)
    rows = _fetch_rows(conn, patient_no=patient_no, date_from=date_from, date_to=date_to)

    # 按"记录"聚合为每天一行：同一条记录的多个子项目合并进一天
    by_date: dict[str, dict[str, Any]] = {}
    for row in rows:
        day = str(row["record_date"])
        entry = by_date.setdefault(
            day,
            {
                "record_date": day,
                "session_periods": set(),
                "therapists": set(),
                "main_items": [],
                "sub_items": [],
                "params": [],
                "responses": set(),
                "notes": [],
                "duration_min": 0,
                "temporary": False,
            },
        )
        if row.get("session_period"):
            entry["session_periods"].add(str(row["session_period"]))
        if row.get("therapist_name"):
            entry["therapists"].add(str(row["therapist_name"]))
        if row.get("main_item_name") and row["main_item_name"] not in entry["main_items"]:
            entry["main_items"].append(str(row["main_item_name"]))
        if row.get("sub_item_name_snapshot") and row["sub_item_name_snapshot"] not in entry["sub_items"]:
            entry["sub_items"].append(str(row["sub_item_name_snapshot"]))
        if row.get("params_digest") and row["params_digest"] not in entry["params"]:
            entry["params"].append(str(row["params_digest"]))
        if row.get("response_digest"):
            entry["responses"].add(str(row["response_digest"]))
        if row.get("note"):
            entry["notes"].append(str(row["note"]))
        entry["duration_min"] += int(row["duration_min"] or 0)
        if row.get("is_temporary"):
            entry["temporary"] = True

    days: list[dict[str, Any]] = []
    for day in sorted(by_date, reverse=True):
        entry = by_date[day]
        days.append(
            {
                "record_date": day,
                "session_periods": sorted(entry["session_periods"]),
                "therapists": sorted(entry["therapists"]),
                "main_items": entry["main_items"],
                "sub_items": entry["sub_items"],
                "params": entry["params"],
                "responses": sorted(entry["responses"]),
                "notes": entry["notes"],
                "duration_min": entry["duration_min"],
                "temporary": entry["temporary"],
            }
        )
    return {
        "patient": {
            "inpatient_no": patient["inpatient_no"],
            "name": patient["name"],
            "diagnosis": patient["diagnosis"],
            "admin_note": patient["admin_note"],
        },
        "date_from": date_from,
        "date_to": date_to,
        "totals": _totals(rows),
        "days": days,
    }


def patient_overview(
    conn: sqlite3.Connection, *, patient_no: str, user: dict[str, Any] | None = None
) -> dict[str, Any]:
    """单患者汇总：基本信息 + 归属 + 全部记录 + 统计（`设计.md` 3.9）。"""
    from app.models import patient as patient_model

    patient = patient_model.get_patient_or_raise(conn, patient_no)
    rows = _fetch_rows(conn, patient_no=patient_no)

    # 按记录分组（一条记录可能含多个子项目）
    records: dict[int, dict[str, Any]] = {}
    for row in rows:
        record_id = int(row["record_id"])
        record = records.setdefault(
            record_id,
            {
                "record_no": len(records) + 1,
                "record_date": row["record_date"],
                "session_period": row.get("session_period"),
                "seq_no": row.get("seq_no"),
                "therapist_name": row.get("therapist_name"),
                "is_temporary": bool(row.get("is_temporary")),
                "duration_min": row.get("duration_min"),
                "note": row.get("note"),
                "response_digest": row.get("response_digest"),
                "items": [],
            },
        )
        record["items"].append(
            {
                "main_item_name": row.get("main_item_name"),
                "sub_item_name": row.get("sub_item_name_snapshot"),
                "params_digest": row.get("params_digest"),
            }
        )

    ordered = [records[key] for key in sorted(records, key=lambda k: str(records[k]["record_date"]))]
    for index, record in enumerate(ordered, start=1):
        record["record_no"] = index

    # 归属：原归属 + 当前可见归属（单日假期间会不同）
    assigned = patient.get("assigned_therapist_id")
    assigned_name = None
    if assigned is not None:
        therapist = conn.execute("SELECT name FROM user WHERE id = ?", (int(assigned),)).fetchone()
        assigned_name = therapist["name"] if therapist else None

    return {
        "patient": {
            "inpatient_no": patient["inpatient_no"],
            "name": patient["name"],
            "diagnosis": patient["diagnosis"],
            "admin_note": patient["admin_note"],
            "status": patient["status"],
            "assigned_therapist_id": assigned,
            "assigned_therapist_name": assigned_name,
            "visible_therapist_id": patient.get("visible_therapist_id"),
        },
        "totals": _totals(rows),
        "records": ordered,
    }


__all__ = [
    "COUNTED_STATUSES",
    "patient_overview",
    "summarize_date",
    "summarize_patient_daily",
]
