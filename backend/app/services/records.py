"""治疗记录表单组装（SOAP 模板驱动，迁移 011 之后的新模型）。

`GET /api/v1/records/form` 的全部业务逻辑都在这里：**只读**，不写库。

## 它回答 App 的四个问题

1. **这次该填哪种文书？** —— 按"该大类已有多少次日常"问
   `record_template.next_session_gate()`：缺首评/复评时 `kind` 直接取那份评估文书
   （用户：「先弹评估文书」），并把它放进 `pending_document` 让界面能提示。
2. **序号是几？** —— `next_seq`（第几次日常）、`total_daily`、`sessions_until_reassessment`。
3. **要预填什么？** —— 评估文书取**上一次评估**的 body（`last_assessment`），
   日常记录取**上次日常**的 body（`last_daily`），同一天同形态已有 1 条时取那一条
   （`same_day_first`）。`prefill_source` 逐个字段说明"这个值是哪来的"。
4. **是不是已经在填了？** —— `existing` 返回已存在的那条记录，App 据此**继续编辑**
   而不是重复新建。

> ⚠ 关于 `same_day_first` 的一个判断：模板里四个形态的字段 `key` 并不通用
> （首评 S 段的 `complaint` 是「自觉症状」，日常 S 段的 `complaint` 是「主诉」，
> 选项集合完全不同）。所以这里只在**同一天同大类同形态**已有 1 条时才套用它的内容 ——
> 若把首评的 body 预填进当天日常记录，会带出不属于该字段选项的值（界面选不中、数据不干净）。
> 用户原话「自动预填第 1 条的内容」指的正是"同一天第 2 条日常"，与本实现一致。
"""

from __future__ import annotations

import sqlite3
from datetime import date as _date
from typing import Any

from app.models import patient as patient_model
from app.models import treatment as treatment_model
from app.models.base import Invalid
from app.services import record_template


def _has_value(value: Any) -> bool:
    """与渲染器同一套"填了才算填"的判断（这里刻意本地实现，不碰模板层的私有函数）。"""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple)):
        return any(_has_value(v) for v in value)
    return True


def _format_value(field: dict[str, Any], value: Any) -> str:
    """把答案格式化成可读片段（不带标签）。与渲染器的取值规则保持一致。"""
    if isinstance(value, (list, tuple)):
        return record_template.SEP_MULTI.join(str(v) for v in value if _has_value(v))
    if field.get("type") == "number":
        return f"{value}{field.get('unit') or ''}"
    return str(value).strip()


def _discharge_auto_summary(
    conn: sqlite3.Connection, *, patient_no: str, discipline: str, template: record_template.Template
) -> str | None:
    """出院小结「治疗过程汇总」的自动内容（`auto: latest_vs_initial`）。

    模板把这一项标成"自动生成，只读"，治疗师不该手打。这里做两件事：

    1. 住院期间共治疗 N 次（只算**已提交/已锁定**的日常记录，评估文书不占次数）；
    2. 与该大类**首评**相比，本次评估（上一次评估）里发生变化的 O 段项
       —— 例如「肌力MMT 下肢 2级→3级」。

    没有首评（或首评没有任何 O 段值）时只输出第 1 条，不编造对比。
    """
    field = template.field("summary")
    if field is None or field.get("auto") != "latest_vs_initial":
        return None

    total = treatment_model.count_sessions(conn, patient_no, discipline)
    parts = [f"住院期间共治疗 {total} 次"]

    latest = treatment_model.last_assessment_body(conn, patient_no, discipline)
    first = _initial_body(conn, patient_no, discipline)
    if latest and first:
        section = next((s for s in template.soap if s.get("key") == "o"), None)
        for item in (section or {}).get("fields", []):
            key = item["key"]
            before, after = first.get(key), latest.get(key)
            if not _has_value(before) or not _has_value(after) or before == after:
                continue
            parts.append(
                f"{item['label']} {_format_value(item, before)}→{_format_value(item, after)}"
            )
    return record_template.SEP_INLINE.join(parts)


def _initial_body(conn: sqlite3.Connection, patient_no: str, discipline: str) -> dict[str, Any] | None:
    from app.core import jsonutil

    row = conn.execute(
        "SELECT body_json FROM treatment_record"
        " WHERE patient_no = ? AND discipline = ? AND kind = 'initial'"
        " ORDER BY id LIMIT 1",
        (patient_no, discipline),
    ).fetchone()
    if row is None:
        return None
    return jsonutil.loads(row["body_json"], {}) or {}


def build_form(
    conn: sqlite3.Connection,
    *,
    patient_no: str,
    discipline: str,
    record_date: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    """组装一份"App 可以直接渲染"的记录表单（只读，见模块文档）。

    `kind` 传了就**强制**用这个形态（唯一用处是 `discharge`：出院是 App 上的显式动作，
    门禁永远推不出"该出院了"）；不传则按门禁自动决定。
    """
    on_date = record_date or _date.today().isoformat()
    patient = patient_model.get_patient_or_raise(conn, patient_no)
    if discipline not in [d["key"] for d in record_template.load_disciplines()]:
        raise Invalid(
            "未知的康复大类",
            details={"discipline": discipline, "allowed": [d["key"] for d in record_template.load_disciplines()]},
        )

    total_daily = treatment_model.daily_count(conn, patient_no, discipline)
    next_seq = total_daily + 1
    pending = treatment_model.pending_document(conn, patient_no, discipline, next_seq)

    # ★ 缺评估文书时，"这次该填的形态"就是那份文书（用户：先弹评估文书）
    if kind is None:
        kind = pending or "daily"
    elif kind not in treatment_model.KINDS:
        raise Invalid("未知的记录形态", details={"kind": kind, "allowed": list(treatment_model.KINDS)})
    template = treatment_model.load_template(discipline, kind)

    answers = record_template.blank_answers(template)

    # 预填的三种来源（只在有真实值时出现）
    same_day_first = _same_day_first_body(conn, patient_no, discipline, on_date, kind)
    last_daily = (
        treatment_model.last_daily_body(conn, patient_no, discipline) if kind == "daily" else None
    )
    last_assessment = (
        treatment_model.last_assessment_body(conn, patient_no, discipline)
        if kind in ("reassessment", "discharge")
        else None
    )

    prefill = record_template.apply_prefill(
        template,
        answers,
        last_assessment=last_assessment,
        last_daily=last_daily,
        same_day_first=same_day_first,
    )

    auto: dict[str, Any] = {}
    if kind == "discharge":
        summary = _discharge_auto_summary(
            conn, patient_no=patient_no, discipline=discipline, template=template
        )
        if summary:
            auto["summary"] = summary

    filled = {
        key: value
        for key, value in {**prefill, **auto}.items()
        if _has_value(value)
    }
    sources = {
        key: _prefill_source(template, key, same_day_first, last_assessment, last_daily, auto)
        for key in filled
    }

    span_seq = None
    if kind in ("initial", "reassessment"):
        span_seq = record_template.assessment_span_seq(next_seq)
    existing = _existing_record(
        conn, patient_no=patient_no, discipline=discipline, kind=kind, on_date=on_date, span_seq=span_seq
    )

    return {
        "patient": {
            "inpatient_no": patient["inpatient_no"],
            "name": patient["name"],
            "status": patient["status"],
        },
        "discipline": discipline,
        "discipline_name": treatment_model.discipline_name(discipline),
        "kind": kind,
        "kind_label": template.kind_label,
        "title": template.title,
        "next_seq": next_seq,
        "total_daily": total_daily,
        "sessions_until_reassessment": record_template.sessions_until_reassessment(next_seq),
        "pending_document": pending,
        "pending_document_label": treatment_model.pending_document_label(pending),
        "template_version": template.version,
        "soap": template.soap,
        "prefill": filled,
        "prefill_source": sources,
        "footer": list(template.footer),
        "existing": existing,
    }


def _same_day_first_body(
    conn: sqlite3.Connection, patient_no: str, discipline: str, on_date: str, kind: str
) -> dict[str, Any] | None:
    """同一天同大类同形态已有**恰好 1 条**时，返回它的 body（第 2 条自动预填）。"""
    rows = conn.execute(
        "SELECT id, status FROM treatment_record"
        " WHERE patient_no = ? AND discipline = ? AND kind = ? AND record_date = ?"
        " ORDER BY id",
        (patient_no, discipline, kind, on_date),
    ).fetchall()
    if len(rows) != 1:
        return None
    return treatment_model.get_record_or_raise(conn, int(rows[0]["id"]))["body"]


def _existing_record(
    conn: sqlite3.Connection,
    *,
    patient_no: str,
    discipline: str,
    kind: str,
    on_date: str,
    span_seq: int | None,
) -> dict[str, Any] | None:
    """已存在的那条（App 用来继续编辑，而不是重复新建）。

    - 评估文书：按 `span_seq` 找（首评挂 1、复评挂 21/41…，同一区间不可能有第二份）；
    - 日常记录：只在**当天那条还是草稿**时返回 —— 同一天允许两条日常记录
      （用户：「同一天同一大类至多 2 条」），所以已提交的那条不该拦着第 2 条新建，
      它只作为 `same_day_first` 的预填来源；
    - 出院小结：不挂区间、也不按日期，直接取最近一份（草稿要能接着写）。
    """
    if kind == "daily":
        return treatment_model.find_daily_record(
            conn, patient_no, discipline, on_date, status=treatment_model.STATUS_DRAFT
        )
    if kind == "discharge":
        row = conn.execute(
            "SELECT id FROM treatment_record"
            " WHERE patient_no = ? AND discipline = ? AND kind = 'discharge'"
            " ORDER BY id DESC LIMIT 1",
            (patient_no, discipline),
        ).fetchone()
        return None if row is None else treatment_model.get_record_or_raise(conn, int(row["id"]))
    if span_seq is None:
        return None
    return treatment_model.record_for_span(conn, patient_no, discipline, kind, span_seq)


def _prefill_source(
    template: record_template.Template,
    key: str,
    same_day_first: dict[str, Any] | None,
    last_assessment: dict[str, Any] | None,
    last_daily: dict[str, Any] | None,
    auto: dict[str, Any],
) -> str:
    """这个预填值是哪来的（界面可据此提示"带出上次内容"）。"""
    if key in auto:
        return "auto"
    if same_day_first and key in same_day_first:
        return "same_day_first"
    field = template.field(key) or {}
    strategy = field.get("prefill")
    if strategy == "last_assessment" and last_assessment and key in last_assessment:
        return "last_assessment"
    if strategy == "last_daily" and last_daily and key in last_daily:
        return "last_daily"
    return "none"


__all__ = ["build_form"]
