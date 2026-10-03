"""JSON 字段的读写工具（`设计.md` 4.2）。

数据库里多处用 TEXT 存 JSON（`options_json`、`params_json`、`patient_response_json`…）。
统一从这里读写，避免各处自己 `json.loads` 时对空值/坏值处理不一致。

约定：**读坏数据不抛异常**，返回调用方给的默认值。理由是一行脏 JSON 不该让整个列表接口 500；
写入侧则由库层 `json_valid()` 约束保证不会产生脏数据。
"""

from __future__ import annotations

import json
from typing import Any


def loads(raw: str | None, default: Any = None) -> Any:
    """解析 JSON 文本；None / 空串 / 非法内容都返回 ``default``。"""
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def dumps(value: Any) -> str | None:
    """序列化成 JSON 文本；None 保持为 None（不写成 "null"）。"""
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


__all__ = ["dumps", "loads"]
