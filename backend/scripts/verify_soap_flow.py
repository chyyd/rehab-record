"""端到端验证 SOAP 记录链路（真实 uvicorn + 真实 HTTP）。

    cd backend
    python scripts/verify_soap_flow.py
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
PN = "SOAP01"

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


def request(path: str, method: str = "GET", body=None, token: str | None = None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, method=method, data=data)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return exc.code, (json.loads(raw) if raw else None)


def diagnose(kind: str) -> dict:
    """取一份「诊断」类型的完整答案（用模板里的必填项 + 几个常见项）。"""
    base = {"diagnosis": ["偏瘫运动功能障碍"], "therapy_items": ["偏瘫肢体综合训练"]}
    if kind == "initial":
        base.update({"complaint": ["肢体无力"], "vas": 3, "mmt_upper": 2, "mmt_lower": 3,
                     "sit_balance": "Ⅱ级", "stand_balance": "Ⅰ级", "fall_risk": "高风险",
                     "impairment": "中度受损", "potential": "良好"})
    elif kind == "reassessment":
        base.update({"mmt_upper": 3, "mmt_lower": 4, "sit_balance": "Ⅲ级",
                     "stand_balance": "Ⅱ级", "fall_risk": "中风险", "prev_goal": "基本完成"})
    elif kind == "daily":
        base = {"therapy_items": ["偏瘫肢体综合训练", "平衡功能训练"]}
    elif kind == "discharge":
        base = {"goal_achieved": "基本达成", "home_training": ["肌力训练"]}
    return base


def main() -> int:
    from app.core.config import get_settings
    from app.db import storage
    from app.main import create_app
    from app.models import user as user_model

    settings = get_settings()
    conn = storage.connect(settings)
    try:
        storage.migrate(conn, storage.discover_migrations(settings=settings))
        ids: dict[str, int] = {}
        for employee_no, name, role, pw in (
            ("A001", "科室管理员", user_model.ROLE_ADMIN, ADMIN_PW),
            ("T001", "张三", user_model.ROLE_THERAPIST, THERAPIST_PW),
        ):
            existing = user_model.get_by_employee_no(conn, employee_no)
            if existing:
                user_model.set_password(conn, int(existing["id"]), pw)
                ids[employee_no] = int(existing["id"])
            else:
                created = user_model.create_user(
                    conn, employee_no=employee_no, name=name, role=role, password=pw)
                ids[employee_no] = int(created["id"])
        purge_patients(conn, [PN])
        conn.execute("INSERT INTO patient (inpatient_no, name, status, assigned_therapist_id)"
                     " VALUES (?, ?, 'in_hospital', ?)", (PN, "SOAP 流程患者", ids["T001"]))
        conn.commit()
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
        _, t1 = request("/api/v1/auth/login", "POST",
                        {"employee_no": "T001", "password": THERAPIST_PW})
        _, adm = request("/api/v1/auth/login", "POST",
                         {"employee_no": "A001", "password": ADMIN_PW})
        h, at = t1["access_token"], adm["access_token"]

        # ---------------------------------------------------------------- #
        # 1) 取表单：无记录 → 先弹首评
        # ---------------------------------------------------------------- #
        code, form = request(f"/api/v1/records/form?patient_no={PN}&discipline=PT", token=h)
        check("取 PT 表单成功", code == 200, f"HTTP {code} {str(form)[:150]}")
        check("无记录时 kind=initial（先弹首评）", form["kind"] == "initial", str(form["kind"]))
        check("pending_document=initial", form["pending_document"] == "initial")
        check("next_seq=1 且 total_daily=0", form["next_seq"] == 1 and form["total_daily"] == 0)
        check("返回四段 SOAP 字段定义",
              [s["key"] for s in form["soap"]] == ["s", "o", "a", "p"], str([s["key"] for s in form["soap"]]))
        check("字段含四种类型",
              {"single", "multi", "number", "text"} <=
              {f["type"] for s in form["soap"] for f in s["fields"]})

        # ---------------------------------------------------------------- #
        # 2) 硬阻断：缺首评时不让记日常
        # ---------------------------------------------------------------- #
        code, err = request("/api/v1/records", "POST",
                            {"patient_no": PN, "record_date": "2026-10-05", "discipline": "PT",
                             "kind": "daily", "body": diagnose("daily")}, h)
        check("缺首评时记日常 → 409", code == 409, f"HTTP {code} {str(err)[:150]}")
        check("409 指出缺哪份文书",
              isinstance(err, dict) and err.get("details", {}).get("missing_document") == "initial",
              str(err)[:150])

        # ---------------------------------------------------------------- #
        # 3) 必填校验
        # ---------------------------------------------------------------- #
        code, err = request("/api/v1/records", "POST",
                            {"patient_no": PN, "record_date": "2026-10-05", "discipline": "PT",
                             "kind": "initial", "body": {}, "status": "submitted"}, h)
        check("空答案提交首评 → 422", code == 422, f"HTTP {code}")
        missing = (err or {}).get("details", {}).get("missing") or []
        check("422 用中文标签指出缺失字段", "功能诊断" in missing, str(missing))

        # ---------------------------------------------------------------- #
        # 4) 建首评（不占次数）→ 同一天记日常（第 1 次）
        # ---------------------------------------------------------------- #
        code, initial = request("/api/v1/records", "POST",
                                {"patient_no": PN, "record_date": "2026-10-05",
                                 "discipline": "PT", "kind": "initial",
                                 "body": diagnose("initial"), "status": "submitted"}, h)
        check("建首评成功", code == 201, f"HTTP {code} {str(initial)[:150]}")
        check("首评 seq_no 为 None（不计次）", initial["seq_no"] is None, str(initial.get("seq_no")))
        check("首评 span_seq=1", initial["span_seq"] == 1, str(initial.get("span_seq")))
        check("rendered_text 是 SOAP 文本、含『主观资料：』",
              "主观资料：" in initial["rendered_text"], initial["rendered_text"][:120])

        code, daily1 = request("/api/v1/records", "POST",
                               {"patient_no": PN, "record_date": "2026-10-05",
                                "discipline": "PT", "kind": "daily",
                                "body": diagnose("daily"), "status": "submitted"}, h)
        check("首评后同一天可记日常", code == 201, f"HTTP {code} {str(daily1)[:150]}")
        check("★ 首评不占次数：当天日常是第 1 次", daily1["seq_no"] == 1, str(daily1.get("seq_no")))

        # ---------------------------------------------------------------- #
        # 5) 同一天同一大类至多 2 条
        # ---------------------------------------------------------------- #
        code, _ = request("/api/v1/records", "POST",
                          {"patient_no": PN, "record_date": "2026-10-05", "discipline": "PT",
                           "kind": "daily", "body": diagnose("daily")}, h)
        check("同一天第 3 条 → 409", code == 409, f"HTTP {code}")

        # ---------------------------------------------------------------- #
        # 6) 复评触发点：第 21 次日常前必须先复评
        # ---------------------------------------------------------------- #
        for i in range(2, 21):
            request("/api/v1/records", "POST",
                    {"patient_no": PN, "record_date": f"2026-10-{i + 4:02d}",
                     "discipline": "PT", "kind": "daily", "body": diagnose("daily"),
                     "status": "submitted"}, h)
        code, form21 = request(f"/api/v1/records/form?patient_no={PN}&discipline=PT"
                               f"&date=2026-10-25", token=h)
        check("满 20 次后表单要求复评", form21["kind"] == "reassessment", str(form21["kind"]))
        check("复评 prefill 来自上次评估",
              "mmt_upper" in (form21.get("prefill") or {}), str(list((form21.get("prefill") or {}).keys()))[:120])

        code, err = request("/api/v1/records", "POST",
                            {"patient_no": PN, "record_date": "2026-10-25", "discipline": "PT",
                             "kind": "daily", "body": diagnose("daily")}, h)
        check("缺复评时记第 21 次 → 409", code == 409, f"HTTP {code}")
        check("409 指出缺 reassessment",
              (err or {}).get("details", {}).get("missing_document") == "reassessment", str(err)[:150])

        # ---------------------------------------------------------------- #
        # 7) 评估文书之间互不干扰：四大类各有各的首评
        # ---------------------------------------------------------------- #
        code, ot_form = request(f"/api/v1/records/form?patient_no={PN}&discipline=OT", token=h)
        check("★ 换大类仍要各自的首评（OT 也要首评）",
              code == 200 and ot_form["kind"] == "initial", str(ot_form.get("kind")))

        # ---------------------------------------------------------------- #
        # 8) 出院小结 → 发起出院 → 待出院后不能再记
        # ---------------------------------------------------------------- #
        code, dx = request(f"/api/v1/records/form?patient_no={PN}&discipline=PT&kind=discharge", token=h)
        check("出院小结表单可取（需显式传 kind）", code == 200 and dx["kind"] == "discharge",
              f"HTTP {code} {str(dx)[:120]}")
        check("出院小结的治疗过程汇总是自动生成的",
              "共治疗" in json.dumps(dx.get("prefill") or {}, ensure_ascii=False),
              str(dx.get("prefill", {}).get("summary"))[:160])

        code, rec = request("/api/v1/records", "POST",
                            {"patient_no": PN, "record_date": "2026-11-01", "discipline": "PT",
                             "kind": "discharge", "body": diagnose("discharge"),
                             "status": "submitted"}, h)
        check("建出院小结成功", code == 201, f"HTTP {code} {str(rec)[:150]}")

        code, pat = request(f"/api/v1/patients/{PN}/discharge", "POST",
                            {"record_id": rec["id"]}, h)
        check("★ 普通治疗师可发起出院", code == 200, f"HTTP {code} {str(pat)[:150]}")
        check("发起后状态为待出院", (pat or {}).get("status") == "pending_discharge",
              str((pat or {}).get("status")))

        code, _ = request("/api/v1/records", "POST",
                          {"patient_no": PN, "record_date": "2026-11-02", "discipline": "PT",
                           "kind": "daily", "body": diagnose("daily")}, h)
        check("★ 待出院期间不能再记治疗 → 409", code == 409, f"HTTP {code}")

        code, dept = request("/api/v1/patients?scope=dept&page_size=200", token=h)
        listed = [i["inpatient_no"] for i in (dept or {}).get("items", [])]
        check("★ 待出院患者从治疗师白板消失", PN not in listed, str(listed[:15]))

        code, back = request(f"/api/v1/patients/{PN}/discharge/cancel", "POST", {}, at)
        check("管理员可取消待出院（患者反悔）", code == 200 and back["status"] == "in_hospital",
              f"HTTP {code} {str(back)[:120]}")

        code, again = request(f"/api/v1/patients/{PN}/discharge/cancel", "POST", {}, h)
        check("普通治疗师不能确认/取消出院 → 403", code == 403, f"HTTP {code}")

        # ---------------------------------------------------------------- #
        # 9) rendered_text 冻结：改模板不影响已存记录
        # ---------------------------------------------------------------- #
        code, got = request(f"/api/v1/records/{daily1['id']}", token=h)
        check("单条记录可读且带 body", code == 200 and isinstance(got.get("body"), dict),
              f"HTTP {code}")
        check("rendered_text 与建时一致（冻结）",
              got["rendered_text"] == daily1["rendered_text"])

        # ---------------------------------------------------------------- #
        # 10) 汇总输出 SOAP 文本（不是表格）
        # ---------------------------------------------------------------- #
        code, s = request("/api/v1/summary/date?date=2026-10-05", token=h)
        check("当日汇总可读", code == 200, f"HTTP {code}")
        # 结构是 {date, group_by, totals, groups:[{key, totals, rows:[…]}]}，
        # 每条记录的 SOAP 文本在 groups[].rows[].rendered_text 里。
        rows = [r for g in (s or {}).get("groups", []) for r in g.get("rows", [])]
        check("当日汇总按分组返回记录行", bool(rows), str(list((s or {}).keys())))
        texts = [str(r.get("rendered_text") or "") for r in rows]
        # ⚠ 断言要按**设计**写：没填的字段/段落整条不出现。
        # 这里的日常记录只填了「本次训练项目」，所以**不该**出现「主观资料：」——
        # 第一版断言写成"必须含主观资料"是错的（已修）。
        check("★ 当日汇总的正文是 SOAP 文本（段名 + 冒号，非表格）",
              any("客观资料：" in t for t in texts), (texts[0][:150] if texts else "无行"))
        check("★ 没填的段落整段不出现（本次日常未填 S 段）",
              all("主观资料：" not in t for t in texts), (texts[0][:200] if texts else "无行"))
        check("★ 不再有表格痕迹（无 '---|---'、无参数快照字段）",
              "---|---" not in json.dumps(s, ensure_ascii=False))
        check("计数只算日常记录（totals.record_count 与日常条数一致）",
              (s.get("totals") or {}).get("record_count") == len(rows),
              f"totals={s.get('totals')} rows={len(rows)}")

    finally:
        conn = storage.connect(settings)
        try:
            purge_patients(conn, [PN])
            conn.commit()
        finally:
            conn.close()
        server.should_exit = True
        thread.join(timeout=10)

    print()
    if failures:
        print(f"SOAP 流程验收：{len(failures)} 项失败")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("SOAP 流程验收：全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
