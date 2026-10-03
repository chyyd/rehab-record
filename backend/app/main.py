"""FastAPI 应用入口（阶段 0 / T0.2）。

从 M0 的标准库 ASGI 实现迁移过来（迁移原因见 CHANGELOG：最初误判依赖不可用）。
`app/core/health.py` 与 `app/core/worktime.py` **原样保留**，它们与框架无关；
`/api/v1/health` 的响应体结构也保持不变，前端与部署脚本不需要跟着改。

运行：
    python -m app.main                      # 127.0.0.1:8000，带热重载关闭
    python -m app.main --port 9000 --reload
    uvicorn app.main:app --reload
"""

from __future__ import annotations

import argparse
import logging

from fastapi import FastAPI

from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.domain_errors import register_domain_error_handler
from app.core.errors import register_exception_handlers

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """应用工厂：便于测试里构造独立实例，也便于以后按环境调整配置。"""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "康复科治疗过程记录系统后端。\n\n"
            "- 范围：治疗过程记录 + 轻量排期（不含收费、医保、患者签字）\n"
            "- 排期单位为**上午/下午半日**，作息 06:00–11:30 / 13:00–17:30\n"
            "- 统一错误响应体：`{\"code\": ..., \"message\": ..., \"details\": {...}}`"
        ),
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )

    # 统一错误响应体（D08）：必须在挂路由之前注册，保证校验错误也走同一格式
    register_exception_handlers(app)
    # 领域异常 → HTTP（services 层不依赖 Web 框架，靠这里翻译）
    register_domain_error_handler(app)

    # CORS：管理后台的 refresh token 走 httpOnly Cookie，
    # 因此必须 `allow_credentials=True`，**且此时 `allow_origins` 不能用 `*`**
    # （浏览器会拒绝 `Access-Control-Allow-Origin: *` 与凭证同时出现）。
    # 同源部署（Nginx 托管前端 + 反代 /api）不需要 CORS，留空即可。
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        logger.info("已启用 CORS，允许携带凭证的来源：%s", origins)

    # 版本化路由
    app.include_router(api_router, prefix=settings.api_prefix)

    # 不带前缀的 /health，供容器编排与负载均衡探活
    from app.api.v1.health import router as health_router

    app.include_router(health_router)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, object]:
        return {
            "service": settings.app_name,
            "version": settings.app_version,
            "api_prefix": settings.api_prefix,
            "docs": "/docs",
            "health": f"{settings.api_prefix}/health",
        }

    logger.info("应用已构建：%s v%s，API 前缀 %s", settings.app_name, settings.app_version, settings.api_prefix)
    return app


app = create_app()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="康复科治疗过程记录系统 — 服务端")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    args = parser.parse_args(argv)

    import uvicorn

    uvicorn.run(
        "app.main:app" if args.reload else app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
