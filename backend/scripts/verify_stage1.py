"""阶段 1 端到端验证：真实 uvicorn + 真实 HTTP，走一遍完整业务流程。

流程：管理员登录 → 建治疗师 → 建患者并分配 → 治疗师登录 → 看自己的患者
      → 看不到别人的 → 认领未分配 → 归属历史 → 退出登录

    cd backend
    python scripts/verify_stage1.py
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn  # noqa: E402
from _e2e import purge_patients  # noqa: E402

HOST = "127.0.0.1"
ADMIN_PW = "Admin#2026pass"
THERAPIST_PW = "Ther#2026pass"

failures: list[str] = []


def _free_port() -> int:
    """向系统要一个空闲端口，避免与残留进程撞端口。"""
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


def main() -> int:
    from app.core.config import get_settings
    from app.db import storage
    from app.main import create_app
    from app.models import user as user_model

    settings = get_settings()
    if not settings.db_path.exists():
        print(f"数据库不存在：{settings.db_path}（请先执行 app.cli init）", file=sys.stderr)
        return 2

    # 准备两个账号（直接建，避免依赖 cli 交互）
    conn = storage.connect(settings)
    try:
        storage.migrate(conn, storage.discover_migrations(settings=settings))
        for employee_no, name, role, pw in (
            ("A001", "科室管理员", user_model.ROLE_ADMIN, ADMIN_PW),
            ("T001", "张三", user_model.ROLE_THERAPIST, THERAPIST_PW),
            ("T002", "李四", user_model.ROLE_THERAPIST, THERAPIST_PW),
        ):
            existing = user_model.get_by_employee_no(conn, employee_no)
            if existing:
                user_model.set_password(conn, int(existing["id"]), pw)
            else:
                user_model.create_user(conn, employee_no=employee_no, name=name, role=role, password=pw)
        t1_id = int(user_model.get_by_employee_no(conn, "T001")["id"])
        t2_id = int(user_model.get_by_employee_no(conn, "T002")["id"])
        # 清理上次运行的示例患者，保证可重复执行
        for no in ("E2E001", "E2E002", "E2E003"):
            purge_patients(conn, [no])
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
        # 1) 登录
        code, admin_login = request(
            "/api/v1/auth/login", "POST", {"employee_no": "A001", "password": ADMIN_PW}
        )
        check("管理员登录", code == 200 and "access_token" in admin_login, str(admin_login)[:120])
        admin_tok = admin_login["access_token"]

        code, ther_login = request(
            "/api/v1/auth/login", "POST", {"employee_no": "T001", "password": THERAPIST_PW}
        )
        check("治疗师登录", code == 200)
        t1_tok = ther_login["access_token"]

        # 2) 密码错误与工号不存在返回同样的信息（不可枚举）
        _, bad_pw = request("/api/v1/auth/login", "POST", {"employee_no": "T001", "password": "nope"})
        _, no_user = request("/api/v1/auth/login", "POST", {"employee_no": "ZZZ", "password": "nope"})
        check("登录失败信息不可枚举", bad_pw["message"] == no_user["message"], str(bad_pw))

        # 3) 未带 token 访问受保护接口
        code, err = request("/api/v1/auth/me")
        check("未认证返回 401", code == 401 and err["code"] == "AUTH_REQUIRED")

        # 4) refresh token 不能当 access token 用
        code, err = request(
            "/api/v1/auth/me", token=admin_login["refresh_token"]
        )
        check("refresh token 不能当 access token", code == 401 and err["code"] == "TOKEN_WRONG_TYPE")

        # 5) 管理员建患者并分配给张三点
        code, created = request(
            "/api/v1/patients",
            "POST",
            {
                "inpatient_no": "E2E001",
                "name": "端到端患者甲",
                "diagnosis": "脑卒中恢复期",
                "admin_note": "左侧偏瘫，起床需两人辅助",
                "assigned_therapist_id": t1_id,
            },
            token=admin_tok,
        )
        check("管理员建患者并分配", code == 201 and created["visible_therapist_id"] == t1_id, str(created)[:160])

        code, other = request(
            "/api/v1/patients",
            "POST",
            {"inpatient_no": "E2E002", "name": "端到端患者乙", "assigned_therapist_id": t2_id},
            token=admin_tok,
        )
        check("管理员建第二个患者（归属李四）", code == 201, str(other)[:120])

        code, free = request(
            "/api/v1/patients", "POST", {"inpatient_no": "E2E003", "name": "端到端患者丙"}, token=admin_tok
        )
        check("管理员建未分配患者", code == 201)

        # 6) 治疗师只能看到自己的 + 未分配的
        code, listed = request("/api/v1/patients", token=t1_tok)
        numbers = {i["inpatient_no"] for i in listed["items"]}
        check("治疗师看到自己的与未分配的", code == 200 and {"E2E001", "E2E003"} <= numbers, str(numbers))
        check("治疗师看不到别人的患者", "E2E002" not in numbers, str(numbers))

        # 7) 详情与越权
        code, _ = request("/api/v1/patients/E2E001", token=t1_tok)
        check("可读自己的患者详情", code == 200)
        code, err = request("/api/v1/patients/E2E002", token=t1_tok)
        check("越权读详情返回 403", code == 403 and err["code"] == "PATIENT_NOT_VISIBLE")

        # 8) 治疗师不能用 scope=all
        code, err = request("/api/v1/patients?scope=all", token=t1_tok)
        check("治疗师不能用 scope=all", code == 403 and err["code"] == "SCOPE_FORBIDDEN")

        # 9) 管理员能看到全部
        code, allp = request("/api/v1/patients?scope=all", token=admin_tok)
        check("管理员可查全部", code == 200 and allp["total"] >= 3, str(allp.get("total")))

        # 10) 治疗师不能管理用户
        code, err = request("/api/v1/users", token=t1_tok)
        check("治疗师不能查用户列表", code == 403 and err["code"] == "ADMIN_REQUIRED")

        # 11) 治疗师不能建患者
        code, err = request("/api/v1/patients", "POST", {"inpatient_no": "X", "name": "X"}, token=t1_tok)
        check("治疗师不能建患者", code == 403 and err["code"] == "ADMIN_REQUIRED")

        # 12) 认领未分配患者
        code, claimed = request("/api/v1/patients/claim?inpatient_no=E2E003", "POST", {}, token=t1_tok)
        check("认领未分配患者", code == 200 and claimed["assigned_therapist_id"] == t1_id, str(claimed)[:140])

        # 13) 归属历史
        code, history = request("/api/v1/patients/E2E003/assignments", token=t1_tok)
        types = [h["change_type"] for h in history]
        check("归属历史记录了 claim", code == 200 and types == ["claim"], str(types))

        # 14) 不能重复认领
        code, err = request("/api/v1/patients/claim?inpatient_no=E2E003", "POST", {}, token=t1_tok)
        check("不能重复认领已有归属的患者", code == 409, str(err)[:120])

        # 15) 放弃归属
        code, released = request("/api/v1/patients/E2E003/release", "POST", {}, token=t1_tok)
        check("放弃归属", code == 200 and released["assigned_therapist_id"] is None)

        # 16) 退出登录后 refresh 失效
        refresh_tok = admin_login["refresh_token"]
        code, _ = request(f"/api/v1/auth/logout?refresh_token={refresh_tok}", "POST", {}, token=admin_tok)
        check("退出登录返回 204", code == 204, str(code))
        code, err = request("/api/v1/auth/refresh", "POST", {"refresh_token": refresh_tok})
        check("退出后 refresh token 失效", code == 403, str(err)[:120])

        # 17) OpenAPI 收录了阶段 1 接口
        code, schema = request("/openapi.json")
        paths = set(schema["paths"])
        wanted = {"/api/v1/auth/login", "/api/v1/patients", "/api/v1/users", "/api/v1/patients/claim"}
        check("OpenAPI 收录阶段 1 接口", code == 200 and wanted <= paths, str(sorted(wanted - paths)))
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    print()
    if failures:
        print(f"{len(failures)} 项失败：")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("阶段 1 端到端验证全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
