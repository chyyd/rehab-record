"""患者反应定义读取（阶段 3 / `设计.md` 3.6.5、M04）。

患者反应在 8.2 里定义得很细（NRS 疼痛、Borg 疲劳、呛咳次数、SpO2、残留程度…），
这里把 `response_def` 读出来，记录页据此渲染可选项与取值约束；
`patient_response_json` 的结构见 `设计.md` 4.2.2（`tags` + `items`）。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.core import jsonutil
from app.models.base import NotFound

COLUMNS = (
    "id, main_item_id, code, label, value_type, value_key, value_unit,"
    " value_min, value_max, options_json, sort, status"
)

# value_type 的语义（供前端渲染与校验共用）
VALUE_TYPES = ("tag", "number", "select", "text")


def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    data["options"] = jsonutil.loads(data.pop("options_json", None), []) or []
    return data


def list_response_defs(
    conn: sqlite3.Connection, *, main_item_id: int | None = None, include_disabled: bool = False
) -> list[dict[str, Any]]:
    """列出反应定义。

    ``main_item_id`` 传入时会同时返回**该主项目专属**与**全科通用**（`main_item_id IS NULL`）两类，
    因为通用反应（如"无不适""疼痛"）在任何主项目下都应可选。
    """
    where: list[str] = []
    params: list[Any] = []
    if not include_disabled:
        where.append("status = 'active'")
    if main_item_id is not None:
        where.append("(main_item_id = ? OR main_item_id IS NULL)")
        params.append(main_item_id)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    rows = conn.execute(
        f"SELECT {COLUMNS} FROM response_def {clause} ORDER BY IFNULL(main_item_id, -1), sort, id",
        params,
    ).fetchall()
    return [d for d in (_decode(r) for r in rows) if d is not None]


def get_response_def(conn: sqlite3.Connection, response_def_id: int) -> dict[str, Any] | None:
    return _decode(
        conn.execute(f"SELECT {COLUMNS} FROM response_def WHERE id = ?", (response_def_id,)).fetchone()
    )


def get_by_code(
    conn: sqlite3.Connection, code: str, *, main_item_id: int | None = None
) -> dict[str, Any] | None:
    """按 code 查定义：优先精确匹配主项目专属，其次回落到全科通用。"""
    if main_item_id is not None:
        row = conn.execute(
            f"SELECT {COLUMNS} FROM response_def WHERE code = ? AND main_item_id = ?", (code, main_item_id)
        ).fetchone()
        if row is not None:
            return _decode(row)
    return _decode(
        conn.execute(
            f"SELECT {COLUMNS} FROM response_def WHERE code = ? AND main_item_id IS NULL", (code,)
        ).fetchone()
    )


def get_by_code_or_raise(conn: sqlite3.Connection, code: str, *, main_item_id: int | None = None) -> dict[str, Any]:
    row = get_by_code(conn, code, main_item_id=main_item_id)
    if row is None:
        raise NotFound("患者反应定义不存在", details={"response_code": code, "main_item_id": main_item_id})
    return row


def response_defs_by_main_item(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """按主项目分组，供前端一次性拉取（含 `common` 通用组）。"""
    grouped: dict[str, list[dict[str, Any]]] = {}
    rows = conn.execute(
        f"SELECT {COLUMNS}, (SELECT code FROM main_item m WHERE m.id = response_def.main_item_id) AS main_code"
        " FROM response_def WHERE status = 'active' ORDER BY sort, id"
    ).fetchall()

    common: list[dict[str, Any]] = []
    per_main: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        data = _decode(row)
        if data is None:
            continue
        main_code = data.pop("main_code", None)
        if main_code is None:
            common.append(data)
        else:
            per_main.setdefault(str(main_code), []).append(data)

    grouped: dict[str, list[dict[str, Any]]] = {"common": common}
    for main_code, specific in per_main.items():
        # 通用在前、专属在后；两边都带上，前端不必自己拼回退逻辑
        grouped[main_code] = [*common, *specific]
    return grouped


__all__ = [
    "COLUMNS",
    "VALUE_TYPES",
    "get_by_code",
    "get_by_code_or_raise",
    "get_response_def",
    "list_response_defs",
    "response_defs_by_main_item",
]
