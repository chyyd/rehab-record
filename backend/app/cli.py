"""运维 CLI（纯标准库，零依赖）。

    python -m app.cli init              # 建库 + 迁移到最新
    python -m app.cli migrate           # 只跑迁移
    python -m app.cli seed              # 已废弃：字典种子不再导入（记录改由 JSON 模板驱动）
    python -m app.cli auto-discharge    # 待出院满 7 天者自动出院（真的自动）
    python -m app.cli health            # 健康检查（JSON）
    python -m app.cli periods           # 打印半日制作息（Q11）
    python -m app.cli tables            # 列出表与行数
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from app.core.config import get_settings
from app.core.health import collect_health
from app.core.worktime import day_period_bounds
from app.db import storage
from app.models import patient as patient_model
from app.models import user as user_model


def cmd_init(args: argparse.Namespace) -> int:
    cfg = get_settings()
    print(f"数据库：{cfg.db_path}")
    result = storage.initialize(cfg)
    if result.applied:
        print(f"已应用 {result.applied_count} 个迁移：")
        for label in result.applied:
            print(f"  + {label}")
    else:
        print("无待应用迁移，数据库已是最新。")
    if result.skipped:
        print(f"已跳过 {len(result.skipped)} 个已应用的迁移。")
    return cmd_health(args)


def cmd_migrate(args: argparse.Namespace) -> int:
    cfg = get_settings()
    conn = storage.connect(cfg)
    try:
        result = storage.migrate(conn)
    finally:
        conn.close()
    print(f"应用 {result.applied_count} 个迁移，跳过 {len(result.skipped)} 个。")
    for label in result.applied:
        print(f"  + {label}")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    """已废弃：字典种子不再导入。

    2026-10-05 的记录模型改造把「字典 + 选项集 + 患者反应定义」六张表整体删除
    （迁移 012），模板与选项改由 `templates/*.json` 承载（用户要求"不进数据库，
    以便以后我手动修改"）。所以这里**保留子命令但不做任何事**：

    - 保留：外部脚本/文档里仍有 `app.cli seed` 的调用，直接报错会让它们无谓地挂掉；
    - 不做事：`seed/dictionary.py` 等导入器指向的表已经不存在，真跑会立刻崩，
      留着"会崩的实现"比删掉更危险。

    `backend/seed/` 下的种子 JSON 与导入器仍然保留，只是不再被调用
    （见迁移 012 的说法：等确认没有任何功能依赖后再清理）。
    """
    print("字典种子已废弃（记录改由 JSON 模板驱动）")
    print("模板与选项现在在仓库根的 templates/ 下：")
    print("  templates/disciplines.json   四大类 + 各类「本次训练项目」清单")
    print("  templates/<大类>/<形态>.json  首评 / 日常 / 复评 / 出院小结")
    return 0


def cmd_auto_discharge(args: argparse.Namespace) -> int:
    """待出院满 N 天者**自动出院**（用户明确要求：「1 周后自动出院」「真的自动」）。

    为什么需要它：治疗师提交出院小结后患者进入 `pending_discharge`（对普通治疗师
    不可见），等管理员确认。用户要求"防止患者临时反悔"，但也不能无限期挂着 ——
    满 7 天就自动落地为 `discharged`。

    倒计时真源是**出院小结的提交时间**（`treatment_record.submitted_at`），
    不是"改状态的时间"，见 `app/models/patient.py::pending_discharge_since`。

    建议由计划任务每天跑一次（运维侧），例如：
        python -m app.cli auto-discharge --days 7
    """
    cfg = get_settings()
    if not cfg.db_path.exists():
        print("数据库不存在，请先执行 init。", file=sys.stderr)
        return 1

    conn = storage.connect(cfg)
    try:
        if args.dry_run:
            numbers = patient_model.auto_discharge_pending(
                conn, days=args.days, now=args.now, dry_run=True
            )
            print(f"（试运行）待出院满 {args.days} 天、应自动出院的患者：{len(numbers)} 人")
        else:
            numbers = patient_model.auto_discharge_pending(conn, days=args.days, now=args.now)
            print(f"已自动出院 {len(numbers)} 人（待出院满 {args.days} 天）")
        for number in numbers:
            print(f"  - {number}")
    finally:
        conn.close()
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    payload = collect_health()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] in {"ok", "degraded"} else 1


def cmd_periods(args: argparse.Namespace) -> int:
    """打印半日制作息（`session_period` 的时间真源）。

    > 2026-10-05：**两段输出被删掉了**，因为它们已无任何消费者：
    > 1. `close-expired` 子命令 —— 随临时指派删除（迁移 009），
    >    它唯一的工作就是把过期的 `temporary_assignment` 置为 closed，那张表已不存在；
    > 2. "各半日区间的结束时刻" —— 那是临时指派 `expires_at` 的计算方式，
    >    临时指派删除后没有任何调用方（`period_end_datetime` 也随之删除）。
    >
    > 剩下的半日边界仍然有用：它决定一条治疗记录属于哪个半日（`session_period`），
    > 运维需要能直接看到它。注意只有 `am`/`pm` —— 治疗记录不接受 `full`。
    """
    cfg = get_settings()
    print("半日制作息（Q11 定稿）：")
    for period, bounds in day_period_bounds(cfg.worktime).items():
        print(f"  {period}（{bounds['label']}）：{bounds['start']} – {bounds['end']}")
    return 0


def cmd_tables(args: argparse.Namespace) -> int:
    cfg = get_settings()
    if not cfg.db_path.exists():
        print("数据库不存在，请先执行 init。", file=sys.stderr)
        return 1
    conn = storage.connect(cfg)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        print(f"{'表名':<32}{'行数':>8}")
        print("-" * 40)
        for row in rows:
            count = conn.execute(f'SELECT COUNT(*) FROM "{row["name"]}"').fetchone()[0]
            print(f"{row['name']:<32}{count:>8}")
        views = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'view' ORDER BY name"
        ).fetchall()
        if views:
            print("\n视图：")
            for row in views:
                print(f"  {row['name']}")
    finally:
        conn.close()
    return 0


def cmd_create_admin(args: argparse.Namespace) -> int:
    """创建初始管理员（首次部署必需）。

    密码来源优先级：命令行 `--password` > 环境变量 `KB_ADMIN_PASSWORD` > 交互式输入。
    **不建议**把密码写在命令行里（会进 shell 历史），部署脚本请用环境变量。
    """
    cfg = get_settings()
    if not cfg.db_path.exists():
        print("数据库不存在，请先执行 init。", file=sys.stderr)
        return 1

    employee_no = args.employee_no
    password = args.password or os.environ.get("KB_ADMIN_PASSWORD")
    if not password:
        import getpass

        password = getpass.getpass(f"为管理员 {employee_no} 设置密码（至少 8 位）：")
    if len(password) < 8:
        print("密码至少 8 位。", file=sys.stderr)
        return 1

    conn = storage.connect(cfg)
    try:
        existing = user_model.get_by_employee_no(conn, employee_no)
        if existing is not None:
            user_model.set_password(conn, int(existing["id"]), password)
            if existing["role"] != user_model.ROLE_ADMIN:
                user_model.update_user(conn, int(existing["id"]), role=user_model.ROLE_ADMIN)
            print(f"已更新管理员密码与角色：{employee_no}（工号 {employee_no}）")
            return 0
        user = user_model.create_user(
            conn,
            employee_no=employee_no,
            name=args.name,
            role=user_model.ROLE_ADMIN,
            password=password,
        )
    finally:
        conn.close()
    print(f"已创建管理员：{user['name']}（工号 {user['employee_no']}，id={user['id']}）")
    if cfg.is_dev_secret:
        print("提醒：仍在使用开发用 JWT 默认密钥，部署前请设置 KB_JWT_SECRET。", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description="康复科治疗过程记录系统 — 运维 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="建库并迁移到最新").set_defaults(func=cmd_init)
    sub.add_parser("migrate", help="应用未执行的迁移").set_defaults(func=cmd_migrate)
    sub.add_parser("seed", help="已废弃：字典种子不再导入（记录改由 JSON 模板驱动）").set_defaults(
        func=cmd_seed
    )
    auto_discharge = sub.add_parser("auto-discharge", help="待出院满 N 天者自动出院（默认 7 天）")
    auto_discharge.add_argument("--days", type=int, default=7, help="待出院多少天后自动出院（默认 7）")
    auto_discharge.add_argument("--now", default=None, help="注入当前时刻（ISO8601 UTC），便于补跑与测试")
    auto_discharge.add_argument("--dry-run", action="store_true", help="只列出将要出院的患者，不改状态")
    auto_discharge.set_defaults(func=cmd_auto_discharge)
    create_admin = sub.add_parser("create-admin", help="创建或重置初始管理员")
    create_admin.add_argument("employee_no", help="管理员工号")
    create_admin.add_argument("--name", default="系统管理员", help="姓名")
    create_admin.add_argument("--password", default=None, help="密码（建议改用环境变量 KB_ADMIN_PASSWORD）")
    create_admin.set_defaults(func=cmd_create_admin)
    sub.add_parser("health", help="健康检查（JSON）").set_defaults(func=cmd_health)
    sub.add_parser("periods", help="打印半日制作息").set_defaults(func=cmd_periods)
    sub.add_parser("tables", help="列出表与行数").set_defaults(func=cmd_tables)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
