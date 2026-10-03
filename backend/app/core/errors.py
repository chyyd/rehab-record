"""统一错误响应体与异常处理器（`开发计划.md` D08）。

统一响应结构：

    {"code": "PATIENT_NOT_FOUND", "message": "患者不存在", "details": {"inpatient_no": "ZY001"}}

HTTP 状态码语义化：400 参数错误、401 未认证、403 越权、404 不存在、409 冲突、422 校验失败、500 内部错误。

**为什么要有这一层**：如果让 FastAPI 的默认处理器直接输出，客户端会同时面对三种错误格式
（`{"detail": "..."}`、`{"detail": [{...}]}`、纯文本 500），前端就得写三套解析。
这里把它们统一成一种，并且让 `code` 可被程序判断、`message` 可直接展示给治疗师。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

# HTTP 状态码 → 默认错误码（当抛出方没有给出更具体的 code 时使用）
DEFAULT_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "TOO_MANY_REQUESTS",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


class AppError(Exception):
    """业务异常基类。

    用法：
        raise AppError("PATIENT_NOT_FOUND", "患者不存在", details={"inpatient_no": no}, status_code=404)

    子类只需改默认参数，例如 ``NotFoundError``。
    """

    status_code: int = 400
    code: str = "BAD_REQUEST"

    def __init__(
        self,
        code: str | None = None,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.code = code or type(self).code
        self.message = message or self.code
        self.details = details or {}
        self.headers: dict[str, str] = headers or {}
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class BadRequestError(AppError):
    status_code = 400
    code = "BAD_REQUEST"


class UnauthorizedError(AppError):
    status_code = 401
    code = "UNAUTHORIZED"

    def __init__(self, code: str | None = None, message: str | None = None, **kwargs: Any) -> None:
        # 401 按 HTTP 规范应带 WWW-Authenticate，客户端据此决定如何重新认证
        headers = kwargs.pop("headers", None) or {"WWW-Authenticate": "Bearer"}
        super().__init__(code, message, **kwargs)
        self.headers = headers


class ForbiddenError(AppError):
    status_code = 403
    code = "FORBIDDEN"


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


def error_payload(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details or {}}


def _json(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error_payload(code, message, details), headers=headers)


def register_exception_handlers(app: FastAPI) -> None:
    """把所有错误出口统一成同一种响应体。"""

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content=exc.to_payload(), headers=exc.headers or None
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = DEFAULT_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
        headers = getattr(exc, "headers", None)  # 401 的 WWW-Authenticate 等
        # HTTPException 的 detail 可能是字符串，也可能已经是结构化对象
        if isinstance(exc.detail, dict):
            merged = {**exc.detail}
            code = str(merged.pop("code", code))
            message = str(merged.pop("message", code))
            return _json(exc.status_code, code, message, merged or None, headers)
        return _json(exc.status_code, code, str(exc.detail), headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # 把 pydantic 的错误列表压平成"字段 → 原因"，治疗师端可直接展示
        fields: dict[str, str] = {}
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", ()) if p not in {"body", "query", "path"})
            fields[loc or "_"] = err.get("msg", "非法取值")
        return _json(422, "VALIDATION_ERROR", "请求参数校验失败", {"fields": fields})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # 未预期异常：记录完整堆栈，但**不把内部细节返回给客户端**
        logger.exception("未处理的异常：%s %s", request.method, request.url.path)
        return _json(500, "INTERNAL_ERROR", "服务器内部错误，请稍后重试或联系管理员")


__all__ = [
    "DEFAULT_CODES",
    "AppError",
    "BadRequestError",
    "ConflictError",
    "ForbiddenError",
    "NotFoundError",
    "UnauthorizedError",
    "error_payload",
    "register_exception_handlers",
]
