"""主项目 / 子项目 / 参数定义的种子导入（幂等）。

数据来源：`seed/dict_seed.json`，由 `设计.md` 8.2 的四套模板表生成
（见 `开发计划.md` 阶段 3 的 T3.2 与风险 R1）。

**幂等**：一切按 `code` upsert，不依赖自增 id。
重复导入同一份数据不会产生重复行，也不会改动已被科室修改过的名称？
—— 会改：名称与参数定义以种子为准（种子是"标准字典"），
但 `code` 永不变，因此历史记录靠快照（`sub_item_name_snapshot` / `params_snapshot_json`）
仍能正确显示（对齐 `设计.md` 4.3）。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SEED_FILE = Path(__file__).resolve().parent / "dict_seed.json"


class SeedError(RuntimeError):
    """种子数据不合法或无法导入。"""


@dataclass
class SeedStats:
    main_items: int = 0
    sub_items: int = 0
    params: int = 0
    created: dict[str, int] = field(default_factory=lambda: {"main_items": 0, "sub_items": 0, "params": 0})
    updated: dict[str, int] = field(default_factory=lambda: {"main_items": 0, "sub_items": 0, "params": 0})

    def summary(self) -> str:
        return (
            f"主项目 {self.main_items}（新增 {self.created['main_items']} / 更新 {self.updated['main_items']}），"
            f"子项目 {self.sub_items}（新增 {self.created['sub_items']} / 更新 {self.updated['sub_items']}），"
            f"参数 {self.params}（新增 {self.created['params']} / 更新 {self.updated['params']}）"
        )


def load_seed_data(path: Path | None = None) -> dict[str, Any]:
    target = path or SEED_FILE
    if not target.is_file():
        raise SeedError(f"种子文件不存在：{target}")
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SeedError(f"种子文件不是合法 JSON：{exc}") from exc

    main_items = data.get("main_items")
    if not isinstance(main_items, list) or not main_items:
        raise SeedError("种子文件缺少 main_items 或为空")
    return data


def _validate(data: dict[str, Any]) -> None:
    """导入前校验：库层约束是最后防线，这里先给出可读的错误。"""
    seen_main: set[str] = set()
    for main in data["main_items"]:
        code = main.get("code")
        if not code:
            raise SeedError(f"主项目缺少 code：{main.get('name')!r}")
        if code in seen_main:
            raise SeedError(f"主项目 code 重复：{code}")
        seen_main.add(code)

        seen_sub: set[str] = set()
        for sub in main.get("sub_items", []):
            sub_code = sub.get("code")
            if not sub_code:
                raise SeedError(f"主项目 {code} 下有子项目缺少 code：{sub.get('name')!r}")
            if sub_code in seen_sub:
                raise SeedError(f"主项目 {code} 下子项目 code 重复：{sub_code}")
            seen_sub.add(sub_code)

            seen_key: set[str] = set()
            for param in sub.get("params", []):
                key = param.get("param_key")
                if not key:
                    raise SeedError(f"子项目 {sub_code} 下有参数缺少 param_key：{param.get('param_name')!r}")
                if key in seen_key:
                    # 库层有 UNIQUE(sub_item_id, param_key)，必须先在这里拦住
                    raise SeedError(f"子项目 {sub_code} 内 param_key 重复：{key}")
                seen_key.add(key)

                input_type = param.get("input_type")
                if input_type not in {"select", "multi_select", "number", "text"}:
                    raise SeedError(f"{sub_code}.{key} 的 input_type 非法：{input_type!r}")
                options = param.get("options") or []
                default = param.get("default_value")
                if input_type in {"select", "multi_select"}:
                    if not options:
                        raise SeedError(f"{sub_code}.{key} 是选择题但没有选项")
                    if default is not None:
                        if not isinstance(default, list):
                            raise SeedError(f"{sub_code}.{key} 是选择题但默认值不是列表：{default!r}")
                        for d in default:
                            if d not in options:
                                raise SeedError(f"{sub_code}.{key} 默认值 {d!r} 不在选项中")
                    if input_type == "select" and isinstance(default, list) and len(default) > 1:
                        raise SeedError(f"{sub_code}.{key} 是单选却有多默认值：{default!r}")
                else:
                    if options:
                        raise SeedError(f"{sub_code}.{key} 非选择题却有选项")
                    if isinstance(default, list):
                        raise SeedError(f"{sub_code}.{key} 非选择题但默认值是列表")


def _encode_default(default: Any) -> str | None:
    """选择题的默认值是列表 → 存 JSON；数字/文本直接存字符串。"""
    if default is None:
        return None
    if isinstance(default, list):
        return json.dumps(default, ensure_ascii=False)
    return str(default)


def seed_dictionary(conn: sqlite3.Connection, path: Path | None = None) -> SeedStats:
    """把种子导入数据库。调用方负责事务边界（本函数用 SAVEPOINT，失败可整体回滚）。"""
    data = load_seed_data(path)
    _validate(data)

    stats = SeedStats()
    conn.execute("SAVEPOINT seed_dictionary")
    try:
        for main in data["main_items"]:
            main_id = _upsert_main_item(conn, main, stats)
            for sub in main.get("sub_items", []):
                sub_id = _upsert_sub_item(conn, main_id, sub, stats)
                for param in sub.get("params", []):
                    _upsert_param(conn, sub_id, param, stats)
        conn.execute("RELEASE seed_dictionary")
    except Exception:
        conn.execute("ROLLBACK TO seed_dictionary")
        conn.execute("RELEASE seed_dictionary")
        raise
    return stats


def _upsert_main_item(conn: sqlite3.Connection, main: dict[str, Any], stats: SeedStats) -> int:
    row = conn.execute("SELECT id FROM main_item WHERE code = ?", (main["code"],)).fetchone()
    if row:
        conn.execute(
            "UPDATE main_item SET name = ?, sort = ?, status = 'active' WHERE id = ?",
            (main["name"], main.get("sort", 0), row["id"]),
        )
        stats.updated["main_items"] += 1
        main_id = int(row["id"])
    else:
        cur = conn.execute(
            "INSERT INTO main_item (name, code, sort, status) VALUES (?, ?, ?, 'active')",
            (main["name"], main["code"], main.get("sort", 0)),
        )
        stats.created["main_items"] += 1
        main_id = int(cur.lastrowid)
    stats.main_items += 1
    return main_id


def _upsert_sub_item(conn: sqlite3.Connection, main_id: int, sub: dict[str, Any], stats: SeedStats) -> int:
    row = conn.execute("SELECT id FROM sub_item WHERE code = ?", (sub["code"],)).fetchone()
    if row:
        conn.execute(
            "UPDATE sub_item SET main_item_id = ?, name = ?, sort = ?, status = 'active' WHERE id = ?",
            (main_id, sub["name"], sub.get("sort", 0), row["id"]),
        )
        stats.updated["sub_items"] += 1
        sub_id = int(row["id"])
    else:
        cur = conn.execute(
            "INSERT INTO sub_item (main_item_id, name, code, sort, status) VALUES (?, ?, ?, ?, 'active')",
            (main_id, sub["name"], sub["code"], sub.get("sort", 0)),
        )
        stats.created["sub_items"] += 1
        sub_id = int(cur.lastrowid)
    stats.sub_items += 1
    return sub_id


def _upsert_param(conn: sqlite3.Connection, sub_id: int, param: dict[str, Any], stats: SeedStats) -> None:
    options = param.get("options") or []
    options_json = json.dumps(options, ensure_ascii=False) if options else None
    default_value = _encode_default(param.get("default_value"))
    # 顺序必须与下面两条 SQL 的占位符一一对应：
    #   (param_name, input_type, options_json, default_value, required, unit, sort)
    values = (
        param["param_name"],
        param["input_type"],
        options_json,
        default_value,
        int(param.get("required", 0)),
        param.get("unit"),
        param.get("sort", 0),
    )
    row = conn.execute(
        "SELECT id FROM sub_item_param_def WHERE sub_item_id = ? AND param_key = ?",
        (sub_id, param["param_key"]),
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE sub_item_param_def SET param_name = ?, input_type = ?, options_json = ?,"
            " default_value = ?, required = ?, unit = ?, sort = ? WHERE id = ?",
            (*values, row["id"]),
        )
        stats.updated["params"] += 1
    else:
        conn.execute(
            "INSERT INTO sub_item_param_def (sub_item_id, param_key, param_name, input_type,"
            " options_json, default_value, required, unit, sort) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sub_id, param["param_key"], *values),
        )
        stats.created["params"] += 1
    stats.params += 1


__all__ = ["SEED_FILE", "SeedError", "SeedStats", "load_seed_data", "seed_dictionary"]
