"""记录模板（阶段 5 / `设计.md` 3.10）。

| 层级 | `scope` | 维护者 |
|---|---|---|
| 科室模板 | `dept` | 管理员（全科通用组合） |
| 个人模板 | `personal` | 治疗师（常用子项目组合 + 参数默认值） |

模板内容 = 一组子项目 + 每个子项目的预填参数（`params_json`，键用 `param_key`）。

**"一键套用"只是预填，不锁定内容** —— 套用后治疗师仍可自由修改（3.10 明确要求）。
因此模板读取接口返回的是"可直接填入表单的 params"，而不是保证最终一致的结构。

自洽约束：`scope='personal'` 必须归属具体人；`scope='dept'` 必须没有 owner。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.core import jsonutil
from app.models.base import Forbidden, Invalid, NotFound

SCOPES = ("dept", "personal")

TEMPLATE_COLUMNS = (
    "id, scope, owner_user_id, main_item_id, code, name, sort, status, created_at, updated_at"
)


def _decode_template(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def list_templates(
    conn: sqlite3.Connection,
    *,
    owner_user_id: int | None = None,
    main_item_id: int | None = None,
    include_disabled: bool = False,
) -> list[dict[str, Any]]:
    """列出对当前用户可见的模板：**科室模板 + 自己的个人模板**。

    刻意不返回别人的个人模板 —— 那是私人快捷方式，不是共享资产。
    """
    where = []
    params: list[Any] = []
    if not include_disabled:
        where.append("status = 'active'")
    if owner_user_id is None:
        where.append("scope = 'dept'")
    else:
        where.append("(scope = 'dept' OR (scope = 'personal' AND owner_user_id = ?))")
        params.append(owner_user_id)
    if main_item_id is not None:
        where.append("main_item_id = ?")
        params.append(main_item_id)

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    rows = conn.execute(
        f"SELECT {TEMPLATE_COLUMNS} FROM record_template {clause}"
        " ORDER BY scope DESC, sort, id",
        params,
    ).fetchall()
    return [_decode_template(row) for row in rows]


def get_template(conn: sqlite3.Connection, template_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {TEMPLATE_COLUMNS} FROM record_template WHERE id = ?", (template_id,)
    ).fetchone()
    if row is None:
        return None
    data = _decode_template(row)
    data["items"] = [
        {
            **dict(item),
            "params": jsonutil.loads(item["params_json"], {}) or {},
        }
        for item in conn.execute(
            "SELECT id, template_id, sub_item_id, params_json, sort FROM record_template_item"
            " WHERE template_id = ? ORDER BY sort, id",
            (template_id,),
        ).fetchall()
    ]
    for item in data["items"]:
        item.pop("params_json", None)
    return data


def get_template_or_raise(conn: sqlite3.Connection, template_id: int) -> dict[str, Any]:
    data = get_template(conn, template_id)
    if data is None:
        raise NotFound("模板不存在", details={"template_id": template_id})
    return data


def _assert_scope(scope: str, owner_user_id: int | None) -> None:
    if scope not in SCOPES:
        raise Invalid(f"模板 scope 非法：{scope}", details={"scope": scope})
    if scope == "personal" and owner_user_id is None:
        raise Invalid("个人模板必须归属到具体治疗师", details={"scope": scope})
    if scope == "dept" and owner_user_id is not None:
        raise Invalid("科室模板不能有归属人", details={"scope": scope})


def _prepare_items(
    conn: sqlite3.Connection, items: list[dict[str, Any]], *, main_item_id: int | None
) -> list[dict[str, Any]]:
    """校验模板明细：子项目必须存在，且（若模板指定了主项目）必须属于该主项目。"""
    prepared: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, item in enumerate(items):
        sub_item_id = int(item["sub_item_id"])
        if sub_item_id in seen:
            raise Invalid("同一子项目不能重复出现在模板里", details={"sub_item_id": sub_item_id})
        seen.add(sub_item_id)

        row = conn.execute(
            "SELECT id, main_item_id, name FROM sub_item WHERE id = ?", (sub_item_id,)
        ).fetchone()
        if row is None:
            raise NotFound("子项目不存在", details={"sub_item_id": sub_item_id})
        if main_item_id is not None and int(row["main_item_id"]) != int(main_item_id):
            raise Invalid(
                "子项目不属于模板指定的主项目",
                details={
                    "sub_item_id": sub_item_id,
                    "expected_main_item_id": int(row["main_item_id"]),
                    "main_item_id": main_item_id,
                },
            )
        prepared.append(
            {
                "sub_item_id": sub_item_id,
                "params": dict(item.get("params") or {}),
                # 显式给了 sort 才用它；显式给了 null 时按"未给"处理，
                # 否则 int(None) 会抛 TypeError → 500（实测踩到过）
                "sort": int(item["sort"]) if item.get("sort") is not None else index * 10,
            }
        )
    return prepared


def create_template(
    conn: sqlite3.Connection,
    *,
    scope: str,
    name: str,
    main_item_id: int,
    owner_user_id: int | None = None,
    items: list[dict[str, Any]] | None = None,
    sort: int = 0,
) -> dict[str, Any]:
    """新建模板。

    `main_item_id` 是**必填**：库层 `record_template.main_item_id` 为 NOT NULL，
    且它是唯一键 `(scope, owner, main_item_id, name)` 的一部分 ——
    同一治疗师在不同主项目下可以有同名模板（如"常规"），这在临床上是常见命名。
    模板里的子项目也必须属于该主项目。
    """
    _assert_scope(scope, owner_user_id)
    if not name:
        raise Invalid("模板名称不能为空")
    if main_item_id is None:
        raise Invalid("必须指定 main_item_id（模板按主项目组织）")
    exists = conn.execute("SELECT 1 FROM main_item WHERE id = ?", (main_item_id,)).fetchone()
    if exists is None:
        raise NotFound("主项目不存在", details={"main_item_id": main_item_id})

    prepared = _prepare_items(conn, items or [], main_item_id=main_item_id)
    cur = conn.execute(
        "INSERT INTO record_template (scope, owner_user_id, main_item_id, name, sort, status)"
        " VALUES (?, ?, ?, ?, ?, 'active')",
        (scope, owner_user_id, main_item_id, name, sort),
    )
    template_id = int(cur.lastrowid)
    _replace_items(conn, template_id, prepared)
    return get_template_or_raise(conn, template_id)


def update_template(
    conn: sqlite3.Connection,
    template_id: int,
    *,
    user_id: int,
    is_admin: bool,
    name: str | None = None,
    main_item_id: int | None = None,
    items: list[dict[str, Any]] | None = None,
    sort: int | None = None,
) -> dict[str, Any]:
    template = get_template_or_raise(conn, template_id)
    _assert_can_edit(template, user_id=user_id, is_admin=is_admin)

    sets: list[str] = []
    params: list[Any] = []
    if name is not None:
        if not name:
            raise Invalid("模板名称不能为空")
        sets.append("name = ?")
        params.append(name)
    if main_item_id is not None:
        sets.append("main_item_id = ?")
        params.append(main_item_id)
    if sort is not None:
        sets.append("sort = ?")
        params.append(sort)
    if sets:
        sets.append("updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')")
        conn.execute(
            f"UPDATE record_template SET {', '.join(sets)} WHERE id = ?", (*params, template_id)
        )
    if items is not None:
        effective_main = main_item_id if main_item_id is not None else template["main_item_id"]
        prepared = _prepare_items(conn, items, main_item_id=effective_main)
        _replace_items(conn, template_id, prepared)
    return get_template_or_raise(conn, template_id)


def _replace_items(conn: sqlite3.Connection, template_id: int, items: list[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM record_template_item WHERE template_id = ?", (template_id,))
    for item in items:
        conn.execute(
            "INSERT INTO record_template_item (template_id, sub_item_id, params_json, sort)"
            " VALUES (?, ?, ?, ?)",
            (template_id, item["sub_item_id"], jsonutil.dumps(item["params"]), item["sort"]),
        )


def _assert_can_edit(template: dict[str, Any], *, user_id: int, is_admin: bool) -> None:
    """科室模板只有管理员能改；个人模板只有本人能改（管理员也不代改别人的私人模板）。"""
    if template["scope"] == "dept":
        if not is_admin:
            raise Forbidden("科室模板只能由管理员维护", details={"template_id": template["id"]})
        return
    if template["owner_user_id"] is None or int(template["owner_user_id"]) != user_id:
        raise Forbidden(
            "个人模板只能由本人维护", details={"template_id": template["id"]}
        )


def delete_template(conn: sqlite3.Connection, template_id: int, *, user_id: int, is_admin: bool) -> None:
    template = get_template_or_raise(conn, template_id)
    _assert_can_edit(template, user_id=user_id, is_admin=is_admin)
    conn.execute("DELETE FROM record_template_item WHERE template_id = ?", (template_id,))
    conn.execute("DELETE FROM record_template WHERE id = ?", (template_id,))


def apply_template(conn: sqlite3.Connection, template_id: int) -> dict[str, Any]:
    """"一键套用"：返回可直接填进记录表单的明细。

    **只做预填**，不产生任何治疗记录，也不锁定内容（3.10）。
    """
    template = get_template_or_raise(conn, template_id)
    main_items: dict[int, str] = {}
    applied: list[dict[str, Any]] = []
    for item in template["items"]:
        sub = conn.execute(
            "SELECT main_item_id, name FROM sub_item WHERE id = ? AND status = 'active'",
            (int(item["sub_item_id"]),),
        ).fetchone()
        if sub is None:
            # 该子项目已被停用（字典调整是常态）：跳过而不是整份失败，模板其余部分仍可用。
            # 注意是"停用"而非"删除" —— 外键会阻止物理删除仍被引用的子项目。
            continue
        main_item_id = int(sub["main_item_id"])
        if main_item_id not in main_items:
            row = conn.execute("SELECT name FROM main_item WHERE id = ?", (main_item_id,)).fetchone()
            main_items[main_item_id] = row["name"] if row else ""
        applied.append(
            {
                "main_item_id": main_item_id,
                "sub_item_id": int(item["sub_item_id"]),
                "sub_item_name": sub["name"],
                "params": item["params"],
            }
        )
    return {
        "template_id": template["id"],
        "name": template["name"],
        "scope": template["scope"],
        "main_item_id": template["main_item_id"],
        "items": applied,
        "note": "套用仅为预填，仍可自由修改",
    }


__all__ = [
    "SCOPES",
    "TEMPLATE_COLUMNS",
    "apply_template",
    "create_template",
    "delete_template",
    "get_template",
    "get_template_or_raise",
    "list_templates",
    "update_template",
]
