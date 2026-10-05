"""健康检查（阶段 0 / T0.3 的验收项）。

把"能不能开工"变成可查询的事实：SQLite 版本、JSON1、外键、WAL、迁移状态。
依赖恢复后 ``/api/v1/health`` 直接复用 collect_health()，不重写一套。

返回的 status 语义：
- ``ok``       全部检查通过
- ``degraded`` 能跑，但有需要关注的问题（如存在未应用迁移、不是 WAL）
- ``down``     JSON1 或外键不可用 —— 在这两种情况下拒绝提供服务，因为都会静默产生坏数据
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.config import Settings, get_settings
from app.core.worktime import day_period_bounds
from app.db import storage


def collect_health(settings: Settings | None = None, *, include_periods: bool = True) -> dict[str, Any]:
    cfg = settings or get_settings()

    payload: dict[str, Any] = {
        "service": cfg.app_name,
        "version": cfg.app_version,
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "timezone": cfg.timezone,
        "database": storage.inspect(cfg),
    }

    if include_periods:
        # 把 Q11 的作息暴露出来（`worktime` 明细 + `periods` 边界），供运维与客户端自描述；
        # 排期页已随排期功能下线删除，这里不再服务于任何排班渲染，但"半日边界"仍是
        # 治疗记录 `session_period` 与临时指派到期时点的定义，必须能查到。
        payload["worktime"] = {
            "morning": {"period": "am", "start": cfg.worktime.morning_start, "end": cfg.worktime.morning_end},
            "afternoon": {"period": "pm", "start": cfg.worktime.afternoon_start, "end": cfg.worktime.afternoon_end},
            "source": "Q11 定稿（上午 06:00–11:30 / 下午 13:00–17:30）",
        }
        payload["periods"] = day_period_bounds(cfg.worktime)

    payload["status"] = payload["database"].get("status", "down")
    return payload


__all__ = ["collect_health"]
