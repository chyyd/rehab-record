"""患者反应定义的种子导入（`设计.md` 3.6.5 / M04）。

数据来源：`seed/response_seed.json`，由 `设计.md` 8.2 四套模板的
「患者反应（多选 + 评分）」表生成（见 `backend/data/_gen_resp.py` 的生成逻辑说明）。

**为什么需要它**：`设计.md` 8.2 把患者反应定义得很细（NRS 疼痛、Borg 疲劳、呛咳次数、
SpO2、残留程度…），但 V1.1 的数据模型只有一个自由 JSON 字段，没有定义可依。`response_def`
就是这份定义，记录页据此渲染可选项与取值约束（见 `设计.md` 4.2.2）。

幂等：按 `(main_item_code, code)` 定位，`main_item_id` 由 `main_item.code` 解析。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SEED_FILE = Path(__file__).resolve().parent / "response_seed.json"

VALID_VALUE_TYPES = {"tag", "number", "select", "text"}


class ResponseSeedError(RuntimeError):
    """反应定义种子不合法或无法导入。"""


@dataclass
class ResponseSeedStats:
    total: int = 0
    created: int = 0
    updated: int = 0
    by_type: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        types = "、".join(f"{k} {v}" for k, v in sorted(self.by_type.items()))
        return f"反应定义 {self.total} 条（新增 {self.created} / 更新 {self.updated}）｜{types}"


def load_seed_data(path: Path | None = None) -> dict[str, Any]:
    target = path or SEED_FILE
    if not target.is_file():
        raise ResponseSeedError(f"反应定义种子文件不存在：{target}")
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ResponseSeedError(f"反应定义种子不是合法 JSON：{exc}") from exc
    defs = data.get("response_defs")
    if not isinstance(defs, list) or not defs:
        raise ResponseSeedError("反应定义种子缺少 response_defs 或为空")
    return data


def validate(data: dict[str, Any]) -> None:
    seen: set[tuple[str, str]] = set()
    for item in data["response_defs"]:
        code = item.get("code")
        main_code = item.get("main_item_code")
        if not code:
            raise ResponseSeedError(f"反应定义缺少 code：{item.get('label')!r}")
        if not main_code:
            raise ResponseSeedError(f"反应定义 {code} 缺少 main_item_code")
        key = (main_code, code)
        if key in seen:
            # 库层有 UNIQUE(IFNULL(main_item_id,-1), code)，必须先在这里拦住
            raise ResponseSeedError(f"同一主项目下反应 code 重复：{key}")
        seen.add(key)

        value_type = item.get("value_type")
        if value_type not in VALID_VALUE_TYPES:
            raise ResponseSeedError(f"{code} 的 value_type 非法：{value_type!r}")

        value_key = item.get("value_key")
        vmin, vmax = item.get("value_min"), item.get("value_max")
        options = item.get("options") or []

        if value_type == "tag":
            # 库层 CHECK：tag 不允许有 value_key（标签类反应没有取值）
            if value_key is not None:
                raise ResponseSeedError(f"{code} 是 tag 但带 value_key={value_key!r}")
        if value_type == "select" and not options:
            raise ResponseSeedError(f"{code} 是 select 但没有选项")
        if value_type != "select" and options:
            raise ResponseSeedError(f"{code} 非 select 却有选项")
        if vmin is not None and vmax is not None and vmax < vmin:
            raise ResponseSeedError(f"{code} 的取值范围颠倒：min={vmin} max={vmax}")


def _resolve_main_item_id(conn: sqlite3.Connection, main_code: str) -> int:
    row = conn.execute("SELECT id FROM main_item WHERE code = ?", (main_code,)).fetchone()
    if row is None:
        raise ResponseSeedError(
            f"主项目 {main_code!r} 不在库中。请先导入字典种子（python -m app.cli seed）。"
        )
    return int(row["id"])


def seed_responses(conn: sqlite3.Connection, path: Path | None = None) -> ResponseSeedStats:
    data = load_seed_data(path)
    validate(data)

    stats = ResponseSeedStats()
    conn.execute("SAVEPOINT seed_responses")
    try:
        for item in data["response_defs"]:
            main_id = _resolve_main_item_id(conn, item["main_item_code"])
            options = item.get("options") or []
            values = (
                item["label"],
                item["value_type"],
                item.get("value_key"),
                item.get("value_unit"),
                item.get("value_min"),
                item.get("value_max"),
                json.dumps(options, ensure_ascii=False) if options else None,
                int(item.get("sort", 0)),
            )
            row = conn.execute(
                "SELECT id FROM response_def WHERE IFNULL(main_item_id, -1) = ? AND code = ?",
                (main_id, item["code"]),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE response_def SET label = ?, value_type = ?, value_key = ?, value_unit = ?,"
                    " value_min = ?, value_max = ?, options_json = ?, sort = ? WHERE id = ?",
                    (*values, row["id"]),
                )
                stats.updated += 1
            else:
                conn.execute(
                    "INSERT INTO response_def (main_item_id, code, label, value_type, value_key,"
                    " value_unit, value_min, value_max, options_json, sort)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (main_id, item["code"], *values),
                )
                stats.created += 1
            stats.total += 1
            stats.by_type[item["value_type"]] = stats.by_type.get(item["value_type"], 0) + 1
        conn.execute("RELEASE seed_responses")
    except Exception:
        conn.execute("ROLLBACK TO seed_responses")
        conn.execute("RELEASE seed_responses")
        raise
    return stats


__all__ = [
    "SEED_FILE",
    "ResponseSeedError",
    "ResponseSeedStats",
    "load_seed_data",
    "seed_responses",
    "validate",
]
