"""阶段 3 端到端验证：字典、选项集、治疗记录与患者反应。

跑真实 uvicorn + 真实 HTTP，覆盖：字典树 → 记录表单（含带入值）→ 创建/提交/锁定
→ 留痕与 edit_count → 两层快照 → 患者反应校验 → 权限边界 → 时间轴。

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
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return exc.code, (json.loads(raw) if raw else None)


def q(**params: object) -> str:
    return "?" + urllib.parse.urlencode(params)


def main() -> int:
    from app.core.config import get_settings
    from app.db import storage
    from app.main import create_app
    from app.models import patient as patient_model
    from app.models import user as user_model
    from seed.dictionary import seed_dictionary
    from seed.options import seed_options
    from seed.responses import seed_responses

    settings = get_settings()
    if not settings.db_path.exists():
        print(f"数据库不存在：{settings.db_path}（请先执行 app.cli init）", file=sys.stderr)
        return 2

    conn = storage.connect(settings)
    try:
        storage.migrate(conn, storage.discover_migrations(settings=settings))
        # 种子里是幂等的，可以放心重复导入
        seed_dictionary(conn)
        seed_responses(conn)
        seed_options(conn)

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

        # 清理上次运行遗留
        for no in ("S3A", "S3B"):
            purge_patients(conn, [no])
        purge_option_sets(conn, scope="personal", owner_user_id=ids["T001"])

        patient_model.create_patient(
            conn, inpatient_no="S3A", name="阶段三患者甲", assigned_therapist_id=ids["T001"]
        )
        patient_model.create_patient(
            conn, inpatient_no="S3B", name="阶段三患者乙", assigned_therapist_id=ids["T002"]
        )

        motor_main = int(conn.execute("SELECT id FROM main_item WHERE code = 'motor_function'").fetchone()["id"])
        swallow_main = int(
            conn.execute("SELECT id FROM main_item WHERE code = 'swallow_function'").fetchone()["id"]
        )
        subs = conn.execute(
            "SELECT id, code FROM sub_item WHERE main_item_id = ? ORDER BY sort", (motor_main,)
        ).fetchall()
        motor_sub = int(subs[0]["id"])
        swallow_row = conn.execute(
            "SELECT id FROM sub_item WHERE main_item_id = ? ORDER BY sort", (swallow_main,)
        ).fetchone()
        swallow_sub = int(swallow_row["id"])
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
        _, t2 = request("/api/v1/auth/login", "POST", {"employee_no": "T002", "password": THERAPIST_PW})
        at, h1, h2 = admin["access_token"], t1["access_token"], t2["access_token"]

        # 1) 字典
        code, tree = request("/api/v1/dict/tree", token=h1)
        ok = code == 200 and len(tree) == 4
        n_sub = sum(len(m["sub_items"]) for m in tree) if ok else 0
        check("字典树：4 个主项目", ok, str(code))
        check("字典树：子项目已展开且带参数", n_sub >= 25 and all(m["sub_items"] for m in tree), str(n_sub))

        # 2) 选项解析顺序
        code, resolved = request("/api/v1/option-sets/resolve" + q(code="side"), token=h1)
        check("侧别回落到全局选项集", code == 200 and resolved["source"] == "global", str(resolved)[:140])

        code, _ = request(
            "/api/v1/option-sets/personal", "PUT",
            {"code": "side", "name": "我的侧别", "values": ["左", "右"], "default_values": ["左"]}, h1,
        )
        check("设置个人快捷选项", code == 200, str(code))
        code, mine = request("/api/v1/option-sets/resolve" + q(code="side"), token=h1)
        check("个人选项优先于全局", mine["source"] == "personal" and len(mine["options"]) == 2, str(mine["source"]))
        code, other = request("/api/v1/option-sets/resolve" + q(code="side"), token=h2)
        check("个人选项不影响他人", other["source"] == "global", other["source"])

        # 3) 记录表单
        code, form = request("/api/v1/records/form" + q(patient_no="S3A"), token=h1)
        check("记录页表单可用", code == 200 and form["patient"]["name"] == "阶段三患者甲", str(code))
        motor = next(m for m in form["main_items"] if m["code"] == "motor_function")
        sub = next(s for s in motor["sub_items"] if int(s["id"]) == motor_sub)
        position = next(p for p in sub["params"] if p["param_key"] == "position")
        check("参数已解析选项并给出带入值",
              position["current_value"] is not None and position["value_source"] in
              {"option_set_default", "dict_default", "last_value"},
              str(position)[:160])
        check("表单含患者反应定义", len(form["response_defs"]) > 0, str(len(form["response_defs"])))

        # 4) 创建草稿：草稿不占序次
        code, draft = request(
            "/api/v1/records", "POST",
            {"patient_no": "S3A", "record_date": "2027-03-01", "session_period": "am",
             "duration_min": 30, "note": "首次记录", "status": "draft",
             "items": [{"main_item_id": motor_main, "sub_item_id": motor_sub,
                        "params": {"position": "坐位", "side": "左", "reps": 10}}]},
            h1,
        )
        check("创建草稿", code == 201 and draft["status"] == "draft", str(draft)[:160])
        check("草稿不占治疗序次", draft["seq_no"] is None, str(draft["seq_no"]))
        check("明细带子项目名称快照",
              draft["items"][0]["sub_item_name_snapshot"] == "偏瘫肢体综合训练",
              str(draft["items"][0]["sub_item_name_snapshot"]))

        # 5) 草稿修改不留痕
        request(f"/api/v1/records/{draft['id']}", "PUT", {"note": "草稿改一下"}, h1)
        code, after_draft_edit = request(f"/api/v1/records/{draft['id']}", token=h1)
        check("草稿修改不累加 edit_count", after_draft_edit["edit_count"] == 0, str(after_draft_edit["edit_count"]))

        # 6) 提交 → 序次
        code, submitted = request(f"/api/v1/records/{draft['id']}/submit", "POST", {}, h1)
        check("提交记录并分配序次", code == 200 and submitted["seq_no"] == 1, str(submitted)[:160])

        # 7) 提交后修改：留痕 + edit_count
        code, edited = request(
            f"/api/v1/records/{draft['id']}", "PUT", {"note": "提交后补充说明"}, h1
        )
        check("提交后修改累加 edit_count", code == 200 and edited["edit_count"] == 1,
              str(edited.get("edit_count")))

        # 8) 参数校验：未知键 / 非选项值
        code, err = request(
            "/api/v1/records", "POST",
            {"patient_no": "S3A", "record_date": "2027-03-02",
             "items": [{"main_item_id": motor_main, "sub_item_id": motor_sub, "params": {"nope": 1}}]},
            h1,
        )
        check("未知参数键被拒", code == 422 and "unknown_keys" in err["details"], str(err)[:160])
        code, err = request(
            "/api/v1/records", "POST",
            {"patient_no": "S3A", "record_date": "2027-03-02",
             "items": [{"main_item_id": motor_main, "sub_item_id": motor_sub, "params": {"side": "上面"}}]},
            h1,
        )
        check("非选项值被拒", code == 422 and "allowed" in err["details"], str(err)[:160])

        # 9) 患者反应
        code, with_resp = request(
            "/api/v1/records", "POST",
            {"patient_no": "S3A", "record_date": "2027-03-03", "session_period": "pm",
             "status": "submitted",
             "patient_response": {"tags": ["no_discomfort"], "items": [{"code": "pain", "value": 3}]},
             "items": [{"main_item_id": motor_main, "sub_item_id": motor_sub, "params": {"side": "左"}}]},
            h1,
        )
        check("患者反应（标签 + NRS 评分）", code == 201, str(with_resp)[:200])
        if code == 201:
            resp_data = with_resp["patient_response"]
            check("标签带 label 快照", resp_data["tags"][0]["label"] == "无不适", str(resp_data["tags"]))
            check("评分带 value_key 与单位",
                  resp_data["items"][0]["value_key"] == "nrs" and resp_data["items"][0]["unit"] == "分",
                  str(resp_data["items"]))

        code, err = request(
            "/api/v1/records", "POST",
            {"patient_no": "S3A", "record_date": "2027-03-04",
             "patient_response": {"tags": [], "items": [{"code": "pain", "value": 99}]},
             "items": [{"main_item_id": motor_main, "sub_item_id": motor_sub, "params": {}}]},
            h1,
        )
        check("评分越界被拒", code == 422, str(err)[:140])

        code, err = request(
            "/api/v1/records", "POST",
            {"patient_no": "S3A", "record_date": "2027-03-04",
             "patient_response": {"tags": ["pain"], "items": []},
             "items": [{"main_item_id": motor_main, "sub_item_id": motor_sub, "params": {}}]},
            h1,
        )
        check("需取值的反应放进 tags 被拒", code == 422, str(err)[:140])

        # 10) 锁定与权限
        code, locked = request(f"/api/v1/records/{draft['id']}/lock", "POST", {}, at)
        check("管理员锁定记录", code == 200 and locked["status"] == "locked", str(locked)[:140])
        code, err = request(f"/api/v1/records/{draft['id']}", "PUT", {"note": "偷改"}, h1)
        check("锁定后治疗师不能改", code == 403 and err["code"] == "RECORD_LOCKED", str(err)[:140])

        code, err = request("/api/v1/records" + q(patient_no="S3B"), token=h1)
        check("治疗师看不到他人患者记录",
              code == 200 and err["total"] == 0, str(err.get("total")))

        code, err = request(
            "/api/v1/records", "POST",
            {"patient_no": "S3B", "record_date": "2027-03-01",
             "items": [{"main_item_id": motor_main, "sub_item_id": motor_sub, "params": {}}]},
            h1,
        )
        check("不能给不可见患者写记录", code == 403 and err["code"] == "PATIENT_NOT_VISIBLE", str(err)[:140])

        # 11) 时间轴
        code, tl = request("/api/v1/timeline", token=h1)
        check("时间轴按日期倒序", code == 200 and tl["total"] >= 2, str(tl.get("total")))
        if code == 200 and tl["items"]:
            dates = [i["record_date"] for i in tl["items"]]
            check("时间轴日期确实倒序", dates == sorted(dates, reverse=True), str(dates))
            check("时间轴带主项目名称",
                  any("运动功能障碍训练" in i["main_item_names"] for i in tl["items"]),
                  str([i["main_item_names"] for i in tl["items"]])[:160])

        # 12) 快照抵御字典改名
        conn = storage.connect(settings)
        try:
            conn.execute("UPDATE sub_item SET name = '偏瘫综合训练（改名后）' WHERE id = ?", (motor_sub,))
        finally:
            conn.close()
        code, reread = request(f"/api/v1/records/{draft['id']}", token=h1)
        check("字典改名不影响历史快照",
              reread["items"][0]["sub_item_name_snapshot"] == "偏瘫肢体综合训练",
              str(reread["items"][0]["sub_item_name_snapshot"]))
        conn = storage.connect(settings)
        try:
            conn.execute("UPDATE sub_item SET name = '偏瘫肢体综合训练' WHERE id = ?", (motor_sub,))
        finally:
            conn.close()

        # 13) 吞嚥主项目的反应专属校验
        code, err = request(
            "/api/v1/records", "POST",
            {"patient_no": "S3A", "record_date": "2027-03-06",
             "patient_response": {"tags": [], "items": [{"code": "oral_residue", "value": "中"}]},
             "items": [{"main_item_id": motor_main, "sub_item_id": motor_sub, "params": {}}]},
            h1,
        )
        check("其他主项目的专属反应被拒（口腔残留不在运动项目下）", code == 422, str(err)[:160])

        code, ok_swallow = request(
            "/api/v1/records", "POST",
            {"patient_no": "S3A", "record_date": "2027-03-06",
             "patient_response": {"tags": [], "items": [{"code": "oral_residue", "value": "中"}]},
             "items": [{"main_item_id": swallow_main, "sub_item_id": swallow_sub, "params": {}}]},
            h1,
        )
        check("吞嚥主项目下该反应可用", code == 201, str(ok_swallow)[:160])

        # 14) 带入"上次值"（F3.7）
        code, form2 = request("/api/v1/records/form" + q(patient_no="S3A"), token=h1)
        motor2 = next(m for m in form2["main_items"] if m["code"] == "motor_function")
        sub2 = next(s for s in motor2["sub_items"] if int(s["id"]) == motor_sub)
        side2 = next(p for p in sub2["params"] if p["param_key"] == "side")
        check("参数带入上次值", side2["value_source"] == "last_value" and side2["current_value"] == "左",
              f"{side2['value_source']} / {side2['current_value']}")

        # 15) OpenAPI 收录阶段 3 接口
        code, schema = request("/openapi.json")
        paths = set(schema["paths"])
        wanted = {"/api/v1/dict/tree", "/api/v1/records", "/api/v1/records/form",
                  "/api/v1/timeline", "/api/v1/response-defs", "/api/v1/option-sets/resolve"}
        check("OpenAPI 收录阶段 3 接口", wanted <= paths, str(sorted(wanted - paths)))
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
