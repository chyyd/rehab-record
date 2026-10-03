"""健康检查路由（阶段 0 验收项 T0.3）。

响应体结构与 M0 阶段完全一致（`app/core/health.collect_health()` 的输出），
这样前端与部署脚本不需要跟着改。

两处入口都指向同一个实现：
- ``/api/v1/health`` —— 版本化，客户端与探针使用
- ``/health``          —— 不带前缀，供负载均衡/容器编排使用
"""

from __future__ import annotations

from typing import Any

from fastapi import Response

from app.api.router import ApiRouter
from app.core.config import Settings
from app.core.deps import SettingsDep
from app.core.health import collect_health

router = ApiRouter(tags=["health"])


def _health_payload(settings: Settings, response: Response) -> dict[str, Any]:
    """共用实现：状态为 down 时用 503，让编排系统能正确判死。"""
    payload = collect_health(settings)
    if payload["status"] not in {"ok", "degraded"}:
        response.status_code = 503
    return payload


@router.get("/health", summary="健康检查")
def health(response: Response, settings: Settings = SettingsDep) -> dict[str, Any]:
    return _health_payload(settings, response)


__all__ = ["router"]
