"""排期、休息与请假的请求/响应模型（阶段 2）。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.appointment import ALL_STATUSES
from app.models.leave import LEAVE_TYPES, SOURCES
from app.models.rest_block import SCOPES

DATE_DESC = "YYYY-MM-DD"
PERIOD_DESC = "am（上午）/ pm（下午）"


class AppointmentOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    patient_no: str
    therapist_id: int
    date: str
    period: str
    start_time: str | None = None
    end_time: str | None = None
    slot_label: str | None = None
    status: str
    note: str | None = None
    revision: int = 1
    patient_name: str | None = None
    therapist_name: str | None = None


class AppointmentCreateRequest(BaseModel):
    patient_no: str = Field(min_length=1)
    date: str = Field(description=DATE_DESC)
    period: str = Field(description=PERIOD_DESC)
    therapist_id: int | None = Field(
        default=None, description="不传则默认排给当前登录的治疗师"
    )
    start_time: str | None = Field(default=None, description="可选，仅用于同日多台排序，不参与冲突判定")
    end_time: str | None = None
    slot_label: str | None = Field(default=None, description="可选展示标签，如「上午第1台」")
    note: str | None = None


class AppointmentUpdateRequest(BaseModel):
    patient_no: str | None = None
    date: str | None = Field(default=None, description=DATE_DESC)
    period: str | None = Field(default=None, description=PERIOD_DESC)
    therapist_id: int | None = None
    status: str | None = Field(default=None, description=" / ".join(ALL_STATUSES))
    start_time: str | None = None
    end_time: str | None = None
    note: str | None = None


class ConflictOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rule: str
    message: str
    appointment_id: int | None = None
    patient_no: str | None = None
    therapist_id: int | None = None


class AvailabilitySlotOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: str
    period: str
    available: bool
    reasons: list[str]
    patient_no: str | None = None
    patient_name: str | None = None
    status: str | None = None


class CopyScheduleRequest(BaseModel):
    mode: str = Field(default="yesterday", description="yesterday / last_week")
    therapist_id: int | None = Field(default=None, description="不传则为当前用户")
    target_date: str | None = Field(default=None, description="目标日期，默认今天")


class RestBlockOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    therapist_id: int
    scope: str
    weekday: int | None = None
    specific_date: str | None = None
    period: str
    note: str | None = None


class RestBlockCreateRequest(BaseModel):
    scope: str = Field(description=" / ".join(SCOPES))
    period: str = Field(description=PERIOD_DESC)
    weekday: int | None = Field(default=None, ge=0, le=6, description="0=周一 … 6=周日，scope=weekly 时必填")
    specific_date: str | None = Field(default=None, description="scope=date 时必填")
    therapist_id: int | None = Field(default=None, description="不传则为当前用户")
    note: str | None = None


class RestBlockUpdateRequest(BaseModel):
    scope: str | None = None
    period: str | None = None
    weekday: int | None = Field(default=None, ge=0, le=6)
    specific_date: str | None = None
    note: str | None = None


class LeaveOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    therapist_id: int
    start_date: str
    end_date: str
    leave_type: str
    period: str | None = None
    source: str
    status: str
    reason: str | None = None
    recorded_at: str
    applied_at: str | None = None
    cancelled_at: str | None = None
    therapist_name: str | None = None
    created_by_name: str | None = None


class LeaveCreateRequest(BaseModel):
    leave_type: str = Field(description=" / ".join(LEAVE_TYPES))
    start_date: str = Field(description=DATE_DESC)
    end_date: str | None = Field(default=None, description="不传则等于 start_date")
    period: str | None = None
    reason: str | None = None
    therapist_id: int | None = Field(
        default=None, description="仅管理员代录时可指定他人；治疗师只能给自己请假"
    )


class LeaveCancelRequest(BaseModel):
    cancel_reason: str | None = None


class LeaveCancelResult(LeaveOut):
    restored: list[str] = Field(default_factory=list, description="已恢复归属的患者")
    not_restored: list[str] = Field(default_factory=list, description="已被他人认领、未自动恢复的患者")


class CopyScheduleResult(BaseModel):
    created: list[AppointmentOut] = Field(default_factory=list)
    skipped: list[dict] = Field(default_factory=list, description="因冲突或已存在而跳过的格子")
    source_date: str
    target_date: str


class ScheduleEnumsOut(BaseModel):
    """暴露允许的枚举值，前端可据此渲染下拉框，避免各处硬编码。"""

    appointment_statuses: list[str] = Field(default_factory=lambda: list(ALL_STATUSES))
    leave_types: list[str] = Field(default_factory=lambda: list(LEAVE_TYPES))
    leave_sources: list[str] = Field(default_factory=lambda: list(SOURCES))
    rest_block_scopes: list[str] = Field(default_factory=lambda: list(SCOPES))


__all__ = [
    "AppointmentCreateRequest",
    "AppointmentOut",
    "AppointmentUpdateRequest",
    "AvailabilitySlotOut",
    "ConflictOut",
    "CopyScheduleRequest",
    "CopyScheduleResult",
    "LeaveCancelRequest",
    "LeaveCancelResult",
    "LeaveCreateRequest",
    "LeaveOut",
    "RestBlockCreateRequest",
    "RestBlockOut",
    "RestBlockUpdateRequest",
    "ScheduleEnumsOut",
]
