"""阶段 4 端到端验证：离线与同步（`设计.md` 5.4）。

场景：治疗师断网期间攒下一批变更 → 恢复网络后一次推送 → 另一端按游标增量拉取。
另外验证：幂等重试、整批重推、冲突分层（草稿客户端优先 / 已提交服务端优先）。

## 2026-10-05：payload 换成 SOAP 契约，并补上「离线不是后门」

治疗记录改成 SOAP 模板驱动后，离线 payload 里的 `items`（主项目/子项目/参数）换成了
`body`（`{field_key: value}`），多出 `discipline` 与 `kind`。更重要的是：**服务端推送入口
`app/services/sync.py::_push_treatment_record` 直接调用 `treatment_model.create_record()`** ——
在线接口的**三条硬阻断**（缺首评 / 缺复评 / 待出院）在离线通道上**同样生效**。
本脚本因此新增一项：把一个"没有首评的日常记录"推进来，必须被拦下（**逐条 conflict**，
见下），否则离线就成了绕过门禁的后门。

> **2026-10-05 补充**：拦截方式从"整批 409"改成"逐条 conflict（HTTP 200）"。
> 门禁强度没变 —— 被拒的条目一样不落库；变的是**可恢复性**：同批里合法的条目照常应用，
> 客户端也能从 `reason`/`message`/`details.missing_document` 知道该补哪份文书。

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

DISC = "PT"
INITIAL_BODY = {"diagnosis": ["偏瘫运动功能障碍"], "therapy_items": ["偏瘫肢体综合训练"]}
DAILY_BODY = {"therapy_items": ["偏瘫肢体综合训练"], "mental": "良好"}

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
        purge_patients(conn, ["S4A", "S4B"])
        conn.execute("DELETE FROM change_log")
        patient_model.create_patient(
            conn, inpatient_no="S4A", name="阶段四患者", assigned_therapist_id=ids["T001"]
        )
        # S4B 故意**不建首评**：用来验证离线通道同样受硬阻断约束
        patient_model.create_patient(
            conn, inpatient_no="S4B", name="阶段四患者乙", assigned_therapist_id=ids["T001"]
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

    def record_payload(
        day: str, note: str, *, kind: str = "daily", status: str = "draft",
        patient_no: str = "S4A",
    ) -> dict:
        """离线端攒下来的那条变更的 payload（SOAP 新契约）。"""
        return {
            "patient_no": patient_no,
            "record_date": day,
            "discipline": DISC,
            "kind": kind,
            "body": INITIAL_BODY if kind == "initial" else DAILY_BODY,
            "status": status,
            "note": note,
        }

    try:
        _, login = request("/api/v1/auth/login", "POST", {"employee_no": "T001", "password": THERAPIST_PW})
        h = login["access_token"]

        # ---------------------------------------------------------------- #
        # 1) 同步契约
        # ---------------------------------------------------------------- #
        code, info = request("/api/v1/sync/info", token=h)
        check("同步契约可获取", code == 200, str(code))
        check("只允许治疗记录离线写",
              info["pushable_entities"] == ["treatment_record"], str(info["pushable_entities"]))
        check("可拉取实体只有患者与治疗记录（字典/选项集/模板已删除）",
              info["pullable_entities"] == ["patient", "treatment_record"],
              str(info["pullable_entities"]))
        check("冲突策略已声明",
              info["conflict_policy"]["treatment_record:draft"] == "client_wins"
              and info["conflict_policy"]["treatment_record:submitted"] == "server_wins",
              str(info["conflict_policy"]))
        check("冲突策略覆盖治疗记录的三种状态",
              {"treatment_record:draft", "treatment_record:submitted",
               "treatment_record:locked"} <= set(info["conflict_policy"]),
              str(sorted(info["conflict_policy"])))
        # ⚠ 已核实的**残留**：`SyncInfoOut.conflict_policy` 里还剩一个 `"dictionary"` 键
        #   （schemas/sync.py），而字典类表与外键在迁移 011/012 之后**已经不存在**，
        #   既不可推也不可拉。这里用"只允许这一个已知残留"锁住，避免再冒出新实体；
        #   清理它要动 `backend/app/**` 行为代码，已按约定**报告**而非就地修改。
        check("冲突策略里除已知残留 dictionary 外没有字典实体",
              set(info["conflict_policy"]) - {"dictionary"}
              == {"treatment_record:draft", "treatment_record:submitted", "treatment_record:locked"},
              str(sorted(info["conflict_policy"])))

        # ---------------------------------------------------------------- #
        # 2) 初始游标
        # ---------------------------------------------------------------- #
        code, start = request("/api/v1/sync/pull" + q(cursor=0), token=h)
        check("初始拉取为空", code == 200 and start["changes"] == [], str(start)[:140])
        base_cursor = start["cursor"]

        # ---------------------------------------------------------------- #
        # 3) 模拟断网期间攒下 5 条文书：首评 + 4 条日常
        #    （第 1 次日常前必须先有首评 —— 离线也一样，见第 10 节）
        # ---------------------------------------------------------------- #
        offline = [
            {
                "entity": "treatment_record",
                "client_uuid": "e2e-rec-0000",
                "op": "insert",
                "payload": record_payload("2027-06-01", "离线首评", kind="initial"),
            },
            *[
                {
                    "entity": "treatment_record",
                    "client_uuid": f"e2e-rec-{index:04d}",
                    "op": "insert",
                    "payload": record_payload(f"2027-06-0{index + 1}", f"离线第{index}条日常"),
                }
                for index in range(1, 5)
            ],
        ]
        code, pushed = request("/api/v1/sync/push", "POST", {"changes": offline}, h)
        check("离线批量推送全部应用",
              code == 200 and len(pushed["applied"]) == 5, f"{code} {str(pushed)[:200]}")
        check("推送无冲突", pushed["conflicts"] == [], str(pushed["conflicts"])[:160])
        cursor_after_push = pushed["cursor"]

        # ---------------------------------------------------------------- #
        # 4) 另一端按游标增量拉取
        # ---------------------------------------------------------------- #
        code, pulled = request("/api/v1/sync/pull" + q(cursor=base_cursor), token=h)
        check("增量拉取拿到全部 5 条变更",
              code == 200 and len(pulled["changes"]) == 5, str(len(pulled.get("changes", []))))
        entities = [c["entity"] for c in pulled["changes"]]
        check("变更全部是治疗记录",
              entities.count("treatment_record") == 5 and "appointment" not in entities, str(entities))
        check("拉取游标与推送返回一致", pulled["cursor"] == cursor_after_push,
              f"{pulled['cursor']} vs {cursor_after_push}")
        check("记录变更带 body（{field_key: value}）而不是旧的 items",
              all(c["payload"] and "body" in c["payload"] and "items" not in c["payload"]
                  for c in pulled["changes"] if c["entity"] == "treatment_record"),
              "客户端据此在本地重建记录")
        check("记录变更带大类与形态",
              all(c["payload"].get("discipline") == DISC and c["payload"].get("kind")
                  in ("initial", "daily")
                  for c in pulled["changes"] if c["entity"] == "treatment_record"),
              "")

        # ---------------------------------------------------------------- #
        # 5) 游标不再前进
        # ---------------------------------------------------------------- #
        code, again = request("/api/v1/sync/pull" + q(cursor=pulled["cursor"]), token=h)
        check("再拉取为空且游标不前移",
              again["changes"] == [] and again["cursor"] == pulled["cursor"], str(again)[:140])

        # ---------------------------------------------------------------- #
        # 6) 幂等：整批重推（模拟"服务端已写入但响应丢失"）
        # ---------------------------------------------------------------- #
        code, retried = request("/api/v1/sync/push", "POST", {"changes": offline}, h)
        check("整批重推不产生冲突", retried["conflicts"] == [], str(retried["conflicts"])[:160])
        conn = storage.connect(settings)
        try:
            total = conn.execute(
                "SELECT COUNT(*) FROM treatment_record WHERE patient_no = 'S4A'"
            ).fetchone()[0]
            kinds = dict(
                conn.execute(
                    "SELECT kind, COUNT(*) FROM treatment_record WHERE patient_no = 'S4A'"
                    " GROUP BY kind"
                ).fetchall()
            )
        finally:
            conn.close()
        check("重推后记录数仍为 5（幂等）", total == 5, str(total))
        check("离线推上来的 5 条由服务端算出了序号（1 条首评 + 4 条日常）",
              kinds.get("initial") == 1 and kinds.get("daily") == 4, str(kinds))

        # ---------------------------------------------------------------- #
        # 7) 冲突：草稿 → 客户端优先
        # ---------------------------------------------------------------- #
        conn = storage.connect(settings)
        try:
            row = conn.execute(
                "SELECT id, revision FROM treatment_record WHERE patient_no = 'S4A'"
                " AND kind = 'initial' ORDER BY id LIMIT 1"
            ).fetchone()
            draft_id, draft_rev = int(row["id"]), int(row["revision"])
        finally:
            conn.close()
        # 服务端侧改动草稿（版本前进），但仍是草稿
        code, edited = request(
            f"/api/v1/records/{draft_id}", "PUT", {"body": {**INITIAL_BODY, "vas": 5}}, h
        )
        check("服务端改动草稿", code == 200, str(code))
        server_rev = edited["revision"]
        check("草稿改动推进了 revision", server_rev > draft_rev, f"{draft_rev} -> {server_rev}")

        code, stale = request(
            "/api/v1/sync/push", "POST",
            {"changes": [{
                "entity": "treatment_record", "client_uuid": "e2e-rec-0000", "op": "update",
                "base_revision": draft_rev,
                "payload": record_payload("2027-06-01", "客户端较新（离线期间写的）", kind="initial"),
            }]},
            h,
        )
        check("草稿冲突 → 客户端优先",
              code == 200 and len(stale["applied"]) == 1 and stale["conflicts"] == [],
              f"{code} {str(stale)[:200]}")
        conn = storage.connect(settings)
        try:
            body_json = conn.execute(
                "SELECT body_json FROM treatment_record WHERE id = ?", (draft_id,)
            ).fetchone()["body_json"]
        finally:
            conn.close()
        check("客户端内容确实生效（服务端改的 vas=5 被覆盖）",
              json.loads(body_json).get("vas") is None, str(body_json)[:160])

        # ---------------------------------------------------------------- #
        # 8) 冲突：已提交 → 服务端优先
        # ---------------------------------------------------------------- #
        code, submitted = request(f"/api/v1/records/{draft_id}/submit", "POST", {}, h)
        check("提交记录", code == 200 and submitted["status"] == "submitted", str(code))
        submitted_rev = submitted["revision"]

        code, conflict = request(
            "/api/v1/sync/push", "POST",
            {"changes": [{
                "entity": "treatment_record", "client_uuid": "e2e-rec-0000", "op": "update",
                "base_revision": draft_rev,  # 故意用过期的基线
                "payload": record_payload("2027-06-01", "试图覆盖已提交", kind="initial"),
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
            note = conn.execute(
                "SELECT note FROM treatment_record WHERE id = ?", (draft_id,)
            ).fetchone()["note"]
        finally:
            conn.close()
        check("已提交内容未被覆盖", note != "试图覆盖已提交", note)

        # ---------------------------------------------------------------- #
        # 9) 一条冲突不影响整批
        # ---------------------------------------------------------------- #
        code, mixed = request(
            "/api/v1/sync/push", "POST",
            {"changes": [
                {"entity": "treatment_record", "client_uuid": "e2e-rec-0000", "op": "update",
                 "base_revision": draft_rev,
                 "payload": record_payload("2027-06-01", "又一条冲突", kind="initial")},
                {"entity": "treatment_record", "client_uuid": "e2e-rec-mixed-0001", "op": "insert",
                 "payload": record_payload("2027-06-07", "同批的另一条"),
                 },
            ]},
            h,
        )
        check("一条冲突不阻断其它条目",
              len(mixed["conflicts"]) == 1 and len(mixed["applied"]) == 1,
              f"conflicts={len(mixed['conflicts'])} applied={len(mixed['applied'])}")

        # ---------------------------------------------------------------- #
        # 10) ★ 离线不是后门：缺首评的日常在推送时同样被拦下
        #
        # ★ 2026-10-05 改了**拦截方式**：原来是整批 409，现在是**逐条 conflict**
        #   （HTTP 仍 200）。理由见 `docs/sync-protocol.md`：离线队列通常攒了几十条，
        #   一条撞门禁就让整批失败时，客户端连"哪一条出的问题"都不知道，只能整批重推。
        #   门禁强度**没变** —— 被拒的条目依然不落库（下面那条断言就是守它的）。
        # ---------------------------------------------------------------- #
        code, pushed = request(
            "/api/v1/sync/push", "POST",
            {"changes": [{
                "entity": "treatment_record", "client_uuid": "e2e-nogate-0001", "op": "insert",
                "payload": record_payload("2027-06-10", "没有首评就想推日常", patient_no="S4B"),
            }]},
            h,
        )
        item = (pushed.get("conflicts") or [{}])[0]
        check("离线推送缺首评的日常 → 逐条 conflict（HTTP 200，门禁与在线一致）",
              code == 200 and not pushed.get("applied")
              and item.get("reason") == "MISSING_ASSESSMENT"
              and (item.get("details") or {}).get("missing_document") == "initial",
              f"{code} {str(pushed)[:220]}")
        check("conflict 带给人看的原因（客户端可直接展示）",
              "首评" in str(item.get("message") or ""), str(item.get("message"))[:120])
        conn = storage.connect(settings)
        try:
            smuggled = conn.execute(
                "SELECT COUNT(*) FROM treatment_record WHERE patient_no = 'S4B'"
            ).fetchone()[0]
        finally:
            conn.close()
        check("被拒的变更没有落库（S4B 仍然 0 条记录）", smuggled == 0, str(smuggled))

        # ---------------------------------------------------------------- #
        # 11) 范围与边界
        # ---------------------------------------------------------------- #
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

        # ---------------------------------------------------------------- #
        # 12) OpenAPI 收录
        # ---------------------------------------------------------------- #
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
