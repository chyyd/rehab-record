"""患者相关的请求/响应模型（阶段 1）。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.patient import PATIENT_STATUSES

SCOPE_DESCRIPTION = (
    "mine（可见归属是我）/ unassigned（无人负责）/ "
    "temp（与我有关的临时指派）/ visible（可见全部）/ all（仅管理员）"
)


class PatientOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    inpatient_no: str
    name: str
    diagnosis: str | None = None
    admin_note: str | None = None
    assigned_therapist_id: int | None = Field(
        default=None, description="原归属。单日假期间不变；多日假排空后为 NULL"
    )
    visible_therapist_id: int | None = Field(
        default=None, description="可见归属（当前实际谁负责），由 visible_therapist 规则解析"
    )
    visibility_state: str = Field(
        default="assigned", description="assigned / temp_released / temp_claimed"
    )
    status: str
    created_at: str | None = None
    updated_at: str | None = None
    revision: int = 1
    temp_assignment_id: int | None = None
    temp_therapist_id: int | None = None
    temp_original_therapist_id: int | None = None
    temp_expires_at: str | None = None


class PatientCreateRequest(BaseModel):
    inpatient_no: str = Field(min_length=1, max_length=64, description="住院编号")
    name: str = Field(min_length=1, max_length=64)
    diagnosis: str | None = None
    admin_note: str | None = Field(default=None, description="注意事项，仅管理员可写")
    assigned_therapist_id: int | None = None
    status: str = Field(default="in_hospital", description=" / ".join(PATIENT_STATUSES))


class PatientUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    diagnosis: str | None = None
    admin_note: str | None = None
    status: str | None = Field(default=None, description=" / ".join(PATIENT_STATUSES))


class AssignRequest(BaseModel):
    therapist_id: int | None = Field(default=None, description="传 null 表示清除归属")


class PatientListOut(BaseModel):
    items: list[PatientOut]
    total: int
    page: int
    page_size: int
    scope: str


class AssignmentHistoryOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    patient_no: str
    from_therapist_id: int | None = None
    to_therapist_id: int | None = None
    change_type: str
    operator_user_id: int | None = None
    created_at: str


__all__ = [
    "SCOPE_DESCRIPTION",
    "AssignRequest",
    "AssignmentHistoryOut",
    "PatientCreateRequest",
    "PatientListOut",
    "PatientOut",
    "PatientUpdateRequest",
]
