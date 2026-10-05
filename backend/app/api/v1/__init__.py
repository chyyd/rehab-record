"""v1 版本路由。新增模块时在这里挂载。

**挂载顺序有讲究**：`/patients/claim` 这类"固定路径"必须能在 `/{id}` 这类参数路径
之前匹配。FastAPI 按注册顺序匹配，所以固定路径的路由模块要**先**注册
（`records.timeline_router` 也因此在 `records.router` 之前 ——
否则 `/records/timeline` 会被 `/records/{record_id}` 抢走）。

> 2026-10-05：排期（`schedule.py`）与请假/休息块（`leave.py`）整体下线，
> 本系统只做"记录做了什么"，不做排班。
"""

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    auth,
    dictionary,
    dictionary_admin,
    health,
    patients,
    records,
    summary,
    sync,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(admin.router)
api_router.include_router(patients.router)
# 字典**写**接口先于只读接口注册：管理端语义优先（见 dictionary_admin.py 的模块说明）
api_router.include_router(dictionary_admin.router)
api_router.include_router(dictionary.router)
api_router.include_router(summary.router)
api_router.include_router(sync.router)
# 时间轴先于 records.router，避免 /records/timeline 被 /records/{record_id} 吞掉
api_router.include_router(records.timeline_router)
api_router.include_router(records.router)

__all__ = ["api_router"]
