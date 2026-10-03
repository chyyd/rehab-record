"""汇总、打印与模板接口（阶段 5 / `设计.md` 3.8、3.9、3.10）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /summary/date | 按日期汇总（可按治疗师/患者分组） |
| GET | /summary/patient/{no} | 按患者每日汇总 |
| GET | /summary/patient/{no}/overview | 单患者总览（含全部记录与统计） |
| GET | /print/patient/{no} | 单患者汇总 PDF |
| GET | /print/summary/date | 按日期汇总 PDF |
| GET | /print/summary/patient/{no} | 按患者每日汇总 PDF |
| GET/POST/PUT/DELETE | /templates | 记录模板（科室模板管理员维护，个人模板本人维护） |

数据级权限与记录一致：先用 `services/visibility` 判断患者是否可见，
**汇总与打印不能成为绕过权限看别人患者的入口**。
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import Depends, Query, Response, status

from app.api.router import ApiRouter
from app.core.db_dep import get_db
from app.core.errors import ForbiddenError
from app.core.security_deps import CurrentUser, is_admin
from app.models import template as template_model
from app.schemas.admin import (
    DateSummaryOut,
    PatientDailySummaryOut,
    PatientOverviewOut,
    TemplateApplyOut,
    TemplateCreateRequest,
    TemplateOut,
    TemplateUpdateRequest,
)
from app.services import pdf as pdf_service
from app.services import summary as summary_service
from app.services import visibility
from app.services.audit import write_audit

router = ApiRouter(tags=["汇总与打印"])


def _require_patient_visible(conn: sqlite3.Connection, user: dict[str, Any], patient_no: str) -> None:
    if not visibility.can_view_patient(conn, user, patient_no):
        raise ForbiddenError("PATIENT_NOT_VISIBLE", "无权访问该患者", details={"inpatient_no": patient_no})


def _pdf_response(content: bytes, filename: str) -> Response:
    """PDF 响应：**明确声明 Content-Disposition**，否则安卓端下载后没有可读文件名。"""
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


# --------------------------------------------------------------------------- #
# 汇总（JSON）
# --------------------------------------------------------------------------- #
@router.get("/summary/date", response_model=DateSummaryOut, summary="按日期汇总")
def summary_date(
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    day: Annotated[str, Query(alias="date", description="YYYY-MM-DD")],
    group_by: Annotated[str, Query(description="therapist / patient")] = "therapist",
) -> dict[str, Any]:
    data = summary_service.summarize_date(
        conn,
        day=day,
        group_by=group_by,
        patient_nos=visibility.visible_patient_numbers(conn, user),
    )
    return data


@router.get(
    "/summary/patient/{inpatient_no}",
    response_model=PatientDailySummaryOut,
    summary="按患者每日汇总",
)
def summary_patient_daily(
    inpatient_no: str,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    date_from: Annotated[str | None, Query(alias="from")] = None,
    date_to: Annotated[str | None, Query(alias="to")] = None,
) -> dict[str, Any]:
    _require_patient_visible(conn, user, inpatient_no)
    return summary_service.summarize_patient_daily(
        conn, patient_no=inpatient_no, date_from=date_from, date_to=date_to
    )


@router.get(
    "/summary/patient/{inpatient_no}/overview",
    response_model=PatientOverviewOut,
    summary="单患者总览（含全部记录与统计）",
)
def summary_patient_overview(
    inpatient_no: str,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    _require_patient_visible(conn, user, inpatient_no)
    return summary_service.patient_overview(conn, patient_no=inpatient_no)


# --------------------------------------------------------------------------- #
# 打印（PDF）
# --------------------------------------------------------------------------- #
@router.get("/print/patient/{inpatient_no}", summary="单患者汇总 PDF")
def print_patient(
    inpatient_no: str,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> Response:
    _require_patient_visible(conn, user, inpatient_no)
    overview = summary_service.patient_overview(conn, patient_no=inpatient_no)
    return _pdf_response(
        pdf_service.patient_summary_pdf(overview), f"patient-{inpatient_no}.pdf"
    )


@router.get("/print/summary/date", summary="按日期汇总 PDF")
def print_date_summary(
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    day: Annotated[str, Query(alias="date", description="YYYY-MM-DD")],
    group_by: Annotated[str, Query(description="therapist / patient")] = "therapist",
) -> Response:
    data = summary_service.summarize_date(
        conn,
        day=day,
        group_by=group_by,
        patient_nos=visibility.visible_patient_numbers(conn, user),
    )
    return _pdf_response(pdf_service.date_summary_pdf(data), f"summary-{day}.pdf")


@router.get("/print/summary/patient/{inpatient_no}", summary="按患者每日汇总 PDF")
def print_patient_daily(
    inpatient_no: str,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    date_from: Annotated[str | None, Query(alias="from")] = None,
    date_to: Annotated[str | None, Query(alias="to")] = None,
) -> Response:
    _require_patient_visible(conn, user, inpatient_no)
    daily = summary_service.summarize_patient_daily(
        conn, patient_no=inpatient_no, date_from=date_from, date_to=date_to
    )
    return _pdf_response(
        pdf_service.patient_daily_pdf(daily), f"patient-daily-{inpatient_no}.pdf"
    )


# --------------------------------------------------------------------------- #
# 模板
# --------------------------------------------------------------------------- #
@router.get("/templates", response_model=list[TemplateOut], summary="模板列表（科室 + 我的）")
def list_templates(
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    main_item_id: int | None = None,
) -> list[dict[str, Any]]:
    return template_model.list_templates(
        conn, owner_user_id=int(user["id"]), main_item_id=main_item_id
    )


@router.post(
    "/templates",
    response_model=TemplateOut,
    status_code=status.HTTP_201_CREATED,
    summary="新建模板",
)
def create_template(
    payload: TemplateCreateRequest,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    """新建模板。

    - `scope='dept'` 需要管理员（科室模板是全科共享资产）；
    - `scope='personal'` 自动归属当前用户，**传别人的 owner 没有意义也不会被采纳**。
    """
    if payload.scope == "dept" and not is_admin(user):
        raise ForbiddenError("DEPT_TEMPLATE_ADMIN_ONLY", "科室模板只能由管理员创建")
    owner = None if payload.scope == "dept" else int(user["id"])
    created = template_model.create_template(
        conn,
        scope=payload.scope,
        name=payload.name,
        owner_user_id=owner,
        main_item_id=payload.main_item_id,
        items=[item.model_dump() for item in payload.items],
        sort=payload.sort,
    )
    write_audit(conn, user_id=int(user["id"]), action="create", target_type="record_template",
                target_id=str(created["id"]), after={"name": created["name"], "scope": created["scope"]})
    return created


@router.get("/templates/{template_id}", response_model=TemplateOut, summary="模板详情")
def get_template(
    template_id: int,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    template = template_model.get_template_or_raise(conn, template_id)
    _assert_template_visible(template, user)
    return template


@router.post("/templates/{template_id}/apply", response_model=TemplateApplyOut, summary="一键套用")
def apply_template(
    template_id: int,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    """返回可直接填进记录表单的明细。**只是预填，不锁定内容**（`设计.md` 3.10）。"""
    template = template_model.get_template_or_raise(conn, template_id)
    _assert_template_visible(template, user)
    return template_model.apply_template(conn, template_id)


@router.put("/templates/{template_id}", response_model=TemplateOut, summary="修改模板")
def update_template(
    template_id: int,
    payload: TemplateUpdateRequest,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    updated = template_model.update_template(
        conn,
        template_id,
        user_id=int(user["id"]),
        is_admin=is_admin(user),
        name=payload.name,
        main_item_id=payload.main_item_id,
        items=None if payload.items is None else [item.model_dump() for item in payload.items],
        sort=payload.sort,
    )
    write_audit(conn, user_id=int(user["id"]), action="update", target_type="record_template",
                target_id=str(template_id), after={"name": updated["name"]})
    return updated


@router.delete(
    "/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="删除模板",
)
def delete_template(
    template_id: int,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> Response:
    template_model.delete_template(
        conn, template_id, user_id=int(user["id"]), is_admin=is_admin(user)
    )
    write_audit(conn, user_id=int(user["id"]), action="delete", target_type="record_template",
                target_id=str(template_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _assert_template_visible(template: dict[str, Any], user: dict[str, Any]) -> None:
    """科室模板人人可见；个人模板只有本人可见（管理员也不看别人的私人模板）。"""
    if template["scope"] == "dept":
        return
    if template["owner_user_id"] is not None and int(template["owner_user_id"]) == int(user["id"]):
        return
    raise ForbiddenError(
        "TEMPLATE_NOT_VISIBLE", "个人模板仅本人可见", details={"template_id": template["id"]}
    )


__all__ = ["router"]
