"""阶段 4 端到端验证：离线与同步（`设计.md` 5.4）。

场景：治疗师断网期间攒下一批变更 → 恢复网络后一次推送 → 另一端按游标增量拉取。
另外验证：幂等重试、整批重推、冲突分层（草稿客户端优先 / 已提交服务端优先）。

    cd backend
    python scripts/verify_stage4.py
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

    settings = get_settings()
    if not settings.db_path.exists():
        print(f"数据库不存在：{settings.db_path}（请先执行 app.cli init）", file=sys.stderr)
        return 2

    conn = storage.connect(settings)
    try:
        storage.migrate(conn, storage.discover_migrations(settings=settings))
        seed_dictionary(conn)
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
                    conn, employee_no=employee_no, name=name, role=role, password=pw
                )
                ids[employee_no] = int(created["id"])

        # 清理上次运行遗留（保证可重复执行）
        purge_patients(conn, ["S4A"])
        conn.execute("DELETE FROM change_log")
        patient_model.create_patient(
            conn, inpatient_no="S4A", name="阶段四患者", assigned_therapist_id=ids["T001"]
        )
        motor_main = int(
            conn.execute("SELECT id FROM main_item WHERE code = 'motor_function'").fetchone()["id"]
        )
        motor_sub = int(
            conn.execute(
                "SELECT id FROM sub_item WHERE main_item_id = ? ORDER BY sort", (motor_main,)
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

    def record_payload(day: str, note: str, status: str = "draft") -> dict:
        return {
            "patient_no": "S4A",
            "record_date": day,
            "session_period": "am",
            "note": note,
            "status": status,
            "items": [{"main_item_id": motor_main, "sub_item_id": motor_sub, "params": {"side": "左"}}],
        }

    try:
        _, login = request("/api/v1/auth/login", "POST", {"employee_no": "T001", "password": THERAPIST_PW})
        h = login["access_token"]

        # 1) 同步契约
        code, info = request("/api/v1/sync/info", token=h)
        check("同步契约可获取", code == 200, str(code))
        check("只允许治疗记录离线写（排期已于 2026-10-05 下线）",
              info["pushable_entities"] == ["treatment_record"], str(info["pushable_entities"]))
        check("冲突策略已声明",
              info["conflict_policy"]["treatment_record:draft"] == "client_wins"
              and info["conflict_policy"]["treatment_record:submitted"] == "server_wins",
              str(info["conflict_policy"]))

        # 2) 初始游标
        code, start = request("/api/v1/sync/pull" + q(cursor=0), token=h)
        check("初始拉取为空", code == 200 and start["changes"] == [], str(start)[:140])
        base_cursor = start["cursor"]

        # 3) 模拟断网期间攒下 5 条记录
        #    （排期已于 2026-10-05 下线，不再往队列里塞 appointment）
        offline = [
            {
                "entity": "treatment_record",
                "client_uuid": f"e2e-rec-{index:04d}",
                "op": "insert",
                "payload": record_payload(f"2027-06-0{index + 1}", f"离线第{index + 1}条"),
            }
            for index in range(5)
        ]
        code, pushed = request("/api/v1/sync/push", "POST", {"changes": offline}, h)
        check("离线批量推送全部应用",
              code == 200 and len(pushed["applied"]) == 5, f"{code} {str(pushed)[:200]}")
        check("推送无冲突", pushed["conflicts"] == [], str(pushed["conflicts"])[:160])
        cursor_after_push = pushed["cursor"]

        # 4) 另一端按游标增量拉取
        code, pulled = request("/api/v1/sync/pull" + q(cursor=base_cursor), token=h)
        check("增量拉取拿到全部 5 条变更",
              code == 200 and len(pulled["changes"]) == 5, str(len(pulled.get("changes", []))))
        entities = [c["entity"] for c in pulled["changes"]]
        check("变更全部是治疗记录（排期已下线）",
              entities.count("treatment_record") == 5 and "appointment" not in entities, str(entities))
        check("拉取游标与推送返回一致", pulled["cursor"] == cursor_after_push,
              f"{pulled['cursor']} vs {cursor_after_push}")
        check("记录变更带 items 快照",
              all(c["payload"] and "items" in c["payload"]
                  for c in pulled["changes"] if c["entity"] == "treatment_record"),
              "客户端需据此在本地重建记录")

        # 5) 游标不再前进
        code, again = request("/api/v1/sync/pull" + q(cursor=pulled["cursor"]), token=h)
        check("再拉取为空且游标不前移",
              again["changes"] == [] and again["cursor"] == pulled["cursor"], str(again)[:140])

        # 6) 幂等：整批重推（模拟"服务端已写入但响应丢失"）
        code, retried = request("/api/v1/sync/push", "POST", {"changes": offline}, h)
        check("整批重推不产生冲突", retried["conflicts"] == [], str(retried["conflicts"])[:160])
        conn = storage.connect(settings)
        try:
            total = conn.execute("SELECT COUNT(*) FROM treatment_record WHERE patient_no = 'S4A'").fetchone()[0]
        finally:
            conn.close()
        check("重推后记录数仍为 5（幂等）", total == 5, str(total))

        # 7) 冲突：草稿 → 客户端优先
        conn = storage.connect(settings)
        try:
            row = conn.execute(
                "SELECT id, revision FROM treatment_record WHERE patient_no = 'S4A' ORDER BY id LIMIT 1"
            ).fetchone()
            draft_id, draft_rev = int(row["id"]), int(row["revision"])
        finally:
            conn.close()
        # 服务端侧改动草稿（版本前进），但仍是草稿
        code, edited = request(
            f"/api/v1/records/{draft_id}", "PUT", {"note": "服务端改的草稿"}, h
        )
        check("服务端改动草稿", code == 200, str(code))
        server_rev = edited["revision"]
        check("草稿改动推进了 revision", server_rev > draft_rev, f"{draft_rev} -> {server_rev}")

        code, stale = request(
            "/api/v1/sync/push", "POST",
            {"changes": [{
                "entity": "treatment_record", "client_uuid": "e2e-rec-0000", "op": "update",
                "base_revision": draft_rev,
                "payload": record_payload("2027-06-01", "客户端较新（离线期间写的）"),
            }]},
            h,
        )
        check("草稿冲突 → 客户端优先",
              code == 200 and len(stale["applied"]) == 1 and stale["conflicts"] == [],
              f"{code} {str(stale)[:200]}")
        conn = storage.connect(settings)
        try:
            note = conn.execute("SELECT note FROM treatment_record WHERE id = ?", (draft_id,)).fetchone()["note"]
        finally:
            conn.close()
        check("客户端内容确实生效", note == "客户端较新（离线期间写的）", note)

        # 8) 冲突：已提交 → 服务端优先
        code, submitted = request(f"/api/v1/records/{draft_id}/submit", "POST", {}, h)
        check("提交记录", code == 200 and submitted["status"] == "submitted", str(code))
        submitted_rev = submitted["revision"]

        code, conflict = request(
            "/api/v1/sync/push", "POST",
            {"changes": [{
                "entity": "treatment_record", "client_uuid": "e2e-rec-0000", "op": "update",
                "base_revision": draft_rev,  # 故意用过期的基线
                "payload": record_payload("2027-06-01", "试图覆盖已提交"),
            }]},
            h,
        )
        check("已提交冲突 → 服务端优先",
              code == 200 and len(conflict["conflicts"]) == 1, f"{code} {str(conflict)[:200]}")
        if conflict["conflicts"]:
            item = conflict["conflicts"][0]
            check("冲突回报服务端状态与版本",
                  item["server_status"] == "submitted" and item["server_revision"] == submitted_rev,
                  str(item))
        conn = storage.connect(settings)
        try:
            note = conn.execute("SELECT note FROM treatment_record WHERE id = ?", (draft_id,)).fetchone()["note"]
        finally:
            conn.close()
        check("已提交内容未被覆盖", note != "试图覆盖已提交", note)

        # 9) 一条冲突不影响整批
        #    第二条用"新建一条记录"（不带基线 → 必然 applied），
        #    排期已于 2026-10-05 下线，不能再拿它来当"正常那一条"。
        code, mixed = request(
            "/api/v1/sync/push", "POST",
            {"changes": [
                {"entity": "treatment_record", "client_uuid": "e2e-rec-0000", "op": "update",
                 "base_revision": draft_rev,
                 "payload": record_payload("2027-06-01", "又一条冲突")},
                {"entity": "treatment_record", "client_uuid": "e2e-rec-mixed-0001", "op": "insert",
                 "payload": record_payload("2027-06-07", "同批的另一条")},
            ]},
            h,
        )
        check("一条冲突不阻断其它条目",
              len(mixed["conflicts"]) == 1 and len(mixed["applied"]) == 1,
              f"conflicts={len(mixed['conflicts'])} applied={len(mixed['applied'])}")

        # 10) 范围与边界
        code, err = request(
            "/api/v1/sync/push", "POST",
            {"changes": [{"entity": "patient", "client_uuid": "e2e-pat-0001", "op": "insert",
                          "payload": {"inpatient_no": "X", "name": "不该离线建"}}]},
            h,
        )
        check("患者不在离线可写范围 → 422", code == 422 and "allowed" in err["details"], str(err)[:160])

        code, err = request(
            "/api/v1/sync/push", "POST",
            {"changes": [{"entity": "treatment_record", "client_uuid": "e2e-bad-0001", "op": "merge",
                          "payload": record_payload("2027-06-08", "非法 op")}]},
            h,
        )
        check("非法 op → 422", code == 422 and err["code"] == "INVALID", str(err)[:160])

        code, err = request(
            "/api/v1/sync/push", "POST",
            {"changes": [{"entity": "treatment_record", "client_uuid": f"e2e-big-{i:04d}",
                          "op": "insert",
                          "payload": record_payload("2027-06-09", f"超限第{i}条")}
                         for i in range(201)]},
            h,
        )
        check("超过批量上限 → 422", code == 422, str(code))

        code, _ = request("/api/v1/sync/push", "POST", {"changes": []}, h)
        check("空批次 → 422", code == 422, str(code))

        code, _ = request("/api/v1/sync/pull" + q(cursor=0), None)
        check("未认证不能拉取", code == 401, str(code))

        # 11) OpenAPI 收录
        code, schema = request("/openapi.json")
        wanted = {"/api/v1/sync/push", "/api/v1/sync/pull", "/api/v1/sync/info"}
        check("OpenAPI 收录同步接口", wanted <= set(schema["paths"]),
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
    print("阶段 4 端到端验证全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
