"""阶段 3 端到端验证（**已重写**）：SOAP 模板记录。

## 为什么整个脚本被重写了

原阶段 3 验收的是「字典树 → 选项集解析 → 记录表单带入 → 两层快照 → 患者反应」。
2026-10-05 用户把治疗记录从**参数表格**改成 **SOAP 模板驱动**：
字典 / 选项集 / 患者反应定义六张表随迁移 012 删除，接口 `/dict/**`、`/option-sets*`、
`/response-defs*` 全部下线，原脚本的 35 项断言**全部失去对象**（必然失败）。

替换它的不是"删掉这个脚本"，而是**同一主题在新契约上的等价验收** ——
"记录页怎么把一次治疗变成一份文书"仍然是最核心的行为：

1. **表单是唯一数据源**：`GET /records/form` 一次回答"该填哪种形态 / 序号是几 /
   预填什么 / 是不是已在填"；缺评估文书时 `kind` 直接就是那份评估文书（先弹它）；
2. **首评不占日常次数**：建完首评后当天仍要有一条日常记录，且它是**第 1 次**；
3. **硬阻断**（用户原话「1A。2不能。3不能。」）：
   缺首评记日常 → 409；满 20 次日常后缺复评 → 409；
4. **每 20 次日常后复评**：补齐复评（`span_seq=21`）后第 21 次日常才放行；
5. **同一天同一大类至多 2 条** → 第 3 条 409；
6. **必填校验**：缺「功能诊断」「本次训练项目」→ 422（`details.missing` 给中文标签）；
7. **`rendered_text` 冻结落库**，且是 **SOAP 纯文本**（含「主观资料：」，不是表格）；
8. 状态机与留痕（草稿不留痕 → 提交后改动累加 `edit_count` → 锁定后治疗师不可改）；
9. 权限边界、时间轴、出院流程（任何治疗师可发起 → `pending_discharge` → 管理员确认或取消）。

    cd backend
    python scripts/verify_stage3.py
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn  # noqa: E402
from _e2e import purge_patients  # noqa: E402

HOST = "127.0.0.1"
ADMIN_PW = "Admin#2026pass"
THERAPIST_PW = "Ther#2026pass"

DISC = "PT"

# 首评的必填项（`templates/PT/initial.json`：A 段 `diagnosis` + P 段 `therapy_items`）
INITIAL_BODY = {
    "complaint": ["肢体无力"],
    "mmt_lower": 2,
    "sit_balance": "Ⅱ级",
    "diagnosis": ["偏瘫运动功能障碍"],
    "therapy_items": ["偏瘫肢体综合训练"],
    "goal_short": "坐位平衡达Ⅲ级",
}
# 日常记录：只需 `therapy_items` 必填；这里再给几项，让 SOAP 的 S/O/A 三段都真的输出
DAILY_BODY = {
    "mental": "良好",
    "complaint": ["乏力"],
    "vas": 2,
    "therapy_items": ["偏瘫肢体综合训练", "平衡功能训练"],
    "performance": "较前改善",
    "next_step": "继续维持原方案",
}

# 20 次日常排在这些日期上（同一天同一大类至多 2 条，所以必须一天一条）
DAILY_DATES = [f"2027-04-{day:02d}" for day in range(1, 21)]
DATE_21 = "2027-04-21"
DATE_DRAFT = "2027-04-22"

failures: list[str] = []


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


PORT = _free_port()
BASE = f"http://{HOST}:{PORT}"


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def request(path: str, method: str = "GET", body: dict | None = None, token: str | None = None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, method=method, data=data)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return exc.code, (json.loads(raw) if raw else None)


def q(**params: object) -> str:
    return "?" + urllib.parse.urlencode(params)


def post_record(
    token: str, patient_no: str, day: str, kind: str, body: dict, *, status: str = "draft"
) -> tuple[int, object]:
    return request(
        "/api/v1/records",
        "POST",
        {
            "patient_no": patient_no,
            "record_date": day,
            "discipline": DISC,
            "kind": kind,
            "body": body,
            "status": status,
        },
        token,
    )


def main() -> int:
    from app.core.config import get_settings
    from app.db import storage
    from app.main import create_app
    from app.models import patient as patient_model
    from app.models import user as user_model

    settings = get_settings()
    if not settings.db_path.exists():
        print(f"数据库不存在：{settings.db_path}（请先执行 app.cli init）", file=sys.stderr)
        return 2

    conn = storage.connect(settings)
    try:
        storage.migrate(conn, storage.discover_migrations(settings=settings))
        ids: dict[str, int] = {}
        for employee_no, name, role, pw in (
            ("A001", "科室管理员", user_model.ROLE_ADMIN, ADMIN_PW),
            ("T001", "张三", user_model.ROLE_THERAPIST, THERAPIST_PW),
            ("T002", "李四", user_model.ROLE_THERAPIST, THERAPIST_PW),
        ):
            existing = user_model.get_by_employee_no(conn, employee_no)
            if existing:
                user_model.set_password(conn, int(existing["id"]), pw)
                ids[employee_no] = int(existing["id"])
            else:
                created = user_model.create_user(
                    conn, employee_no=employee_no, name=name, role=role, password=pw
                )
                ids[employee_no] = int(created["id"])

        # 清理上次运行遗留（记录模板是 JSON 文件，没有需要清理的模板表）
        for no in ("S3A", "S3B"):
            purge_patients(conn, [no])

        patient_model.create_patient(
            conn, inpatient_no="S3A", name="阶段三患者甲", assigned_therapist_id=ids["T001"]
        )
        patient_model.create_patient(
            conn, inpatient_no="S3B", name="阶段三患者乙", assigned_therapist_id=ids["T002"]
        )
    finally:
        conn.close()

    config = uvicorn.Config(create_app(), host=HOST, port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.2)
    if not server.started:
        print("服务未能启动", file=sys.stderr)
        return 2
    print(f"uvicorn 已启动：{BASE}\n")

    try:
        _, admin = request("/api/v1/auth/login", "POST", {"employee_no": "A001", "password": ADMIN_PW})
        _, t1 = request("/api/v1/auth/login", "POST", {"employee_no": "T001", "password": THERAPIST_PW})
        at, h1 = admin["access_token"], t1["access_token"]

        # ---------------------------------------------------------------- #
        # 1) 枚举：状态 / 形态 / 四大类
        # ---------------------------------------------------------------- #
        code, enums = request("/api/v1/records/enums", token=h1)
        check("记录枚举可读（状态 / 形态 / 四大类）", code == 200, str(code))
        check("形态是四种（initial/daily/reassessment/discharge）",
              enums.get("kinds") == ["initial", "daily", "reassessment", "discharge"],
              str(enums.get("kinds")))
        check("四大类是运动/生活技能/吞咽/言语",
              [d["key"] for d in enums.get("disciplines") or []] == ["PT", "OT", "ST_SW", "ST_SP"]
              and [d["name"] for d in enums.get("disciplines") or []]
              == ["运动", "生活技能", "吞咽", "言语"],
              str(enums.get("disciplines")))
        check("记录状态只有 draft/submitted/locked",
              enums.get("statuses") == ["draft", "submitted", "locked"], str(enums.get("statuses")))

        # ---------------------------------------------------------------- #
        # 2) 记录表单：缺首评时"这次要填的就是首评"（先弹评估文书）
        # ---------------------------------------------------------------- #
        code, form = request(
            "/api/v1/records/form" + q(patient_no="S3A", discipline=DISC), token=h1
        )
        check("记录表单可用（患者 / 大类 / 本次形态）",
              code == 200 and form["patient"]["name"] == "阶段三患者甲"
              and form["discipline_name"] == "运动",
              f"{code} {str(form)[:160]}")
        check("首诊取到的形态就是首评（缺评估文书时先弹它）",
              form["kind"] == "initial" and form["pending_document"] == "initial",
              f"{form.get('kind')} / {form.get('pending_document')}")
        check("表单给出本次序号与待复评提示",
              form["next_seq"] == 1 and form["total_daily"] == 0
              and form["sessions_until_reassessment"] == 20,
              f"{form.get('next_seq')} / {form.get('total_daily')} / "
              f"{form.get('sessions_until_reassessment')}")
        check("表单带出 SOAP 四段字段定义（S/O/A/P）",
              [s["key"] for s in form["soap"]] == ["s", "o", "a", "p"],
              str([s["key"] for s in form["soap"]]))
        check("表单标题来自模板 JSON 文件",
              form["title"].startswith("康复初始评定") and form["template_version"] >= 1,
              str(form.get("title")))

        code, err = request(
            "/api/v1/records/form" + q(patient_no="S3A", discipline="XX"), token=h1
        )
        check("未知大类取表单 → 422", code == 422 and err["code"] == "INVALID", str(err)[:140])
        code, err = request("/api/v1/records/form" + q(patient_no="S3A"), token=h1)
        check("缺 discipline 参数 → 422", code == 422, str(code))

        # 出院小结不是门禁推出来的，必须显式传 kind=discharge
        code, discharge_form = request(
            "/api/v1/records/form" + q(patient_no="S3A", discipline=DISC, kind="discharge"), token=h1
        )
        check("显式 kind=discharge 取到出院小结表单",
              code == 200 and discharge_form["kind"] == "discharge"
              and discharge_form["title"].startswith("康复出院小结"),
              f"{code} {str(discharge_form)[:160]}")

        # ---------------------------------------------------------------- #
        # 3) 硬阻断 ①：缺首评就想记日常 → 409
        # ---------------------------------------------------------------- #
        code, err = post_record(h1, "S3A", DAILY_DATES[0], "daily", DAILY_BODY, status="submitted")
        check("缺首评记日常 → 409 MISSING_ASSESSMENT",
              code == 409 and err["code"] == "MISSING_ASSESSMENT"
              and err["details"]["missing_document"] == "initial"
              and err["details"]["missing_document_label"] == "首评"
              and err["details"]["next_seq"] == 1,
              f"{code} {str(err)[:200]}")

        # ---------------------------------------------------------------- #
        # 4) 必填校验：缺「功能诊断」「本次训练项目」→ 422
        # ---------------------------------------------------------------- #
        code, err = post_record(h1, "S3A", DAILY_DATES[0], "initial", {}, status="draft")
        check("首评缺必填项 → 422 且列出中文标签",
              code == 422 and err["code"] == "INVALID"
              and set(err["details"]["missing"]) == {"功能诊断", "本次训练项目"},
              f"{code} {str(err)[:200]}")
        code, err = post_record(h1, "S3A", DAILY_DATES[0], "daily", {}, status="draft")
        check("日常记录缺「本次训练项目」→ 422",
              code == 422 and err["details"]["missing"] == ["本次训练项目"],
              f"{code} {str(err)[:200]}")

        # ---------------------------------------------------------------- #
        # 5) 建首评 → 首评**不占**日常次数
        # ---------------------------------------------------------------- #
        code, initial = post_record(
            h1, "S3A", DAILY_DATES[0], "initial", INITIAL_BODY, status="submitted"
        )
        check("建首评成功", code == 201, f"{code} {str(initial)[:200]}")
        check("首评没有日常序号、挂靠在第 1 次日常区间",
              initial["seq_no"] is None and initial["span_seq"] == 1,
              f"seq_no={initial.get('seq_no')} span_seq={initial.get('span_seq')}")
        check("首评的 rendered_text 是 SOAP 纯文本（不是表格）",
              "主观资料：" in initial["rendered_text"]
              and "客观资料：" in initial["rendered_text"]
              and "评估分析：" in initial["rendered_text"]
              and "|" not in initial["rendered_text"],
              str(initial["rendered_text"])[:200])

        code, form2 = request("/api/v1/records/form" + q(patient_no="S3A", discipline=DISC), token=h1)
        check("首评不占次数：这次该填日常，且仍是第 1 次",
              form2["kind"] == "daily" and form2["next_seq"] == 1
              and form2["total_daily"] == 0 and form2["pending_document"] is None,
              f"{form2.get('kind')} / {form2.get('next_seq')} / {form2.get('total_daily')}")

        # ---------------------------------------------------------------- #
        # 6) 当天日常：第 1 次；渲染文本落库且含「主观资料：」
        # ---------------------------------------------------------------- #
        code, daily1 = post_record(
            h1, "S3A", DAILY_DATES[0], "daily", DAILY_BODY, status="submitted"
        )
        check("同一天建日常记录（首评与日常并存）",
              code == 201 and daily1["seq_no"] == 1 and daily1["kind"] == "daily",
              f"{code} {str(daily1)[:200]}")
        check("日常记录的 rendered_text 含「主观资料：」且是纯文本",
              "主观资料：" in daily1["rendered_text"]
              and "本次训练项目：偏瘫肢体综合训练/平衡功能训练" in daily1["rendered_text"]
              and "|" not in daily1["rendered_text"],
              str(daily1["rendered_text"])[:240])
        check("日常记录的表头带「第 1 次」",
              "第 1 次" in daily1["rendered_text"].splitlines()[1],
              str(daily1["rendered_text"].splitlines()[:2]))

        conn = storage.connect(settings)
        try:
            row = conn.execute(
                "SELECT kind, seq_no, span_seq, body_json, rendered_text FROM treatment_record"
                " WHERE id = ?",
                (daily1["id"],),
            ).fetchone()
        finally:
            conn.close()
        check("rendered_text 真的落库（与响应逐字一致）",
              row["rendered_text"] == daily1["rendered_text"], "")
        check("body_json 落库并按 field_key 存答案",
              json.loads(row["body_json"])["mental"] == "良好"
              and json.loads(row["body_json"])["therapy_items"]
              == ["偏瘫肢体综合训练", "平衡功能训练"],
              str(row["body_json"])[:160])

        # ---------------------------------------------------------------- #
        # 7) 同一天同一大类至多 2 条
        # ---------------------------------------------------------------- #
        code, err = post_record(h1, "S3A", DAILY_DATES[0], "daily", DAILY_BODY, status="draft")
        check("同一天同一大类第 3 条 → 409（至多 2 条）",
              code == 409 and "至多 2 条" in err["message"]
              and err["details"]["date"] == DAILY_DATES[0],
              f"{code} {str(err)[:160]}")

        # ---------------------------------------------------------------- #
        # 8) 硬阻断 ②：满 20 次日常后缺复评 → 409
        # ---------------------------------------------------------------- #
        seqs = []
        codes = []
        for day in DAILY_DATES[1:]:
            code, created = post_record(h1, "S3A", day, "daily", DAILY_BODY, status="submitted")
            codes.append(code)
            seqs.append(created.get("seq_no") if isinstance(created, dict) else None)
        check("日常记录第 2–20 次按次递增（一天一条）",
              codes == [201] * 19 and seqs == list(range(2, 21)),
              f"{codes[:4]}… {seqs[:4]}…{seqs[-2:]}")

        code, err = post_record(h1, "S3A", DATE_21, "daily", DAILY_BODY, status="submitted")
        check("第 21 次日常前缺复评 → 409 MISSING_ASSESSMENT",
              code == 409 and err["code"] == "MISSING_ASSESSMENT"
              and err["details"]["missing_document"] == "reassessment"
              and err["details"]["missing_document_label"] == "阶段性复评"
              and err["details"]["next_seq"] == 21,
              f"{code} {str(err)[:200]}")

        code, form21 = request(
            "/api/v1/records/form" + q(patient_no="S3A", discipline=DISC), token=h1
        )
        check("满 20 次后表单直接给出复评（先弹评估文书）",
              form21["kind"] == "reassessment" and form21["pending_document"] == "reassessment"
              and form21["next_seq"] == 21 and form21["total_daily"] == 20,
              f"{form21.get('kind')} / {form21.get('next_seq')} / {form21.get('total_daily')}")

        code, reassess = post_record(
            h1, "S3A", DATE_21, "reassessment",
            {"therapy_items": ["偏瘫肢体综合训练"], "mmt_lower": 3, "prev_goal": "坐位平衡达Ⅲ级"},
            status="submitted",
        )
        check("补齐复评（挂靠第 21 次日常）",
              code == 201 and reassess["seq_no"] is None and reassess["span_seq"] == 21,
              f"{code} seq_no={reassess.get('seq_no')} span_seq={reassess.get('span_seq')}")

        code, daily21 = post_record(
            h1, "S3A", DATE_21, "daily", DAILY_BODY, status="submitted"
        )
        check("复评补齐后第 21 次日常放行",
              code == 201 and daily21["seq_no"] == 21, f"{code} {str(daily21)[:160]}")

        # 评估文书不占次数：已提交的**日常**共 21 条，而记录总数是 24（首评 + 复评 + 21 条日常）
        code, listed = request("/api/v1/records" + q(patient_no="S3A", page_size=200), token=h1)
        kinds = [i["kind"] for i in listed["items"]]
        check("该患者共 23 条文书：21 条日常 + 首评 + 复评（评估文书不占次数）",
              listed["total"] == 23 and kinds.count("daily") == 21 and kinds.count("initial") == 1
              and kinds.count("reassessment") == 1,
              f"total={listed.get('total')} daily={kinds.count('daily')}")

        # ---------------------------------------------------------------- #
        # 9) 状态机与留痕：草稿不留痕、提交后累加 edit_count、锁定后不可改
        # ---------------------------------------------------------------- #
        code, draft = post_record(h1, "S3A", DATE_DRAFT, "daily", DAILY_BODY, status="draft")
        check("建日常草稿（第 22 次）", code == 201 and draft["seq_no"] == 22, f"{code}")
        code, _ = request(
            f"/api/v1/records/{draft['id']}", "PUT", {"body": {**DAILY_BODY, "vas": 3}}, h1
        )
        check("草稿可任意修改", code == 200, str(code))
        code, after_draft_edit = request(f"/api/v1/records/{draft['id']}", token=h1)
        check("草稿修改不累加 edit_count",
              after_draft_edit["edit_count"] == 0, str(after_draft_edit["edit_count"]))
        check("改 body 会重新渲染 rendered_text",
              "疼痛VAS：3分" in after_draft_edit["rendered_text"],
              str(after_draft_edit["rendered_text"])[:200])

        code, submitted = request(f"/api/v1/records/{draft['id']}/submit", "POST", {}, h1)
        check("提交草稿", code == 200 and submitted["status"] == "submitted", f"{code}")
        code, edited = request(
            f"/api/v1/records/{draft['id']}", "PUT", {"body": {**DAILY_BODY, "vas": 4}}, h1
        )
        check("提交后修改累加 edit_count",
              code == 200 and edited["edit_count"] == 1 and edited["revision"] > submitted["revision"],
              f"{code} edit_count={edited.get('edit_count')}")

        code, locked = request(f"/api/v1/records/{draft['id']}/lock", "POST", {}, at)
        check("管理员锁定记录", code == 200 and locked["status"] == "locked", f"{code}")
        code, err = request(
            f"/api/v1/records/{draft['id']}", "PUT", {"body": DAILY_BODY}, h1
        )
        check("锁定后治疗师不能改 → 403 RECORD_LOCKED",
              code == 403 and err["code"] == "RECORD_LOCKED", f"{code} {str(err)[:140]}")

        # ---------------------------------------------------------------- #
        # 10) 权限边界（全科白板）与时间轴
        # ---------------------------------------------------------------- #
        # 同样受硬阻断约束：同事负责的患者也要先有首评才能记日常
        code, init_b = post_record(
            h1, "S3B", DAILY_DATES[0], "initial", INITIAL_BODY, status="submitted"
        )
        check("全科白板：给同事负责的患者建首评",
              code == 201 and init_b["seq_no"] is None, f"{code} {str(init_b)[:160]}")
        code, written_b = post_record(
            h1, "S3B", DAILY_DATES[0], "daily", DAILY_BODY, status="draft"
        )
        check("全科白板：给同事负责的患者写记录 → 记录人是自己",
              code == 201 and written_b["therapist_id"] == ids["T001"],
              f"{code} {str(written_b)[:160]}")
        code, listed_b = request("/api/v1/records" + q(patient_no="S3B"), token=h1)
        check("全科白板：能读到同事患者刚写入的记录",
              code == 200 and listed_b["total"] >= 1, str(listed_b.get("total")))
        check("记录列表带 SOAP 摘要（rendered_excerpt）",
              all("rendered_excerpt" in i for i in listed_b["items"]),
              str(listed_b["items"][:1])[:160])

        code, tl = request("/api/v1/timeline" + q(page_size=200), token=h1)
        check("时间轴可用", code == 200 and tl["total"] >= 21, str(tl.get("total")))
        if code == 200 and tl["items"]:
            dates = [i["record_date"] for i in tl["items"]]
            check("时间轴按日期倒序", dates == sorted(dates, reverse=True), str(dates[:6]))
            check("时间轴条目带冻结的 SOAP 文本",
                  all("rendered_text" in i for i in tl["items"])
                  and any("主观资料：" in (i["rendered_text"] or "") for i in tl["items"]),
                  "")
        code, err = request("/api/v1/timeline" + q(scope="temp"), token=h1)
        check("scope=temp 已删除 → 404", code == 404 and err["code"] == "INVALID_SCOPE",
              f"{code} {str(err)[:140]}")

        # ---------------------------------------------------------------- #
        # 11) 出院流程：任何治疗师可发起 → 待出院 → 管理员确认或取消
        # ---------------------------------------------------------------- #
        code, summary = post_record(h1, "S3B", DATE_21, "discharge", {}, status="submitted")
        check("治疗师可建出院小结并提交",
              code == 201 and summary["kind"] == "discharge"
              and summary["seq_no"] is None and summary["span_seq"] is None,
              f"{code} {str(summary)[:160]}")

        code, pending = request(
            "/api/v1/patients/S3B/discharge", "POST", {"record_id": summary["id"]}, h1
        )
        check("任何治疗师可发起出院 → 患者待出院",
              code == 200 and pending["status"] == "pending_discharge",
              f"{code} {str(pending)[:160]}")

        code, err = post_record(h1, "S3B", DATE_DRAFT, "daily", DAILY_BODY, status="draft")
        check("待出院患者不能再记新记录 → 409",
              code == 409 and err["code"] == "PATIENT_PENDING_DISCHARGE",
              f"{code} {str(err)[:160]}")

        code, err = request(
            "/api/v1/patients/S3B/discharge/confirm", "POST", {}, h1
        )
        check("治疗师不能确认出院 → 403", code == 403 and err["code"] == "ADMIN_REQUIRED",
              f"{code} {str(err)[:140]}")

        code, cancelled = request(
            "/api/v1/patients/S3B/discharge/cancel", "POST", {}, at
        )
        check("管理员可取消待出院（患者回在院）",
              code == 200 and cancelled["status"] == "in_hospital", f"{code} {str(cancelled)[:140]}")

        code, pending2 = request(
            "/api/v1/patients/S3B/discharge", "POST", {"record_id": summary["id"]}, at
        )
        check("出院动作幂等可重入", code == 200 and pending2["status"] == "pending_discharge",
              f"{code}")
        code, discharged = request(
            "/api/v1/patients/S3B/discharge/confirm", "POST", {}, at
        )
        check("管理员确认出院 → 已出院",
              code == 200 and discharged["status"] == "discharged", f"{code} {str(discharged)[:140]}")

        # ---------------------------------------------------------------- #
        # 12) OpenAPI：新接口在册、已删接口不在册
        # ---------------------------------------------------------------- #
        code, schema = request("/openapi.json")
        paths = set(schema["paths"])
        wanted = {
            "/api/v1/records/form",
            "/api/v1/records",
            "/api/v1/records/{record_id}",
            "/api/v1/patients/{inpatient_no}/discharge",
            "/api/v1/patients/{inpatient_no}/discharge/confirm",
            "/api/v1/patients/{inpatient_no}/discharge/cancel",
            "/api/v1/timeline",
        }
        check("OpenAPI 收录阶段 3 的新接口", wanted <= paths, str(sorted(wanted - paths)))
        removed = {p for p in paths if "/dict" in p or "/option-sets" in p
                   or "/response-defs" in p or "/templates" in p}
        check("OpenAPI 不再收录字典/选项集/反应定义/模板接口", not removed, str(sorted(removed)))
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    print()
    if failures:
        print(f"{len(failures)} 项失败：")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("阶段 3 端到端验证全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
