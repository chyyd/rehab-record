"""阶段 5 端到端验证：汇总、打印（三套 PDF）、模板与后台。

跑真实 uvicorn + 真实 HTTP，并**用 pypdf 反向提取中文文本**确认 PDF 真的印出了中文
（这是唯一能发现"满页方框"的手段）。

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
from _e2e import purge_option_sets, purge_patients  # noqa: E402

HOST = "127.0.0.1"
ADMIN_PW = "Admin#2026pass"
THERAPIST_PW = "Ther#2026pass"

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
    from seed.dictionary import seed_dictionary
    from seed.options import seed_options
    from seed.responses import seed_responses
    from seed.templates import seed_templates

    settings = get_settings()
    if not settings.db_path.exists():
        print(f"数据库不存在：{settings.db_path}（请先执行 app.cli init）", file=sys.stderr)
        return 2

    conn = storage.connect(settings)
    try:
        storage.migrate(conn, storage.discover_migrations(settings=settings))
        # 先清上一轮遗留，**再**导种子 —— 顺序反了会把刚导进去的科室模板又删掉
        # （包括四大高频模板种子），后面的断言就会看到空列表。
        conn.execute(
            "DELETE FROM record_template_item WHERE template_id IN"
            " (SELECT id FROM record_template WHERE name LIKE '%·常规'"
            "    OR name IN ('我的运动组合', '全科运动模板'))"
        )
        conn.execute(
            "DELETE FROM record_template WHERE name LIKE '%·常规'"
            " OR name IN ('我的运动组合', '全科运动模板')"
        )

        seed_dictionary(conn)
        seed_responses(conn)
        seed_options(conn)
        # 模板种子依赖字典里的主项目/子项目，必须最后导（与 app.cli seed 的顺序一致）
        seed_templates(conn)

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

        # 清理上次运行遗留（按外键顺序，见 scripts/_e2e.py）
        for no in ("S5A", "S5B"):
            purge_patients(conn, [no])
        # 模板与个人选项集的清理已在开头（导入种子之前）完成，此处不再重复
        purge_option_sets(conn, scope="personal", owner_user_id=ids["T001"])
        conn.execute("UPDATE sub_item SET status = 'active'")

        patient_model.create_patient(
            conn, inpatient_no="S5A", name="阶段五患者甲", diagnosis="脑卒中恢复期",
            admin_note="左侧偏瘫，注意防跌倒", assigned_therapist_id=ids["T001"],
        )
        patient_model.create_patient(
            conn, inpatient_no="S5B", name="阶段五患者乙", assigned_therapist_id=ids["T002"]
        )

        motor_main = int(
            conn.execute("SELECT id FROM main_item WHERE code = 'motor_function'").fetchone()["id"]
        )
        swallow_main = int(
            conn.execute("SELECT id FROM main_item WHERE code = 'swallow_function'").fetchone()["id"]
        )
        motor_subs = conn.execute(
            "SELECT id FROM sub_item WHERE main_item_id = ? ORDER BY sort", (motor_main,)
        ).fetchall()
        motor_sub = int(motor_subs[0]["id"])
        motor_sub2 = int(motor_subs[1]["id"])
        swallow_sub = int(
            conn.execute(
                "SELECT id FROM sub_item WHERE main_item_id = ? ORDER BY sort", (swallow_main,)
            ).fetchone()["id"]
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

    def write_record(patient_no, day, period, main_id, sub_id, params, note=None, duration=30, headers=None):
        return request(
            "/api/v1/records", "POST",
            {"patient_no": patient_no, "record_date": day, "session_period": period,
             "duration_min": duration, "status": "submitted", "note": note,
             "patient_response": {"tags": ["no_discomfort"], "items": [{"code": "pain", "value": 3}]},
             "items": [{"main_item_id": main_id, "sub_item_id": sub_id, "params": params}]},
            headers,
        )

    try:
        _, admin = request("/api/v1/auth/login", "POST", {"employee_no": "A001", "password": ADMIN_PW})
        _, t1 = request("/api/v1/auth/login", "POST", {"employee_no": "T001", "password": THERAPIST_PW})
        _, t2 = request("/api/v1/auth/login", "POST", {"employee_no": "T002", "password": THERAPIST_PW})
        ha, h1, h2 = admin["access_token"], t1["access_token"], t2["access_token"]

        # 造数据：甲患者 2 天 3 条，乙患者 1 条
        write_record("S5A", "2027-07-01", "am", motor_main, motor_sub,
                     {"side": "左", "position": "坐位"}, "首次治疗", headers=h1)
        write_record("S5A", "2027-07-01", "pm", swallow_main, swallow_sub, {}, "当日第二次", headers=h1)
        write_record("S5A", "2027-07-03", "am", motor_main, motor_sub, {"side": "右"}, headers=h1)
        write_record("S5B", "2027-07-01", "am", motor_main, motor_sub, {"side": "左"}, headers=h2)
        # 一条草稿：不应计入汇总
        request("/api/v1/records", "POST",
                {"patient_no": "S5A", "record_date": "2027-07-05", "session_period": "am",
                 "status": "draft",
                 "items": [{"main_item_id": motor_main, "sub_item_id": motor_sub, "params": {}}]},
                h1)

        # 1) 按日期汇总
        code, summary = request("/api/v1/summary/date" + q(date="2027-07-01"), token=ha)
        check("按日期汇总可用", code == 200, str(code))
        check("汇总只计已提交（草稿不计入）", summary["totals"]["record_count"] == 3,
              str(summary["totals"]))
        check("总时长正确", summary["totals"]["total_duration_min"] == 90, str(summary["totals"]))
        check("主项目频次已统计", summary["totals"]["main_item_counts"].get("运动功能障碍训练") == 2,
              str(summary["totals"]["main_item_counts"]))
        code, grouped = request(
            "/api/v1/summary/date" + q(date="2027-07-01", group_by="therapist"), token=ha
        )
        check("按治疗师分组", {g["key"] for g in grouped["groups"]} == {"张三", "李四"},
              str([g["key"] for g in grouped["groups"]]))
        raw = grouped["groups"][0]["rows"][0]
        check("参数摘要用显示名", "侧别：" in raw["params_digest"], raw["params_digest"])
        check("反应摘要含标签与评分",
              "无不适" in raw["response_digest"] and "疼痛 3分" in raw["response_digest"],
              raw["response_digest"])

        # 2) 按患者每日汇总
        code, daily = request("/api/v1/summary/patient/S5A", token=h1)
        check("按患者每日汇总可用", code == 200, str(code))
        check("同一天合并为一行", [d["record_date"] for d in daily["days"]] == ["2027-07-03", "2027-07-01"],
              str([d["record_date"] for d in daily["days"]]))
        day0701 = next(d for d in daily["days"] if d["record_date"] == "2027-07-01")
        check("当天两个主项目都列出", len(day0701["main_items"]) == 2, str(day0701["main_items"]))

        code, ranged = request(
            "/api/v1/summary/patient/S5A" + q(**{"from": "2027-07-02", "to": "2027-07-04"}), token=h1
        )
        check("日期范围筛选", [d["record_date"] for d in ranged["days"]] == ["2027-07-03"],
              str([d["record_date"] for d in ranged["days"]]))

        # 3) 单患者总览
        code, overview = request("/api/v1/summary/patient/S5A/overview", token=h1)
        check("单患者总览含归属治疗师",
              overview["patient"]["assigned_therapist_name"] == "张三" and len(overview["records"]) == 3,
              str(overview["patient"])[:160])

        # 4) 三套 PDF
        code, data = request("/api/v1/print/patient/S5A", token=h1)
        check("单患者汇总 PDF 生成", code == 200 and data[:4] == b"%PDF", str(code))
        text = pdf_text(data)
        for expected in ("康复医学科", "阶段五患者甲", "S5A", "脑卒中恢复期", "张三", "汇总统计"):
            check(f"PDF 含「{expected}」", expected in text)
        check("PDF 无签名栏（Q10）", "签名" not in text)
        check("PDF 页脚含页码与打印时间", "第 1 页" in text and "打印时间：" in text)

        code, data2 = request("/api/v1/print/summary/date" + q(date="2027-07-01"), token=ha)
        check("按日期汇总 PDF 生成", code == 200 and data2[:4] == b"%PDF", str(code))
        text2 = pdf_text(data2)
        check("日期汇总 PDF 含日期与患者", "2027-07-01" in text2 and "阶段五患者甲" in text2,
              text2[:160])

        code, data3 = request("/api/v1/print/summary/patient/S5A", token=h1)
        check("按患者每日汇总 PDF 生成", code == 200 and data3[:4] == b"%PDF", str(code))
        text3 = pdf_text(data3)
        check("每日汇总 PDF 含两个日期", "2027-07-01" in text3 and "2027-07-03" in text3, text3[:160])

        # 5) 打印的权限边界
        # 5) 白板下的打印边界：同事负责的在院患者也可打印/汇总
        code, data_b = request("/api/v1/print/patient/S5B", token=h1)
        check("白板：可打印同事负责患者的汇总 PDF",
              code == 200 and data_b[:4] == b"%PDF", str(code))
        code, sum_b = request("/api/v1/summary/patient/S5B", token=h1)
        check("白板：可汇总同事负责患者", code == 200, str(code))

        code, data4 = request("/api/v1/print/summary/date" + q(date="2027-07-01"), token=h1)
        text4 = pdf_text(data4)
        check("日期汇总覆盖全科在院患者", "阶段五患者甲" in text4 and "阶段五患者乙" in text4,
              text4[:200])

        # 5b) 已出院患者默认不在白板范围内 —— 这才是权限边界
        #     用公开接口改状态（本脚本不持有数据库连接；ha 是管理员令牌）
        code, _ = request("/api/v1/patients/S5B", "PUT", {"status": "discharged"}, token=ha)
        check("准备权限边界用例：置为已出院", code == 200, str(code))
        code, err = request("/api/v1/print/patient/S5B", token=h1)
        check("已出院患者不可打印 → 403",
              code == 403 and err["code"] == "PATIENT_NOT_VISIBLE", str(err)[:120])
        code, err = request("/api/v1/summary/patient/S5B", token=h1)
        check("已出院患者不可汇总 → 403", code == 403, str(code))
        # 复原，避免影响后续断言（管理员可把已出院改回在院）
        code, _ = request("/api/v1/patients/S5B", "PUT", {"status": "in_hospital"}, token=ha)
        check("恢复为在院", code == 200, str(code))

        # 6) 模板
        code, tpl = request(
            "/api/v1/templates", "POST",
            {"name": "我的运动组合", "scope": "personal", "main_item_id": motor_main,
             "items": [{"sub_item_id": motor_sub, "params": {"side": "左", "position": "坐位"}},
                       {"sub_item_id": motor_sub2, "params": {}}]},
            h1,
        )
        check("创建个人模板", code == 201 and len(tpl["items"]) == 2, f"{code} {str(tpl)[:160]}")
        check("个人模板归属自己", tpl["owner_user_id"] == ids["T001"], str(tpl["owner_user_id"]))

        code, applied = request(f"/api/v1/templates/{tpl['id']}/apply", "POST", {}, h1)
        check("一键套用返回预填参数",
              code == 200 and len(applied["items"]) == 2
              and applied["items"][0]["params"]["position"] == "坐位", str(applied)[:200])
        check("套用只是预填（有说明）", "仅为预填" in applied["note"], applied["note"])

        code, err = request(
            "/api/v1/templates", "POST",
            {"name": "全科模板", "scope": "dept", "main_item_id": motor_main,
             "items": [{"sub_item_id": motor_sub}]},
            h1,
        )
        check("治疗师不能建科室模板 → 403", code == 403 and err["code"] == "DEPT_TEMPLATE_ADMIN_ONLY",
              str(err)[:140])

        # 6a) 四大高频模板种子（科室模板）应当已由 `app.cli seed` 导入
        code, seeded = request("/api/v1/templates", token=h1)
        by_code = {t.get("code"): t for t in seeded if t.get("code")}
        expected_codes = {
            "tpl_motor_function", "tpl_adl_skill", "tpl_speech_function", "tpl_swallow_function",
        }
        check("四大高频模板种子已导入", expected_codes <= set(by_code), str(sorted(by_code)))
        if expected_codes <= set(by_code):
            # 注意：列表接口不返回明细（items），明细数要从详情接口取
            counts = {}
            for tpl_code in sorted(expected_codes):
                _, detail = request(f"/api/v1/templates/{by_code[tpl_code]['id']}", token=h1)
                counts[tpl_code] = len(detail["items"])
            check("模板明细数与子项目数一致（6/8/6/9）",
                  counts == {"tpl_adl_skill": 8, "tpl_motor_function": 6,
                             "tpl_speech_function": 6, "tpl_swallow_function": 9},
                  str(counts))
            check("种子模板都是科室级且无归属人",
                  all(by_code[c]["scope"] == "dept" and by_code[c]["owner_user_id"] is None
                      for c in expected_codes))
            # 套用运动模板，确认预填参数可直接用于建记录
            code, applied_seed = request(
                f"/api/v1/templates/{by_code['tpl_motor_function']['id']}/apply", "POST", {}, h1
            )
            check("套用运动模板返回 6 项预填",
                  code == 200 and len(applied_seed["items"]) == 6, f"{code} {str(applied_seed)[:160]}")
            first_item = applied_seed["items"][0]
            check("预填参数类型正确（数字是数字、单选是标量）",
                  isinstance(first_item["params"].get("reps"), int)
                  and isinstance(first_item["params"].get("position"), str),
                  str(first_item["params"]))
            code, from_tpl = request(
                "/api/v1/records", "POST",
                {"patient_no": "S5A", "record_date": "2027-07-08", "session_period": "pm",
                 "items": [{"main_item_id": first_item["main_item_id"],
                            "sub_item_id": first_item["sub_item_id"],
                            "params": first_item["params"]}]},
                h1,
            )
            check("用套用参数直接建记录成功", code == 201, f"{code} {str(from_tpl)[:160]}")

        code, dept_tpl = request(
            "/api/v1/templates", "POST",
            {"name": "全科运动模板", "scope": "dept", "main_item_id": motor_main,
             "items": [{"sub_item_id": motor_sub, "params": {"side": "双侧"}}]},
            ha,
        )
        check("管理员建科室模板", code == 201 and dept_tpl["owner_user_id"] is None,
              f"{code} {str(dept_tpl)[:140]}")

        code, listed = request("/api/v1/templates", token=h1)
        listed_names = {t["name"] for t in listed}
        # 科室模板（含四大高频模板种子）+ 自己的个人模板都应可见；
        # 他人（李四）的个人模板不可见。
        check("列表含自己的个人模板与全部科室模板",
              {"我的运动组合", "全科运动模板"} <= listed_names
              and expected_codes <= {t.get("code") for t in listed}
              and "李四的模板" not in listed_names,
              str(sorted(listed_names)))
        code, listed2 = request("/api/v1/templates", token=h2)
        listed2_names = {t["name"] for t in listed2}
        check("他人看不到我的个人模板",
              "我的运动组合" not in listed2_names and "全科运动模板" in listed2_names,
              str(sorted(listed2_names)))

        code, err = request(f"/api/v1/templates/{tpl['id']}", token=h2)
        check("他人看不到我的个人模板详情 → 403", code == 403 and err["code"] == "TEMPLATE_NOT_VISIBLE",
              str(err)[:120])

        code, err = request(f"/api/v1/templates/{dept_tpl['id']}", "DELETE", {}, h1)
        check("治疗师不能删科室模板 → 403", code == 403, str(code))

        # 7) 后台：选项集
        code, opt = request(
            "/api/v1/admin/option-sets", "PUT",
            {"code": "side", "name": "全科侧别", "values": ["左", "右", "双侧"], "default_values": ["左"]},
            ha,
        )
        check("管理员维护全局选项集", code == 200 and opt["scope"] == "global", f"{code} {str(opt)[:140]}")

        code, resolved = request("/api/v1/option-sets/resolve" + q(code="side"), token=h1)
        # 解析顺序是 个人 → 科室 → 全局。本脚本开头已清掉该治疗师的个人选项集，
        # 因此这里应回落到刚设的全局层；若个人层还在，它会（正确地）盖住全局 ——
        # 那正是 verify_stage3 跑过之后本项会失败的原因，属真实层叠语义而非缺陷。
        check("治疗师立刻看到新选项（回落到全局层）",
              resolved["source"] == "global" and len(resolved["options"]) == 3,
              str(resolved)[:200])

        code, err = request(
            "/api/v1/admin/option-sets", "PUT",
            {"code": "side2", "name": "x", "values": ["左"]},
            h1,
        )
        check("治疗师不能改全局选项集 → 403", code == 403, str(code))

        code, all_sets = request("/api/v1/admin/option-sets" + q(scope="global"), token=ha)
        check("管理员可总览全部选项集",
              code == 200 and all(s["scope"] == "global" for s in all_sets), str(code))

        # 8) 后台：审计日志
        code, logs = request("/api/v1/audit-logs", token=ha)
        check("管理员可查审计日志", code == 200 and logs["total"] > 0, str(code))
        check("审计日志带操作人姓名", logs["items"][0].get("user_name") is not None,
              str(logs["items"][0])[:160])

        code, filtered = request("/api/v1/audit-logs" + q(target_type="option_set"), token=ha)
        check("按对象类型筛选审计",
              filtered["total"] > 0
              and all(i["target_type"] == "option_set" for i in filtered["items"]),
              str(filtered["total"]))

        code, facets = request("/api/v1/audit-logs/facets", token=ha)
        check("审计筛选维度可用",
              "treatment_record" in facets["target_types"] and "create" in facets["actions"],
              str(facets)[:160])

        code, err = request("/api/v1/audit-logs", token=h1)
        check("治疗师不能查审计日志 → 403", code == 403, str(code))

        # 9) OpenAPI 收录阶段 5 接口
        code, schema = request("/openapi.json")
        wanted = {
            "/api/v1/summary/date", "/api/v1/summary/patient/{inpatient_no}",
            "/api/v1/print/patient/{inpatient_no}", "/api/v1/print/summary/date",
            "/api/v1/print/summary/patient/{inpatient_no}",
            "/api/v1/templates", "/api/v1/templates/{template_id}/apply",
            "/api/v1/audit-logs", "/api/v1/admin/option-sets",
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
