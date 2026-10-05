"""运维 CLI（纯标准库，零依赖）。

    python -m app.cli init      # 建库 + 迁移到最新
    python -m app.cli migrate   # 只跑迁移
    python -m app.cli seed      # 导入字典种子（幂等）
    python -m app.cli health    # 健康检查（JSON）
    python -m app.cli periods   # 打印半日制作息与边界（Q11）
    python -m app.cli tables    # 列出表与行数
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

from app.core.config import get_settings
from app.core.health import collect_health
from app.core.worktime import day_period_bounds, period_end_datetime, period_label
from app.db import storage
from app.models import user as user_model
from seed.dictionary import seed_dictionary
from seed.options import seed_options
from seed.responses import seed_responses
from seed.templates import seed_templates


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
    """导入全部种子（幂等，可重复执行）。

    顺序有依赖：反应定义、选项集、模板都要引用字典里的 `code`，所以字典必须先导。
    模板放最后 —— 它同时依赖主项目与子项目，字典导完才可能成功。
    """
    cfg = get_settings()
    if not cfg.db_path.exists():
        print("数据库不存在，请先执行 init。", file=sys.stderr)
        return 1

    conn = storage.connect(cfg)
    try:
        print("① 字典（主项目 / 子项目 / 参数定义）")
        dict_stats = seed_dictionary(conn)
        print(f"   {dict_stats.summary()}")

        print("② 患者反应定义")
        resp_stats = seed_responses(conn)
        print(f"   {resp_stats.summary()}")

        print("③ 全局选项集")
        opt_stats = seed_options(conn)
        print(f"   {opt_stats.summary()}")
        if opt_stats.skipped_variants:
            codes = "、".join(sorted(opt_stats.variants))
            print(f"   注意：以下 code 存在多套选项变体，全局层只保留主变体（差异仍在各子项目的参数里）：{codes}")

        print("④ 四大高频模板（科室模板）")
        tpl_stats = seed_templates(conn)
        print(f"   {tpl_stats.summary()}")
    finally:
        conn.close()
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    payload = collect_health()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] in {"ok", "degraded"} else 1


def cmd_periods(args: argparse.Namespace) -> int:
    """打印半日制作息与各半日区间的结束时刻。

    > 2026-10-05：`close-expired` 子命令随临时指派删除（迁移 009）——
    > 它唯一的工作就是把过期的 `temporary_assignment` 置为 closed，那张表已经不存在。
    > 本子命令保留：半日边界仍是治疗记录 `session_period` 的时间真源，
    > 运维需要能直接看到它。原来"临时指派到期时点"的说法已去掉。
    """
    cfg = get_settings()
    print("半日制作息（Q11 定稿）：")
    for period, bounds in day_period_bounds(cfg.worktime).items():
        print(f"  {period}（{bounds['label']}）：{bounds['start']} – {bounds['end']}")
    print("\n各半日区间的结束时刻（当地墙钟）：")
    today = date.today()
    for period in ("am", "pm", "full"):
        end_at = period_end_datetime(today, period, cfg.worktime)
        print(f"  {period:<4}（{period_label(period)}）→ {end_at.isoformat(sep=' ')}")
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
    sub.add_parser("seed", help="导入字典种子（幂等）").set_defaults(func=cmd_seed)
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
