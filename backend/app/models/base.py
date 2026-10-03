"""models 层公共工具：行 → 字典、领域异常。

这一层刻意不引入 ORM：表结构的唯一真源是 `db/migrations/*.sql`，
这里只做「SQL 行 ↔ Python 字典」的转换与通用异常定义，
避免 ORM 模型与 SQL 迁移两处描述同一张表而漂移。
"""

from __future__ import annotations

import sqlite3
from typing import Any


class DomainError(Exception):
    """领域层通用错误。

    继承自 `Exception` 而不是 FastAPI 的异常，是为了让 services 层不依赖 Web 框架
    （可测试性与复用性都依赖这一点）。路由层负责把它翻译成响应。

    构造形式：``DomainError(message, code=..., details=...)``

    - 平时只给 message，用子类的默认 `code`（如 `NOT_FOUND`）；
    - 需要更精确的机器可判错误码时显式给 ``code=``（如 ``code="RECORD_LOCKED"``）。

    **注意 `details` 里不要放 `code` 键**：那会与"错误码"混淆。
    业务实体的编码请用具体名字（如 `response_code`、`param_key`、`inpatient_no`）。
    """

    status_code: int = 400
    code: str = "BAD_REQUEST"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code or type(self).code
        self.message = message or self.code
        self.details = details or {}
        super().__init__(self.message)


class NotFound(DomainError):
    """404。默认消息是「资源不存在」，调用方通常给更具体的消息。"""

    code = "NOT_FOUND"
    status_code = 404


class Conflict(DomainError):
    """409。用于可预期的业务冲突（半日被占、重复认领等）。"""

    code = "CONFLICT"
    status_code = 409


class Forbidden(DomainError):
    """403。已认证但无权操作。"""

    code = "FORBIDDEN"
    status_code = 403


class Invalid(DomainError):
    """422。参数非法。"""

    code = "INVALID"
    status_code = 422


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    """安全的行转换：None 透传，避免调用方到处判空。"""
    return dict(row) if row is not None else None


def entity_to_dict(row: sqlite3.Row | None, *, drop: tuple[str, ...] = ()) -> dict[str, Any] | None:
    """转换为对外字典，并剔除不该外传的字段（如 `password_hash`）。"""
    data = row_to_dict(row)
    if data is None:
        return None
    for key in drop:
        data.pop(key, None)
    return data


__all__ = [
    "Conflict",
    "DomainError",
    "Forbidden",
    "Invalid",
    "NotFound",
    "entity_to_dict",
    "row_to_dict",
]
