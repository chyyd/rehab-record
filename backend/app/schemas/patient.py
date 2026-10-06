"""患者相关的请求/响应模型（阶段 1）。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.patient import PATIENT_STATUSES

SCOPE_DESCRIPTION = (
    "dept（科室白板：在院+暂停，治疗师默认）/ mine（归属是我）/ "
    "unassigned（归属为空 = 无人负责）/ "
    "visible（dept 的同义兼容值）/ all（全表含已出院，仅管理员）"
)


class PatientOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    inpatient_no: str
    name: str
    diagnosis: str | None = None
    admin_note: str | None = None
    assigned_therapist_id: int | None = Field(
        default=None, description="归属治疗师（可见归属恒等于它）；放弃或批量排空后为 NULL"
    )
    assigned_therapist_name: str | None = Field(
        default=None,
        description=(
            "归属治疗师的姓名（服务端解析）。客户端要显示**姓名**而不是"
            "『治疗师 #2』这种原始 id —— 2026-10-05 加。未分配时为 null。"
        ),
    )
    visible_therapist_id: int | None = Field(
        default=None, description="可见归属，2026-10-05 起直接等于 assigned_therapist_id"
    )
    status: str
    created_at: str | None = None
    updated_at: str | None = None
    revision: int = 1


class PatientCreateRequest(BaseModel):
    inpatient_no: str = Field(min_length=1, max_length=64, description="住院编号")
    name: str = Field(min_length=1, max_length=64)
    diagnosis: str | None = None
    # ★ 2026-10-06：原说明是"仅管理员可写"，权限放开给所有治疗师（见 api/v1/patients.py）。
    admin_note: str | None = Field(default=None, description="注意事项，任何治疗师可写")
    assigned_therapist_id: int | None = None
    status: str = Field(default="in_hospital", description=" / ".join(PATIENT_STATUSES))


class PatientUpdateRequest(BaseModel):
    """修改患者。**字段级语义**：`None` = 不改（而不是"清空"）。"""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    diagnosis: str | None = None
    admin_note: str | None = None
    status: str | None = Field(default=None, description=" / ".join(PATIENT_STATUSES))


class AssignRequest(BaseModel):
    therapist_id: int | None = Field(default=None, description="传 null 表示清除归属")


class DischargeRequest(BaseModel):
    """发起出院（用户 2026-10-05：任何治疗师都能做）。

    必须带上**该患者已提交的出院小结**的 `record_id` —— 出院不是点一下按钮，
    而是"这份小结写完了"，所以请求体里必须有那份文书。
    """

    record_id: int = Field(description="该患者已提交的出院小结记录 id")


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
    "DischargeRequest",
    "PatientCreateRequest",
    "PatientListOut",
    "PatientOut",
    "PatientUpdateRequest",
]
