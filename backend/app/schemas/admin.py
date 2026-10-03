"""汇总、打印、模板与审计的请求/响应模型（阶段 5）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.template import SCOPES


# --------------------------------------------------------------------------- #
# 汇总
# --------------------------------------------------------------------------- #
class TotalsOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    record_count: int = Field(default=0, description="治疗次数（按记录去重）")
    item_count: int = Field(default=0, description="子项目条目数")
    total_duration_min: int = 0
    patient_count: int = 0
    main_item_counts: dict[str, int] = Field(default_factory=dict)
    sub_item_counts: dict[str, int] = Field(default_factory=dict)
    therapist_counts: dict[str, int] = Field(default_factory=dict)


class SummaryRowOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    record_id: int
    record_date: str
    session_period: str | None = None
    patient_no: str
    patient_name: str | None = None
    therapist_id: int | None = None
    therapist_name: str | None = None
    main_item_name: str | None = None
    sub_item_name_snapshot: str | None = None
    params_digest: str = ""
    response_digest: str = ""
    note: str | None = None
    duration_min: int | None = None
    is_temporary: int = 0


class SummaryGroupOut(BaseModel):
    key: str
    totals: TotalsOut
    rows: list[SummaryRowOut] = Field(default_factory=list)


class DateSummaryOut(BaseModel):
    date: str
    group_by: str = Field(description="therapist / patient")
    totals: TotalsOut
    groups: list[SummaryGroupOut] = Field(default_factory=list)


class PatientBriefOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    inpatient_no: str
    name: str
    diagnosis: str | None = None
    admin_note: str | None = None
    status: str | None = None
    assigned_therapist_id: int | None = None
    assigned_therapist_name: str | None = None
    visible_therapist_id: int | None = None


class PatientDailyRowOut(BaseModel):
    record_date: str
    session_periods: list[str] = Field(default_factory=list)
    therapists: list[str] = Field(default_factory=list)
    main_items: list[str] = Field(default_factory=list)
    sub_items: list[str] = Field(default_factory=list)
    params: list[str] = Field(default_factory=list)
    responses: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    duration_min: int = 0
    temporary: bool = False


class PatientDailySummaryOut(BaseModel):
    patient: PatientBriefOut
    date_from: str | None = None
    date_to: str | None = None
    totals: TotalsOut
    days: list[PatientDailyRowOut] = Field(default_factory=list)


class OverviewItemOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    main_item_name: str | None = None
    sub_item_name: str | None = None
    params_digest: str = ""


class OverviewRecordOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    record_no: int
    record_date: str
    session_period: str | None = None
    seq_no: int | None = None
    therapist_name: str | None = None
    is_temporary: bool = False
    duration_min: int | None = None
    note: str | None = None
    response_digest: str = ""
    items: list[OverviewItemOut] = Field(default_factory=list)


class PatientOverviewOut(BaseModel):
    patient: PatientBriefOut
    totals: TotalsOut
    records: list[OverviewRecordOut] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 模板
# --------------------------------------------------------------------------- #
class TemplateItemIn(BaseModel):
    sub_item_id: int
    params: dict[str, Any] = Field(default_factory=dict, description="键为 param_key")
    sort: int | None = None


class TemplateItemOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    template_id: int | None = None
    sub_item_id: int
    params: dict[str, Any] = Field(default_factory=dict)
    sort: int = 0


class TemplateOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    scope: str
    owner_user_id: int | None = None
    main_item_id: int | None = None
    code: str | None = Field(
        default=None,
        description="非空表示这是**种子/标准模板**（身份稳定，可被种子重复导入更新）；"
        "为空表示用户自建模板，种子不会改动它",
    )
    name: str
    sort: int = 0
    status: str = "active"
    items: list[TemplateItemOut] = Field(default_factory=list)


class TemplateCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    scope: str = Field(default="personal", description=" / ".join(SCOPES))
    main_item_id: int = Field(
        description="模板必须归属于某个主项目。"
        "《设计.md》3.10 的例子是「某主项目下常用子项目组合 + 参数默认值」，"
        "且库层把 (scope, owner, main_item_id, name) 作为唯一键 —— "
        "同一治疗师在不同主项目下可以有同名模板。"
    )
    items: list[TemplateItemIn] = Field(default_factory=list, description="只能放该主项目下的子项目")
    sort: int = 0


class TemplateUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    main_item_id: int | None = None
    items: list[TemplateItemIn] | None = None
    sort: int | None = None


class TemplateApplyItemOut(BaseModel):
    main_item_id: int
    sub_item_id: int
    sub_item_name: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class TemplateApplyOut(BaseModel):
    template_id: int
    name: str
    scope: str
    main_item_id: int | None = None
    items: list[TemplateApplyItemOut] = Field(default_factory=list)
    note: str = ""


# --------------------------------------------------------------------------- #
# 审计日志
# --------------------------------------------------------------------------- #
class AuditLogOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    user_id: int | None = None
    user_name: str | None = None
    employee_no: str | None = None
    action: str
    target_type: str
    target_id: str | None = None
    before: Any = None
    after: Any = None
    created_at: str


class AuditLogListOut(BaseModel):
    items: list[AuditLogOut]
    total: int
    page: int
    page_size: int


class AuditFacetsOut(BaseModel):
    actions: list[str] = Field(default_factory=list)
    target_types: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 后台：选项集维护
# --------------------------------------------------------------------------- #
class DeptOptionSetRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    values: list[str] = Field(min_length=1)
    dept_tag: str | None = Field(
        default=None, description="传了就是科室级（dept），不传就是全局（global）"
    )
    default_values: list[str] = Field(default_factory=list)


__all__ = [
    "AuditFacetsOut",
    "AuditLogListOut",
    "AuditLogOut",
    "DateSummaryOut",
    "DeptOptionSetRequest",
    "OverviewItemOut",
    "OverviewRecordOut",
    "PatientBriefOut",
    "PatientDailyRowOut",
    "PatientDailySummaryOut",
    "PatientOverviewOut",
    "SummaryGroupOut",
    "SummaryRowOut",
    "TemplateApplyItemOut",
    "TemplateApplyOut",
    "TemplateCreateRequest",
    "TemplateItemIn",
    "TemplateItemOut",
    "TemplateOut",
    "TemplateUpdateRequest",
    "TotalsOut",
]
