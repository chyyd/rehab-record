"""选项集种子导入（`设计.md` 3.6.4 / M03）。

数据来源：`seed/option_seed.json`，从 `dict_seed.json` 汇总——把每个 `param_key`
在各子项目里**实际使用**的选项集合提取出来，作为全局（`scope='global'`）选项集。

**为什么要单独一份**：`sub_item_param_def.options_json` 是"该子项目开箱可用的内置选项"；
`option_set` 是科室/个人可维护、可停用、可改别名的三层选项集（3.6.4）。
两者通过 `code`（= `param_key`）关联，解析顺序为 个人 → 科室 → 全局 → 内置。

**关于变体（重要限制）**：同一个 `param_key` 在不同子项目里可能有不同选项集合
（如 `assistance_level` 有 6 项与 4 项两套）。`option_seed.json` 保留了全部变体，
但当前库结构 `UNIQUE(scope, owner_user_id, dept_tag, code)` **只允许一个 code 一套全局选项**，
因此这里只导入每套的**主变体**（选项最多的那套）。差异仍完整保留在
`sub_item_param_def.options_json` 里，记录页按子项目渲染不受影响，
只是"跨子项目的全局统一选项"这一层暂时取并集的最大集合。
如需让全局层也支持多变体，需要给 `option_set` 增加 `variant` 列（记入待办）。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SEED_FILE = Path(__file__).resolve().parent / "option_seed.json"


class OptionSeedError(RuntimeError):
    """选项集种子不合法或无法导入。"""


@dataclass
class OptionSeedStats:
    sets: int = 0
    items: int = 0
    created_sets: int = 0
    updated_sets: int = 0
    created_items: int = 0
    updated_items: int = 0
    skipped_variants: int = 0
    variants: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        return (
            f"全局选项集 {self.sets} 套 / {self.items} 项"
            f"（选项集 新增 {self.created_sets} 更新 {self.updated_sets}；"
            f"选项项 新增 {self.created_items} 更新 {self.updated_items}）"
            f"｜跳过同 code 变体 {self.skipped_variants} 套"
        )


def load_seed_data(path: Path | None = None) -> dict[str, Any]:
    target = path or SEED_FILE
    if not target.is_file():
        raise OptionSeedError(f"选项集种子文件不存在：{target}")
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OptionSeedError(f"选项集种子不是合法 JSON：{exc}") from exc
    sets = data.get("option_sets")
    if not isinstance(sets, list) or not sets:
        raise OptionSeedError("选项集种子缺少 option_sets 或为空")
    return data


def validate(data: dict[str, Any]) -> None:
    primaries: set[tuple[str, str, str]] = set()
    for item in data["option_sets"]:
        code = item.get("code")
        scope = item.get("scope")
        if not code:
            raise OptionSeedError("选项集缺少 code")
        if scope not in {"global", "dept", "personal"}:
            raise OptionSeedError(f"选项集 {code} 的 scope 非法：{scope!r}")
        items = item.get("items") or []
        if not items:
            raise OptionSeedError(f"选项集 {code} 没有选项项")
        values = [i.get("value") for i in items]
        if any(v is None or v == "" for v in values):
            raise OptionSeedError(f"选项集 {code} 存在空的选项 value")
        if len(values) != len(set(values)):
            raise OptionSeedError(f"选项集 {code} 的选项 value 重复")

        if item.get("is_primary"):
            key = (scope, item.get("dept_tag") or "", code)
            if key in primaries:
                # 库层 UNIQUE(scope, owner, dept_tag, code) 只允许一套
                raise OptionSeedError(f"同一 scope 下 code 有多个主变体：{key}")
            primaries.add(key)


def seed_options(conn: sqlite3.Connection, path: Path | None = None) -> OptionSeedStats:
    data = load_seed_data(path)
    validate(data)

    stats = OptionSeedStats()
    conn.execute("SAVEPOINT seed_options")
    try:
        for item in data["option_sets"]:
            if not item.get("is_primary"):
                # 同 code 的非主变体：库结构不允许，跳过并计数（见模块 docstring）
                stats.skipped_variants += 1
                stats.variants[item["code"]] = stats.variants.get(item["code"], 0) + 1
                continue

            scope = item["scope"]
            dept_tag = item.get("dept_tag")
            code = item["code"]
            row = conn.execute(
                "SELECT id FROM option_set WHERE scope = ? AND IFNULL(dept_tag, '') = ? AND code = ?",
                (scope, dept_tag or "", code),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE option_set SET name = ?, status = 'active', sort = ? WHERE id = ?",
                    (item["name"], int(item.get("sort", 0)), row["id"]),
                )
                set_id = int(row["id"])
                stats.updated_sets += 1
            else:
                cur = conn.execute(
                    "INSERT INTO option_set (scope, dept_tag, code, name, status, sort)"
                    " VALUES (?, ?, ?, ?, 'active', ?)",
                    (scope, dept_tag, code, item["name"], int(item.get("sort", 0))),
                )
                set_id = int(cur.lastrowid)
                stats.created_sets += 1
            stats.sets += 1

            # 选项项：按 (option_set_id, value) 幂等
            for n, opt in enumerate(item["items"]):
                opt_row = conn.execute(
                    "SELECT id FROM option_item WHERE option_set_id = ? AND value = ?",
                    (set_id, opt["value"]),
                ).fetchone()
                if opt_row:
                    conn.execute(
                        "UPDATE option_item SET label = ?, sort = ?, status = 'active' WHERE id = ?",
                        (opt.get("label", opt["value"]), int(opt.get("sort", n * 10)), opt_row["id"]),
                    )
                    stats.updated_items += 1
                else:
                    conn.execute(
                        "INSERT INTO option_item (option_set_id, value, label, sort, status)"
                        " VALUES (?, ?, ?, ?, 'active')",
                        (set_id, opt["value"], opt.get("label", opt["value"]), int(opt.get("sort", n * 10))),
                    )
                    stats.created_items += 1
                stats.items += 1
        conn.execute("RELEASE seed_options")
    except Exception:
        conn.execute("ROLLBACK TO seed_options")
        conn.execute("RELEASE seed_options")
        raise
    return stats


__all__ = ["SEED_FILE", "OptionSeedError", "OptionSeedStats", "load_seed_data", "seed_options", "validate"]
