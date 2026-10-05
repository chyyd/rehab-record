"""治疗记录接口（阶段 3 / `开发计划.md` 4.6、4.7）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /records/form | 记录页表单：患者 + 字典树 + 解析后的选项与带入值 + 患者反应 |
| GET | /records | 记录列表（按可见患者过滤） |
| POST | /records | 创建记录（支持草稿与直接提交） |
| GET | /records/{id} | 详情（含明细与快照） |
| PUT | /records/{id} | 修改（提交后由库层触发器留痕） |
| POST | /records/{id}/submit | 草稿 → 已提交 |
| POST | /records/{id}/lock | 已提交 → 已锁定（管理员） |
| DELETE | /records/{id} | 删除草稿（已提交的记录不允许删除） |
| GET | /timeline | 时间轴（按日期倒序） |
| GET | /records/enums | 状态与半日枚举 |

数据级权限（D10）：记录列表与时间轴都先算"我能看到哪些患者"，
再据此过滤；单条访问先判断患者可见性。两个入口共用 `services/visibility`，
避免"列表看不到、直接猜 URL 能拿到"的越权。
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
from app.models import treatment as treatment_model
from app.models import user as user_model
from app.models.base import Invalid
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


@router.get("/enums", response_model=RecordEnumsOut, summary="记录状态与半日枚举")
def record_enums(user: CurrentUser) -> dict[str, Any]:
    return RecordEnumsOut().model_dump()


@router.get("/form", response_model=RecordFormOut, summary="记录页表单")
def record_form(
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    patient_no: str = Query(..., description="住院编号"),
    main_item_id: int | None = Query(None, description="只返回某个主项目（按入口裁剪）"),
    dept_tag: str | None = Query(None, description="科室选项集标签，如 PT/OT/ST"),
) -> dict[str, Any]:
    _require_patient_visible(conn, user, patient_no)
    return records_service.build_form(
        conn,
        patient_no=patient_no,
        owner_user_id=int(user["id"]),
        dept_tag=dept_tag,
        main_item_id=main_item_id,
    )


@router.get("", response_model=RecordListOut, summary="治疗记录列表")
def list_records(
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    page: Annotated[Page, Depends(page_params)],
    patient_no: str | None = None,
    therapist_id: int | None = None,
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
        therapist_id=int(user["id"]) if resolved_scope == "mine" else therapist_id,
        status=record_status,
        date_from=date_from,
        date_to=date_to,
        patient_nos=patient_nos,
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

    日期与半日由调用方显式给出（未给日期则用当天）；不再有"从排期自动带入"
    这条路 —— 排期功能已于 2026-10-05 整体下线，本系统只记录**已经做了什么**。
    """
    from datetime import date as _date

    therapist_id = payload.therapist_id or int(user["id"])
    if not is_admin(user) and therapist_id != int(user["id"]):
        raise ForbiddenError("RECORD_OTHER_THERAPIST", "只能给自己写记录")
    if payload.therapist_id is not None:
        user_model.get_by_id_or_raise(conn, payload.therapist_id)

    patient_no = payload.patient_no
    _require_patient_visible(conn, user, str(patient_no))

    record_date = payload.record_date or _date.today().isoformat()
    session_period = payload.session_period

    # 明细：校验子项目归属与参数，并生成快照
    items = _prepare_items(
        conn,
        items=[i.model_dump() for i in payload.items],
        owner_user_id=int(user["id"]),
    )
    patient_response = records_service.normalize_responses(
        conn,
        patient_response=payload.patient_response,
        main_item_ids=[i["main_item_id"] for i in items] or None,
    )

    record = treatment_model.create_record(
        conn,
        patient_no=str(patient_no),
        therapist_id=therapist_id,
        record_date=record_date,
        session_period=session_period,
        duration_min=payload.duration_min,
        patient_response=patient_response,
        note=payload.note,
        status=payload.status,
        items=items,
    )
    write_audit(conn, user_id=int(user["id"]), action="create", target_type="treatment_record",
                target_id=str(record["id"]), after={"status": record["status"]})
    sync_service.record_change(
        conn, entity="treatment_record", entity_id=record["id"], op="insert",
        revision=int(record["revision"]), actor_user_id=int(user["id"]),
        # 带上 items 一起快照：客户端据此在本地完整重建这条记录
        payload={**record, "items": record.get("items")},
    )
    return record


def _prepare_items(
    conn: sqlite3.Connection, *, items: list[dict[str, Any]], owner_user_id: int
) -> list[dict[str, Any]]:
    """校验明细并生成两层快照（子项目名称 + 参数名与选项文本）。"""
    from app.models import dictionary as dictionary_model

    prepared: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, item in enumerate(items):
        sub_item_id = int(item["sub_item_id"])
        if sub_item_id in seen:
            # 参数问题而非"找不到资源"，用 422 而不是 404
            raise Invalid("同一子项目不能重复出现", details={"sub_item_id": sub_item_id})
        seen.add(sub_item_id)

        sub = dictionary_model.get_sub_item_or_raise(conn, sub_item_id)
        main_item_id = int(item["main_item_id"])
        if int(sub["main_item_id"]) != main_item_id:
            raise Invalid(
                "子项目不属于所给主项目",
                details={"sub_item_id": sub_item_id, "main_item_id": main_item_id,
                         "expected_main_item_id": int(sub["main_item_id"])},
            )
        params, snapshot = records_service.resolve_params(
            conn, sub_item_id=sub_item_id, params=item.get("params"), owner_user_id=owner_user_id
        )
        prepared.append(
            {
                "main_item_id": main_item_id,
                "sub_item_id": sub_item_id,
                "sub_item_name_snapshot": sub["name"],
                "params": params,
                "params_snapshot": snapshot,
                "sort": item.get("sort", index * 10),
            }
        )
    return prepared


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

    items = None
    if payload.items is not None:
        items = _prepare_items(
            conn, items=[i.model_dump() for i in payload.items], owner_user_id=int(user["id"])
        )
    patient_response = None
    if payload.patient_response is not None:
        patient_response = records_service.normalize_responses(
            conn,
            patient_response=payload.patient_response,
            main_item_ids=[i["main_item_id"] for i in (items or before["items"])] or None,
        )

    after = treatment_model.update_record(
        conn,
        record_id,
        user_id=int(user["id"]),
        is_admin=is_admin(user),
        record_date=payload.record_date,
        session_period=payload.session_period,
        duration_min=payload.duration_min,
        patient_response=patient_response,
        clear_patient_response=payload.clear_patient_response,
        note=payload.note,
        items=items,
    )
    write_audit(conn, user_id=int(user["id"]), action="update", target_type="treatment_record",
                target_id=str(record_id),
                before={"status": before["status"], "edit_count": before["edit_count"]},
                after={"status": after["status"], "edit_count": after["edit_count"]})
    sync_service.record_change(
        conn, entity="treatment_record", entity_id=record_id, op="update",
        revision=int(after["revision"]), actor_user_id=int(user["id"]),
        payload={**after, "items": after.get("items")},
    )
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
    # 提交会改 status 与 seq_no，对离线客户端是"重要变更"，必须进日志
    sync_service.record_change(
        conn, entity="treatment_record", entity_id=record_id, op="update",
        revision=int(after["revision"]), actor_user_id=int(user["id"]),
        payload={**after, "items": after.get("items")},
    )
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
        revision=int(after["revision"]), actor_user_id=int(admin["id"]),
        payload={**after, "items": after.get("items")},
    )
    return after


@router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除草稿")
def delete_draft(
    record_id: int,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    from fastapi import Response

    from app.services import sync as sync_service

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
    main_item_id: int | None = None,
    scope: str = Query("visible", description="mine / temp / visible"),
) -> dict[str, Any]:
    """按日期倒序的记录流。

    `scope=temp` 只看"临时治疗"（记录人 ≠ 患者归属人），
    这是治疗师在临时接管他人患者期间需要复查的部分。
    """
    from app.models import dictionary as dictionary_model

    if scope not in {"mine", "temp", "visible"}:
        raise NotFoundError("INVALID_SCOPE", "scope 只能是 mine / temp / visible", details={"scope": scope})

    patient_nos = None if scope == "visible" and is_admin(user) else visibility.visible_patient_numbers(conn, user)
    items, total = treatment_model.list_records(
        conn,
        patient_nos=patient_nos,
        therapist_id=int(user["id"]) if scope == "mine" else None,
        date_from=date_from,
        date_to=date_to,
        limit=page.limit,
        offset=page.offset,
    )

    ids = [int(i["id"]) for i in items]
    main_names: dict[int, list[str]] = {}
    if ids:
        rows = conn.execute(
            "SELECT ri.record_id, m.name FROM record_item ri"
            " JOIN main_item m ON m.id = ri.main_item_id"
            f" WHERE ri.record_id IN ({', '.join('?' for _ in ids)})"
            " GROUP BY ri.record_id, m.id ORDER BY ri.record_id, m.sort",
            ids,
        ).fetchall()
        for row in rows:
            main_names.setdefault(int(row["record_id"]), []).append(str(row["name"]))

    out: list[dict[str, Any]] = []
    for record in items:
        if scope == "temp" and not int(record.get("is_temporary") or 0):
            continue
        if main_item_id is not None:
            names = main_names.get(int(record["id"]), [])
            target = dictionary_model.get_main_item(conn, main_item_id)
            if target is None or target["name"] not in names:
                continue
        enriched = dict(record)
        enriched["main_item_names"] = main_names.get(int(record["id"]), [])
        out.append(enriched)
    return {"items": out, "total": total, "page": page.page, "page_size": page.page_size}


__all__ = ["router", "timeline_router"]
