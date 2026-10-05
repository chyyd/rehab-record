r"""端到端验收脚本的公共设施。

## 为什么需要这个模块

验收脚本要能在**同一个数据库上重复运行**（跑一次通过、再跑一次还得通过）。
最早就吃过亏：脚本按"干净库"写，删患者时没有先清依赖行，
第二次运行必定 `FOREIGN KEY constraint failed`；而每次换新库跑就永远发现不了。

因此删除一律走 :func:`purge_patients`，由它按外键依赖顺序清理，
脚本自己不要手写 DELETE 语句。

## 依赖顺序（子表 → 父表）

    treatment_record ┐
    patient_assignment_history ┘→ patient

`change_log` 用实体名+字符串 id 记录，没有外键，可以最后按 entity_id 清。

## 历史

> 2026-10-05：`appointment` / `rest_block` / `leave_record` 三张表随排期功能下线删除（迁移 008），
> `temporary_assignment` 随后也被彻底删除（迁移 009）。
>
> 2026-10-05（SOAP 改造）：`record_item` 随迁移 011 删除（记录只存 `body_json` +
> `rendered_text`），字典/选项集/反应定义六张表随迁移 012 删除。
> 曾经在本文件里的 `purge_option_sets()` 与 `purge_templates()` 也随之**删除** ——
> 它们要删的表已经不存在了，留着只会在运行时报 `no such table`。
> 记录模板现在是 `templates/*.json` **文件**，不进数据库，所以没有任何"清理模板"的需求。
## 独立数据库（2026-10-05 新增）

**验收脚本不再写开发库。** 原来 `data/kf.db` 会被跑验收时塞满测试夹具
（一次全跑留下 12 位测试患者 + 51 条记录），把开发库搞脏 ——
而 `purge_patients` 只在脚本正常跑到结尾时才清，中途失败就留下残留。

现在本模块**在导入时**把 `KB_DB_PATH` 指到 `.run/e2e_kf.db`（仓库根下、已 gitignore），
每个脚本一份（按脚本名区分）。想覆盖就自己先设 `KB_DB_PATH`。
想重建就在跑之前删掉那个文件。

```powershell
Remove-Item .run\e2e_*.db            # 清掉所有验收库
python scripts\verify_stage3.py      # 会用 .run\e2e_verify_stage3.db
```

> 为什么在**导入时**设：`app.core.config.get_settings()` 是 `lru_cache` 单例，
> 而各脚本都是在 `main()` 里才第一次调用它 —— 只要本模块先被导入就来得及。
> 各脚本的 `from _e2e import …` 都在 `import uvicorn` 之前，所以顺序是安全的。
"""

from __future__ import annotations

import os
import sqlite3
import sys
from collections.abc import Iterable
from pathlib import Path


# --------------------------------------------------------------------------- #
# 把本次验收切到独立库（必须在任何 get_settings() 之前执行 —— 见模块 docstring）
# --------------------------------------------------------------------------- #
def _use_isolated_db() -> Path | None:
    """把 `KB_DB_PATH` 指到 `.run/e2e_<脚本名>.db`；调用方已显式指定则不动。"""
    if os.environ.get("KB_DB_PATH"):
        return None  # 调用方自己指定了（例如想复用某个库），尊重它

    # backend/scripts/_e2e.py -> 仓库根
    repo_root = Path(__file__).resolve().parents[2]
    run_dir = repo_root / ".run"
    run_dir.mkdir(parents=True, exist_ok=True)

    stem = Path(sys.argv[0]).stem or "e2e"
    # 文件名只用 ASCII 与下划线：Windows 上路径带中文/特殊字符容易出事
    safe = "".join(ch if (ch.isascii() and (ch.isalnum() or ch in "_-")) else "_" for ch in stem)
    db_path = run_dir / f"e2e_{safe}.db"
    os.environ["KB_DB_PATH"] = str(db_path)
    return db_path


ISOLATED_DB = _use_isolated_db()


def ensure_database() -> None:
    """确保隔离库存在并已迁移到最新。

    ★ 这一步是**必须**的：切到独立库后它一开始是空的，而各脚本都有
    "库不存在就早退 exit 2"的保护（那条保护本身是对的 —— 在开发库上误跑
    确实应该先提示 `app.cli init`）。这里替它们建好，脚本就不必自己管库。

    幂等：已存在的库只会"跳过 N 个迁移"，没有副作用。
    """
    from app.core.config import get_settings
    from app.db import storage

    settings = get_settings()
    conn = storage.connect(settings)
    try:
        storage.migrate(conn, storage.discover_migrations(settings=settings))
    finally:
        conn.close()


# 建库时机：只有真的切到了隔离库才建。调用方自己指定 KB_DB_PATH 时不动它的库 ——
# 那种情况调用方知道自己要什么（例如刻意复用某个库做对比）。
if ISOLATED_DB is not None:
    ensure_database()


def purge_patients(conn: sqlite3.Connection, patient_nos: Iterable[str]) -> None:
    """彻底删除这些患者及其全部关联数据（按外键顺序）。"""
    nos = [str(no) for no in patient_nos]
    if not nos:
        return
    marks = ", ".join("?" for _ in nos)

    # 治疗记录（SOAP 模型：一条记录一行，不再有 record_item 子表）
    record_ids = [
        str(row["id"])
        for row in conn.execute(
            f"SELECT id FROM treatment_record WHERE patient_no IN ({marks})", nos
        ).fetchall()
    ]
    conn.execute(f"DELETE FROM treatment_record WHERE patient_no IN ({marks})", nos)

    # 归属历史
    conn.execute(f"DELETE FROM patient_assignment_history WHERE patient_no IN ({marks})", nos)

    # 变更日志（无外键，按实体名 + 字符串 id 清）
    if record_ids:
        id_marks = ", ".join("?" for _ in record_ids)
        conn.execute(
            f"DELETE FROM change_log WHERE entity = 'treatment_record'"
            f" AND entity_id IN ({id_marks})",
            record_ids,
        )

    conn.execute(f"DELETE FROM patient WHERE inpatient_no IN ({marks})", nos)


def purge_users(conn: sqlite3.Connection, employee_nos: Iterable[str]) -> None:
    """删除用户及其会话等关联行（按外键顺序）。

    验收脚本一般不删用户（改为重置密码），保留此函数供特殊场景使用。
    """
    nos = [str(n) for n in employee_nos]
    if not nos:
        return
    marks = ", ".join("?" for _ in nos)
    ids = [
        str(row["id"])
        for row in conn.execute(f"SELECT id FROM user WHERE employee_no IN ({marks})", nos).fetchall()
    ]
    if not ids:
        return
    id_marks = ", ".join("?" for _ in ids)
    conn.execute(f"DELETE FROM auth_session WHERE user_id IN ({id_marks})", ids)
    conn.execute(f"DELETE FROM user WHERE id IN ({id_marks})", ids)


__all__ = ["purge_patients", "purge_users"]
