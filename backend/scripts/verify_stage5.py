"""阶段 5 端到端验证（**已重写版式部分**）：汇总、打印（三套 PDF）与后台。

跑真实 uvicorn + 真实 HTTP，并**用 pypdf 反向提取中文文本**确认 PDF 真的印出了中文
（这是唯一能发现"满页方框"的手段）。

## 2026-10-05：输出从"表格"改成"SOAP 纯文本"

用户要求：「输出时也用类似格式，避免现有的表格方式」+「多日的情况下，是按时间顺序
往下排就行，不用一天一张」。因此本脚本的断言对象换了：

| 旧断言 | 新断言 |
|---|---|
| 汇总里有 `total_duration_min`（总时长） | 该字段**已不存在**（`duration_min` 随 SOAP 改造删除） |
| 汇总里有 `main_item_counts`（主项目频次） | 改为 `discipline_counts`（四大类频次） |
| 行里的 `params_digest` / `response_digest` | 行里的 `rendered_text`（冻结的 SOAP 纯文本） |
| PDF 里是参数表格 | PDF 正文是 SOAP 文本，且含「主观资料：」 |
| 多日各占一张 | 多日**按时间顺序连排**（早的在前），不分页不一天一张 |
| 模板接口 `/templates`（科室/个人模板） | 模板是 `templates/*.json` 文件，**没有模板接口** |
| 后台选项集维护 `/admin/option-sets` | 选项集已随迁移 012 删除，改验收审计日志 |

    cd backend
    python scripts/verify_stage5.py
"""

from __future__ import annotations

import io
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

D1 = "2027-07-01"
D2 = "2027-07-03"
D3 = "2027-07-05"

PT_INITIAL = {"complaint": ["肢体无力"], "diagnosis": ["偏瘫运动功能障碍"],
              "therapy_items": ["偏瘫肢体综合训练"]}
PT_DAILY = {"mental": "良好", "complaint": ["乏力"],
            "therapy_items": ["偏瘫肢体综合训练"], "performance": "较前改善"}
OT_INITIAL = {"diagnosis": ["日常生活能力受限"], "therapy_items": ["日常生活能力训练"]}
OT_DAILY = {"compliance": "良好", "therapy_items": ["日常生活能力训练"], "performance": "较前改善"}

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
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            ctype = resp.headers.get("Content-Type", "")
            if "pdf" in ctype:
                return resp.status, raw
            return resp.status, (json.loads(raw.decode("utf-8")) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return exc.code, None


def q(**params: object) -> str:
    return "?" + urllib.parse.urlencode(params)


def pdf_text(content: bytes) -> str:
    from pypdf import PdfReader

    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)


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

        # 清理上次运行遗留（记录模板是 JSON 文件，没有模板表要清）
        for no in ("S5A", "S5B"):
            purge_patients(conn, [no])

        patient_model.create_patient(
            conn, inpatient_no="S5A", name="阶段五患者甲", diagnosis="脑卒中恢复期",
            admin_note="左侧偏瘫，注意防跌倒", assigned_therapist_id=ids["T001"],
        )
        patient_model.create_patient(
            conn, inpatient_no="S5B", name="阶段五患者乙", assigned_therapist_id=ids["T002"]
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

    def write_record(token, patient_no, day, discipline, kind, body, *, status="submitted"):
        return request(
            "/api/v1/records", "POST",
            {"patient_no": patient_no, "record_date": day, "discipline": discipline,
             "kind": kind, "body": body, "status": status},
            token,
        )

    try:
        _, admin = request("/api/v1/auth/login", "POST", {"employee_no": "A001", "password": ADMIN_PW})
        _, t1 = request("/api/v1/auth/login", "POST", {"employee_no": "T001", "password": THERAPIST_PW})
        _, t2 = request("/api/v1/auth/login", "POST", {"employee_no": "T002", "password": THERAPIST_PW})
        ha, h1, h2 = admin["access_token"], t1["access_token"], t2["access_token"]

        # ---------------------------------------------------------------- #
        # 造数据（SOAP 契约：首评不占次数，所以每次"第一天"都是两份文书）
        #   甲：07-01 运动首评 + 运动日常 + 生活技能首评 + 生活技能日常；
        #       07-03 运动日常（第 2 次）；07-05 一条**草稿**（不计入汇总）
        #   乙：07-01 运动首评 + 运动日常
        # ---------------------------------------------------------------- #
        code, _ = write_record(h1, "S5A", D1, "PT", "initial", PT_INITIAL)
        check("甲：运动首评入库", code == 201, f"HTTP {code}")
        code, _ = write_record(h1, "S5A", D1, "PT", "daily", PT_DAILY)
        check("甲：运动日常入库（同一天两条文书）", code == 201, f"HTTP {code}")
        code, _ = write_record(h1, "S5A", D1, "OT", "initial", OT_INITIAL)
        check("甲：生活技能首评入库（四大类分开记录）", code == 201, f"HTTP {code}")
        code, _ = write_record(h1, "S5A", D1, "OT", "daily", OT_DAILY)
        check("甲：生活技能日常入库（同一天、不同大类互不占用名额）", code == 201, f"HTTP {code}")
        code, _ = write_record(h1, "S5A", D2, "PT", "daily", PT_DAILY)
        check("甲：07-03 运动日常入库", code == 201, f"HTTP {code}")
        code, draft = write_record(h1, "S5A", D3, "PT", "daily", PT_DAILY, status="draft")
        check("甲：07-05 草稿（不应计入汇总）", code == 201, f"HTTP {code}")
        code, _ = write_record(h2, "S5B", D1, "PT", "initial", PT_INITIAL)
        check("乙：运动首评入库", code == 201, f"HTTP {code}")
        code, _ = write_record(h2, "S5B", D1, "PT", "daily", PT_DAILY)
        check("乙：运动日常入库", code == 201, f"HTTP {code}")

        # ---------------------------------------------------------------- #
        # 1) 按日期汇总（只算日常、只算已提交/已锁定）
        # ---------------------------------------------------------------- #
        code, summary = request("/api/v1/summary/date" + q(date=D1), token=ha)
        check("按日期汇总可用", code == 200, str(code))
        check("汇总只计已提交的**日常**记录（草稿与首评都不计）",
              summary["totals"]["record_count"] == 3, str(summary["totals"]))
        check("汇总按四大类统计（运动 2 / 生活技能 1）",
              summary["totals"]["discipline_counts"] == {"运动": 2, "生活技能": 1},
              str(summary["totals"]["discipline_counts"]))
        check("汇总按治疗师统计（张三 2 / 李四 1）",
              summary["totals"]["therapist_counts"] == {"张三": 2, "李四": 1},
              str(summary["totals"]["therapist_counts"]))
        check("汇总不再有「总时长」与「主项目频次」（表格口径已删除）",
              "total_duration_min" not in summary["totals"]
              and "main_item_counts" not in summary["totals"],
              str(sorted(summary["totals"])))
        check("汇总行带冻结的 SOAP 文本（rendered_text）",
              all("rendered_text" in row for g in summary["groups"] for row in g["rows"])
              and any("主观资料：" in row["rendered_text"]
                      for g in summary["groups"] for row in g["rows"]),
              "")
        check("汇总行带形态与序号（kind_label / seq_no）",
              all(row["kind_label"] == "日常治疗记录" and row["seq_no"] is not None
                  for g in summary["groups"] for row in g["rows"]),
              "")

        code, grouped = request(
            "/api/v1/summary/date" + q(date=D1, group_by="therapist"), token=ha
        )
        check("按治疗师分组", {g["key"] for g in grouped["groups"]} == {"张三", "李四"},
              str([g["key"] for g in grouped["groups"]]))
        code, by_patient = request(
            "/api/v1/summary/date" + q(date=D1, group_by="patient"), token=ha
        )
        check("按患者分组", {g["key"] for g in by_patient["groups"]}
              == {"阶段五患者甲", "阶段五患者乙"},
              str([g["key"] for g in by_patient["groups"]]))

        # ---------------------------------------------------------------- #
        # 2) 按患者每日汇总（逐日，带回当天全部文书）
        # ---------------------------------------------------------------- #
        code, daily = request("/api/v1/summary/patient/S5A", token=h1)
        check("按患者每日汇总可用", code == 200, str(code))
        check("每日汇总按日期倒序（草稿那天不出现）",
              [d["record_date"] for d in daily["days"]] == [D2, D1],
              str([d["record_date"] for d in daily["days"]]))
        day1 = next(d for d in daily["days"] if d["record_date"] == D1)
        check("当天四份文书都列出（首评/日常 × 两个大类）",
              len(day1["records"]) == 4, str(len(day1["records"])))
        check("当天的 record_count 只数日常（2 条，首评不计）",
              day1["record_count"] == 2, str(day1["record_count"]))
        check("当天文本列表都是 SOAP 文本（有「治疗日期：」且不是表格）",
              all("治疗日期：" in t and "|" not in t for t in day1["texts"]),
              str(day1["texts"])[:200])
        # 模板规则：「没填的字段整条不出现、整段都没填就整段不出现」。
        # 甲的生活技能首评只填了 A/P 两段，所以它既没有「主观资料：」也没有「客观资料：」。
        check("没填的整段不出现（4 份文书里 3 份有 S 段、2 份有 O 段）",
              sum(1 for t in day1["texts"] if "主观资料：" in t) == 3
              and sum(1 for t in day1["texts"] if "客观资料：" in t) == 2,
              str([t[:24] for t in day1["texts"]]))
        check("当天四大类都标了出来（运动 / 生活技能）",
              day1["disciplines"] == ["生活技能", "运动"], str(day1["disciplines"]))

        code, ranged = request(
            "/api/v1/summary/patient/S5A" + q(**{"from": "2027-07-02", "to": "2027-07-04"}),
            token=h1,
        )
        check("日期范围筛选", [d["record_date"] for d in ranged["days"]] == [D2],
              str([d["record_date"] for d in ranged["days"]]))

        # ---------------------------------------------------------------- #
        # 3) 单患者总览
        # ---------------------------------------------------------------- #
        code, overview = request("/api/v1/summary/patient/S5A/overview", token=h1)
        check("单患者总览含归属治疗师",
              overview["patient"]["assigned_therapist_name"] == "张三", str(overview["patient"])[:160])
        check("总览返回全部文书（草稿之外 5 条）且带 SOAP 文本",
              len(overview["records"]) == 5
              and all("rendered_text" in r for r in overview["records"]),
              str(len(overview["records"])))
        check("总览的统计口径与汇总一致（3 次日常）",
              overview["totals"]["record_count"] == 3, str(overview["totals"]))

        # ---------------------------------------------------------------- #
        # 4) 三套 PDF：正文是 SOAP 文本，多日按时间顺序连排
        # ---------------------------------------------------------------- #
        code, data = request("/api/v1/print/patient/S5A", token=h1)
        check("单患者汇总 PDF 生成", code == 200 and data[:4] == b"%PDF", str(code))
        text = pdf_text(data)
        for expected in ("康复医学科", "阶段五患者甲", "S5A", "脑卒中恢复期", "张三",
                         "康复治疗记录汇总", "主观资料：", "本次训练项目：偏瘫肢体综合训练"):
            check(f"PDF 含「{expected}」", expected in text)
        check("PDF 正文是 SOAP 文本而不是表格（有「客观资料：」段）", "客观资料：" in text)
        # Q10「不做签名栏」指的是**不额外画**签名框（见 services/pdf.py 的注释）；
        # 而 SOAP 文本自己的页脚里本来就带「治疗师签名：____」一行（模板 `footer`）。
        # 所以这里断言的是"页脚跟着 `rendered_text` 一起原样打印"，而不是"全文没有签名二字"。
        check("PDF 原样打印模板页脚（治疗师签名行随 rendered_text 一起冻结）",
              "治疗师签名" in text)
        check("PDF 页脚含页码与打印时间", "第 1 页" in text and "打印时间：" in text)
        check("PDF 不含已删除的参数字段名（session_period / 患者反应）",
              "session_period" not in text and "患者反应" not in text)

        code, data_daily = request("/api/v1/print/summary/patient/S5A", token=h1)
        check("按患者每日汇总 PDF 生成", code == 200 and data_daily[:4] == b"%PDF", str(code))
        text_daily = pdf_text(data_daily)
        check("每日汇总 PDF 只印已提交的日期（草稿那天不打印）",
              D1 in text_daily and D2 in text_daily and D3 not in text_daily,
              text_daily[:200])
        # ★ 多日**按时间顺序往下排**：早的在前（不是倒序、也不是一天一张分页）
        check("多日按时间顺序连排（07-01 在 07-03 之前）",
              text_daily.index(D1) < text_daily.index(D2),
              str([text_daily.index(d) for d in (D1, D2)]))
        check("每日汇总 PDF 正文也是 SOAP 文本", "主观资料：" in text_daily)

        code, data_date = request("/api/v1/print/summary/date" + q(date=D1), token=ha)
        check("按日期汇总 PDF 生成", code == 200 and data_date[:4] == b"%PDF", str(code))
        text_date = pdf_text(data_date)
        check("日期汇总 PDF 含日期与两名患者",
              D1 in text_date and "阶段五患者甲" in text_date and "阶段五患者乙" in text_date,
              text_date[:200])
        check("日期汇总 PDF 正文是 SOAP 文本", "主观资料：" in text_date)

        # ---------------------------------------------------------------- #
        # 5) 打印/汇总的权限边界
        # ---------------------------------------------------------------- #
        code, data_b = request("/api/v1/print/patient/S5B", token=h1)
        check("白板：可打印同事负责患者的汇总 PDF",
              code == 200 and data_b[:4] == b"%PDF", str(code))
        code, sum_b = request("/api/v1/summary/patient/S5B", token=h1)
        check("白板：可汇总同事负责患者", code == 200, str(code))

        code, data_all = request("/api/v1/print/summary/date" + q(date=D1), token=h1)
        text_all = pdf_text(data_all)
        check("日期汇总覆盖全科在院患者",
              "阶段五患者甲" in text_all and "阶段五患者乙" in text_all, text_all[:200])

        # 已出院患者默认不在白板范围内 —— 这才是权限边界
        code, _ = request("/api/v1/patients/S5B", "PUT", {"status": "discharged"}, token=ha)
        check("准备权限边界用例：置为已出院", code == 200, str(code))
        code, err = request("/api/v1/print/patient/S5B", token=h1)
        check("已出院患者不可打印 → 403",
              code == 403 and err["code"] == "PATIENT_NOT_VISIBLE", str(err)[:120])
        code, err = request("/api/v1/summary/patient/S5B", token=h1)
        check("已出院患者不可汇总 → 403", code == 403, str(code))
        code, _ = request("/api/v1/patients/S5B", "PUT", {"status": "in_hospital"}, token=ha)
        check("恢复为在院", code == 200, str(code))

        # ---------------------------------------------------------------- #
        # 6) 模板不再是数据库实体（记录模板是 templates/*.json 文件）
        # ---------------------------------------------------------------- #
        for path in ("/api/v1/templates", "/api/v1/admin/option-sets",
                     "/api/v1/option-sets/resolve", "/api/v1/dict/tree",
                     "/api/v1/response-defs"):
            code, _ = request(path, token=h1)
            check(f"已删除的模板/选项集/字典接口不再存在：{path}", code == 404, f"HTTP {code}")
        code, schema = request("/openapi.json")
        check("OpenAPI 里没有 templates / option-sets / response-defs / dict 路径",
              not [p for p in schema["paths"]
                   if "templates" in p or "option-sets" in p
                   or "response-defs" in p or "/dict" in p],
              str([p for p in schema["paths"] if "template" in p or "dict" in p]))

        # ---------------------------------------------------------------- #
        # 7) 后台：审计日志
        # ---------------------------------------------------------------- #
        code, logs = request("/api/v1/audit-logs", token=ha)
        check("管理员可查审计日志", code == 200 and logs["total"] > 0, str(code))
        check("审计日志带操作人姓名", logs["items"][0].get("user_name") is not None,
              str(logs["items"][0])[:160])

        code, filtered = request("/api/v1/audit-logs" + q(target_type="treatment_record"), token=ha)
        check("按对象类型筛选审计（治疗记录）",
              filtered["total"] > 0
              and all(i["target_type"] == "treatment_record" for i in filtered["items"]),
              str(filtered["total"]))

        code, facets = request("/api/v1/audit-logs/facets", token=ha)
        check("审计筛选维度可用",
              "treatment_record" in facets["target_types"]
              and "patient" in facets["target_types"]
              and "create" in facets["actions"],
              str(facets)[:200])

        code, err = request("/api/v1/audit-logs", token=h1)
        check("治疗师不能查审计日志 → 403", code == 403, str(code))

        # ---------------------------------------------------------------- #
        # 8) OpenAPI 收录阶段 5 接口
        # ---------------------------------------------------------------- #
        wanted = {
            "/api/v1/summary/date", "/api/v1/summary/patient/{inpatient_no}",
            "/api/v1/summary/patient/{inpatient_no}/overview",
            "/api/v1/print/patient/{inpatient_no}", "/api/v1/print/summary/date",
            "/api/v1/print/summary/patient/{inpatient_no}",
            "/api/v1/audit-logs", "/api/v1/audit-logs/facets",
        }
        check("OpenAPI 收录阶段 5 接口", wanted <= set(schema["paths"]),
              str(sorted(wanted - set(schema["paths"]))))
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    print()
    if failures:
        print(f"{len(failures)} 项失败：")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("阶段 5 端到端验证全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
