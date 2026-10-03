"""FastAPI 依赖注入（阶段 0 / D10）。

集中放置所有 `Depends(...)` 目标，便于测试用 `app.dependency_overrides` 替换。
**不要**在路由里直接 `get_settings()` —— 那样测试无法把配置指向临时库，
而且以后加缓存或请求级上下文时要改一堆路由。
"""

from __future__ import annotations

from fastapi import Depends

from app.core.config import Settings, get_settings


def get_app_settings() -> Settings:
    """当前应用的配置。

    注意：这里**不加** `lru_cache`。`get_settings()` 本身已有缓存，
    多包一层会让测试里的 `get_settings.cache_clear()` 失效，
    导致健康检查指向真实数据库而不是临时库。
    """
    return get_settings()


SettingsDep = Depends(get_app_settings)

__all__ = ["SettingsDep", "get_app_settings"]
