"""汇总、打印与审计的请求/响应模型（阶段 5）。

记录已是 SOAP 纯文本模型（迁移 011），所以汇总行里不再有"主项目 / 子项目 / 参数摘要 /
患者反应摘要 / 时长"这些旧表格字段 —— 汇总与打印都直接输出 `rendered_text`。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# 汇总
# --------------------------------------------------------------------------- #
class TotalsOut(BaseModel):
    """计数口径：**只算 `kind='daily'` 且已提交/已锁定**（评估文书不计治疗次数）。"""

    record_count: int = Field(default=0, description="治疗次数（日常记录，按记录去重）")
    patient_count: int = 0
    therapist_counts: dict[str, int] = Field(default_factory=dict)
    discipline_counts: dict[str, int] = Field(default_factory=dict)


class SummaryRowOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    record_id: int
    record_date: str
    patient_no: str
    patient_name: str | None = None
    therapist_id: int | None = None
    therapist_name: str | None = None
    discipline: str
    discipline_name: str | None = None
    kind: str
    kind_label: str | None = None
    seq_no: int | None = None
    status: str
    note: str | None = None
    rendered_text: str = ""
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


class PatientDailyRecordOut(BaseModel):
    """一天里的一条文书（直接给 `rendered_text`，界面与 PDF 都不再拼表格）。"""

    model_config = ConfigDict(extra="ignore")

    record_id: int
    discipline: str
    discipline_name: str | None = None
    kind: str
    kind_label: str | None = None
    seq_no: int | None = None
    status: str
    therapist_name: str | None = None
    is_temporary: int = 0
    note: str | None = None
    rendered_text: str = ""


class PatientDailyRowOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    record_date: str
    record_count: int = Field(default=0, description="当天的**日常**记录条数（评估文书不计）")
    therapists: list[str] = Field(default_factory=list)
    disciplines: list[str] = Field(default_factory=list)
    temporary: bool = False
    records: list[PatientDailyRecordOut] = Field(default_factory=list)
    texts: list[str] = Field(default_factory=list, description="当天各条文书的 SOAP 纯文本（按时间顺序）")


class PatientDailySummaryOut(BaseModel):
    patient: PatientBriefOut
    date_from: str | None = None
    date_to: str | None = None
    totals: TotalsOut
    days: list[PatientDailyRowOut] = Field(default_factory=list)


class OverviewRecordOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    record_no: int
    record_id: int
    record_date: str
    discipline: str
    discipline_name: str | None = None
    kind: str
    kind_label: str | None = None
    seq_no: int | None = None
    status: str
    therapist_name: str | None = None
    is_temporary: bool = False
    note: str | None = None
    rendered_text: str = ""


class PatientOverviewOut(BaseModel):
    patient: PatientBriefOut
    totals: TotalsOut
    records: list[OverviewRecordOut] = Field(default_factory=list)


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


__all__ = [
    "AuditFacetsOut",
    "AuditLogListOut",
    "AuditLogOut",
    "DateSummaryOut",
    "OverviewRecordOut",
    "PatientBriefOut",
    "PatientDailyRecordOut",
    "PatientDailyRowOut",
    "PatientDailySummaryOut",
    "PatientOverviewOut",
    "SummaryGroupOut",
    "SummaryRowOut",
    "TotalsOut",
]
