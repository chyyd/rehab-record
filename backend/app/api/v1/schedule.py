"""排期与休息块接口（阶段 2 / `开发计划.md` 4.3）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /schedule | 按 `(date, period)` 返回半日格子 |
| POST | /schedule | 新建排期（冲突返回 409 与冲突对象） |
| PUT | /schedule/{id} | 改患者/改半日/改状态 |
| DELETE | /schedule/{id} | 取消（软删除，让出格子） |
| GET | /schedule/availability | 查可排/不可排格子（含休息、请假、已占） |
| POST | /schedule/copy | 复制昨天 / 上周 |
| GET/POST/PUT/DELETE | /rest-blocks | 休息块 |

排期权限（Q3）：治疗师只能给"可见归属是自己"或"未分配"的患者排期，
且只能排给自己（管理员可代排给他人）。
"""

from __future__ import annotations

import sqlite3
from datetime import date as _date
from datetime import timedelta
from typing import Annotated, Any

from fastapi import Depends, Query, status

from app.api.router import ApiRouter
from app.core.db_dep import get_db
from app.core.errors import ForbiddenError, NotFoundError
from app.core.security_deps import CurrentUser, is_admin
from app.core.worktime import day_period_bounds, period_label
from app.models import appointment as appointment_model
from app.models import patient as patient_model
from app.models import rest_block as rest_block_model
from app.schemas.schedule import (
    AppointmentCreateRequest,
    AppointmentOut,
    AppointmentUpdateRequest,
    AvailabilitySlotOut,
    CopyScheduleRequest,
    CopyScheduleResult,
    RestBlockCreateRequest,
    RestBlockOut,
    RestBlockUpdateRequest,
)
from app.services import sync as sync_service
from app.services.audit import write_audit

router = ApiRouter(tags=["排期"])


# --------------------------------------------------------------------------- #
# 权限辅助
# --------------------------------------------------------------------------- #
def _require_schedulable(
    conn: sqlite3.Connection, user: dict[str, Any], patient_no: str, therapist_id: int
) -> None:
    """排期权限（2026-10-03 起为"全科白板"）。

    - **限制 1（保留）**：治疗师只能给自己排期（``SCHEDULE_OTHER_THERAPIST``）。
    - **限制 2（已放开）**：原先要求患者必须是"我的 / 未分配 / 临时认领"
      （``PATIENT_NOT_SCHEDULABLE``）。全科白板下治疗师需要能给任何在院/暂停患者排期
      —— 一个上午里 PT / OT / 言语 / 吞咽 可能各给同一患者排一台，
      且归属人通常只有一个，若不放开会直接挡住正常业务。

    > ``patient_model.can_schedule()`` 仍然保留：它表达的是**归属语义**
    > （可见归属解析），单测直接覆盖它；但**不再作为排期的前置拒绝条件**。
    """
    if is_admin(user):
        return
    if therapist_id != int(user["id"]):
        raise ForbiddenError("SCHEDULE_OTHER_THERAPIST", "只能给自己排期")


def _require_can_view_schedule(user: dict[str, Any], therapist_id: int) -> None:
    """治疗师可以看全科室排期（床旁协作需要知道谁在哪），但只看自己时不额外限制。"""
    return None


# --------------------------------------------------------------------------- #
# 排期
# --------------------------------------------------------------------------- #
@router.get("/schedule", response_model=list[AppointmentOut], summary="排期查询（半日格子）")
def list_schedule(
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    date_from: str = Query(..., alias="from", description="起始日期 YYYY-MM-DD"),
    date_to: str = Query(..., alias="to", description="结束日期 YYYY-MM-DD"),
    therapist_id: int | None = Query(None, description="默认全部治疗师"),
    patient_no: str | None = None,
    include_inactive: bool = Query(False, description="是否包含已取消/已改期的记录"),
) -> list[dict[str, Any]]:
    return appointment_model.list_appointments(
        conn,
        date_from=date_from,
        date_to=date_to,
        therapist_id=therapist_id,
        patient_no=patient_no,
        include_inactive=include_inactive,
    )


@router.post(
    "/schedule",
    response_model=AppointmentOut,
    status_code=status.HTTP_201_CREATED,
    summary="新建排期",
)
def create_appointment(
    payload: AppointmentCreateRequest,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    therapist_id = payload.therapist_id or int(user["id"])
    patient_model.get_patient_or_raise(conn, payload.patient_no)
    _require_schedulable(conn, user, payload.patient_no, therapist_id)

    created = appointment_model.create_appointment(
        conn,
        patient_no=payload.patient_no,
        therapist_id=therapist_id,
        day=payload.date,
        period=payload.period,
        start_time=payload.start_time,
        end_time=payload.end_time,
        slot_label=payload.slot_label,
        note=payload.note,
    )
    write_audit(conn, user_id=int(user["id"]), action="create", target_type="appointment",
                target_id=str(created["id"]), after=created)
    # 写变更日志：离线客户端靠 change_log.id 游标增量拉取（阶段 4）
    sync_service.record_change(
        conn, entity="appointment", entity_id=created["id"], op="insert",
        revision=int(created["revision"]), actor_user_id=int(user["id"]), payload=created,
    )
    return created


@router.get("/schedule/availability", response_model=list[AvailabilitySlotOut], summary="可排性查询")
def schedule_availability(
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    date_from: str = Query(..., alias="from"),
    date_to: str = Query(..., alias="to"),
    therapist_id: int | None = None,
    patient_no: str | None = Query(
        None, description="传入后额外回传该患者在这些半日的排期（谁在做），不参与可排性判定"
    ),
) -> list[dict[str, Any]]:
    """逐半日返回可排性与已有排期。

    2026-10-03 起半日格子**不再互斥**：``available`` 只受休息块与生效请假影响；
    格子里的已有排期通过 ``appointments`` / ``appointment_count`` 回传，供客户端展示。
    """
    target = therapist_id or int(user["id"])
    return appointment_model.availability(
        conn, therapist_id=target, date_from=date_from, date_to=date_to, patient_no=patient_no
    )


@router.get("/schedule/periods", summary="半日边界（供前端渲染表头）")
def schedule_periods(user: CurrentUser) -> dict[str, Any]:
    return {
        "periods": day_period_bounds(),
        "labels": {p: period_label(p) for p in ("am", "pm")},
        "note": "排期单位为上午/下午半日；start_time/end_time 仅作同日排序，不参与冲突判定",
    }


@router.put("/schedule/{appointment_id}", response_model=AppointmentOut, summary="修改排期")
def update_appointment(
    appointment_id: int,
    payload: AppointmentUpdateRequest,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    before = appointment_model.get_appointment_or_raise(conn, appointment_id)
    if not is_admin(user) and int(before["therapist_id"]) != int(user["id"]):
        raise ForbiddenError("SCHEDULE_OTHER_THERAPIST", "只能修改自己的排期")

    target_patient = payload.patient_no or before["patient_no"]
    target_therapist = payload.therapist_id or int(before["therapist_id"])
    _require_schedulable(conn, user, target_patient, target_therapist)

    after = appointment_model.update_appointment(
        conn,
        appointment_id,
        patient_no=payload.patient_no,
        therapist_id=payload.therapist_id,
        day=payload.date,
        period=payload.period,
        status=payload.status,
        start_time=payload.start_time,
        end_time=payload.end_time,
        note=payload.note,
    )
    write_audit(conn, user_id=int(user["id"]), action="update", target_type="appointment",
                target_id=str(appointment_id), before=before, after=after)
    sync_service.record_change(
        conn, entity="appointment", entity_id=appointment_id, op="update",
        revision=int(after["revision"]), actor_user_id=int(user["id"]), payload=after,
    )
    return after


@router.delete("/schedule/{appointment_id}", response_model=AppointmentOut, summary="取消排期")
def cancel_appointment(
    appointment_id: int,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    before = appointment_model.get_appointment_or_raise(conn, appointment_id)
    if not is_admin(user) and int(before["therapist_id"]) != int(user["id"]):
        raise ForbiddenError("SCHEDULE_OTHER_THERAPIST", "只能取消自己的排期")
    after = appointment_model.cancel_appointment(conn, appointment_id)
    write_audit(conn, user_id=int(user["id"]), action="cancel", target_type="appointment",
                target_id=str(appointment_id), before=before, after=after)
    sync_service.record_change(
        conn, entity="appointment", entity_id=appointment_id, op="update",
        revision=int(after["revision"]), actor_user_id=int(user["id"]), payload=after,
    )
    return after


@router.post("/schedule/copy", response_model=CopyScheduleResult, summary="复制昨天 / 上周")
def copy_schedule(
    payload: CopyScheduleRequest,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    """把某一天的排期整批复制到目标日期。

    冲突格子**跳过并回报**，不整体失败——复制排期本来就是"尽力而为"的操作，
    因为源日期与目标日期的休息/请假情况可能不同。
    """
    if payload.mode not in {"yesterday", "last_week"}:
        raise NotFoundError("INVALID_MODE", "mode 只能是 yesterday 或 last_week", details={"mode": payload.mode})

    therapist_id = payload.therapist_id or int(user["id"])
    if not is_admin(user) and therapist_id != int(user["id"]):
        raise ForbiddenError("SCHEDULE_OTHER_THERAPIST", "只能复制自己的排期")

    target = _date.fromisoformat(payload.target_date) if payload.target_date else _date.today()
    source = target - timedelta(days=1 if payload.mode == "yesterday" else 7)

    source_items = appointment_model.list_appointments(
        conn,
        date_from=source.isoformat(),
        date_to=source.isoformat(),
        therapist_id=therapist_id,
    )
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in source_items:
        try:
            new_item = appointment_model.create_appointment(
                conn,
                patient_no=item["patient_no"],
                therapist_id=therapist_id,
                day=target.isoformat(),
                period=item["period"],
                start_time=item["start_time"],
                end_time=item["end_time"],
                slot_label=item["slot_label"],
                note=item["note"],
            )
            created.append(new_item)
            # 复制出来的每一条也要进变更日志，否则离线客户端拉不到
            sync_service.record_change(
                conn, entity="appointment", entity_id=new_item["id"], op="insert",
                revision=int(new_item["revision"]), actor_user_id=int(user["id"]), payload=new_item,
            )
        except Exception as exc:  # noqa: BLE001 - 冲突/占用都算跳过，逐条回报
            skipped.append(
                {
                    "patient_no": item["patient_no"],
                    "period": item["period"],
                    "reason": getattr(exc, "code", type(exc).__name__),
                    "message": getattr(exc, "message", str(exc)),
                }
            )
    write_audit(conn, user_id=int(user["id"]), action="copy_schedule", target_type="appointment",
                target_id=target.isoformat(),
                after={"mode": payload.mode, "created": len(created), "skipped": len(skipped)})
    return {
        "created": created,
        "skipped": skipped,
        "source_date": source.isoformat(),
        "target_date": target.isoformat(),
    }


# --------------------------------------------------------------------------- #
# 休息块
# --------------------------------------------------------------------------- #
@router.get("/rest-blocks", response_model=list[RestBlockOut], summary="休息块列表")
def list_rest_blocks(
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    therapist_id: int | None = None,
) -> list[dict[str, Any]]:
    # 治疗师默认看自己的；管理员可看全部或指定某人
    target = therapist_id if is_admin(user) else int(user["id"])
    return rest_block_model.list_rest_blocks(conn, target)


@router.post(
    "/rest-blocks",
    response_model=RestBlockOut,
    status_code=status.HTTP_201_CREATED,
    summary="新建休息块",
)
def create_rest_block(
    payload: RestBlockCreateRequest,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    target = payload.therapist_id or int(user["id"])
    if not is_admin(user) and target != int(user["id"]):
        raise ForbiddenError("REST_BLOCK_OTHER_THERAPIST", "只能维护自己的休息块")
    block = rest_block_model.create_rest_block(
        conn,
        therapist_id=target,
        scope=payload.scope,
        period=payload.period,
        weekday=payload.weekday,
        specific_date=payload.specific_date,
        note=payload.note,
    )
    write_audit(conn, user_id=int(user["id"]), action="create", target_type="rest_block",
                target_id=str(block["id"]), after=block)
    return block


@router.put("/rest-blocks/{block_id}", response_model=RestBlockOut, summary="修改休息块")
def update_rest_block(
    block_id: int,
    payload: RestBlockUpdateRequest,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    before = rest_block_model.get_rest_block_or_raise(conn, block_id)
    if not is_admin(user) and int(before["therapist_id"]) != int(user["id"]):
        raise ForbiddenError("REST_BLOCK_OTHER_THERAPIST", "只能维护自己的休息块")
    after = rest_block_model.update_rest_block(
        conn,
        block_id,
        scope=payload.scope,
        weekday=payload.weekday,
        specific_date=payload.specific_date,
        period=payload.period,
        note=payload.note,
    )
    write_audit(conn, user_id=int(user["id"]), action="update", target_type="rest_block",
                target_id=str(block_id), before=before, after=after)
    return after


@router.delete("/rest-blocks/{block_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除休息块")
def delete_rest_block(
    block_id: int,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> None:
    before = rest_block_model.get_rest_block_or_raise(conn, block_id)
    if not is_admin(user) and int(before["therapist_id"]) != int(user["id"]):
        raise ForbiddenError("REST_BLOCK_OTHER_THERAPIST", "只能维护自己的休息块")
    rest_block_model.delete_rest_block(conn, block_id)
    write_audit(conn, user_id=int(user["id"]), action="delete", target_type="rest_block",
                target_id=str(block_id), before=before)


__all__ = ["router"]
