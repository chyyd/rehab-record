"""全局配置。

放在 core/ 下，任何模块都通过 get_settings() 读取，避免散落的魔法值。
所有取值都可用环境变量覆盖，优先级：环境变量 > 默认值。

注意：本模块**只用标准库**。第三方依赖（pydantic-settings 等）在依赖恢复后再评估是否替换，
当前阶段先把配置契约稳定下来。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

# 仓库根目录：backend/app/core/config.py -> 上溯 3 层
REPO_ROOT = Path(__file__).resolve().parents[3]


def _env_str(key: str, default: str) -> str:
    value = os.environ.get(key)
    return default if value is None or value.strip() == "" else value.strip()


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:  # 配置错误要早暴露，不要静默回退
        raise ValueError(f"环境变量 {key} 必须是整数，当前值：{raw!r}") from exc


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class WorkTimeConfig:
    """科室作息（依据《开发计划.md》Q11 定稿）。

    上午 06:00–11:30、下午 13:00–17:30。

    这两个区间是**半日**的边界，被以下模块共同依赖，改这里等于改全局：
    - 记录的 `session_period`（上午做的还是下午做的）；
    - 临时指派的 `expires_at`（取所属半日区间的结束时刻）。

    > 2026-10-05：排期、休息块、请假功能整体下线后，本配置不再服务于排班判定，
    > 但仍决定"一条记录属于哪个半日" —— 这是记录本身的属性，不会因为不排班而消失。
    """

    morning_start: str = "06:00"
    morning_end: str = "11:30"
    afternoon_start: str = "13:00"
    afternoon_end: str = "17:30"

    @property
    def periods(self) -> tuple[str, str]:
        return ("am", "pm")


@dataclass(frozen=True)
class Settings:
    app_name: str = "康复科治疗过程记录系统"
    app_version: str = "0.1.0"
    timezone: str = "Asia/Shanghai"  # 依据 D07
    api_prefix: str = "/api/v1"

    # SQLite 单文件；生产为 Docker 数据卷
    db_path: Path = field(default_factory=lambda: Path(_env_str("KB_DB_PATH", str(REPO_ROOT / "data" / "kf.db"))))
    migrations_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1] / "db" / "migrations")

    # D05：SQLite 并发参数
    sqlite_busy_timeout_ms: int = field(default_factory=lambda: _env_int("KB_SQLITE_BUSY_TIMEOUT_MS", 5000))
    sqlite_wal: bool = field(default_factory=lambda: _env_bool("KB_SQLITE_WAL", True))

    # 认证（D01 / 设计.md 5.5）
    # 注意：默认 secret 只用于开发。生产必须通过 KB_JWT_SECRET 提供，
    # 否则重启或多实例部署会互相踢掉令牌（见 docs/setup.md 与部署检查表）。
    jwt_secret: str = field(default_factory=lambda: _env_str("KB_JWT_SECRET", "dev-only-insecure-secret-change-me"))
    jwt_algorithm: str = field(default_factory=lambda: _env_str("KB_JWT_ALGORITHM", "HS256"))
    # 床旁离线场景：短过期 access token 会把治疗师挡在登录页，故一期取较长有效期
    access_token_ttl_seconds: int = field(
        default_factory=lambda: _env_int("KB_ACCESS_TOKEN_TTL_SECONDS", 30 * 24 * 3600)
    )
    refresh_token_ttl_seconds: int = field(
        default_factory=lambda: _env_int("KB_REFRESH_TOKEN_TTL_SECONDS", 90 * 24 * 3600)
    )

    # 管理后台 Web 的 refresh token 走 httpOnly Cookie（见 `app/api/v1/auth.py`）。
    # Cookie 名与属性都可配：SameSite 默认 `lax`，前后端同源部署（Nginx 托管前端 + 反代 /api）即可；
    # 若前端单独域名部署，应设为 `none` 并**必须**同时开启 cookie_secure。
    refresh_cookie_name: str = field(
        default_factory=lambda: _env_str("KB_REFRESH_COOKIE_NAME", "kb_refresh")
    )
    refresh_cookie_path: str = field(
        default_factory=lambda: _env_str("KB_REFRESH_COOKIE_PATH", "/api/v1/auth")
    )
    refresh_cookie_samesite: str = field(
        default_factory=lambda: _env_str("KB_REFRESH_COOKIE_SAMESITE", "lax")
    )
    refresh_cookie_secure: bool = field(
        default_factory=lambda: _env_bool("KB_REFRESH_COOKIE_SECURE", False)
    )
    # 允许携带凭证的前端来源（逗号分隔）。同源部署可留空。
    cors_origins: str = field(default_factory=lambda: _env_str("KB_CORS_ORIGINS", ""))

    worktime: WorkTimeConfig = field(default_factory=WorkTimeConfig)

    @property
    def is_dev_secret(self) -> bool:
        """是否仍在使用开发用默认密钥（部署检查表会据此告警）。"""
        return self.jwt_secret == "dev-only-insecure-secret-change-me"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内单例。测试可用 get_settings.cache_clear() 重置。"""
    return Settings()


__all__ = ["Settings", "WorkTimeConfig", "get_settings", "REPO_ROOT"]
