"""治疗记录接口（SOAP 模板驱动，迁移 011 之后的新模型）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /records/enums | 状态 / 形态 / 四大类枚举 |
| GET | /records/form | 记录页表单：该填哪份文书 + 字段定义 + 预填 + 已存在的那条 |
| GET | /records | 记录列表（可按大类/形态筛选，按权限过滤） |
| POST | /records | 创建记录（草稿或直接提交） |
| GET | /records/{id} | 详情（含 body 与冻结的 rendered_text） |
| PUT | /records/{id} | 修改（改 body/日期会**重新渲染**；提交后由库层触发器留痕） |
| POST | /records/{id}/submit | 草稿 → 已提交 |
| POST | /records/{id}/lock | 已提交 → 已锁定（管理员） |
| DELETE | /records/{id} | 删除草稿（已提交的记录不允许删除；**写 change_log**） |
| GET | /timeline | 时间轴（按日期倒序） |

数据级权限（D10）：记录列表与时间轴都先算"我能看到哪些患者"，再据此过滤；
单条访问先判断患者可见性 —— 列表看不到、直接猜 URL 却能拿到，就是越权。

三条业务硬规则在**模型层**执行（`app/models/treatment.py`）：
评估文书不能跳过（第 1 次日常前必须有首评，第 21/41… 次前必须有复评）、
同一天同一大类至多 2 条、待出院患者不能再记新记录。
"""

from __future__ import annotations

import sqlite3
from datetime import date as _date
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
from app.schemas.records import (
    RecordCreateRequest,
    RecordEnumsOut,
    RecordFormOut,
    RecordListOut,
    RecordOut,
    RecordUpdateRequest,
    TimelineOut,
)
from app.services import records as records_service
from app.services import sync as sync_service
from app.services import visibility
from app.services.audit import write_audit

router = ApiRouter(prefix="/records", tags=["治疗记录"])


def _require_patient_visible(conn: sqlite3.Connection, user: dict[str, Any], patient_no: str) -> None:
    if not visibility.can_view_patient(conn, user, patient_no):
        raise ForbiddenError("PATIENT_NOT_VISIBLE", "无权访问该患者", details={"inpatient_no": patient_no})


def _require_record_access(conn: sqlite3.Connection, user: dict[str, Any], record: dict[str, Any]) -> None:
    """能改/看的判据：记录所属患者对我可见，或我就是记录人。"""
    if is_admin(user):
        return
    if int(record["therapist_id"]) == int(user["id"]):
        return
    if not visibility.can_view_patient(conn, user, str(record["patient_no"])):
        raise ForbiddenError(
            "RECORD_NOT_VISIBLE", "无权访问该治疗记录", details={"record_id": record["id"]}
        )


def _mark_pending_discharge(
    conn: sqlite3.Connection, record: dict[str, Any], *, user_id: int
) -> None:
    """提交出院小结后把患者置为**待出院**（用户要求：「填完小结即待出院」）。

    - 已是 `pending_discharge` / 已 `discharged` 时不动（幂等：重复提交不覆盖既有状态）；
    - 真正出院由管理员确认，或满 7 天由 `app.cli auto-discharge` 自动完成。
    """
    if str(record.get("kind")) != "discharge":
        return
    if str(record.get("status")) not in (treatment_model.STATUS_SUBMITTED, treatment_model.STATUS_LOCKED):
        return
    patient_no = str(record["patient_no"])
    patient = patient_model.get_patient_or_raise(conn, patient_no)
    if patient["status"] == patient_model.STATUS_PENDING_DISCHARGE:
        return
    if patient["status"] == patient_model.STATUS_DISCHARGED:
        return
    before = patient["status"]
    after = patient_model.update_patient(
        conn, patient_no, status=patient_model.STATUS_PENDING_DISCHARGE
    )
    write_audit(
        conn,
        user_id=user_id,
        action="pending_discharge",
        target_type="patient",
        target_id=patient_no,
        before={"status": before},
        after={"status": after["status"], "record_id": record.get("id")},
    )


@router.get("/enums", response_model=RecordEnumsOut, summary="记录状态、形态与四大类枚举")
def record_enums(user: CurrentUser) -> dict[str, Any]:
    return {
        "statuses": list(treatment_model.STATUSES),
        "kinds": list(treatment_model.KINDS),
        "disciplines": treatment_model.discipline_options(),
    }


@router.get("/form", response_model=RecordFormOut, summary="记录页表单（SOAP 模板）")
def record_form(
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    patient_no: str = Query(..., description="住院编号"),
    discipline: str = Query(..., description="PT / OT / ST_SW / ST_SP"),
    date: str | None = Query(None, alias="date", description="记录日期，默认今天"),
    kind: str | None = Query(
        None,
        description=(
            "强制指定形态（如 discharge —— App 的「出院」入口）；"
            "不传则由门禁自动决定：缺评估文书时先弹那份文书"
        ),
    ),
) -> dict[str, Any]:
    """这次该填哪份文书、长什么样、预填什么、是不是已经在填了。

    `pending_document` 非空时 `kind` **就是那份评估文书**（用户：「先弹评估文书」），
    填完它再回来拿一次表单，就会变成当天的日常记录。
    `kind=discharge` 用来取「出院小结」表单（它不是门禁推出来的，而是 App 上的一次显式动作）。
    """
    _require_patient_visible(conn, user, patient_no)
    return records_service.build_form(
        conn, patient_no=patient_no, discipline=discipline, record_date=date, kind=kind
    )


@router.get("", response_model=RecordListOut, summary="治疗记录列表")
def list_records(
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    page: Annotated[Page, Depends(page_params)],
    patient_no: str | None = None,
    therapist_id: int | None = None,
    discipline: str | None = Query(None, description="按大类筛选"),
    kind: str | None = Query(None, description="按形态筛选（daily / initial / reassessment / discharge）"),
    record_status: str | None = Query(None, alias="status"),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    scope: str | None = Query(None, description="mine（我写的）/ visible（我能看到的患者）"),
) -> dict[str, Any]:
    resolved_scope = scope or "visible"
    if resolved_scope not in {"mine", "visible"}:
        raise NotFoundError("INVALID_SCOPE", "scope 只能是 mine 或 visible", details={"scope": resolved_scope})

    patient_nos = None if resolved_scope == "mine" else visibility.visible_patient_numbers(conn, user)
    items, total = treatment_model.list_records(
        conn,
        patient_no=patient_no,
        patient_nos=patient_nos,
        therapist_id=int(user["id"]) if resolved_scope == "mine" else therapist_id,
        discipline=discipline,
        kind=kind,
        status=record_status,
        date_from=date_from,
        date_to=date_to,
        limit=page.limit,
        offset=page.offset,
    )
    return {"items": items, "total": total, "page": page.page, "page_size": page.page_size}


@router.post("", response_model=RecordOut, status_code=status.HTTP_201_CREATED, summary="创建治疗记录")
def create_record(
    payload: RecordCreateRequest,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    """创建记录。

    `body` 的键是模板里的字段 `key`（见 `templates/<大类>/<形态>.json`）。
    必填缺失 → 422；缺评估文书 / 同一天超过 2 条 / 待出院患者 → 409。
    """
    therapist_id = payload.therapist_id or int(user["id"])
    if not is_admin(user) and therapist_id != int(user["id"]):
        raise ForbiddenError("RECORD_OTHER_THERAPIST", "只能给自己写记录")
    if payload.therapist_id is not None:
        user_model.get_by_id_or_raise(conn, payload.therapist_id)

    patient_no = str(payload.patient_no)
    # 待出院患者要走**模型层**的"不能记新记录"判定（409 PATIENT_PENDING_DISCHARGE）：
    # 患者此时不在治疗师白板上，但治疗师手上很可能还留着这个患者的页面
    #（刚给他写完出院小结），这时回一句"无权访问"远不如"已提交出院小结"可操作。
    patient = patient_model.get_patient(conn, patient_no)
    if patient is None:
        raise NotFoundError("PATIENT_NOT_FOUND", "患者不存在", details={"inpatient_no": patient_no})
    if str(patient["status"]) != patient_model.STATUS_PENDING_DISCHARGE:
        _require_patient_visible(conn, user, patient_no)

    record = treatment_model.create_record(
        conn,
        patient_no=patient_no,
        therapist_id=therapist_id,
        record_date=payload.record_date or _date.today().isoformat(),
        discipline=payload.discipline,
        kind=payload.kind,
        body=payload.body,
        status=payload.status,
        client_uuid=payload.client_uuid,
        note=payload.note,
    )
    write_audit(conn, user_id=int(user["id"]), action="create", target_type="treatment_record",
                target_id=str(record["id"]),
                after={"status": record["status"], "kind": record["kind"],
                       "discipline": record["discipline"]})
    sync_service.record_change(
        conn, entity="treatment_record", entity_id=record["id"], op="insert",
        revision=int(record["revision"]), actor_user_id=int(user["id"]),
        payload=record,
    )
    # 用户要求：出院小结提交后患者即为"待出院"（再经管理员确认或满 7 天自动出院）
    _mark_pending_discharge(conn, record, user_id=int(user["id"]))
    return record


@router.get("/{record_id}", response_model=RecordOut, summary="治疗记录详情")
def get_record(
    record_id: int,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    record = treatment_model.get_record_or_raise(conn, record_id)
    _require_record_access(conn, user, record)
    return record


@router.put("/{record_id}", response_model=RecordOut, summary="修改治疗记录")
def update_record(
    record_id: int,
    payload: RecordUpdateRequest,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    before = treatment_model.get_record_or_raise(conn, record_id)
    _require_record_access(conn, user, before)

    after = treatment_model.update_record(
        conn,
        record_id,
        user_id=int(user["id"]),
        is_admin=is_admin(user),
        body=payload.body,
        status=payload.status,
        record_date=payload.record_date,
        note=payload.note,
    )
    write_audit(conn, user_id=int(user["id"]), action="update", target_type="treatment_record",
                target_id=str(record_id),
                before={"status": before["status"], "edit_count": before["edit_count"]},
                after={"status": after["status"], "edit_count": after["edit_count"]})
    sync_service.record_change(
        conn, entity="treatment_record", entity_id=record_id, op="update",
        revision=int(after["revision"]), actor_user_id=int(user["id"]), payload=after,
    )
    # 若这次修改让一份出院小结成为正式文书，患者随即进入待出院
    # （函数内部先判形态与状态，非出院小结直接返回）
    _mark_pending_discharge(conn, after, user_id=int(user["id"]))
    return after


@router.post("/{record_id}/submit", response_model=RecordOut, summary="提交记录")
def submit_record(
    record_id: int,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    before = treatment_model.get_record_or_raise(conn, record_id)
    _require_record_access(conn, user, before)
    after = treatment_model.submit_record(conn, record_id, user_id=int(before["therapist_id"]))
    write_audit(conn, user_id=int(user["id"]), action="submit", target_type="treatment_record",
                target_id=str(record_id), after={"status": "submitted", "seq_no": after["seq_no"]})
    sync_service.record_change(
        conn, entity="treatment_record", entity_id=record_id, op="update",
        revision=int(after["revision"]), actor_user_id=int(user["id"]), payload=after,
    )
    _mark_pending_discharge(conn, after, user_id=int(user["id"]))
    return after


@router.post("/{record_id}/lock", response_model=RecordOut, summary="锁定记录（管理员）")
def lock_record(
    record_id: int,
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    after = treatment_model.lock_record(conn, record_id)
    write_audit(conn, user_id=int(admin["id"]), action="lock", target_type="treatment_record",
                target_id=str(record_id), after={"status": "locked"})
    sync_service.record_change(
        conn, entity="treatment_record", entity_id=record_id, op="update",
        revision=int(after["revision"]), actor_user_id=int(admin["id"]), payload=after,
    )
    return after


@router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除草稿")
def delete_draft(
    record_id: int,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    from fastapi import Response

    treatment_model.delete_draft(conn, record_id, user_id=int(user["id"]))
    write_audit(conn, user_id=int(user["id"]), action="delete_draft", target_type="treatment_record",
                target_id=str(record_id))
    # ★ 必须写变更日志（op="delete"），否则**删除事件传不到客户端**：
    # 已经通过 `/sync/pull` 拉到过这条草稿的离线端会永久保留一条幻影记录
    #（记录在服务端已经不存在，却没有任何变更告诉它删掉）。
    # 这是 `change_log` 里唯一的 delete 来源 —— 治疗记录是唯一可离线写的实体，
    # 而只有草稿允许删除。
    sync_service.record_change(
        conn,
        entity="treatment_record",
        entity_id=record_id,
        op="delete",
        # 删除没有"新版本"；用 0 表示终止态，客户端按 op 处理即可。
        revision=0,
        actor_user_id=int(user["id"]),
        payload=None,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# 时间轴（独立 router：路径是 /timeline，不在 /records 前缀下）
# --------------------------------------------------------------------------- #
timeline_router = ApiRouter(tags=["治疗记录"])


@timeline_router.get("/timeline", response_model=TimelineOut, summary="时间轴")
def timeline(
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    page: Annotated[Page, Depends(page_params)],
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    discipline: str | None = Query(None, description="按大类筛选"),
    kind: str | None = Query(None, description="按形态筛选"),
    scope: str = Query("visible", description="mine / visible"),
) -> dict[str, Any]:
    """按日期倒序的记录流（SOAP 文本随条目一起返回，App 直接渲染）。

    > 曾有的 `scope=temp`（只看"临时治疗"）已按用户决定**删除**（2026-10-05）。
    > 注意 `is_temporary` 这个**标记本身仍然保留** —— 打印 PDF 会标"（临时）"、
    > 汇总会带 `is_temporary`、后台记录列表也有该列。
    """
    if scope not in {"mine", "visible"}:
        raise NotFoundError("INVALID_SCOPE", "scope 只能是 mine / visible", details={"scope": scope})

    patient_nos = None if scope == "visible" and is_admin(user) else visibility.visible_patient_numbers(conn, user)
    items, total = treatment_model.list_records(
        conn,
        patient_nos=patient_nos,
        therapist_id=int(user["id"]) if scope == "mine" else None,
        discipline=discipline,
        kind=kind,
        date_from=date_from,
        date_to=date_to,
        limit=page.limit,
        offset=page.offset,
    )
    return {"items": items, "total": total, "page": page.page, "page_size": page.page_size}


__all__ = ["router", "timeline_router"]
