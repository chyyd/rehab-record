"""错误翻译：领域异常 → HTTP 响应（阶段 1）。

services 层不依赖 Web 框架，抛的是 `app.models.base.DomainError`。
这里集中把它翻成 D08 的统一响应体，**只有这一处**做映射，
避免每个路由自己写 try/except。
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.errors import error_payload
from app.models.base import Conflict, DomainError, Forbidden, Invalid, NotFound

# 领域错误码前缀/类型 → HTTP 状态码
_STATUS_BY_TYPE: tuple[tuple[type[DomainError], int], ...] = (
    (NotFound, 404),
    (Forbidden, 403),
    (Conflict, 409),
    (Invalid, 422),
)


def domain_error_status(exc: DomainError) -> int:
    for exc_type, status in _STATUS_BY_TYPE:
        if isinstance(exc, exc_type):
            return status
    return 400


def register_domain_error_handler(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
        # 错误码一律取自 `exc.code`，**不再从 details 里挖 `code`**：
        # details 里可能有业务实体的编码（如患者反应的 response_code），
        # 早先那种"details.code 优先"的写法会把业务编码误当成错误码返回给客户端。
        return JSONResponse(
            status_code=domain_error_status(exc),
            content=error_payload(exc.code, exc.message, exc.details),
        )


__all__ = ["domain_error_status", "register_domain_error_handler"]
