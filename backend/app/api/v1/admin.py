"""后台管理接口（阶段 5 / `设计.md` 6.2）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /audit-logs | 审计日志查询（按人/对象/时间） |
| GET | /audit-logs/facets | 出现过的动作与对象类型（供筛选下拉） |
| GET | /admin/option-sets | 全部选项集（含个人），供管理员总览 |
| PUT | /admin/option-sets | 维护科室 / 全局选项集 |
| DELETE | /admin/option-sets/{id} | 删除科室 / 全局选项集 |

**审计日志是只读的** —— 能改的审计日志就不是审计日志。因此这里只有 GET。

字典的**读**接口在 `dictionary.py`（治疗师也要用）；这里只放管理员专属的写操作。
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import Depends, Query, Response, status

from app.api.pagination import Page, page_params
from app.api.router import ApiRouter
from app.core.db_dep import get_db
from app.core.security_deps import AdminUser
from app.models import audit as audit_model
from app.schemas.admin import AuditFacetsOut, AuditLogListOut, DeptOptionSetRequest
from app.schemas.records import OptionSetOut
from app.services import options as options_service
from app.services.audit import write_audit

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


# --------------------------------------------------------------------------- #
# 选项集维护（科室 / 全局）
# --------------------------------------------------------------------------- #
@router.get("/admin/option-sets", response_model=list[OptionSetOut], summary="全部选项集（管理员总览）")
def list_all_option_sets(
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    scope: Annotated[str | None, Query(description="global / dept / personal，不传则全部")] = None,
) -> list[dict[str, Any]]:
    """管理员总览：能看见全部三层（含个人），便于排查"为什么某人看到的选项不一样"。"""
    where = ["status = 'active'"]
    params: list[Any] = []
    if scope:
        where.append("scope = ?")
        params.append(scope)
    rows = conn.execute(
        "SELECT id, scope, owner_user_id, dept_tag, code, name, alias, sort FROM option_set"
        f" WHERE {' AND '.join(where)} ORDER BY scope, sort, id",
        params,
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        data["items"] = options_service.items_of(conn, int(row["id"]))
        out.append(data)
    return out


@router.put("/admin/option-sets", response_model=OptionSetOut, summary="维护科室 / 全局选项集")
def upsert_option_set(
    payload: DeptOptionSetRequest,
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    """传了 `dept_tag` 就是科室级（`dept`），否则是全局（`global`）。

    这一层影响全科治疗师，所以限定管理员；个人的快捷选项走
    `PUT /option-sets/personal`（本人在治疗师端自己维护）。
    """
    result = options_service.upsert_dept_option_set(
        conn,
        code=payload.code,
        name=payload.name,
        values=payload.values,
        dept_tag=payload.dept_tag,
        default_values=payload.default_values,
    )
    write_audit(conn, user_id=int(admin["id"]), action="upsert", target_type="option_set",
                target_id=str(result["id"]),
                after={"code": result["code"], "scope": result["scope"], "values": payload.values})
    return result


@router.delete(
    "/admin/option-sets/{option_set_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="删除科室 / 全局选项集",
)
def delete_option_set(
    option_set_id: int,
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> Response:
    options_service.delete_option_set(conn, option_set_id)
    write_audit(conn, user_id=int(admin["id"]), action="delete", target_type="option_set",
                target_id=str(option_set_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
