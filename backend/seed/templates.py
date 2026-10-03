"""四大高频模板的种子导入（幂等）。

数据来源：`seed/dict_seed.json` 的 `templates` 段，由 `设计.md` 8.2.1–8.2.4 生成
（见 `开发计划.md` 的 D04 与 T3.2）。

## 模板是什么

模板 =「某主项目下的一组常用子项目 + 每个子项目的预填参数」。
`record_template.main_item_id` 是必填且参与唯一键，因此**每套模板归属一个主项目** ——
设计里的四大高频模板正好与四个主项目一一对应，各含该主项目下的全部子项目。

## 参数预填值从哪来

**直接取字典种子里的参数默认值**（`default_value`），不另写一份参数映射。

理由：`设计.md` 8.2 的"默认值"列同时是字典默认值和模板预填值，两者本就同源。
如果再维护一份模板参数表，两处默认值迟早会各自漂移，而"记录页带入的值"与
"模板套出来的值"不一致是极难排查的问题。字典种子已是单一事实来源，这里只做转换。

## 幂等

按 `(scope='dept', main_item_id, name)` upsert（按 code/名称，不按自增 id）；
明细整体替换而非追加，因此重复导入不会产生重复行。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from seed.dictionary import SEED_FILE, SeedError, load_seed_data

TEMPLATE_SCOPE = "dept"


@dataclass
class TemplateSeedStats:
    templates: int = 0
    items: int = 0
    created: int = 0
    updated: int = 0
    skipped: list[str] = field(default_factory=list)

    def summary(self) -> str:
        text = (
            f"模板 {self.templates}（新增 {self.created} / 更新 {self.updated}），"
            f"模板明细 {self.items}"
        )
        if self.skipped:
            text += f"；跳过 {len(self.skipped)} 项：{', '.join(self.skipped)}"
        return text


def load_templates(path: Path | None = None) -> list[dict[str, Any]]:
    """从字典种子里取出模板定义。"""
    data = load_seed_data(path)
    templates = data.get("templates") or []
    if not isinstance(templates, list):
        raise SeedError("种子文件的 templates 必须是数组")

    seen: set[tuple[str, str]] = set()
    seen_codes: set[str] = set()
    for template in templates:
        name = template.get("name")
        main_code = template.get("main_item_code")
        code = template.get("code")
        if not name or not main_code or not code:
            raise SeedError(f"模板缺少 name、code 或 main_item_code：{template!r}")
        if str(code) in seen_codes:
            raise SeedError(f"模板 code 重复：{code}")
        seen_codes.add(str(code))
        key = (str(main_code), str(name))
        if key in seen:
            raise SeedError(f"同一主项目下模板名重复：{main_code} / {name}")
        seen.add(key)
        if template.get("scope", TEMPLATE_SCOPE) != TEMPLATE_SCOPE:
            raise SeedError(
                f"种子只导入科室模板（scope='dept'），但 {name} 声明为 {template.get('scope')!r}"
            )
        codes = template.get("sub_item_codes")
        if not isinstance(codes, list) or not codes:
            raise SeedError(f"模板 {name} 的 sub_item_codes 必须是非空数组")
        if len(set(codes)) != len(codes):
            raise SeedError(f"模板 {name} 的子项目 code 重复")
    return templates


def _params_from_defaults(
    conn: sqlite3.Connection, sub_item_id: int, stats: TemplateSeedStats, sub_code: str
) -> dict[str, Any]:
    """用字典里的参数默认值组成模板的预填参数。

    - `default_value` 是 JSON 字符串（选择题）或裸值（数字/文本），需解码：
      模板参数被当作**值**存进 `params_json`，而字典默认值是**存储形式**，
      两者不同，直接塞进去会让"10"变成字符串 "10" 而不是数字 10。
    - 没有默认值的参数不写入 —— 预填一个 None 没有意义，还会在表单上显示成已填。
    """
    params: dict[str, Any] = {}
    rows = conn.execute(
        "SELECT param_key, default_value, input_type FROM sub_item_param_def"
        " WHERE sub_item_id = ? ORDER BY sort, id",
        (sub_item_id,),
    ).fetchall()
    if not rows:
        stats.skipped.append(f"{sub_code}（无参数定义）")
    for row in rows:
        raw = row["default_value"]
        if raw is None:
            continue
        params[str(row["param_key"])] = _decode_default(raw, str(row["input_type"]))
    return params


def _decode_default(raw: str, input_type: str) -> Any:
    """把字典里的默认值还原成参数值。

    选择题的默认值以 JSON 数组存储（单选也是长度 1 的数组），
    而参数值对单选应是标量、对多选应是数组 —— 因此单选要拆出首项。
    """
    if input_type == "number":
        try:
            number = float(raw)
        except (TypeError, ValueError):
            return raw
        return int(number) if number.is_integer() else number
    if input_type == "text":
        return raw
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if not isinstance(parsed, list):
        return parsed
    if input_type == "select":
        return parsed[0] if parsed else None
    return parsed


def seed_templates(conn: sqlite3.Connection, path: Path | None = None) -> TemplateSeedStats:
    """导入四大高频模板（幂等）。调用方负责事务边界（本函数用 SAVEPOINT）。"""
    templates = load_templates(path)
    stats = TemplateSeedStats()

    conn.execute("SAVEPOINT seed_templates")
    try:
        for template in templates:
            main_code = str(template["main_item_code"])
            main = conn.execute("SELECT id FROM main_item WHERE code = ?", (main_code,)).fetchone()
            if main is None:
                # 字典没导就先跑模板：明确报错，不要静默产生半套数据
                raise SeedError(f"主项目不存在：{main_code}（请先导入字典种子）")
            main_item_id = int(main["id"])

            items: list[tuple[int, dict[str, Any]]] = []
            for sub_code in template["sub_item_codes"]:
                sub = conn.execute("SELECT id FROM sub_item WHERE code = ?", (str(sub_code),)).fetchone()
                if sub is None:
                    raise SeedError(f"子项目不存在：{sub_code}（模板 {template['name']}）")
                sub_item_id = int(sub["id"])
                items.append(
                    (sub_item_id, _params_from_defaults(conn, sub_item_id, stats, str(sub_code)))
                )

            template_id = _upsert_template(
                conn,
                code=str(template["code"]),
                main_item_id=main_item_id,
                name=str(template["name"]),
                sort=int(template.get("sort", 0)),
                stats=stats,
            )
            # 明细整体替换：重复导入不产生重复行
            conn.execute("DELETE FROM record_template_item WHERE template_id = ?", (template_id,))
            for index, (sub_item_id, params) in enumerate(items):
                conn.execute(
                    "INSERT INTO record_template_item (template_id, sub_item_id, params_json, sort)"
                    " VALUES (?, ?, ?, ?)",
                    (template_id, sub_item_id, json.dumps(params, ensure_ascii=False), index * 10),
                )
                stats.items += 1
            stats.templates += 1
        conn.execute("RELEASE seed_templates")
    except Exception:
        conn.execute("ROLLBACK TO seed_templates")
        conn.execute("RELEASE seed_templates")
        raise
    return stats


def _upsert_template(
    conn: sqlite3.Connection, *, code: str, main_item_id: int, name: str, sort: int,
    stats: TemplateSeedStats
) -> int:
    """按 `code` 查已有模板（身份键），名称只是展示字段。

    **为什么不能用 name 当身份键**：唯一索引 `ux_template_scope` 含 name，
    而 name 是可改的。若按 name 查，一旦有人改了模板名，重导种子就会查不到旧行、
    再插一行，产生重复模板（实测踩到）。`code` 是稳定的，改名后仍能命中同一行。
    """
    row = conn.execute("SELECT id FROM record_template WHERE code = ?", (code,)).fetchone()
    if row is not None:
        conn.execute(
            "UPDATE record_template SET name = ?, main_item_id = ?, sort = ?, status = 'active',"
            " updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
            (name, main_item_id, sort, row["id"]),
        )
        stats.updated += 1
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO record_template (scope, owner_user_id, main_item_id, code, name, sort, status)"
        " VALUES (?, NULL, ?, ?, ?, ?, 'active')",
        (TEMPLATE_SCOPE, main_item_id, code, name, sort),
    )
    stats.created += 1
    return int(cur.lastrowid)


__all__ = [
    "SEED_FILE",
    "TEMPLATE_SCOPE",
    "TemplateSeedStats",
    "load_templates",
    "seed_templates",
]
