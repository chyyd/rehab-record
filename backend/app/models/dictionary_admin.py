"""字典写入（阶段 5 后台的"字典管理"模块 / `开发计划.md` 4.5 第 580–582 行）。

`models/dictionary.py` 刻意是**只读**的 —— 业务接口渲染记录表单时不该有改字典的能力。
管理员维护字典走本模块，由路由层用 `AdminUser` 约束到管理员。

## 删除安全（这里的设计取舍）

字典是被**历史数据引用**的：
- `record_item` 里存了 `sub_item_id` / `main_item_id`，并且**已经固化了快照**
  （`sub_item_name_snapshot`、`params_snapshot_json`），所以即使字典被删，
  历史记录仍能正确显示。
- 但**新记录**会引用字典，若删掉已用过的项，`/records/form` 就少了一项，
  而且 `record_template_item` 有外键指向 `sub_item`。

因此删除策略：

| 对象 | 从未被使用 | 已被使用 |
|---|---|---|
| 子项目 | 允许**物理删除**（保持字典干净） | **改为停用**并在响应里说明原因 |
| 参数定义 | 允许物理删除（无法可靠判断 JSON 里的使用情况，但参数是可重加的） | 同上，物理删除 |
| 主项目 | 仅当其下没有处于活动状态的子项目时才允许；否则报 409 | — |

"已被使用"的判据是 `record_item` 里是否存在该 `sub_item_id`。
这是可靠的 —— `record_item.sub_item_id` 是结构化列，不是 JSON。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.core import jsonutil
from app.models.base import Conflict, Invalid, NotFound

INPUT_TYPES = ("select", "multi_select", "number", "text")


# --------------------------------------------------------------------------- #
# 校验辅助
# --------------------------------------------------------------------------- #
def _ensure_unique_code(
    conn: sqlite3.Connection, table: str, code: str, *, exclude_id: int | None = None
) -> None:
    sql = f"SELECT id FROM {table} WHERE code = ?"
    params: list[Any] = [code]
    if exclude_id is not None:
        sql += " AND id <> ?"
        params.append(exclude_id)
    if conn.execute(sql, params).fetchone() is not None:
        raise Conflict(f"code 已存在：{code}", details={"code": code})


def validate_param_payload(
    *,
    param_key: str,
    param_name: str,
    input_type: str,
    options: list[str] | None,
    default_value: Any,
) -> tuple[str | None, str | None]:
    """校验参数定义，返回 ``(options_json, default_value_encoded)``。

    规则与字典种子导入一致（`seed/dictionary.py._validate`）——
    **同一套约束必须在两处表现一致**，否则种子能过、后台过不了（或反之）会很难查。

    注意：`sub_item_param_def` **没有** `value_min`/`value_max` 列
    （数值取值范围是 `response_def` 才有的字段，见 `设计.md` 4.1）。
    因此这里不校验数值上下限 —— 不要凭想象加字段。
    """
    if not param_key or not param_key.strip():
        raise Invalid("param_key 不能为空")
    if not param_name or not param_name.strip():
        raise Invalid("param_name 不能为空")
    if input_type not in INPUT_TYPES:
        raise Invalid(f"input_type 只能是 {'/'.join(INPUT_TYPES)}", details={"input_type": input_type})

    option_list = [str(o) for o in (options or [])]
    if len(set(option_list)) != len(option_list):
        raise Invalid("选项不能重复", details={"options": option_list})

    if input_type in ("select", "multi_select"):
        if not option_list:
            raise Invalid("选择题必须至少有一个选项")
    elif option_list:
        raise Invalid("非选择题不应有选项", details={"input_type": input_type})

    encoded_default: str | None = None
    if default_value in (None, "", []):
        encoded_default = None
    elif isinstance(default_value, list):
        if input_type not in ("select", "multi_select"):
            raise Invalid("非选择题的默认值不应是数组")
        if input_type == "select" and len(default_value) > 1:
            raise Invalid("单选只能有一个默认值", details={"default_value": default_value})
        for item in default_value:
            if str(item) not in option_list:
                raise Invalid("默认值必须来自选项列表", details={"default": item})
        encoded_default = jsonutil.dumps([str(i) for i in default_value])
    else:
        if input_type in ("select", "multi_select"):
            # 允许前端把单选的默认值传成裸值，这里统一成数组存储（与种子格式一致）
            if str(default_value) not in option_list:
                raise Invalid("默认值必须来自选项列表", details={"default": default_value})
            encoded_default = jsonutil.dumps([str(default_value)])
        elif input_type == "number":
            try:
                number = float(default_value)
            except (TypeError, ValueError) as exc:
                raise Invalid("数值参数的默认值必须是数字", details={"default": default_value}) from exc
            encoded_default = str(int(number) if number.is_integer() else number)
        else:
            encoded_default = str(default_value)

    options_json = jsonutil.dumps(option_list) if option_list else None
    return options_json, encoded_default


# --------------------------------------------------------------------------- #
# 主项目
# --------------------------------------------------------------------------- #
def create_main_item(
    conn: sqlite3.Connection, *, name: str, code: str, alias: str | None = None, sort: int = 0
) -> dict[str, Any]:
    if not name.strip() or not code.strip():
        raise Invalid("主项目名称与 code 不能为空")
    _ensure_unique_code(conn, "main_item", code)
    cur = conn.execute(
        "INSERT INTO main_item (name, code, alias, sort, status) VALUES (?, ?, ?, ?, 'active')",
        (name, code, alias, sort),
    )
    return _main_item(conn, int(cur.lastrowid))


def _main_item(conn: sqlite3.Connection, main_item_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, name, code, alias, sort, status FROM main_item WHERE id = ?", (main_item_id,)
    ).fetchone()
    if row is None:
        raise NotFound("主项目不存在", details={"main_item_id": main_item_id})
    return dict(row)


def update_main_item(
    conn: sqlite3.Connection,
    main_item_id: int,
    *,
    name: str | None = None,
    code: str | None = None,
    alias: str | None = None,
    sort: int | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    _main_item(conn, main_item_id)
    sets: list[str] = []
    params: list[Any] = []
    if name is not None:
        if not name.strip():
            raise Invalid("主项目名称不能为空")
        sets.append("name = ?")
        params.append(name)
    if code is not None:
        if not code.strip():
            raise Invalid("code 不能为空")
        _ensure_unique_code(conn, "main_item", code, exclude_id=main_item_id)
        sets.append("code = ?")
        params.append(code)
    if alias is not None:
        sets.append("alias = ?")
        params.append(alias)
    if sort is not None:
        sets.append("sort = ?")
        params.append(sort)
    if status is not None:
        if status not in ("active", "disabled"):
            raise Invalid("status 只能是 active / disabled", details={"status": status})
        sets.append("status = ?")
        params.append(status)
    if sets:
        conn.execute(f"UPDATE main_item SET {', '.join(sets)} WHERE id = ?", (*params, main_item_id))
    return _main_item(conn, main_item_id)


def delete_main_item(conn: sqlite3.Connection, main_item_id: int) -> dict[str, Any]:
    """删除主项目。

    前置条件：其下**没有启用的子项目**（否则 409，避免把在用字典连带弄没）。

    满足条件后仍要小心：剩下的停用子项目可能还被 `record_template_item` 引用，
    直接删主项目会撞外键。因此这里先逐个走 `delete_sub_item`（它自己会判断能不能真删），
    只有当所有子项目都真的删掉了，才删主项目。

    实测踩到过：只把子项目停用就删主项目 → `FOREIGN KEY constraint failed` → 500。
    """
    main = _main_item(conn, main_item_id)
    active_subs = int(
        conn.execute(
            "SELECT COUNT(*) FROM sub_item WHERE main_item_id = ? AND status = 'active'",
            (main_item_id,),
        ).fetchone()[0]
    )
    if active_subs:
        raise Conflict(
            "该主项目下仍有启用的子项目，请先停用或删除它们",
            details={"main_item_id": main_item_id, "active_sub_items": active_subs},
        )

    sub_ids = [
        int(row["id"])
        for row in conn.execute(
            "SELECT id FROM sub_item WHERE main_item_id = ?", (main_item_id,)
        ).fetchall()
    ]
    kept: list[int] = []
    for sub_id in sub_ids:
        result = delete_sub_item(conn, sub_id)
        if not result.get("deleted"):
            kept.append(sub_id)

    if kept:
        # 还有子项目删不掉（被历史记录或模板引用）→ 主项目也不能删，否则留下孤儿子项目
        raise Conflict(
            "该主项目下的子项目已被治疗记录或模板引用，无法删除；请改为停用主项目",
            details={"main_item_id": main_item_id, "kept_sub_item_ids": kept},
        )

    conn.execute("DELETE FROM main_item WHERE id = ?", (main_item_id,))
    return {**main, "deleted": True, "soft_deleted": False}


# --------------------------------------------------------------------------- #
# 子项目
# --------------------------------------------------------------------------- #
def sub_item_in_use(conn: sqlite3.Connection, sub_item_id: int) -> bool:
    """是否被治疗记录引用过（`record_item.sub_item_id` 是结构化列，判据可靠）。"""
    row = conn.execute(
        "SELECT 1 FROM record_item WHERE sub_item_id = ? LIMIT 1", (sub_item_id,)
    ).fetchone()
    return row is not None


def create_sub_item(
    conn: sqlite3.Connection,
    *,
    main_item_id: int,
    name: str,
    code: str,
    alias: str | None = None,
    sort: int = 0,
) -> dict[str, Any]:
    _main_item(conn, main_item_id)
    if not name.strip() or not code.strip():
        raise Invalid("子项目名称与 code 不能为空")
    _ensure_unique_code(conn, "sub_item", code)
    cur = conn.execute(
        "INSERT INTO sub_item (main_item_id, name, code, alias, sort, status)"
        " VALUES (?, ?, ?, ?, ?, 'active')",
        (main_item_id, name, code, alias, sort),
    )
    return _sub_item(conn, int(cur.lastrowid))


def _sub_item(conn: sqlite3.Connection, sub_item_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, main_item_id, name, code, alias, sort, status FROM sub_item WHERE id = ?",
        (sub_item_id,),
    ).fetchone()
    if row is None:
        raise NotFound("子项目不存在", details={"sub_item_id": sub_item_id})
    return dict(row)


def update_sub_item(
    conn: sqlite3.Connection,
    sub_item_id: int,
    *,
    main_item_id: int | None = None,
    name: str | None = None,
    code: str | None = None,
    alias: str | None = None,
    sort: int | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    _sub_item(conn, sub_item_id)
    if main_item_id is not None:
        _main_item(conn, main_item_id)
    if code is not None:
        _ensure_unique_code(conn, "sub_item", code, exclude_id=sub_item_id)
    if status is not None and status not in ("active", "disabled"):
        raise Invalid("status 只能是 active / disabled", details={"status": status})

    sets: list[str] = []
    params: list[Any] = []
    for column, value in (
        ("main_item_id", main_item_id), ("name", name), ("code", code),
        ("alias", alias), ("sort", sort), ("status", status),
    ):
        if value is not None:
            sets.append(f"{column} = ?")
            params.append(value)
    if sets:
        conn.execute(f"UPDATE sub_item SET {', '.join(sets)} WHERE id = ?", (*params, sub_item_id))
    return _sub_item(conn, sub_item_id)


def delete_sub_item(conn: sqlite3.Connection, sub_item_id: int) -> dict[str, Any]:
    """删除子项目：**用过就只停用**。

    用过的子项目若物理删除，会撞上 `record_template_item` 的外键，
    更重要的是"新记录不该再选它、历史记录仍要能看"—— 这正是 `status='disabled'` 的用途。
    """
    sub = _sub_item(conn, sub_item_id)
    if sub_item_in_use(conn, sub_item_id):
        update_sub_item(conn, sub_item_id, status="disabled")
        return {
            **sub,
            "status": "disabled",
            "deleted": False,
            "soft_deleted": True,
            "reason": "该子项目已有治疗记录引用，已改为停用（历史记录不受影响）",
        }

    # 未被记录引用，但可能仍被模板引用（外键会拦），那就同样退化为停用
    referenced = conn.execute(
        "SELECT 1 FROM record_template_item WHERE sub_item_id = ? LIMIT 1", (sub_item_id,)
    ).fetchone()
    if referenced is not None:
        update_sub_item(conn, sub_item_id, status="disabled")
        return {
            **sub,
            "status": "disabled",
            "deleted": False,
            "soft_deleted": True,
            "reason": "该子项目仍被模板引用，已改为停用（请先在模板中移除）",
        }

    conn.execute("DELETE FROM sub_item_param_def WHERE sub_item_id = ?", (sub_item_id,))
    conn.execute("DELETE FROM sub_item WHERE id = ?", (sub_item_id,))
    return {**sub, "deleted": True, "soft_deleted": False}


# --------------------------------------------------------------------------- #
# 参数定义
# --------------------------------------------------------------------------- #
# 列名以库表为准；`sub_item_param_def` 没有 value_min/value_max/status
PARAM_COLUMNS = (
    "id, sub_item_id, param_key, param_name, input_type, options_json, default_value,"
    " required, unit, sort"
)


def _param(conn: sqlite3.Connection, param_id: int) -> dict[str, Any]:
    row = conn.execute(
        f"SELECT {PARAM_COLUMNS} FROM sub_item_param_def WHERE id = ?", (param_id,)
    ).fetchone()
    if row is None:
        raise NotFound("参数定义不存在", details={"param_id": param_id})
    data = dict(row)
    data["options"] = jsonutil.loads(data.pop("options_json", None), []) or []
    return data


def create_param(
    conn: sqlite3.Connection,
    *,
    sub_item_id: int,
    param_key: str,
    param_name: str,
    input_type: str,
    options: list[str] | None = None,
    default_value: Any = None,
    required: int = 0,
    unit: str | None = None,
    sort: int = 0,
) -> dict[str, Any]:
    _sub_item(conn, sub_item_id)
    options_json, encoded_default = validate_param_payload(
        param_key=param_key, param_name=param_name, input_type=input_type,
        options=options, default_value=default_value,
    )
    exists = conn.execute(
        "SELECT id FROM sub_item_param_def WHERE sub_item_id = ? AND param_key = ?",
        (sub_item_id, param_key),
    ).fetchone()
    if exists is not None:
        raise Conflict(
            "该子项目下 param_key 已存在", details={"param_key": param_key, "sub_item_id": sub_item_id}
        )
    cur = conn.execute(
        "INSERT INTO sub_item_param_def (sub_item_id, param_key, param_name, input_type,"
        " options_json, default_value, required, unit, sort)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (sub_item_id, param_key, param_name, input_type, options_json, encoded_default,
         int(required or 0), unit, sort),
    )
    return _param(conn, int(cur.lastrowid))


def update_param(
    conn: sqlite3.Connection,
    param_id: int,
    *,
    param_key: str | None = None,
    param_name: str | None = None,
    input_type: str | None = None,
    options: list[str] | None = None,
    default_value: Any = None,
    required: int | None = None,
    unit: str | None = None,
    sort: int | None = None,
) -> dict[str, Any]:
    current = _param(conn, param_id)
    effective_key = param_key if param_key is not None else str(current["param_key"])
    effective_name = param_name if param_name is not None else str(current["param_name"])
    effective_type = input_type if input_type is not None else str(current["input_type"])
    effective_options = options if options is not None else list(current["options"] or [])
    # 默认值比较特殊：None 是合法取值（表示"清空默认值"），无法用 None 表示"不修改"；
    # 路由层会传入完整对象（PUT 语义），因此这里把传入值直接当作目标值。
    options_json, encoded_default = validate_param_payload(
        param_key=effective_key, param_name=effective_name, input_type=effective_type,
        options=effective_options, default_value=default_value,
    )

    if param_key is not None and param_key != current["param_key"]:
        clash = conn.execute(
            "SELECT id FROM sub_item_param_def WHERE sub_item_id = ? AND param_key = ? AND id <> ?",
            (int(current["sub_item_id"]), param_key, param_id),
        ).fetchone()
        if clash is not None:
            raise Conflict("该子项目下 param_key 已存在", details={"param_key": param_key})

    conn.execute(
        "UPDATE sub_item_param_def SET param_key = ?, param_name = ?, input_type = ?,"
        " options_json = ?, default_value = ?, required = ?, unit = ?, sort = ? WHERE id = ?",
        (
            effective_key, effective_name, effective_type, options_json, encoded_default,
            int(required) if required is not None else int(current["required"]),
            unit if unit is not None else current["unit"],
            sort if sort is not None else int(current["sort"]),
            param_id,
        ),
    )
    return _param(conn, param_id)


def delete_param(conn: sqlite3.Connection, param_id: int) -> dict[str, Any]:
    """删除参数定义。

    参数没有被结构化引用（`record_item.params_json` 里只有 `param_key` 与快照），
    因此无法可靠判断"用没用过"；但参数是可重加的定义，物理删除风险低。
    """
    param = _param(conn, param_id)
    conn.execute("DELETE FROM sub_item_param_def WHERE id = ?", (param_id,))
    return {**param, "deleted": True}


__all__ = [
    "INPUT_TYPES",
    "PARAM_COLUMNS",
    "create_main_item",
    "create_param",
    "create_sub_item",
    "delete_main_item",
    "delete_param",
    "delete_sub_item",
    "sub_item_in_use",
    "update_main_item",
    "update_param",
    "update_sub_item",
    "validate_param_payload",
]
