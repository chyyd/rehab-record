"""汇总与打印接口（阶段 5 / `设计.md` 3.8、3.9）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /summary/date | 按日期汇总（可按治疗师/患者分组） |
| GET | /summary/patient/{no} | 按患者每日汇总（SOAP 纯文本） |
| GET | /summary/patient/{no}/overview | 单患者总览（含全部文书与统计） |
| GET | /print/patient/{no} | 单患者汇总 PDF（SOAP 纯文本） |
| GET | /print/summary/date | 按日期汇总 PDF |
| GET | /print/summary/patient/{no} | 按患者每日汇总 PDF |

> 2026-10-05：`/templates`（科室/个人记录模板）整组删除 —— 模板改由
> `templates/*.json` 承载（用户要求"不进数据库"），承载它的
> `record_template` / `record_template_item` 两张表已随迁移 011 删除。

数据级权限与记录一致：先用 `services/visibility` 判断患者是否可见，
**汇总与打印不能成为绕过权限看别人患者的入口**。
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import Depends, Query, Response

from app.api.router import ApiRouter
from app.core.db_dep import get_db
from app.core.errors import ForbiddenError
from app.core.security_deps import CurrentUser
from app.schemas.admin import (
    DateSummaryOut,
    PatientDailySummaryOut,
    PatientOverviewOut,
)
from app.services import pdf as pdf_service
from app.services import summary as summary_service
from app.services import visibility

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
    return summary_service.summarize_date(
        conn,
        day=day,
        group_by=group_by,
        patient_nos=visibility.visible_patient_numbers(conn, user),
    )


@router.get(
    "/summary/patient/{inpatient_no}",
    response_model=PatientDailySummaryOut,
    summary="按患者每日汇总（SOAP 文本）",
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
    summary="单患者总览（含全部文书与统计）",
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


__all__ = ["router"]
