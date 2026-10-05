"""治疗记录数据访问与状态机（SOAP 模板驱动，迁移 011 之后的新模型）。

## 记录长什么样

一条记录只有两样「内容」：

- `body_json`     结构化答案 `{field_key: value}` —— 用于回显、预填、复查；
- `rendered_text` **生成那一刻**渲染出来的 SOAP 纯文本 —— 用于打印与归档。

★ `rendered_text` **冻结保存**，不在打印时从模板 JSON 重算：用户以后会手改模板，
而病历是法律文书，旧病历的措辞不该跟着变（理由见 `011_record_soap_model.sql`）。

评估文书（首评/复评/出院小结）与日常记录是**并存的独立文书**：

| 形态 | `seq_no` | `span_seq` | 计入治疗次数 |
|---|---|---|---|
| `daily` | 第几次**日常**（必填） | NULL | **是** |
| `initial` / `reassessment` | NULL | 挂靠的日常序号（1 / 21 / 41…） | 否 |
| `discharge` | NULL | NULL | 否 |

次数与门禁规则全部来自 `app/services/record_template.py`（**唯一实现**，
App 与后端共用同一份判定），本模块只负责把它接到数据库上。

## 三条硬阻断（用户 2026-10-05：「1A。2不能。3不能。」）

1. 记第 1 次日常前必须有首评；
2. 记第 21、41、61… 次日常前必须有对应区间的复评；
3. 待出院（`pending_discharge`）的患者不能再记新记录。

前两条抛 `Conflict`（409，`details.missing_document`），第三条也抛 `Conflict`。

## 状态机

    draft（草稿）──submit──> submitted（已提交）──lock──> locked（已锁定）

- **草稿**：任意修改，**不留痕、不计 `edit_count`**；
- **已提交**：实质修改由**库层触发器**（`trg_record_edit_trace`）累加 `edit_count`；
- **已锁定**：治疗师不可再改；管理员可改（仍留痕）。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.core import jsonutil
from app.models.base import Conflict, Forbidden, Invalid, NotFound, row_to_dict
from app.services import record_template

STATUS_DRAFT = "draft"
STATUS_SUBMITTED = "submitted"
STATUS_LOCKED = "locked"
STATUSES = (STATUS_DRAFT, STATUS_SUBMITTED, STATUS_LOCKED)

# 允许被修改的状态（草稿与已提交都可改；已锁定只有管理员能改）
EDITABLE_BY_OWNER = (STATUS_DRAFT, STATUS_SUBMITTED)

# 形态与日常计数规则由模板层定义（不在本模块重复一份）
KINDS = record_template.KINDS
ASSESSMENT_KINDS = tuple(k for k in KINDS if k != "daily")

# 同一患者 + 同一天 + 同一大类 **至多 2 条**（用户 2026-10-05 明确要求）
MAX_SAME_DAY_RECORDS = 2

COLUMN_NAMES = (
    "id",
    "patient_no",
    "therapist_id",
    "record_date",
    "discipline",
    "kind",
    "seq_no",
    "span_seq",
    "body_json",
    "rendered_text",
    "note",
    "status",
    "edit_count",
    "locked_at",
    "created_at",
    "submitted_at",
    "updated_at",
    "revision",
    "client_uuid",
)


def record_columns(alias: str = "") -> str:
    """统一列清单（带 `body_json` / `rendered_text`）。

    所有查询都从这里拼列名：曾经出现过"列表少查了一列、详情多查了一列"的漂移，
    而 `body` 缺失时前端只会安静地显示成空表单。
    """
    prefix = f"{alias}." if alias else ""
    return ", ".join(f"{prefix}{name}" for name in COLUMN_NAMES)


def temporary_expr(alias: str = "") -> str:
    """生成「是否临时治疗」的 SQL 表达式（`AS is_temporary`）。

    语义：**记录人不是该患者在当时（记录创建时刻）的归属治疗师**。

    为什么要在查询时重建而不能"看当前归属"：治疗师会换、患者会转手，
    用当前归属去判断历史记录，等于"回头把旧账按今天的归属重算" ——
    那些本来正常的记录会突然变成"临时"，已经计过的统计也会变。
    `patient_assignment_history` 每次归属变更都留了痕（谁→谁、何时），
    所以"当时是谁"是可以准确回溯的。

    归零安全：拿不到历史（该患者从未有过归属变更记录，或历史早于记录时间）
    时视为**非临时**，与"患者当时无人负责"的事实一致（谁做都算正常）。

    ★ 它**不查任何已删除的表**（`temporary_assignment` 早已不存在）——
    只用 `patient_assignment_history` 与记录自身两列。
    """
    p = f"{alias}." if alias else ""
    latest = (
        "   SELECT h.to_therapist_id FROM patient_assignment_history h"
        f"   WHERE h.patient_no = {p}patient_no"
        f"     AND h.created_at <= {p}created_at"
        "   ORDER BY h.created_at DESC, h.id DESC LIMIT 1"
    )
    return f" CASE WHEN ({latest}) IS NOT NULL AND ({latest}) <> {p}therapist_id THEN 1 ELSE 0 END AS is_temporary"


# --------------------------------------------------------------------------- #
# 模板与规则（薄封装，规则本身在 record_template.py）
# --------------------------------------------------------------------------- #
def _discipline_keys() -> list[str]:
    return [str(d["key"]) for d in record_template.load_disciplines()]


def discipline_name(discipline: str) -> str:
    for item in record_template.load_disciplines():
        if item["key"] == discipline:
            return str(item["name"])
    raise Invalid("未知的康复大类", details={"discipline": discipline})


def discipline_options() -> list[dict[str, Any]]:
    """四大类（`key` + 中文名），供枚举接口与 App 渲染选择器。"""
    return [
        {"key": str(d["key"]), "name": str(d["name"]), "order": d.get("order", 99)}
        for d in record_template.load_disciplines()
    ]


def load_template(discipline: str, kind: str) -> record_template.Template:
    """取模板；未知大类/形态统一转成 422（而不是 500 或模板层的裸异常）。"""
    if discipline not in _discipline_keys():
        raise Invalid(
            "未知的康复大类",
            details={"discipline": discipline, "allowed": _discipline_keys()},
        )
    if kind not in KINDS:
        raise Invalid("未知的记录形态", details={"kind": kind, "allowed": list(KINDS)})
    try:
        return record_template.load(discipline, kind)
    except record_template.TemplateError as exc:
        raise Invalid("模板不可用", details={"discipline": discipline, "kind": kind, "reason": str(exc)}) from exc


# --------------------------------------------------------------------------- #
# 次数、区间与门禁
# --------------------------------------------------------------------------- #
def daily_count(
    conn: sqlite3.Connection,
    patient_no: str,
    discipline: str,
    *,
    statuses: tuple[str, ...] | None = None,
) -> int:
    """该患者在该大类下的日常记录条数（不含评估文书）。

    `statuses=None` 表示**不分状态全算** —— 编号必须这样算：
    库层 `CHECK ((kind = 'daily') = (seq_no IS NOT NULL))` 与唯一索引
    `ux_record_daily_seq` 都要求日常记录一落库就带序号，所以草稿也占号。
    """
    sql = "SELECT COUNT(*) FROM treatment_record WHERE patient_no = ? AND discipline = ? AND kind = 'daily'"
    params: list[Any] = [patient_no, discipline]
    if statuses:
        sql += f" AND status IN ({', '.join('?' for _ in statuses)})"
        params.extend(statuses)
    return int(conn.execute(sql, params).fetchone()[0])


def next_daily_seq(conn: sqlite3.Connection, patient_no: str, discipline: str) -> int:
    """下一次日常记录的序号（第几次日常）。"""
    return daily_count(conn, patient_no, discipline) + 1


def has_initial(conn: sqlite3.Connection, patient_no: str, discipline: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM treatment_record WHERE patient_no = ? AND discipline = ? AND kind = 'initial' LIMIT 1",
        (patient_no, discipline),
    ).fetchone()
    return row is not None


def reassessment_spans(conn: sqlite3.Connection, patient_no: str, discipline: str) -> set[int]:
    """该大类已存在的复评所挂靠的日常序号集合。"""
    rows = conn.execute(
        "SELECT span_seq FROM treatment_record"
        " WHERE patient_no = ? AND discipline = ? AND kind = 'reassessment' AND span_seq IS NOT NULL",
        (patient_no, discipline),
    ).fetchall()
    return {int(r["span_seq"]) for r in rows}


def pending_document(conn: sqlite3.Connection, patient_no: str, discipline: str, next_seq: int) -> str | None:
    """记第 `next_seq` 次日常之前还缺哪份评估文书（None = 可以记）。"""
    return record_template.next_session_gate(
        next_seq,
        has_initial=has_initial(conn, patient_no, discipline),
        reassessment_spans=reassessment_spans(conn, patient_no, discipline),
    )


def pending_document_label(kind: str | None) -> str | None:
    return None if kind is None else record_template.KIND_LABELS.get(kind, kind)


def count_sessions(conn: sqlite3.Connection, patient_no: str, discipline: str) -> int:
    """真正"治疗了几次"：只算已提交/已锁定的日常记录（评估文书不计数）。"""
    return daily_count(
        conn, patient_no, discipline, statuses=(STATUS_SUBMITTED, STATUS_LOCKED)
    )


def record_for_span(
    conn: sqlite3.Connection, patient_no: str, discipline: str, kind: str, span_seq: int
) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {record_columns()} FROM treatment_record"
        " WHERE patient_no = ? AND discipline = ? AND kind = ? AND span_seq = ? LIMIT 1",
        (patient_no, discipline, kind, span_seq),
    ).fetchone()
    return _with_body(row_to_dict(row))


def find_daily_record(
    conn: sqlite3.Connection,
    patient_no: str,
    discipline: str,
    record_date: str,
    *,
    status: str | None = None,
) -> dict[str, Any] | None:
    sql = (
        f"SELECT {record_columns()} FROM treatment_record"
        " WHERE patient_no = ? AND discipline = ? AND kind = 'daily' AND record_date = ?"
    )
    params: list[Any] = [patient_no, discipline, record_date]
    if status is not None:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY id DESC LIMIT 1"
    return _with_body(row_to_dict(conn.execute(sql, params).fetchone()))


def same_day_records(
    conn: sqlite3.Connection, patient_no: str, discipline: str, record_date: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, kind, status, seq_no, span_seq FROM treatment_record"
        " WHERE patient_no = ? AND discipline = ? AND record_date = ? ORDER BY id",
        (patient_no, discipline, record_date),
    ).fetchall()
    return [dict(r) for r in rows]


def last_daily_body(conn: sqlite3.Connection, patient_no: str, discipline: str) -> dict[str, Any] | None:
    """该大类**上一次日常记录**的 body（预填「本次训练项目」用）。"""
    row = conn.execute(
        "SELECT body_json FROM treatment_record"
        " WHERE patient_no = ? AND discipline = ? AND kind = 'daily'"
        " ORDER BY record_date DESC, id DESC LIMIT 1",
        (patient_no, discipline),
    ).fetchone()
    if row is None:
        return None
    return jsonutil.loads(row["body_json"], {}) or {}


def last_assessment_body(conn: sqlite3.Connection, patient_no: str, discipline: str) -> dict[str, Any] | None:
    """该大类**上一次评估**（首评或上次复评）的 body（复评/出院小结预填用）。"""
    row = conn.execute(
        "SELECT body_json FROM treatment_record"
        " WHERE patient_no = ? AND discipline = ? AND kind IN ('initial', 'reassessment')"
        " ORDER BY COALESCE(span_seq, 0) DESC, record_date DESC, id DESC LIMIT 1",
        (patient_no, discipline),
    ).fetchone()
    if row is None:
        return None
    return jsonutil.loads(row["body_json"], {}) or {}


# --------------------------------------------------------------------------- #
# 查询
# --------------------------------------------------------------------------- #
def _with_body(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if data is None:
        return None
    data["body"] = jsonutil.loads(data.get("body_json"), {}) or {}
    data["discipline_name"] = discipline_name(str(data["discipline"]))
    data["kind_label"] = record_template.KIND_LABELS.get(str(data["kind"]), str(data["kind"]))
    return data


def get_record(conn: sqlite3.Connection, record_id: int) -> dict[str, Any] | None:
    """取单条记录：统一列 + 解析后的 `body` + 患者/治疗师姓名 + `is_temporary`。"""
    row = conn.execute(
        f"SELECT {record_columns('r')}, {temporary_expr('r')},"
        " p.name AS patient_name, u.name AS therapist_name"
        " FROM treatment_record r"
        " JOIN patient p ON p.inpatient_no = r.patient_no"
        " JOIN user u ON u.id = r.therapist_id"
        " WHERE r.id = ?",
        (record_id,),
    ).fetchone()
    return _with_body(row_to_dict(row))


def get_record_or_raise(conn: sqlite3.Connection, record_id: int) -> dict[str, Any]:
    record = get_record(conn, record_id)
    if record is None:
        raise NotFound("治疗记录不存在", details={"record_id": record_id})
    return record


def list_records(
    conn: sqlite3.Connection,
    *,
    patient_nos: list[str] | None = None,
    therapist_id: int | None = None,
    discipline: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    patient_no: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """列记录：按 `record_date DESC, id DESC` 排序，返回 `(items, total)`。

    ``patient_nos`` 是调用方算好的"我能看到哪些患者"（`None` = 不限制，管理员）。
    """
    where: list[str] = []
    params: list[Any] = []
    if patient_no:
        where.append("r.patient_no = ?")
        params.append(patient_no)
    if therapist_id is not None:
        where.append("r.therapist_id = ?")
        params.append(therapist_id)
    if discipline:
        where.append("r.discipline = ?")
        params.append(discipline)
    if kind:
        where.append("r.kind = ?")
        params.append(kind)
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
            return [], 0  # 没有可见患者时直接短路，避免拼出 IN ()
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
        f"SELECT {record_columns('r')}, {temporary_expr('r')},"
        " p.name AS patient_name, u.name AS therapist_name"
        f" {base}"
        " ORDER BY r.record_date DESC, r.id DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    items = [_with_body(dict(r)) for r in rows]
    for item in items:
        item["rendered_excerpt"] = rendered_excerpt(str(item.get("rendered_text") or ""))
    return items, total


def rendered_excerpt(text: str, *, limit: int = 80) -> str:
    """列表用的 SOAP 摘要：跳过标题行，取第一段正文。"""
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("治疗日期") and "：" in line:
            return line if len(line) <= limit else line[: limit - 1] + "…"
    return ""


# --------------------------------------------------------------------------- #
# 写入
# --------------------------------------------------------------------------- #
def _assert_status(status: str) -> None:
    if status not in STATUSES:
        raise Invalid(f"记录状态非法：{status}", details={"status": status, "allowed": list(STATUSES)})


def _assert_transition(old: str, new: str) -> None:
    """只允许向前推进的状态迁移（草稿 → 已提交 → 已锁定）。"""
    if new == old:
        return
    allowed = {STATUS_DRAFT: (STATUS_SUBMITTED,), STATUS_SUBMITTED: (STATUS_LOCKED,), STATUS_LOCKED: ()}
    if new not in allowed.get(old, ()):
        raise Conflict(
            "记录状态不能这样变更",
            details={"record_id": None, "from": old, "to": new, "allowed": list(allowed.get(old, ()))},
        )


def _assert_editable(record: dict[str, Any], *, user_id: int, is_admin: bool) -> None:
    if record["status"] != STATUS_LOCKED:
        return
    if not is_admin:
        raise Forbidden(
            "该记录已锁定，治疗师不能再修改",
            code="RECORD_LOCKED",
            details={"record_id": record["id"]},
        )


def _patient_status(conn: sqlite3.Connection, patient_no: str) -> str:
    row = conn.execute("SELECT status FROM patient WHERE inpatient_no = ?", (patient_no,)).fetchone()
    if row is None:
        raise NotFound("患者不存在", details={"inpatient_no": patient_no})
    return str(row["status"])


def _assert_same_day_limit(
    conn: sqlite3.Connection, *, patient_no: str, discipline: str, record_date: str
) -> None:
    """同一患者 + 同一天 + 同一大类至多 2 条（用户 2026-10-05 明确要求）。"""
    count = int(
        conn.execute(
            "SELECT COUNT(*) FROM treatment_record"
            " WHERE patient_no = ? AND discipline = ? AND record_date = ?",
            (patient_no, discipline, record_date),
        ).fetchone()[0]
    )
    if count >= MAX_SAME_DAY_RECORDS:
        raise Conflict(
            f"同一天同一大类至多 {MAX_SAME_DAY_RECORDS} 条记录",
            details={"limit": MAX_SAME_DAY_RECORDS, "date": record_date, "discipline": discipline},
        )


def _resolve_placement(
    conn: sqlite3.Connection, *, patient_no: str, discipline: str, kind: str, record_date: str
) -> tuple[int | None, int | None]:
    """算出该记录应有的 `(seq_no, span_seq)`，并在需要时执行**硬阻断门禁**。

    - `daily`：序号 = 已有日常数 + 1；记之前必须先有首评/对应复评（缺 → 409）
    - `initial` / `reassessment`：挂到"下一个日常序号"对应的评估区间上
    - `discharge`：两者都为 NULL（出院小结不占次数、不挂区间）
    """
    if kind == "discharge":
        return None, None

    next_seq = next_daily_seq(conn, patient_no, discipline)

    if kind == "daily":
        missing = pending_document(conn, patient_no, discipline, next_seq)
        if missing is not None:
            # ★ 硬阻断：评估文书不能跳过（用户：「1A。2不能。3不能。」）
            raise Conflict(
                f"第 {next_seq} 次日常记录前必须先完成{record_template.KIND_LABELS.get(missing, missing)}",
                code="MISSING_ASSESSMENT",
                details={
                    "missing_document": missing,
                    "missing_document_label": pending_document_label(missing),
                    "next_seq": next_seq,
                    "discipline": discipline,
                },
            )
        return next_seq, None

    span_seq = record_template.assessment_span_seq(next_seq)
    taken = conn.execute(
        "SELECT id FROM treatment_record"
        " WHERE patient_no = ? AND discipline = ? AND kind = ? AND span_seq = ? LIMIT 1",
        (patient_no, discipline, kind, span_seq),
    ).fetchone()
    if taken is not None:
        raise Conflict(
            f"该区间（第 {span_seq} 次日常）已有{record_template.KIND_LABELS.get(kind, kind)}",
            code="ASSESSMENT_ALREADY_EXISTS",
            details={
                "kind": kind,
                "span_seq": span_seq,
                "record_id": int(taken["id"]),
                "discipline": discipline,
            },
        )
    return None, span_seq


def _render(
    conn: sqlite3.Connection,
    template: record_template.Template,
    body: dict[str, Any],
    *,
    record_date: str,
    seq_no: int | None,
    patient_no: str,
    discipline: str,
) -> str:
    total_sessions = None
    if template.kind == "discharge":
        total_sessions = count_sessions(conn, patient_no, discipline)
    return record_template.render(
        template,
        body,
        record_date=record_date,
        seq_no=seq_no,
        total_sessions=total_sessions,
    )


def create_record(
    conn: sqlite3.Connection,
    *,
    patient_no: str,
    therapist_id: int,
    record_date: str,
    discipline: str,
    kind: str,
    body: dict[str, Any] | None = None,
    status: str = STATUS_DRAFT,
    client_uuid: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """新建记录（草稿或直接提交）。

    校验顺序（先便宜后昂贵，且**先查权限与状态**再谈内容）：

    1. 状态枚举；
    2. 患者存在且**不是待出院**（待出院不能再记新记录 → 409）；
    3. 模板可加载；
    4. 同一天同一大类至多 2 条（→ 409）；
    5. 必填字段校验（→ 422，`details.missing` 给出缺失字段的中文标签）；
    6. 门禁与序号（缺评估文书 → 409，`details.missing_document`）。
    """
    from app.core.clock import utc_timestamp_now

    _assert_status(status)
    answers = dict(body or {})
    if not isinstance(answers, dict):  # pragma: no cover - pydantic 已保证类型
        raise Invalid("body 必须是对象", details={"type": type(body).__name__})

    patient_status = _patient_status(conn, patient_no)
    if patient_status == "pending_discharge":
        # ★ 硬阻断：待出院患者不能再产生新的治疗文书
        raise Conflict(
            "该患者已提交出院小结，处于待出院状态，不能再记新记录",
            code="PATIENT_PENDING_DISCHARGE",
            details={"inpatient_no": patient_no, "status": patient_status},
        )

    template = load_template(discipline, kind)

    missing = record_template.validate_answers(template, answers)
    if missing:
        raise Invalid("必填项缺失", details={"missing": missing, "discipline": discipline, "kind": kind})

    _assert_same_day_limit(
        conn, patient_no=patient_no, discipline=discipline, record_date=record_date
    )
    seq_no, span_seq = _resolve_placement(
        conn, patient_no=patient_no, discipline=discipline, kind=kind, record_date=record_date
    )

    rendered = _render(
        conn,
        template,
        answers,
        record_date=record_date,
        seq_no=seq_no,
        patient_no=patient_no,
        discipline=discipline,
    )
    submitted_at = utc_timestamp_now() if status in (STATUS_SUBMITTED, STATUS_LOCKED) else None
    locked_at = utc_timestamp_now() if status == STATUS_LOCKED else None

    cur = conn.execute(
        "INSERT INTO treatment_record"
        " (patient_no, therapist_id, record_date, discipline, kind, seq_no, span_seq,"
        "  body_json, rendered_text, note, status, locked_at, submitted_at, client_uuid)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            patient_no,
            therapist_id,
            record_date,
            discipline,
            kind,
            seq_no,
            span_seq,
            jsonutil.dumps(answers),
            rendered,
            note,
            status,
            locked_at,
            submitted_at,
            client_uuid,
        ),
    )
    return get_record_or_raise(conn, int(cur.lastrowid))


def update_record(
    conn: sqlite3.Connection,
    record_id: int,
    *,
    user_id: int,
    is_admin: bool = False,
    body: dict[str, Any] | None = None,
    status: str | None = None,
    record_date: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """修改记录。留痕与 `edit_count` 由库层触发器负责（status <> 'draft' 时生效）。

    改了 `body`（或日期）就**重新渲染** `rendered_text` —— 冻结的是"生成时"的文本，
    不是"永不更新"的文本；治疗师在当前这条记录上改内容，打印出来当然要跟着变。
    """
    record = get_record_or_raise(conn, record_id)
    _assert_editable(record, user_id=user_id, is_admin=is_admin)

    new_status = record["status"] if status is None else status
    _assert_status(new_status)
    if status is not None:
        try:
            _assert_transition(str(record["status"]), new_status)
        except Conflict as exc:
            exc.details["record_id"] = record_id
            raise

    if body is not None and not isinstance(body, dict):
        raise Invalid("body 必须是对象", details={"type": type(body).__name__})

    template = load_template(str(record["discipline"]), str(record["kind"]))
    answers = dict(record["body"]) if body is None else dict(body)

    # 必填只在"这份文书要成为正式文书"时强制：草稿允许边写边存。
    if new_status != STATUS_DRAFT:
        missing = record_template.validate_answers(template, answers)
        if missing:
            raise Invalid(
                "必填项缺失",
                details={"missing": missing, "discipline": record["discipline"], "kind": record["kind"]},
            )

    next_date = str(record_date or record["record_date"])
    content_changed = body is not None or next_date != record["record_date"]

    sets: list[str] = []
    params: list[Any] = []
    if body is not None:
        sets.append("body_json = ?")
        params.append(jsonutil.dumps(answers))
    if record_date is not None:
        sets.append("record_date = ?")
        params.append(next_date)
    # `note` 是**记录级**的自由备注（与模板里的 `extra_note` 字段不同 ——
    # 那个进 body_json、是文书内容的一部分；这个是记录上的附加说明）。
    #
    # ★ 2026-10-05 修 bug：`RecordUpdateRequest` 一直收着 `note`，但这里没有该参数、
    #   路由也没往下传 → 「改备注」**永远静默无效**（不报错也不生效）。
    #   收了就必须生效，不能假装成功。
    if note is not None:
        sets.append("note = ?")
        params.append(note)
    if status is not None:
        sets.append("status = ?")
        params.append(new_status)
        if new_status == STATUS_SUBMITTED and not record.get("submitted_at"):
            sets.append("submitted_at = ?")
            params.append(_now())
        if new_status == STATUS_LOCKED and not record.get("locked_at"):
            sets.append("locked_at = ?")
            params.append(_now())
    if content_changed:
        rendered = _render(
            conn,
            template,
            answers,
            record_date=next_date,
            seq_no=record["seq_no"],
            patient_no=str(record["patient_no"]),
            discipline=str(record["discipline"]),
        )
        sets.append("rendered_text = ?")
        params.append(rendered)

    if sets:
        # 推进 revision：离线客户端靠它判断手上的副本是否过期。
        sets.append("revision = revision + 1")
        conn.execute(
            f"UPDATE treatment_record SET {', '.join(sets)} WHERE id = ?", (*params, record_id)
        )
    return get_record_or_raise(conn, record_id)


def _now() -> str:
    from app.core.clock import utc_timestamp_now

    return utc_timestamp_now()


def submit_record(conn: sqlite3.Connection, record_id: int, *, user_id: int) -> dict[str, Any]:
    """draft → submitted。"""
    record = get_record_or_raise(conn, record_id)
    if int(record["therapist_id"]) != user_id:
        raise Forbidden("只能提交自己的记录", details={"record_id": record_id})
    if record["status"] == STATUS_SUBMITTED:
        raise Conflict("该记录已提交", details={"record_id": record_id})
    if record["status"] == STATUS_LOCKED:
        raise Conflict("该记录已锁定", details={"record_id": record_id})

    conn.execute(
        "UPDATE treatment_record SET status = ?, submitted_at = ?, revision = revision + 1 WHERE id = ?",
        (STATUS_SUBMITTED, _now(), record_id),
    )
    return get_record_or_raise(conn, record_id)


def lock_record(conn: sqlite3.Connection, record_id: int) -> dict[str, Any]:
    """submitted → locked（管理员操作）。"""
    record = get_record_or_raise(conn, record_id)
    if record["status"] == STATUS_LOCKED:
        raise Conflict("该记录已锁定", details={"record_id": record_id})
    if record["status"] == STATUS_DRAFT:
        raise Conflict("草稿不能直接锁定，请先提交", details={"record_id": record_id})
    conn.execute(
        "UPDATE treatment_record SET status = ?, locked_at = ?, revision = revision + 1 WHERE id = ?",
        (STATUS_LOCKED, _now(), record_id),
    )
    return get_record_or_raise(conn, record_id)


def delete_draft(conn: sqlite3.Connection, record_id: int, *, user_id: int) -> None:
    """只允许删除自己的草稿——已提交的记录是医疗文书，不能删。

    注意：日常记录的序号**不会重排**。删掉"第 5 次"的草稿后，后面的记录仍是
    第 6、7… 次 —— 序号是刻在文书上的历史，重排会让已经打印/导出过的记录对不上号。
    """
    record = get_record_or_raise(conn, record_id)
    if int(record["therapist_id"]) != user_id:
        raise Forbidden("只能删除自己的记录", details={"record_id": record_id})
    if record["status"] != STATUS_DRAFT:
        raise Conflict(
            "只有草稿可以删除；已提交的记录是医疗文书，请用修改留痕",
            details={"record_id": record_id, "status": record["status"]},
        )
    conn.execute("DELETE FROM treatment_record WHERE id = ?", (record_id,))


def submitted_discharge_summary(
    conn: sqlite3.Connection, patient_no: str, record_id: int
) -> dict[str, Any]:
    """校验「这份记录确实是该患者**已提交**的出院小结」（出院流程的入口条件）。"""
    record = get_record_or_raise(conn, record_id)
    if str(record["patient_no"]) != patient_no:
        raise Invalid("该记录不属于此患者", details={"record_id": record_id, "inpatient_no": patient_no})
    if record["kind"] != "discharge":
        raise Invalid("只有出院小结可以发起出院", details={"record_id": record_id, "kind": record["kind"]})
    if record["status"] not in (STATUS_SUBMITTED, STATUS_LOCKED):
        raise Conflict(
            "出院小结尚未提交", details={"record_id": record_id, "status": record["status"]}
        )
    return record


__all__ = [
    "ASSESSMENT_KINDS",
    "COLUMN_NAMES",
    "EDITABLE_BY_OWNER",
    "KINDS",
    "MAX_SAME_DAY_RECORDS",
    "STATUSES",
    "STATUS_DRAFT",
    "STATUS_LOCKED",
    "STATUS_SUBMITTED",
    "count_sessions",
    "create_record",
    "daily_count",
    "delete_draft",
    "discipline_name",
    "discipline_options",
    "find_daily_record",
    "get_record",
    "get_record_or_raise",
    "has_initial",
    "last_assessment_body",
    "last_daily_body",
    "list_records",
    "load_template",
    "lock_record",
    "next_daily_seq",
    "pending_document",
    "pending_document_label",
    "reassessment_spans",
    "record_columns",
    "record_for_span",
    "rendered_excerpt",
    "same_day_records",
    "submit_record",
    "submitted_discharge_summary",
    "temporary_expr",
    "update_record",
]
