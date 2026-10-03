"""选项集解析（阶段 3 / `设计.md` 3.6.4、M03）。

三层来源 + 一层内置，**解析顺序固定为**：

    个人（personal） → 科室（dept） → 全局（global） → 参数自带的 options_json（内置默认）

`sub_item_param_def.options_json` 是"开箱可用"的内置选项；`option_set` 用于覆盖与扩展，
两者通过 `code`（= `param_key`）关联。

**已知限制**：同一个 `code` 在库层只允许一套 `global` 选项
（唯一索引 `(scope, owner_user_id, dept_tag, code)`），而设计文档里同一参数在不同子项目下
可能有多套选项（如「辅助程度」6 项与 4 项）。导入种子时只保留了主变体，
差异仍完整保留在各子项目的 `options_json` 中 —— 因此**当三层覆盖都不存在时，
必须回落到该子项目自己的内置选项**，而不是用一个全局的"最大集合"。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.models.base import Invalid

SCOPES = ("personal", "dept", "global")


def option_set_by_scope(
    conn: sqlite3.Connection,
    code: str,
    *,
    scope: str,
    owner_user_id: int | None = None,
    dept_tag: str | None = None,
) -> dict[str, Any] | None:
    if scope == "personal":
        if owner_user_id is None:
            return None
        row = conn.execute(
            "SELECT id, scope, owner_user_id, dept_tag, code, name, status FROM option_set"
            " WHERE scope = 'personal' AND owner_user_id = ? AND code = ?",
            (owner_user_id, code),
        ).fetchone()
    elif scope == "dept":
        if not dept_tag:
            return None
        row = conn.execute(
            "SELECT id, scope, owner_user_id, dept_tag, code, name, status FROM option_set"
            " WHERE scope = 'dept' AND dept_tag = ? AND code = ?",
            (dept_tag, code),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id, scope, owner_user_id, dept_tag, code, name, status FROM option_set"
            " WHERE scope = 'global' AND code = ?",
            (code,),
        ).fetchone()
    if row is None or row["status"] != "active":
        return None
    return dict(row)


def items_of(conn: sqlite3.Connection, option_set_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, value, label, is_default, sort FROM option_item"
        " WHERE option_set_id = ? AND status = 'active' ORDER BY sort, id",
        (option_set_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def resolve_options(
    conn: sqlite3.Connection,
    *,
    code: str,
    builtin: list[str] | None = None,
    owner_user_id: int | None = None,
    dept_tag: str | None = None,
) -> dict[str, Any]:
    """按 个人 → 科室 → 全局 → 内置 的顺序解析出有效选项。

    返回 ``{"code", "source", "options": [...], "defaults": [...]}``；
    ``source`` 表明最终用了哪一层，便于前端提示"这是你的个人选项"。
    """
    for scope in ("personal", "dept", "global"):
        found = option_set_by_scope(
            conn, code, scope=scope, owner_user_id=owner_user_id, dept_tag=dept_tag
        )
        if found is None:
            continue
        items = items_of(conn, int(found["id"]))
        if not items:
            continue
        return {
            "code": code,
            "source": scope,
            "option_set_id": int(found["id"]),
            "option_set_name": found["name"],
            "options": [{"value": i["value"], "label": i["label"]} for i in items],
            "defaults": [i["value"] for i in items if i["is_default"]],
        }

    builtin_options = list(builtin or [])
    return {
        "code": code,
        "source": "builtin",
        "option_set_id": None,
        "option_set_name": None,
        "options": [{"value": v, "label": v} for v in builtin_options],
        "defaults": [],
    }


def list_option_sets(
    conn: sqlite3.Connection, *, owner_user_id: int | None = None, dept_tag: str | None = None
) -> list[dict[str, Any]]:
    """列出对当前用户有效的选项集（个人 + 科室 + 全局）。"""
    where = ["status = 'active'", "(scope = 'global'"]
    params: list[Any] = []
    if owner_user_id is not None:
        where.append("OR (scope = 'personal' AND owner_user_id = ?)")
        params.append(owner_user_id)
    if dept_tag:
        where.append("OR (scope = 'dept' AND dept_tag = ?)")
        params.append(dept_tag)
    where.append(")")
    rows = conn.execute(
        "SELECT id, scope, owner_user_id, dept_tag, code, name, alias, sort FROM option_set"
        f" WHERE {' '.join(where)} ORDER BY scope, sort, id",
        params,
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        data["items"] = items_of(conn, int(row["id"]))
        out.append(data)
    return out


# --------------------------------------------------------------------------- #
# 写入（个人快捷选项：治疗师维护自己的常用选项组合）
# --------------------------------------------------------------------------- #
def upsert_personal_option_set(
    conn: sqlite3.Connection,
    *,
    owner_user_id: int,
    code: str,
    name: str,
    values: list[str],
    default_values: list[str] | None = None,
) -> dict[str, Any]:
    """新建或覆盖某个治疗师的个人选项集。

    这是"个人快捷"层的唯一写入口（`设计.md` 3.6.4）。科室/全局层由管理员与种子负责。
    """
    if not code:
        raise Invalid("code 不能为空")
    if not values:
        raise Invalid("选项不能为空", details={"option_code": code})
    if len(set(values)) != len(values):
        raise Invalid("选项值不能重复", details={"option_code": code})
    defaults = list(default_values or [])
    for d in defaults:
        if d not in values:
            raise Invalid("默认值必须来自选项列表", details={"option_code": code, "default": d})

    row = conn.execute(
        "SELECT id FROM option_set WHERE scope = 'personal' AND owner_user_id = ? AND code = ?",
        (owner_user_id, code),
    ).fetchone()
    if row is None:
        cur = conn.execute(
            "INSERT INTO option_set (scope, owner_user_id, code, name, status) VALUES ('personal', ?, ?, ?, 'active')",
            (owner_user_id, code, name),
        )
        set_id = int(cur.lastrowid)
    else:
        set_id = int(row["id"])
        conn.execute("UPDATE option_set SET name = ?, status = 'active' WHERE id = ?", (name, set_id))
        # 覆盖式更新：先清空旧项，避免残留已删除的选项
        conn.execute("DELETE FROM option_item WHERE option_set_id = ?", (set_id,))

    for index, value in enumerate(values):
        conn.execute(
            "INSERT INTO option_item (option_set_id, value, label, is_default, sort)"
            " VALUES (?, ?, ?, ?, ?)",
            (set_id, value, value, 1 if value in defaults else 0, index * 10),
        )
    return {
        "id": set_id,
        "scope": "personal",
        "code": code,
        "name": name,
        "items": items_of(conn, set_id),
    }


def delete_personal_option_set(conn: sqlite3.Connection, *, owner_user_id: int, code: str) -> None:
    from app.models.base import NotFound

    row = conn.execute(
        "SELECT id FROM option_set WHERE scope = 'personal' AND owner_user_id = ? AND code = ?",
        (owner_user_id, code),
    ).fetchone()
    if row is None:
        raise NotFound("个人选项集不存在", details={"option_code": code})
    conn.execute("DELETE FROM option_item WHERE option_set_id = ?", (int(row["id"]),))
    conn.execute("DELETE FROM option_set WHERE id = ?", (int(row["id"]),))


# --------------------------------------------------------------------------- #
# 管理员维护科室 / 全局选项集（阶段 5 后台的"字典管理"模块）
# --------------------------------------------------------------------------- #
def upsert_dept_option_set(
    conn: sqlite3.Connection,
    *,
    code: str,
    name: str,
    values: list[str],
    dept_tag: str | None = None,
    default_values: list[str] | None = None,
) -> dict[str, Any]:
    """新建或覆盖**科室级 / 全局**选项集（`设计.md` 3.6.4、6.2 字典管理）。

    与个人快捷选项的区别：这一层影响全科（或某个科室标签下）的治疗师，
    因此只允许管理员调用（路由层用 `AdminUser` 约束）。
    """
    if not code:
        raise Invalid("code 不能为空")
    if not values:
        raise Invalid("选项不能为空", details={"option_code": code})
    if len(set(values)) != len(values):
        raise Invalid("选项值不能重复", details={"option_code": code})
    defaults = list(default_values or [])
    for value in defaults:
        if value not in values:
            raise Invalid("默认值必须来自选项列表", details={"option_code": code, "default": value})

    scope = "global" if not dept_tag else "dept"
    if scope == "dept":
        row = conn.execute(
            "SELECT id FROM option_set WHERE scope = 'dept' AND dept_tag = ? AND code = ?",
            (dept_tag, code),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM option_set WHERE scope = 'global' AND code = ?", (code,)
        ).fetchone()

    if row is None:
        cur = conn.execute(
            "INSERT INTO option_set (scope, dept_tag, code, name, status)"
            " VALUES (?, ?, ?, ?, 'active')",
            (scope, dept_tag, code, name),
        )
        set_id = int(cur.lastrowid)
    else:
        set_id = int(row["id"])
        conn.execute(
            "UPDATE option_set SET name = ?, status = 'active' WHERE id = ?", (name, set_id)
        )
        conn.execute("DELETE FROM option_item WHERE option_set_id = ?", (set_id,))

    for index, value in enumerate(values):
        conn.execute(
            "INSERT INTO option_item (option_set_id, value, label, is_default, sort)"
            " VALUES (?, ?, ?, ?, ?)",
            (set_id, value, value, 1 if value in defaults else 0, index * 10),
        )
    return {
        "id": set_id,
        "scope": scope,
        "dept_tag": dept_tag,
        "code": code,
        "name": name,
        "items": items_of(conn, set_id),
    }


def delete_option_set(conn: sqlite3.Connection, option_set_id: int) -> None:
    """删除科室 / 全局选项集。**个人选项集不允许从这里删**（那是治疗师的私人数据）。"""
    from app.models.base import NotFound

    row = conn.execute("SELECT scope FROM option_set WHERE id = ?", (option_set_id,)).fetchone()
    if row is None:
        raise NotFound("选项集不存在", details={"option_set_id": option_set_id})
    if row["scope"] == "personal":
        raise Invalid(
            "个人选项集不能由管理员删除，请由本人通过个人快捷选项接口维护",
            details={"option_set_id": option_set_id},
        )
    conn.execute("DELETE FROM option_item WHERE option_set_id = ?", (option_set_id,))
    conn.execute("DELETE FROM option_set WHERE id = ?", (option_set_id,))


__all__ = [
    "SCOPES",
    "delete_option_set",
    "delete_personal_option_set",
    "items_of",
    "list_option_sets",
    "option_set_by_scope",
    "resolve_options",
    "upsert_dept_option_set",
    "upsert_personal_option_set",
]
