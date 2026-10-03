"""请假接口（阶段 2 / `开发计划.md` 4.4）。

**Q6 定稿：无审批流。**

| 方法 | 路径 | 角色 | 说明 |
|---|---|---|---|
| POST | /leave | 治疗师 | 登记请假（**立即生效**并执行释放/排空） |
| POST | /leave/admin | 管理员 | 代录请假（`source='admin_entry'`） |
| GET | /leave | 全部 | 自己的记录；管理员可查全部 |
| POST | /leave/{id}/cancel | 治疗师/管理员 | 撤销并回滚释放效果 |
| GET | /leave/effective | 全部 | 查某治疗师某半日是否请假（供排期页置灰） |
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import Depends, status

from app.api.router import ApiRouter
from app.core.db_dep import get_db
from app.core.errors import ForbiddenError, NotFoundError
from app.core.security_deps import AdminUser, CurrentUser, is_admin
from app.models import leave as leave_model
from app.models import user as user_model
from app.schemas.schedule import (
    LeaveCancelRequest,
    LeaveCancelResult,
    LeaveCreateRequest,
    LeaveOut,
    ScheduleEnumsOut,
)
from app.services.audit import write_audit

router = ApiRouter(prefix="/leave", tags=["请假"])


def _require_self_or_admin(user: dict[str, Any], therapist_id: int) -> None:
    if not is_admin(user) and int(user["id"]) != therapist_id:
        raise ForbiddenError("LEAVE_OTHER_THERAPIST", "只能操作自己的请假")


def _create(
    conn: sqlite3.Connection,
    *,
    user: dict[str, Any],
    payload: LeaveCreateRequest,
    source: str,
    therapist_id: int,
) -> dict[str, Any]:
    end_date = payload.end_date or payload.start_date
    leave = leave_model.create_leave(
        conn,
        therapist_id=therapist_id,
        leave_type=payload.leave_type,
        start_date=payload.start_date,
        end_date=end_date,
        operator_user_id=int(user["id"]),
        source=source,
        period=payload.period,
        reason=payload.reason,
    )
    write_audit(conn, user_id=int(user["id"]), action="create", target_type="leave_record",
                target_id=str(leave["id"]), after=leave)
    return leave


@router.get("/enums", response_model=ScheduleEnumsOut, summary="请假相关枚举值")
def leave_enums(user: CurrentUser) -> dict[str, Any]:
    return ScheduleEnumsOut().model_dump()


@router.post("", response_model=LeaveOut, status_code=status.HTTP_201_CREATED, summary="登记请假")
def create_leave(
    payload: LeaveCreateRequest,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    """治疗师给自己请假：**登记即生效**。

    即使是管理员，也请用 ``/leave/admin`` 代录，以保持 `source` 字段的语义准确
    （用于区分"自己请"与"管理员代录"，审计时需要）。
    """
    therapist_id = payload.therapist_id or int(user["id"])
    _require_self_or_admin(user, therapist_id)
    source = "therapist_self" if therapist_id == int(user["id"]) else "admin_entry"
    return _create(conn, user=user, payload=payload, source=source, therapist_id=therapist_id)


@router.post(
    "/admin",
    response_model=LeaveOut,
    status_code=status.HTTP_201_CREATED,
    summary="管理员代录请假",
)
def create_leave_as_admin(
    payload: LeaveCreateRequest,
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    if payload.therapist_id is None:
        raise NotFoundError("THERAPIST_REQUIRED", "管理员代录请假必须指定 therapist_id")
    user_model.get_by_id_or_raise(conn, payload.therapist_id)
    return _create(
        conn,
        user=admin,
        payload=payload,
        source="admin_entry",
        therapist_id=payload.therapist_id,
    )


@router.get("", response_model=list[LeaveOut], summary="请假记录")
def list_leaves(
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    therapist_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    leave_status: str | None = None,
) -> list[dict[str, Any]]:
    # 治疗师只看自己的；管理员可查全部或指定某人
    target = therapist_id if is_admin(user) else int(user["id"])
    return leave_model.list_leaves(
        conn,
        therapist_id=target,
        date_from=date_from,
        date_to=date_to,
        status=leave_status,
    )


@router.get("/effective", summary="某治疗师某半日是否处于请假")
def effective_leave(
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    date: str,
    period: str,
    therapist_id: int | None = None,
) -> dict[str, Any]:
    target = therapist_id or int(user["id"])
    leave = leave_model.is_on_leave(conn, target, date, period)
    return {"therapist_id": target, "date": date, "period": period, "on_leave": leave is not None, "leave": leave}


@router.post("/{leave_id}/cancel", response_model=LeaveCancelResult, summary="撤销请假")
def cancel_leave(
    leave_id: int,
    payload: LeaveCancelRequest,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    leave = leave_model.get_leave_or_raise(conn, leave_id)
    _require_self_or_admin(user, int(leave["therapist_id"]))
    result = leave_model.cancel_leave(
        conn,
        leave_id,
        operator_user_id=int(user["id"]),
        cancel_reason=payload.cancel_reason,
    )
    write_audit(conn, user_id=int(user["id"]), action="cancel", target_type="leave_record",
                target_id=str(leave_id), before=leave, after=result)
    return result


__all__ = ["router"]
