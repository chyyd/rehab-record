"""后台管理接口（阶段 5 / `设计.md` 6.2）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /audit-logs | 审计日志查询（按人/对象/时间） |
| GET | /audit-logs/facets | 出现过的动作与对象类型（供筛选下拉） |

**审计日志是只读的** —— 能改的审计日志就不是审计日志。因此这里只有 GET。

> 2026-10-05：`/admin/option-sets`（科室 / 全局选项集维护）整组删除 ——
> 记录改由 SOAP 模板驱动后，选项来自 `templates/*.json` 与 `disciplines.json`，
> `option_set` / `option_item` 两张表已随迁移 012 删除。
> 字典的读写接口（`dictionary.py` / `dictionary_admin.py`）同样已删除。
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import Depends, Query

from app.api.pagination import Page, page_params
from app.api.router import ApiRouter
from app.core.db_dep import get_db
from app.core.security_deps import AdminUser
from app.models import audit as audit_model
from app.schemas.admin import AuditFacetsOut, AuditLogListOut

router = ApiRouter(tags=["后台管理"])


# --------------------------------------------------------------------------- #
# 审计日志
# --------------------------------------------------------------------------- #
@router.get("/audit-logs", response_model=AuditLogListOut, summary="审计日志查询（管理员）")
def list_audit_logs(
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    page: Annotated[Page, Depends(page_params)],
    user_id: int | None = None,
    action: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    date_from: Annotated[str | None, Query(alias="from", description="ISO8601，如 2027-03-01")] = None,
    date_to: Annotated[str | None, Query(alias="to")] = None,
) -> dict[str, Any]:
    items, total = audit_model.list_audit_logs(
        conn,
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        date_from=date_from,
        date_to=date_to,
        limit=page.limit,
        offset=page.offset,
    )
    return {"items": items, "total": total, "page": page.page, "page_size": page.page_size}


@router.get("/audit-logs/facets", response_model=AuditFacetsOut, summary="审计日志筛选维度")
def audit_facets(
    admin: AdminUser, conn: Annotated[sqlite3.Connection, Depends(get_db)]
) -> dict[str, Any]:
    return {
        "actions": audit_model.distinct_actions(conn),
        "target_types": audit_model.distinct_target_types(conn),
    }


__all__ = ["router"]
