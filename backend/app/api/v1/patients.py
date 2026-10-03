"""患者与归属接口（阶段 1 / `开发计划.md` 4.2、D10、M09、M12、M18）。

**数据级权限的唯一执行点。** 关键规则：

- 治疗师可读：归属自己 ∪ 临时认领自己 ∪ 未分配 ∪ 与我有关的临时指派。
- 治疗师可写归属：只能认领"未分配"、放弃"自己的"、临时认领"临时释放中"的患者。
- 只有管理员能写 `admin_note`（注意事项）与患者状态。

特别注意：**可见归属（`visible_therapist_id`）才是权限判据，不是原归属**。
单日假期间原归属者反而不能给自己的患者排期——这正是临时释放的意义。
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import Depends, Query, status

from app.api.pagination import Page, page_params
from app.api.router import ApiRouter
from app.core.db_dep import get_db
from app.core.errors import ForbiddenError, NotFoundError
from app.core.security_deps import AdminUser, CurrentUser, is_admin
from app.models import patient as patient_model
from app.models import user as user_model
from app.models.base import DomainError, Forbidden
from app.schemas.patient import (
    SCOPE_DESCRIPTION,
    AssignmentHistoryOut,
    AssignRequest,
    PatientCreateRequest,
    PatientListOut,
    PatientOut,
    PatientUpdateRequest,
)
from app.services.audit import write_audit

router = ApiRouter(prefix="/patients", tags=["患者"])


def _can_view(user: dict[str, Any], patient: dict[str, Any]) -> bool:
    """治疗师能否看到该患者（管理员不受限）。"""
    if is_admin(user):
        return True
    uid = int(user["id"])
    visible = patient["visible_therapist_id"]
    if visible is None or int(visible) == uid:
        return True
    # 与我有关的临时指派（我请假释放出去的，或我临时认领的）也可见
    if patient.get("temp_assignment_id") is not None:
        return uid in {patient.get("temp_therapist_id"), patient.get("temp_original_therapist_id")}
    return False


def _require_view(user: dict[str, Any], patient: dict[str, Any]) -> None:
    if not _can_view(user, patient):
        # 越权访问统一返回 403，且**不透露该患者是否存在**之外的信息
        raise ForbiddenError("PATIENT_NOT_VISIBLE", "无权查看该患者", details={"inpatient_no": patient["inpatient_no"]})


def _resolve_scope(user: dict[str, Any], scope: str | None) -> str:
    """普通用户不许用 ``all``。"""
    requested = scope or ("all" if is_admin(user) else "visible")
    if requested == "all" and not is_admin(user):
        raise ForbiddenError("SCOPE_FORBIDDEN", "只有管理员可以查看全部患者", details={"scope": "all"})
    return requested


@router.get("", response_model=PatientListOut, summary="患者列表（按权限过滤）")
def list_patients(
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    page: Annotated[Page, Depends(page_params)],
    scope: str | None = Query(None, description=SCOPE_DESCRIPTION),
    patient_status: str | None = Query(None, alias="status", description="在院状态筛选"),
    keyword: str | None = Query(None, description="按姓名或住院编号模糊匹配"),
) -> dict[str, Any]:
    resolved = _resolve_scope(user, scope)
    items, total = patient_model.list_patients(
        conn,
        scope=resolved,  # type: ignore[arg-type]
        user_id=int(user["id"]),
        status=patient_status,
        keyword=keyword,
        limit=page.limit,
        offset=page.offset,
    )
    return {
        "items": items,
        "total": total,
        "page": page.page,
        "page_size": page.page_size,
        "scope": resolved,
    }


@router.post("", response_model=PatientOut, status_code=status.HTTP_201_CREATED, summary="新建患者")
def create_patient(
    payload: PatientCreateRequest,
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    if payload.assigned_therapist_id is not None:
        try:
            user_model.get_by_id_or_raise(conn, payload.assigned_therapist_id)
        except DomainError:
            # models 层抛的是通用 NotFound（code=NOT_FOUND），这里换成对调用方更有用的码
            raise NotFoundError(
                "USER_NOT_FOUND",
                "指定的治疗师不存在",
                details={"therapist_id": payload.assigned_therapist_id},
            ) from None
    if payload.status == patient_model.STATUS_DISCHARGED:
        # 出院不可逆（Q9）：不允许直接建一个"已出院"的患者
        raise ForbiddenError("PATIENT_DISCHARGED_IMMUTABLE", "不能新建已出院的患者")
    patient = patient_model.create_patient(
        conn,
        inpatient_no=payload.inpatient_no,
        name=payload.name,
        diagnosis=payload.diagnosis,
        admin_note=payload.admin_note,
        assigned_therapist_id=payload.assigned_therapist_id,
        status=payload.status,
    )
    write_audit(conn, user_id=int(admin["id"]), action="create", target_type="patient",
                target_id=patient["inpatient_no"], after=patient)
    return patient


@router.get("/{inpatient_no}", response_model=PatientOut, summary="患者详情")
def get_patient(
    inpatient_no: str,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    patient = patient_model.get_patient(conn, inpatient_no)
    if patient is None:
        raise NotFoundError("PATIENT_NOT_FOUND", "患者不存在", details={"inpatient_no": inpatient_no})
    _require_view(user, patient)
    return patient


@router.put("/{inpatient_no}", response_model=PatientOut, summary="修改患者")
def update_patient(
    inpatient_no: str,
    payload: PatientUpdateRequest,
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    before = patient_model.get_patient_or_raise(conn, inpatient_no)

    # 出院不可逆（Q9）：已出院的患者不允许再改状态，需管理员显式走"恢复"路径
    trying_to_undelete = before["status"] == patient_model.STATUS_DISCHARGED and payload.status not in (
        None,
        patient_model.STATUS_DISCHARGED,
    )
    if trying_to_undelete:
        raise ForbiddenError(
            "PATIENT_DISCHARGED_IMMUTABLE",
            "已出院的患者不能改回其他状态，如需恢复请联系系统管理员",
            details={"inpatient_no": inpatient_no},
        )

    after = patient_model.update_patient(
        conn,
        inpatient_no,
        name=payload.name,
        diagnosis=payload.diagnosis,
        admin_note=payload.admin_note,
        status=payload.status,
    )
    write_audit(conn, user_id=int(admin["id"]), action="update", target_type="patient",
                target_id=inpatient_no, before=before, after=after)
    return after


@router.post("/claim", response_model=PatientOut, summary="认领未分配患者")
def claim_patient(
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    inpatient_no: str = Query(..., description="住院编号"),
) -> dict[str, Any]:
    patient = patient_model.claim_patient(conn, inpatient_no, int(user["id"]))
    write_audit(conn, user_id=int(user["id"]), action="claim", target_type="patient",
                target_id=inpatient_no, after={"assigned_therapist_id": user["id"]})
    return patient


@router.post("/{inpatient_no}/release", response_model=PatientOut, summary="放弃归属")
def release_patient(
    inpatient_no: str,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    before = patient_model.get_patient_or_raise(conn, inpatient_no)
    if not is_admin(user) and before["assigned_therapist_id"] != user["id"]:
        raise Forbidden("只能放弃属于自己的患者", details={"inpatient_no": inpatient_no})
    after = patient_model.release_patient(conn, inpatient_no, int(user["id"]))
    write_audit(conn, user_id=int(user["id"]), action="release", target_type="patient",
                target_id=inpatient_no, before={"assigned_therapist_id": before["assigned_therapist_id"]},
                after={"assigned_therapist_id": None})
    return after


@router.post("/{inpatient_no}/assign", response_model=PatientOut, summary="管理员指定归属")
def assign_patient(
    inpatient_no: str,
    payload: AssignRequest,
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    if payload.therapist_id is not None:
        try:
            user_model.get_by_id_or_raise(conn, payload.therapist_id)
        except DomainError:
            raise NotFoundError(
                "USER_NOT_FOUND", "指定的治疗师不存在", details={"therapist_id": payload.therapist_id}
            ) from None
    before = patient_model.get_patient_or_raise(conn, inpatient_no)
    after = patient_model.assign_patient(conn, inpatient_no, payload.therapist_id, int(admin["id"]))
    write_audit(conn, user_id=int(admin["id"]), action="assign", target_type="patient",
                target_id=inpatient_no,
                before={"assigned_therapist_id": before["assigned_therapist_id"]},
                after={"assigned_therapist_id": payload.therapist_id})
    return after


@router.get("/{inpatient_no}/assignments", response_model=list[AssignmentHistoryOut], summary="归属历史")
def assignment_history(
    inpatient_no: str,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> list[dict[str, Any]]:
    patient = patient_model.get_patient_or_raise(conn, inpatient_no)
    _require_view(user, patient)
    return patient_model.assignment_history(conn, inpatient_no)


__all__ = ["router"]
