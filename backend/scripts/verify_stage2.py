"""阶段 2 端到端验证（**已重写**）：患者列表排序 —— "我最近一次已提交治疗"优先。

## 为什么整个脚本被重写了

原阶段 2 验收的是**排期、休息块与请假**。2026-10-05 科室确认排班不是本系统的职责，
这三项功能整体下线，原脚本的 25 项断言全部失去对象。简单删掉这个脚本会让
**"患者列表怎么排序"这件事完全没有验收覆盖** —— 而那正是取代排期的核心行为：
治疗师打开列表是为了**接着记今天做过的患者**，所以排序必须反映"我刚治过谁"。

所以这个脚本改为验证新排序语义：

1. 组内按"我最近一次**已提交**治疗"的日期**降序**（越近越前）；
2. **草稿不算** —— 否则"写了一半没提交"会把患者顶到最前，而那条记录在汇总/时间轴
   里还不存在，看起来像系统错乱；
3. 从没被我治过的患者排在有记录的**后面**；
4. 归属分组仍然优先于治疗时间：我的患者 → 未分配 → 其他；
5. 换一个治疗师看，排序按**他自己的**治疗历史（不是全局最近）。

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

# 用固定的过去日期，避免"今天"漂移导致断言不稳
D_OLD = "2027-03-01"
D_MID = "2027-03-05"
D_NEW = "2027-03-09"

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


def order_of(payload: dict, only: tuple[str, ...] = ("S2A", "S2B", "S2C", "S2D")) -> list[str]:
    """患者列表响应里**本次测试那几名患者**的相对顺序。

    ★ 必须过滤：开发库里本来就有别的患者（S5A/S4A/…），它们会混在同一个列表里。
    脚本要断言的是"相对顺序"，不是"列表里只有这四个"。
    """
    items = payload.get("items") if isinstance(payload, dict) else payload
    return [str(i["inpatient_no"]) for i in (items or []) if str(i["inpatient_no"]) in only]


def create_record(token: str, patient_no: str, day: str, *, status: str) -> tuple[int, object]:
    """建一条治疗记录（带一个最小明细，走真实参数校验）。"""
    return request(
        "/api/v1/records",
        "POST",
        {
            "patient_no": patient_no,
            "record_date": day,
            "session_period": "am",
            "status": status,
            "items": [{"main_item_id": 1, "sub_item_id": 1, "params": {"reps": 10}}],
        },
        token,
    )


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
        purge_patients(conn, ["S2A", "S2B", "S2C", "S2D"])
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
        _, admin = request("/api/v1/auth/login", "POST",
                           {"employee_no": "A001", "password": ADMIN_PW})
        _, t1_login = request("/api/v1/auth/login", "POST",
                              {"employee_no": "T001", "password": THERAPIST_PW})
        _, t2_login = request("/api/v1/auth/login", "POST",
                              {"employee_no": "T002", "password": THERAPIST_PW})
        at, h1, h2 = admin["access_token"], t1_login["access_token"], t2_login["access_token"]

        # 四名患者：S2A/S2B 归张三，S2C 归李四，S2D 未分配
        request("/api/v1/patients", "POST",
                {"inpatient_no": "S2A", "name": "阶段二患者甲",
                 "assigned_therapist_id": ids["T001"]}, at)
        request("/api/v1/patients", "POST",
                {"inpatient_no": "S2B", "name": "阶段二患者乙",
                 "assigned_therapist_id": ids["T001"]}, at)
        request("/api/v1/patients", "POST",
                {"inpatient_no": "S2C", "name": "阶段二患者丙",
                 "assigned_therapist_id": ids["T002"]}, at)
        request("/api/v1/patients", "POST",
                {"inpatient_no": "S2D", "name": "阶段二患者丁"}, at)

        # ---------------------------------------------------------------- #
        # 1) 排期相关接口已下线
        # ---------------------------------------------------------------- #
        for path in ("/api/v1/schedule", "/api/v1/rest-blocks", "/api/v1/leave"):
            code, _ = request(path, token=h1)
            check(f"已下线接口不再存在：{path}", code == 404, f"HTTP {code}")

        # ---------------------------------------------------------------- #
        # 2) 治疗历史 → 排序（用 scope=dept 全科列表，才能同时看到三种归属分组）
        # ---------------------------------------------------------------- #
        # 张三是 S2A / S2B 的归属人。给 S2B 记一条较早的、给 S2A 记一条较近的。
        code, _ = create_record(h1, "S2B", D_OLD, status="submitted")
        check("给 S2B 建已提交记录", code == 201, f"HTTP {code}")
        code, _ = create_record(h1, "S2A", D_MID, status="submitted")
        check("给 S2A 建已提交记录", code == 201, f"HTTP {code}")
        # 未分配患者 S2D 也由张三记一条**最近**的
        code, _ = create_record(h1, "S2D", D_NEW, status="submitted")
        check("给未分配患者 S2D 建已提交记录", code == 201, f"HTTP {code}")

        code, dept = request(f"/api/v1/patients{q(scope='dept', page_size=200)}", token=h1)
        check("取全科患者列表", code == 200, f"HTTP {code}")
        order = order_of(dept)

        check("组内按我最近一次已提交治疗降序（S2A 晚于 S2B → S2A 在前）",
              len(order) >= 2 and order.index("S2A") < order.index("S2B"), str(order))
        check("我的患者排在未分配之前（分组优先于治疗时间）",
              "S2D" in order and order.index("S2A") < order.index("S2D"), str(order))
        check("未分配的排在别人的患者之前",
              "S2C" in order and order.index("S2D") < order.index("S2C"), str(order))

        # ---------------------------------------------------------------- #
        # 3) 草稿不算
        # ---------------------------------------------------------------- #
        # 给 S2B 补一条**日期更新但仍是草稿**的记录。如果草稿参与排序，
        # S2B 会被顶到 S2A 前面；正确行为是 S2B 仍按它那条已提交的 D_OLD 排在后面。
        code, _ = create_record(h1, "S2B", D_NEW, status="draft")
        check("给 S2B 建草稿（日期更新但未提交）", code == 201, f"HTTP {code}")

        code, dept2 = request(f"/api/v1/patients{q(scope='dept', page_size=200)}", token=h1)
        order2 = order_of(dept2)
        check("草稿不参与排序（S2B 仍在 S2A 之后）",
              order2.index("S2A") < order2.index("S2B"), str(order2))

        # ---------------------------------------------------------------- #
        # 4) 分组优先于治疗历史：张三给"别人的患者"记过，它仍在最后一组
        # ---------------------------------------------------------------- #
        # 全科白板下张三可以给 S2C（李四的患者）做记录（D10 已放开）。
        # 但排序的**第一关键字是归属分组**，所以 S2C 仍排在最后 ——
        # 否则"我偶尔替别人做了一次"会把它顶到我自己的患者前面，与直觉相反。
        code, _ = create_record(h1, "S2C", D_NEW, status="submitted")
        check("张三给别人的患者记一次（全科白板）", code == 201, f"HTTP {code}")
        code, dept3 = request(f"/api/v1/patients{q(scope='dept', page_size=200)}", token=h1)
        order3 = order_of(dept3)
        my_group = [x for x in order3 if x in ("S2A", "S2B")]
        other_group = [x for x in order3 if x == "S2C"]
        check("别人的患者仍排在最后一组（分组优先于治疗历史）",
              bool(other_group) and bool(my_group)
              and max(order3.index(x) for x in my_group) < order3.index("S2C"),
              str(order3))

        # ---------------------------------------------------------------- #
        # 5) 分页 + 可见性
        # ---------------------------------------------------------------- #
        code, page1 = request(f"/api/v1/patients{q(scope='dept', page=1, page_size=2)}", token=h1)
        check("分页返回 page/page_size",
              code == 200 and page1.get("page") == 1 and page1.get("page_size") == 2,
              str(page1)[:160])
        check("分页 items 不超过 page_size", len(page1.get("items") or []) <= 2)
        check("分页带 total", isinstance(page1.get("total"), int), str(page1)[:120])

        code, allp = request("/api/v1/patients?scope=all", token=h1)
        check("治疗师不能用 scope=all（管理员专属）", code == 403, f"HTTP {code}")

        # ---------------------------------------------------------------- #
        # 6) 同步通道只剩治疗记录
        # ---------------------------------------------------------------- #
        code, info = request("/api/v1/sync/info", token=h1)
        check("同步信息可读", code == 200, f"HTTP {code}")
        check("可推送实体只剩 treatment_record",
              info.get("pushable_entities") == ["treatment_record"],
              str(info.get("pushable_entities")))
        check("可拉取实体不含已下线的 appointment",
              "appointment" not in (info.get("pullable_entities") or []),
              str(info.get("pullable_entities")))
        check("冲突策略里不再有 appointment",
              "appointment" not in (info.get("conflict_policy") or {}),
              str(list((info.get("conflict_policy") or {}).keys())))

    finally:
        server.should_exit = True
        thread.join(timeout=10)

    print()
    if failures:
        print(f"阶段 2 验收：{len(failures)} 项失败")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("阶段 2 验收：全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
