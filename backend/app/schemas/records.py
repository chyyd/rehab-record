"""字典、选项集、患者反应与治疗记录的请求/响应模型（阶段 3）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.treatment import PERIODS, STATUSES


# --------------------------------------------------------------------------- #
# 字典
# --------------------------------------------------------------------------- #
class ParamDefOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    sub_item_id: int
    param_key: str
    param_name: str
    input_type: str
    options: list[str] = Field(default_factory=list)
    default_value: str | None = None
    required: int = 0
    unit: str | None = None
    sort: int = 0
    # 表单组装时补充的字段（纯字典查询时为空）
    options_resolved: dict[str, Any] | None = None
    current_value: Any = None
    value_source: str | None = Field(default=None, description="last_value / option_set_default / dict_default / none")
    last_value: Any = None


class SubItemOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    main_item_id: int
    name: str
    code: str | None = None
    alias: str | None = None
    sort: int = 0
    params: list[ParamDefOut] = Field(default_factory=list)


class MainItemOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    code: str | None = None
    alias: str | None = None
    sort: int = 0
    sub_items: list[SubItemOut] = Field(default_factory=list)


class ResponseDefOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    main_item_id: int | None = None
    code: str
    label: str
    value_type: str = Field(description="tag / number / select / text")
    value_key: str | None = None
    value_unit: str | None = None
    value_min: float | None = None
    value_max: float | None = None
    options: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 选项集
# --------------------------------------------------------------------------- #
class OptionItemOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    value: str
    label: str
    is_default: int = 0
    sort: int = 0


class OptionSetOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    scope: str
    owner_user_id: int | None = None
    dept_tag: str | None = None
    code: str
    name: str
    alias: str | None = None
    items: list[OptionItemOut] = Field(default_factory=list)


class ResolvedOptionsOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    source: str = Field(description="personal / dept / global / builtin")
    option_set_id: int | None = None
    option_set_name: str | None = None
    options: list[dict[str, str]] = Field(default_factory=list)
    defaults: list[str] = Field(default_factory=list)


class PersonalOptionSetRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    values: list[str] = Field(min_length=1, description="选项值列表")
    default_values: list[str] = Field(default_factory=list, description="默认值，必须来自 values")


# --------------------------------------------------------------------------- #
# 记录表单
# --------------------------------------------------------------------------- #
class RecordFormPatientOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    inpatient_no: str
    name: str
    diagnosis: str | None = None
    admin_note: str | None = None
    status: str
    visible_therapist_id: int | None = None


class RecordFormOut(BaseModel):
    patient: RecordFormPatientOut
    main_items: list[MainItemOut]
    response_defs: list[ResponseDefOut]
    last_completed_seq_no: int = Field(description="该患者已完成治疗次数，本次为第 seq+1 次")
    reference_date: str | None = None


# --------------------------------------------------------------------------- #
# 治疗记录
# --------------------------------------------------------------------------- #
class RecordItemIn(BaseModel):
    main_item_id: int
    sub_item_id: int
    params: dict[str, Any] = Field(default_factory=dict, description="键为 param_key")


class RecordItemOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    main_item_id: int
    sub_item_id: int
    sub_item_name_snapshot: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    params_snapshot: list[dict[str, Any]] | None = None
    sort: int = 0


class RecordOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    appointment_id: int | None = None
    patient_no: str
    patient_name: str | None = None
    therapist_id: int
    therapist_name: str | None = None
    original_therapist_id: int | None = None
    is_temporary: int = 0
    record_date: str
    session_period: str | None = None
    seq_no: int | None = Field(default=None, description="该患者第几次治疗")
    duration_min: int | None = None
    patient_response: dict[str, Any] | None = None
    note: str | None = None
    status: str
    edit_count: int = 0
    locked_at: str | None = None
    created_at: str | None = None
    submitted_at: str | None = None
    revision: int = 1
    items: list[RecordItemOut] = Field(default_factory=list)


class RecordListItemOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    patient_no: str
    patient_name: str | None = None
    therapist_id: int
    therapist_name: str | None = None
    record_date: str
    session_period: str | None = None
    seq_no: int | None = None
    status: str
    edit_count: int = 0
    item_count: int = 0


class RecordListOut(BaseModel):
    items: list[RecordListItemOut]
    total: int
    page: int
    page_size: int


class RecordCreateRequest(BaseModel):
    patient_no: str = Field(min_length=1)
    record_date: str | None = Field(default=None, description="不传则由排期或当天推导")
    session_period: str | None = Field(default=None, description=" / ".join(PERIODS))
    appointment_id: int | None = Field(default=None, description="从排期进入时传入，自动带入日期与半日")
    duration_min: int | None = Field(default=None, ge=0)
    note: str | None = None
    patient_response: dict[str, Any] | None = Field(
        default=None, description='{"tags": ["no_discomfort"], "items": [{"code": "pain", "value": 3}]}'
    )
    items: list[RecordItemIn] = Field(default_factory=list)
    status: str = Field(default="draft", description=" / ".join(STATUSES))
    therapist_id: int | None = Field(default=None, description="不传则为当前用户（管理员可代录）")


class RecordUpdateRequest(BaseModel):
    record_date: str | None = None
    session_period: str | None = None
    duration_min: int | None = Field(default=None, ge=0)
    note: str | None = None
    patient_response: dict[str, Any] | None = None
    clear_patient_response: bool = Field(default=False, description="显式清空患者反应")
    items: list[RecordItemIn] | None = Field(default=None, description="传了就整体替换明细")


class TimelineItemOut(RecordListItemOut):
    main_item_names: list[str] = Field(default_factory=list)


class TimelineOut(BaseModel):
    items: list[TimelineItemOut]
    total: int
    page: int
    page_size: int


class RecordEnumsOut(BaseModel):
    statuses: list[str] = Field(default_factory=lambda: list(STATUSES))
    periods: list[str] = Field(default_factory=lambda: list(PERIODS))


__all__ = [
    "MainItemOut",
    "OptionItemOut",
    "OptionSetOut",
    "ParamDefOut",
    "PersonalOptionSetRequest",
    "RecordCreateRequest",
    "RecordEnumsOut",
    "RecordFormOut",
    "RecordFormPatientOut",
    "RecordItemIn",
    "RecordItemOut",
    "RecordListOut",
    "RecordListItemOut",
    "RecordOut",
    "RecordUpdateRequest",
    "ResolvedOptionsOut",
    "ResponseDefOut",
    "SubItemOut",
    "TimelineItemOut",
    "TimelineOut",
]
