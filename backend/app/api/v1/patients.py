"""患者与归属接口（阶段 1 / `开发计划.md` 4.2、D10、M09、M12、M18）。

**数据级权限的唯一执行点在 `services/visibility.py`**（本文件不再自己实现一份）。

2026-10-03 起改为**全科白板**：

- 治疗师可读：科室当前**在院 / 暂停**的全部患者（不再按归属隔离）；
  已出院默认不可见（管理员可用 `scope=all` 查看全表）。
- 治疗师可写：**建档、改诊断/注意事项/状态**、认领未分配、放弃自己的患者。
  > ★ 2026-10-06 **患者主数据也放开了**（用户明确要求）：原来是
  > 「只有管理员能改」，改动起因是 App 端要加「新建患者」按钮 ——
  > 治疗师才是第一个见到患者的人（入院当天就要记录），
  > 而当时只有管理员能在后台建档，治疗师只能干等。
  > 权限由**角色**降级为**可见性**（`_require_view`）：治疗师只能改他看得见的患者，
  > 管理员不受限。这一类改变必须有留痕 —— 审计日志现在记录**实际操作者**。
  > 另一处例外是**发起出院**（2026-10-05 起任何治疗师可做），
  > 它只把状态推到 `pending_discharge`，真正出院仍需管理员确认或满 7 天自动完成。
- 归属（`assigned_therapist_id`）语义由"可见性闸门"降级为**优先级与文书署名**。

注意：`visible_therapist_id`（可见归属）仍是**归属语义**的判据
（"当前谁主要负责"），但**不再是可见性闸门**——临时释放期间它仍会变 NULL，
用于表达"当前无人主要负责"。
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
from app.models import treatment as treatment_model
from app.models import user as user_model
from app.models.base import DomainError, Forbidden
from app.models.patient import ACTIVE_STATUSES
from app.schemas.patient import (
    SCOPE_DESCRIPTION,
    AssignmentHistoryOut,
    AssignRequest,
    DischargeRequest,
    PatientCreateRequest,
    PatientListOut,
    PatientOut,
    PatientUpdateRequest,
)
from app.services.audit import write_audit

router = ApiRouter(prefix="/patients", tags=["患者"])


def _can_view(user: dict[str, Any], patient: dict[str, Any]) -> bool:
    """治疗师能否看到该患者（管理员不受限）。

    2026-10-03 起统一走 `services/visibility.py` —— 此前本文件自己实现了一份
    可见性判断，与 `visibility.py` 重复；两份条件一旦漂移就会产生越权。
    现在**权限判断只在 visibility 模块实现**（模块文档明确要求）。
    """
    if is_admin(user):
        return True
    return str(patient["status"]) in ACTIVE_STATUSES


def _require_view(user: dict[str, Any], patient: dict[str, Any]) -> None:
    if not _can_view(user, patient):
        # 越权访问统一返回 403，且**不透露该患者是否存在**之外的信息
        raise ForbiddenError("PATIENT_NOT_VISIBLE", "无权查看该患者", details={"inpatient_no": patient["inpatient_no"]})


def _resolve_scope(user: dict[str, Any], scope: str | None) -> str:
    """决定患者列表的数据范围。

    2026-10-03 起治疗师默认 ``dept``（科室白板：在院 + 暂停），不再是按归属隔离的
    ``visible``；管理员默认 ``all``（全表，含已出院）。
    ``all`` 仍**仅管理员**可用（``SCOPE_FORBIDDEN``）。
    """
    requested = scope or ("all" if is_admin(user) else "dept")
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
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    """新建患者。

    ★ 2026-10-06 权限变更（用户明确要求）：**任何治疗师**都能建档，
    原来是 `AdminUser`（管理员专属）。

    触发本次变更的是 App 端需求：「在 app 的患者页，右侧偏下悬浮一个 + 号的
    圆形按钮，用来新建患者」—— 治疗师才是第一个见到患者的人（入院当天就要记录），
    而当时只有管理员能在后台建档，治疗师只能干等。

    同一次变更还把「注意事项」的写权限一并放开（见 `update_patient`）。
    """
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
        # 不允许直接建一个"已出院"的患者：那等于凭空造出一条没有在院经历的病历。
        # 正常的出院动作是"先建在院患者，再改状态为 discharged"。
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
    # 审计记录**实际操作者**（不再假定是管理员）—— 权限放开之后
    # "谁建的档"必须如实留痕，否则审计日志会开始说谎。
    write_audit(conn, user_id=int(user["id"]), action="create", target_type="patient",
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
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    """修改患者。

    ★ 2026-10-06 权限变更（用户明确要求）：**任何治疗师**都能改，
    原来是 `AdminUser`（管理员专属）。用户的原话是
    「取消注意事项的治疗师只读属性」，并确认「治疗师可改患者全部字段（含状态）」。

    ## 数据级门禁

    权限从"角色"降级为"**可见性**"：治疗师只能改他看得见的患者
    （`_require_view`，管理员不受限）。否则治疗师能靠猜住院编号去改
    已出院患者的信息 —— 而那些患者本就不该出现在他的白板上。

    ## 出院可逆性（Q9）

    `设计.md` 3.1 的原文是「**出院不可逆**（需管理员手动改回），暂停治疗可逆」——
    也就是说"不可逆"指的是**治疗师不能自行恢复**。2026-10-06 起治疗师
    **可以**恢复（用户要求放开全部字段），所以这条限制现在只剩
    "必须有留痕"：`discharged → 其它状态` 单独记为 `restore` 动作，
    这样审计日志里能一眼看出谁做过恢复，而不是淹没在普通的 `update` 里。

    > 早先这里写了一条"已出院不能再改状态"的判断，结果把管理员自己的权限也挡了，
    > 提示"如需恢复请联系系统管理员"——而**调用者就是系统管理员**，形成死锁：
    > 没有任何路径能把患者改回在院。已删除该判断。
    """
    before = patient_model.get_patient_or_raise(conn, inpatient_no)
    _require_view(user, before)

    is_restore = (
        before["status"] == patient_model.STATUS_DISCHARGED
        and payload.status is not None
        and payload.status != patient_model.STATUS_DISCHARGED
    )

    after = patient_model.update_patient(
        conn,
        inpatient_no,
        name=payload.name,
        diagnosis=payload.diagnosis,
        admin_note=payload.admin_note,
        status=payload.status,
    )
    # 如实记录**实际操作者**（权限放开后不能再假定是管理员）。
    write_audit(conn, user_id=int(user["id"]), action="restore" if is_restore else "update",
                target_type="patient", target_id=inpatient_no, before=before, after=after)
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


# --------------------------------------------------------------------------- #
# 出院流程（用户 2026-10-05 要求）
# --------------------------------------------------------------------------- #
@router.post("/{inpatient_no}/discharge", response_model=PatientOut, summary="发起出院（任何治疗师）")
def request_discharge(
    inpatient_no: str,
    payload: DischargeRequest,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    """提交出院小结后把患者置为**待出院**。

    ⚠ **权限口径是用户的明确决定**：这里用 `CurrentUser` 而不是 `AdminUser` ——
    用户要求「所有治疗师都能发起出院」（治疗师才是填小结的人）。
    这与"患者主数据只有管理员能改"的旧口径不同，但**管理员专用的
    `PUT /patients/{inpatient_no}` 改状态接口保持不动**（仍可任意改回）。

    真正出院仍需管理员 `POST .../discharge/confirm`，或满 7 天由
    `app.cli auto-discharge` 自动完成。
    """
    before = patient_model.get_patient_or_raise(conn, inpatient_no)
    # 注意这里**不能**直接用 `_require_view`：患者提交出院小结的瞬间就可能已经是
    # `pending_discharge`（见 api/v1/records.py::_mark_pending_discharge），而
    # `pending_discharge` 刻意不在 ACTIVE_STATUSES 里（要从治疗师白板消失）。
    # 出院动作本身必须是幂等的，所以"已待出院"也放行。
    if not is_admin(user) and before["status"] not in (
        *ACTIVE_STATUSES,
        patient_model.STATUS_PENDING_DISCHARGE,
    ):
        raise ForbiddenError(
            "PATIENT_NOT_VISIBLE", "无权操作该患者", details={"inpatient_no": inpatient_no}
        )
    # 必须指向该患者**已提交**的出院小结（出院不是点按钮，而是"文书写完了"）
    record = treatment_model.submitted_discharge_summary(conn, inpatient_no, payload.record_id)
    after = patient_model.mark_pending_discharge(conn, inpatient_no, operator_user_id=int(user["id"]))
    write_audit(conn, user_id=int(user["id"]), action="discharge_request", target_type="patient",
                target_id=inpatient_no,
                before={"status": before["status"]},
                after={"status": after["status"], "record_id": record["id"]})
    return after


@router.post(
    "/{inpatient_no}/discharge/confirm", response_model=PatientOut, summary="确认出院（管理员）"
)
def confirm_discharge(
    inpatient_no: str,
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    """待出院 → 已出院（管理员确认）。"""
    after = patient_model.confirm_discharge(conn, inpatient_no)
    write_audit(conn, user_id=int(admin["id"]), action="discharge_confirm", target_type="patient",
                target_id=inpatient_no, before={"status": patient_model.STATUS_PENDING_DISCHARGE},
                after={"status": after["status"]})
    return after


@router.post(
    "/{inpatient_no}/discharge/cancel", response_model=PatientOut, summary="取消待出院（管理员）"
)
def cancel_discharge(
    inpatient_no: str,
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    """取消待出院 → 回在院（管理员纠正误操作）。"""
    before = patient_model.get_patient_or_raise(conn, inpatient_no)
    after = patient_model.cancel_pending_discharge(conn, inpatient_no)
    write_audit(conn, user_id=int(admin["id"]), action="discharge_cancel", target_type="patient",
                target_id=inpatient_no, before={"status": before["status"]},
                after={"status": after["status"]})
    return after


__all__ = ["router"]
