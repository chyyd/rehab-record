"""阶段 2 端到端验证：排期、休息与请假，跑真实 uvicorn + 真实 HTTP。

流程：登录 → 建患者 → 排期 → 三条冲突 → 可排性查询 → 休息块 → 单日假临时释放
      → 多日假正式排空 → 撤销回滚 → 复制排期 → 过期清理

    cd backend
    python scripts/verify_stage2.py
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

D_MON = "2027-03-01"  # 周一
D_TUE = "2027-03-02"

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
        with urllib.request.urlopen(req, timeout=15) as resp:
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
        # 清理上次运行遗留（保证可重复执行）
        for no in ("S2A", "S2B"):
            purge_patients(conn, [no])
        for therapist_id in (ids["T001"], ids["T002"]):
            conn.execute("DELETE FROM rest_block WHERE therapist_id = ?", (therapist_id,))
            conn.execute("DELETE FROM leave_record WHERE therapist_id = ?", (therapist_id,))
            conn.execute(
                "UPDATE patient SET assigned_therapist_id = ? WHERE inpatient_no = 'S2A'", (ids["T001"],)
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
        _, t1_login = request("/api/v1/auth/login", "POST", {"employee_no": "T001", "password": THERAPIST_PW})
        _, t2_login = request("/api/v1/auth/login", "POST", {"employee_no": "T002", "password": THERAPIST_PW})
        at, h1, h2 = admin["access_token"], t1_login["access_token"], t2_login["access_token"]

        # 建两名患者：S2A 归张三，S2B 未分配
        request("/api/v1/patients", "POST",
                {"inpatient_no": "S2A", "name": "阶段二患者甲", "assigned_therapist_id": ids["T001"]}, at)
        request("/api/v1/patients", "POST", {"inpatient_no": "S2B", "name": "阶段二患者乙"}, at)

        # 1) 半日边界
        code, periods = request("/api/v1/schedule/periods", token=h1)
        check("半日边界为 Q11 值",
              code == 200 and periods["periods"]["am"]["start"] == "06:00"
              and periods["periods"]["am"]["end"] == "11:30"
              and periods["periods"]["pm"]["start"] == "13:00"
              and periods["periods"]["pm"]["end"] == "17:30")

        # 2) 正常排期
        code, appt = request("/api/v1/schedule", "POST",
                             {"patient_no": "S2A", "date": D_MON, "period": "am"}, h1)
        check("新建排期", code == 201 and appt["period"] == "am", str(appt)[:140])
        check("排期返回患者/治疗师姓名", appt["patient_name"] == "阶段二患者甲" and appt["therapist_name"] == "张三",
              str(appt)[:140])

        # 3) 规则 1：治疗师半日唯一
        code, err = request("/api/v1/schedule", "POST",
                            {"patient_no": "S2B", "date": D_MON, "period": "am"}, h1)
        check("治疗师半日已占用 → 409",
              code == 409 and any(c["rule"] == "therapist_slot_taken" for c in err["details"]["conflicts"]),
              str(err)[:160])

        # 4) 规则 2：患者半日唯一（换治疗师）
        code, err = request("/api/v1/schedule", "POST",
                            {"patient_no": "S2B", "date": D_MON, "period": "pm"}, h1)
        check("同治疗师另一半天可排", code == 201, str(err)[:140])
        code, err = request("/api/v1/schedule", "POST",
                            {"patient_no": "S2B", "date": D_MON, "period": "pm"}, h2)
        check("患者半日已占用 → 409",
              code == 409 and any(c["rule"] == "patient_slot_taken" for c in err["details"]["conflicts"]),
              str(err)[:160])

        # 5) 可排性
        avail_path = "/api/v1/schedule/availability" + q(
            **{"from": D_MON, "to": D_MON, "therapist_id": ids["T001"]}
        )
        code, slots = request(avail_path, token=h1)
        check("可排性查询返回 2 个半日", code == 200 and len(slots) == 2, str(slots)[:140])
        check("上午不可排且给出原因", slots[0]["available"] is False and "therapist_slot_taken" in slots[0]["reasons"])

        # 6) 休息块
        code, block = request("/api/v1/rest-blocks", "POST",
                              {"scope": "date", "specific_date": D_TUE, "period": "am"}, h1)
        check("新建休息块", code == 201, str(block)[:140])
        code, err = request("/api/v1/schedule", "POST",
                            {"patient_no": "S2A", "date": D_TUE, "period": "am"}, h1)
        check("休息半日不可排 → 409",
              code == 409 and any(c["rule"] == "rest_block" for c in err["details"]["conflicts"]),
              str(err)[:160])

        # 7) 计划时间必须落在半日区间内
        code, err = request("/api/v1/schedule", "POST",
                            {"patient_no": "S2A", "date": "2027-03-05", "period": "am", "start_time": "14:00"}, h1)
        check("计划时间越界 → 422", code == 422 and err["code"] == "INVALID", str(err)[:140])

        # 8) 单日假：临时释放，原归属不变
        code, leave = request("/api/v1/leave", "POST",
                              {"leave_type": "half_day_am", "start_date": "2027-03-08", "reason": "门诊"}, h1)
        check("登记单日假即生效", code == 201 and leave["status"] == "active" and leave["source"] == "therapist_self",
              str(leave)[:160])
        code, patient = request("/api/v1/patients/S2A", token=h1)
        check("单日假不改原归属",
              patient["assigned_therapist_id"] == ids["T001"] and patient["visibility_state"] == "temp_released",
              str(patient)[:180])
        check("临时释放后可见归属为空", patient["visible_therapist_id"] is None, str(patient)[:180])

        # 9) 请假半日治疗师本人不能排
        code, err = request("/api/v1/schedule", "POST",
                            {"patient_no": "S2A", "date": "2027-03-08", "period": "am"}, h1)
        check("请假半日不能排 → 409",
              code == 409 and any(c["rule"] == "on_leave" for c in err["details"]["conflicts"]),
              str(err)[:160])

        # 10) 他人可排被临时释放的患者
        code, other = request("/api/v1/schedule", "POST",
                              {"patient_no": "S2A", "date": "2027-03-08", "period": "pm"}, h2)
        check("他人可排被临时释放的患者", code == 201, str(other)[:140])

        # 11) 请假生效查询
        code, eff = request(f"/api/v1/leave/effective{q(date='2027-03-08', period='am')}", token=h1)
        check("am 处于请假", code == 200 and eff["on_leave"] is True, str(eff)[:140])
        code, eff = request(f"/api/v1/leave/effective{q(date='2027-03-08', period='pm')}", token=h1)
        check("同日下午未请假", eff["on_leave"] is False)

        # 12) 多日假：正式排空
        code, multi = request("/api/v1/leave", "POST",
                              {"leave_type": "multi_day", "start_date": "2027-04-01", "end_date": "2027-04-05"}, h1)
        check("登记多日假", code == 201, str(multi)[:140])
        code, patient = request("/api/v1/patients/S2A", token=h1)
        check("多日假正式排空归属", patient["assigned_therapist_id"] is None, str(patient)[:180])

        # 13) 撤销多日假：回收未认领的
        code, cancelled = request(f"/api/v1/leave/{multi['id']}/cancel", "POST", {"cancel_reason": "计划变更"}, h1)
        check("撤销多日假", code == 200 and cancelled["status"] == "cancelled", str(cancelled)[:160])
        check("未认领患者被恢复", "S2A" in cancelled.get("restored", []), str(cancelled.get("restored")))

        # 14) 撤销单日假后临时释放被关闭
        code, c2 = request(f"/api/v1/leave/{leave['id']}/cancel", "POST", {}, h1)
        check("撤销单日假", code == 200, str(c2)[:140])
        code, patient = request("/api/v1/patients/S2A", token=h1)
        check("撤销后归属恢复为原治疗师",
              patient["visible_therapist_id"] == ids["T001"] and patient["visibility_state"] == "assigned",
              str(patient)[:180])

        # 15) 复制排期（跳过冲突格子）
        code, copied = request("/api/v1/schedule/copy", "POST",
                               {"mode": "yesterday", "target_date": D_TUE}, h1)
        check("复制昨天返回结果", code == 200 and "created" in copied and "skipped" in copied, str(copied)[:200])

        # 16) 权限：治疗师不能排别人的患者
        code, err = request("/api/v1/schedule", "POST",
                            {"patient_no": "S2A", "date": "2027-03-15", "period": "am",
                             "therapist_id": ids["T002"]}, h1)
        check("治疗师不能替他人排期 → 403", code == 403 and err["code"] == "SCHEDULE_OTHER_THERAPIST",
              str(err)[:140])

        # 17) 管理员代录请假
        code, admin_leave = request("/api/v1/leave/admin", "POST",
                                    {"leave_type": "full_day", "start_date": "2027-05-06",
                                     "therapist_id": ids["T002"]}, at)
        check("管理员代录请假 source=admin_entry",
              code == 201 and admin_leave["source"] == "admin_entry"
              and admin_leave["created_by_name"] == "科室管理员", str(admin_leave)[:200])

        # 18) 取消排期释放格子
        code, cancelled_appt = request(f"/api/v1/schedule/{appt['id']}", "DELETE", {}, h1)
        check("取消排期", code == 200 and cancelled_appt["status"] == "cancelled", str(cancelled_appt)[:140])
        code, again = request("/api/v1/schedule", "POST",
                              {"patient_no": "S2B", "date": D_MON, "period": "am"}, h1)
        check("取消后格子可复用", code == 201, str(again)[:140])
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    print()
    if failures:
        print(f"{len(failures)} 项失败：")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("阶段 2 端到端验证全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
