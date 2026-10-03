"""字典读取（阶段 3 / `设计.md` 3.6）。

字典是**只读**引用数据：写入由种子脚本（`seed/`）与管理后台负责，
业务接口只读。这样记录页渲染表单时不会意外改到字典。

三层结构：主项目 → 子项目 → 参数定义。参数定义里的 `options_json` 是
"内置默认选项"；科室与个人覆盖在 `option_set`（见 `services/options.py`）。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.core import jsonutil
from app.models.base import NotFound, row_to_dict

MAIN_ITEM_COLUMNS = "id, name, code, alias, sort, status"
SUB_ITEM_COLUMNS = "id, main_item_id, name, code, alias, sort, status"
PARAM_COLUMNS = (
    "id, sub_item_id, param_key, param_name, input_type, options_json, default_value,"
    " required, unit, sort, created_at, updated_at"
)


# --------------------------------------------------------------------------- #
# 主项目
# --------------------------------------------------------------------------- #
def list_main_items(conn: sqlite3.Connection, *, include_disabled: bool = False) -> list[dict[str, Any]]:
    clause = "" if include_disabled else "WHERE status = 'active'"
    rows = conn.execute(
        f"SELECT {MAIN_ITEM_COLUMNS} FROM main_item {clause} ORDER BY sort, id"
    ).fetchall()
    return [dict(r) for r in rows]


def get_main_item(conn: sqlite3.Connection, main_item_id: int) -> dict[str, Any] | None:
    return row_to_dict(
        conn.execute(f"SELECT {MAIN_ITEM_COLUMNS} FROM main_item WHERE id = ?", (main_item_id,)).fetchone()
    )


def get_main_item_or_raise(conn: sqlite3.Connection, main_item_id: int) -> dict[str, Any]:
    row = get_main_item(conn, main_item_id)
    if row is None:
        raise NotFound("主项目不存在", details={"main_item_id": main_item_id})
    return row


# --------------------------------------------------------------------------- #
# 子项目
# --------------------------------------------------------------------------- #
def list_sub_items(
    conn: sqlite3.Connection,
    *,
    main_item_id: int | None = None,
    include_disabled: bool = False,
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if not include_disabled:
        where.append("status = 'active'")
    if main_item_id is not None:
        where.append("main_item_id = ?")
        params.append(main_item_id)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    rows = conn.execute(
        f"SELECT {SUB_ITEM_COLUMNS} FROM sub_item {clause} ORDER BY main_item_id, sort, id", params
    ).fetchall()
    return [dict(r) for r in rows]


def get_sub_item(conn: sqlite3.Connection, sub_item_id: int) -> dict[str, Any] | None:
    return row_to_dict(
        conn.execute(f"SELECT {SUB_ITEM_COLUMNS} FROM sub_item WHERE id = ?", (sub_item_id,)).fetchone()
    )


def get_sub_item_or_raise(conn: sqlite3.Connection, sub_item_id: int) -> dict[str, Any]:
    row = get_sub_item(conn, sub_item_id)
    if row is None:
        raise NotFound("子项目不存在", details={"sub_item_id": sub_item_id})
    return row


# --------------------------------------------------------------------------- #
# 参数定义
# --------------------------------------------------------------------------- #
def _decode_param(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    """把参数行转成对外结构：`options_json` 解码成 `options` 列表。"""
    data = dict(row)
    data["options"] = jsonutil.loads(data.pop("options_json", None), []) or []
    return data


def list_params(conn: sqlite3.Connection, sub_item_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT {PARAM_COLUMNS} FROM sub_item_param_def WHERE sub_item_id = ? ORDER BY sort, id",
        (sub_item_id,),
    ).fetchall()
    return [_decode_param(r) for r in rows]


def get_param_by_key(conn: sqlite3.Connection, sub_item_id: int, param_key: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {PARAM_COLUMNS} FROM sub_item_param_def WHERE sub_item_id = ? AND param_key = ?",
        (sub_item_id, param_key),
    ).fetchone()
    return _decode_param(row) if row is not None else None


def dictionary_tree(conn: sqlite3.Connection, *, main_item_id: int | None = None) -> list[dict[str, Any]]:
    """一次性返回「主项目 → 子项目 → 参数」完整树。

    记录页需要一次性拿到结构来渲染表单，逐个请求会很慢（网络往返 × 子项目数）。
    """
    main_items = list_main_items(conn)
    if main_item_id is not None:
        main_items = [m for m in main_items if int(m["id"]) == main_item_id]

    sub_items = list_sub_items(conn, main_item_id=main_item_id)
    params_by_sub: dict[int, list[dict[str, Any]]] = {}
    for sub in sub_items:
        params_by_sub[int(sub["id"])] = list_params(conn, int(sub["id"]))

    tree: list[dict[str, Any]] = []
    for main in main_items:
        node = dict(main)
        node["sub_items"] = []
        for sub in sub_items:
            if int(sub["main_item_id"]) != int(main["id"]):
                continue
            sub_node = dict(sub)
            sub_node["params"] = params_by_sub.get(int(sub["id"]), [])
            node["sub_items"].append(sub_node)
        tree.append(node)
    return tree


__all__ = [
    "MAIN_ITEM_COLUMNS",
    "PARAM_COLUMNS",
    "SUB_ITEM_COLUMNS",
    "dictionary_tree",
    "get_main_item",
    "get_main_item_or_raise",
    "get_param_by_key",
    "get_sub_item",
    "get_sub_item_or_raise",
    "list_main_items",
    "list_params",
    "list_sub_items",
]
