"""离线同步的请求/响应模型（阶段 4 / `设计.md` 5.4）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.services.sync import MAX_PULL_LIMIT, MAX_PUSH_BATCH, PULLABLE_ENTITIES, PUSHABLE_ENTITIES


class SyncChangeIn(BaseModel):
    """客户端的一条本地变更。"""

    entity: str = Field(description=f"可离线写：{' / '.join(PUSHABLE_ENTITIES)}")
    client_uuid: str = Field(
        min_length=8, max_length=64,
        description="客户端生成的 UUIDv4，用于幂等去重；同一条变更重试要带同一个值",
    )
    op: str = Field(default="update", description="insert / update / delete")
    base_revision: int | None = Field(
        default=None, description="客户端本地看到的版本号，用于冲突检测；新增时可不传"
    )
    payload: dict[str, Any] = Field(default_factory=dict, description="实体字段快照")


class SyncPushRequest(BaseModel):
    changes: list[SyncChangeIn] = Field(
        min_length=1, max_length=MAX_PUSH_BATCH, description=f"单次最多 {MAX_PUSH_BATCH} 条"
    )


class SyncPushResultItem(BaseModel):
    outcome: str = Field(description="applied / skipped / conflict")
    client_uuid: str
    entity: str
    entity_id: Any = None
    op: str | None = None
    revision: int | None = None
    server_revision: int | None = None
    server_status: str | None = None
    reason: str | None = None
    # 给人看的具体原因（如「第 1 次日常记录前必须先完成首评」）——
    # 客户端可直接展示，不必自己按 reason 拼文案。
    message: str | None = None
    # ★ 2026-10-05：业务门禁失败（如缺评估文书）改为**逐条 conflict** 上报，
    # 客户端要据此提示"先补首评/复评"，所以 `details` 必须透出来 ——
    # 少了这个字段，客户端只知道"被拒了"，不知道**要补哪份文书**。
    # （实测过：没有它时 `details.missing_document` 会被 pydantic 静默丢掉。）
    details: dict[str, Any] = Field(default_factory=dict)


class SyncPushResponse(BaseModel):
    applied: list[SyncPushResultItem] = Field(default_factory=list)
    skipped: list[SyncPushResultItem] = Field(default_factory=list)
    conflicts: list[SyncPushResultItem] = Field(
        default_factory=list, description="冲突条目：已提交/已锁定的记录以服务端为准，客户端需留痕重提"
    )
    cursor: int = Field(description="当前服务端游标，客户端可存下来供下次 pull 使用")


class SyncChangeOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = Field(description="即同步游标")
    entity: str
    entity_id: str
    op: str
    revision: int
    actor_user_id: int | None = None
    payload: dict[str, Any] | None = None
    created_at: str


class SyncPullResponse(BaseModel):
    cursor: int = Field(description="本次返回的最后一条 id；无新变更时与请求游标相同")
    latest_cursor: int = Field(
        default=0, description="服务端当前最大游标；按实体过滤做全量同步时用它作为终点"
    )
    changes: list[SyncChangeOut] = Field(default_factory=list)
    has_more: bool = Field(description="为 true 时还有未拉取的变更，客户端应继续拉")


class SyncInfoOut(BaseModel):
    """客户端启动时拉一次，据此了解服务端的同步契约。"""

    pushable_entities: list[str] = Field(default_factory=lambda: list(PUSHABLE_ENTITIES))
    pullable_entities: list[str] = Field(default_factory=lambda: list(PULLABLE_ENTITIES))
    max_push_batch: int = MAX_PUSH_BATCH
    max_pull_limit: int = MAX_PULL_LIMIT
    conflict_policy: dict[str, str] = Field(
        default_factory=lambda: {
            "treatment_record:draft": "client_wins",
            "treatment_record:submitted": "server_wins",
            "treatment_record:locked": "server_wins",
            "dictionary": "server_wins",
        },
        description="冲突策略说明，供客户端决定提示方式",
    )
    note: str = (
        "游标为 change_log.id；请勿用时间戳做游标（时钟偏移会漏数据）。"
        "entities 过滤只适合首次全量同步，之后请不带过滤地增量拉取并在客户端筛选。"
    )


__all__ = [
    "SyncChangeIn",
    "SyncChangeOut",
    "SyncInfoOut",
    "SyncPullResponse",
    "SyncPushRequest",
    "SyncPushResponse",
    "SyncPushResultItem",
]
