"""离线同步接口（阶段 4 / `开发计划.md` 4.8、`设计.md` 5.4）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /sync/info | 同步契约：可推/可拉实体、批量上限、冲突策略 |
| POST | /sync/push | 批量幂等推送（带 client_uuid 与 base_revision） |
| GET | /sync/pull | 按 change_log.id 游标增量拉取 |

一期只允许**治疗记录**离线写（`设计.md` 5.4 末尾"缩小同步面"）——
排期（appointment）已随排期功能整体下线（2026-10-05）从可推实体中移除，
字典类只做只读缓存。
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import Depends, Query

from app.api.router import ApiRouter
from app.core.db_dep import get_db
from app.core.security_deps import CurrentUser
from app.schemas.sync import (
    SyncInfoOut,
    SyncPullResponse,
    SyncPushRequest,
    SyncPushResponse,
)
from app.services import sync as sync_service

router = ApiRouter(prefix="/sync", tags=["离线同步"])


@router.get("/info", response_model=SyncInfoOut, summary="同步契约")
def sync_info(user: CurrentUser) -> dict[str, Any]:
    return SyncInfoOut().model_dump()


@router.post("/push", response_model=SyncPushResponse, summary="批量幂等推送")
def push(
    payload: SyncPushRequest,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    """把客户端本地攒下的变更推上来。

    幂等性由 `client_uuid` 保证：弱网下同一条变更重试多次不会产生重复数据。
    冲突按实体与状态分层处理（草稿客户端优先，已提交/已锁定服务端优先），
    冲突条目**逐条返回**而不是让整批失败——离线队列里通常攒了几十条，
    因为一条冲突就整批退回，客户端很难恢复。
    """
    return sync_service.apply_push(
        conn, user=user, changes=[c.model_dump() for c in payload.changes]
    )


@router.get("/pull", response_model=SyncPullResponse, summary="游标增量拉取")
def pull(
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    cursor: Annotated[int, Query(ge=0, description="上次拉取返回的游标；首次传 0")] = 0,
    limit: Annotated[
        int, Query(ge=1, le=sync_service.MAX_PULL_LIMIT, description="单次最多拉取条数")
    ] = sync_service.MAX_PULL_LIMIT,
    entities: Annotated[
        list[str] | None,
        Query(description="只拉取指定实体（如仅 treatment_record），不传则全部"),
    ] = None,
) -> dict[str, Any]:
    return sync_service.pull_changes(conn, cursor=cursor, limit=limit, entities=entities)


__all__ = ["router"]
