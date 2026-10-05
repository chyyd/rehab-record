"""汇总统计（阶段 5 / `设计.md` 3.8、3.9；2026-10-05 改为 SOAP 纯文本口径）。

## 口径（用户明确要求）

- **计数**：只算 `kind='daily'` 且 `status IN ('submitted','locked')` 的记录。
  首评/复评/出院小结是**独立文书**，不占治疗次数（`record_template.counts_as_session`）。
- **内容**：一律输出记录落库时**冻结**的 `rendered_text`（SOAP 纯文本），
  彻底不再拼「主项目 / 子项目 / 参数 / 患者反应」表格。

## 三种口径

- ``summarize_date``：某一天全部**日常**记录，可按治疗师或患者分组（3.8 按日期汇总）；
- ``summarize_patient_daily``：某患者逐日汇总（3.8 按患者每日汇总）——
  每天带回当天**所有文书**的 SOAP 文本（含首评/复评/出院小结），计数仍只算日常；
- ``patient_overview``：单患者全部文书 + 统计（3.9 单患者汇总打印）。

三条查询共享同一段取行逻辑（`_fetch_rows`），保证 PDF 与 JSON 汇总**口径一致**。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.models import treatment as treatment_model
from app.services import record_template

# 计入汇总的记录状态
COUNTED_STATUSES = ("submitted", "locked")
# 计入**次数**的形态：只有日常记录
COUNTED_KINDS = ("daily",)


def _row_to_public(row: dict[str, Any]) -> dict[str, Any]:
    """把数据库行整成对外的一行（含 SOAP 文本）。"""
    return {
        "record_id": int(row["record_id"]),
        "record_date": str(row["record_date"]),
        "patient_no": str(row["patient_no"]),
        "patient_name": row.get("patient_name"),
        "therapist_id": row.get("therapist_id"),
        "therapist_name": row.get("therapist_name"),
        "discipline": str(row["discipline"]),
        "discipline_name": treatment_model.discipline_name(str(row["discipline"])),
        "kind": str(row["kind"]),
        "kind_label": record_template.KIND_LABELS.get(str(row["kind"]), str(row["kind"])),
        "seq_no": row.get("seq_no"),
        "status": str(row["status"]),
        "note": row.get("note"),
        "rendered_text": str(row.get("rendered_text") or ""),
        "is_temporary": int(row.get("is_temporary") or 0),
    }


def _fetch_rows(
    conn: sqlite3.Connection,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    day: str | None = None,
    patient_no: str | None = None,
    therapist_id: int | None = None,
    patient_nos: list[str] | None = None,
    kinds: tuple[str, ...] = COUNTED_KINDS,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """取汇总用的行（**一条记录一行** —— SOAP 文本本来就是整条的）。

    `kinds` 默认只取日常记录（计数口径）；患者侧的打印用 `None` 表示"所有文书都要"。
    """
    where = [f"r.status IN ({', '.join('?' for _ in COUNTED_STATUSES)})"]
    params: list[Any] = list(COUNTED_STATUSES)

    if kinds:
        where.append(f"r.kind IN ({', '.join('?' for _ in kinds)})")
        params.extend(kinds)
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

    sql = (
        "SELECT r.id AS record_id, r.record_date, r.discipline, r.kind, r.seq_no, r.status,"
        " r.note, r.rendered_text,"
        + treatment_model.temporary_expr("r")
        + ","
        " r.patient_no, p.name AS patient_name,"
        " r.therapist_id, u.name AS therapist_name"
        " FROM treatment_record r"
        " JOIN patient p ON p.inpatient_no = r.patient_no"
        " JOIN user u ON u.id = r.therapist_id"
        f" WHERE {' AND '.join(where)}"
        " ORDER BY r.record_date, r.id"
    )
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return [_row_to_public(dict(row)) for row in conn.execute(sql, params).fetchall()]


def _counter(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        name = row.get(key)
        if name:
            counts[str(name)] = counts.get(str(name), 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """统计口径：只把 `kind='daily'` 的行算作"治疗次数"。"""
    daily = [row for row in rows if row["kind"] == "daily"]
    return {
        "record_count": len({int(r["record_id"]) for r in daily}),
        "patient_count": len({str(r["patient_no"]) for r in daily}),
        "therapist_counts": _counter(daily, "therapist_name"),
        "discipline_counts": _counter(daily, "discipline_name"),
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
    from app.models.base import Invalid

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
    """按患者逐日汇总：每天带回当天所有文书的 SOAP 纯文本（`设计.md` 3.8 / 3.9）。"""
    from app.models import patient as patient_model

    patient = patient_model.get_patient_or_raise(conn, patient_no)
    # 患者侧的打印要**完整**：首评/复评/出院小结也要出现在当天文本里（它们不计数）
    rows = _fetch_rows(conn, patient_no=patient_no, date_from=date_from, date_to=date_to, kinds=())

    by_date: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_date.setdefault(str(row["record_date"]), []).append(row)

    days: list[dict[str, Any]] = []
    for day in sorted(by_date, reverse=True):
        items = by_date[day]
        days.append(
            {
                "record_date": day,
                "record_count": len({r["record_id"] for r in items if r["kind"] == "daily"}),
                "therapists": sorted({str(r["therapist_name"]) for r in items if r.get("therapist_name")}),
                "disciplines": sorted({str(r["discipline_name"]) for r in items if r.get("discipline_name")}),
                "temporary": any(r.get("is_temporary") for r in items),
                "records": items,
                "texts": [r["rendered_text"] for r in items],
            }
        )
    return {
        "patient": {
            "inpatient_no": patient["inpatient_no"],
            "name": patient["name"],
            "diagnosis": patient["diagnosis"],
            "admin_note": patient["admin_note"],
            "status": patient["status"],
        },
        "date_from": date_from,
        "date_to": date_to,
        "totals": _totals(rows),
        "days": days,
    }


def patient_overview(
    conn: sqlite3.Connection, *, patient_no: str, user: dict[str, Any] | None = None
) -> dict[str, Any]:
    """单患者汇总：基本信息 + 归属 + 全部文书（SOAP 文本）+ 统计（`设计.md` 3.9）。"""
    from app.models import patient as patient_model

    patient = patient_model.get_patient_or_raise(conn, patient_no)
    rows = _fetch_rows(conn, patient_no=patient_no, kinds=())

    records: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        records.append(
            {
                "record_no": index,
                "record_id": row["record_id"],
                "record_date": row["record_date"],
                "discipline": row["discipline"],
                "discipline_name": row["discipline_name"],
                "kind": row["kind"],
                "kind_label": row["kind_label"],
                "seq_no": row["seq_no"],
                "status": row["status"],
                "therapist_name": row["therapist_name"],
                "is_temporary": bool(row["is_temporary"]),
                "note": row["note"],
                "rendered_text": row["rendered_text"],
            }
        )

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
        "records": records,
    }


__all__ = [
    "COUNTED_KINDS",
    "COUNTED_STATUSES",
    "patient_overview",
    "summarize_date",
    "summarize_patient_daily",
]
