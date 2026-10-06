"""治疗记录的请求/响应模型（SOAP 模板驱动）。

模板本身**不在数据库里**，而是在 `templates/*.json`（用户要求"不进数据库，以便以后我手动修改"），
所以这里不再有字典 / 选项集 / 患者反应 / 科室模板相关的模型 —— 那些表已随迁移 011/012 删除。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.treatment import KINDS, STATUSES


# --------------------------------------------------------------------------- #
# 记录表单（GET /records/form）
# --------------------------------------------------------------------------- #
class RecordFormPatientOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    inpatient_no: str
    name: str
    status: str


class OptionUsageItemOut(BaseModel):
    """一个选项被用过的次数。"""

    value: str
    count: int


class OptionUsageOut(BaseModel):
    """多选字段的选项使用排行（2026-10-06）。

    App 用它把「最常用的 N 项」置顶、其余折叠 ——
    用户：「58项太多了，能不能将所有人最常用的10个放在前面，后面的可以折叠」。
    """

    model_config = ConfigDict(extra="ignore")

    discipline: str
    field: str
    items: list[OptionUsageItemOut] = Field(default_factory=list)


class RecordFormOut(BaseModel):
    """App 渲染一次录入所需的全部信息（详见 `services/records.py::build_form`）。"""

    model_config = ConfigDict(extra="ignore")

    patient: RecordFormPatientOut
    discipline: str
    discipline_name: str
    kind: str = Field(description="本次要填的形态：缺评估文书时它就是那份评估文书")
    kind_label: str
    title: str
    next_seq: int = Field(description="这次是第几次日常（评估文书不占次数）")
    total_daily: int
    # ★ 2026-10-06：复评周期改成 30 个自然日，所以对外报的是**天**而不是次数。
    #   原来的 `sessions_until_reassessment`（"还差 N 次"）已删除 ——
    #   次数不再是复评的判据，继续返回它只会让界面显示一个误导人的数字。
    days_until_reassessment: int | None = Field(
        default=None,
        description="距复评应做日还有几天；负数=已逾期；null=该大类还没有评估，无从计算",
    )
    reassessment_due: str | None = Field(
        default=None, description="复评应做日（上次评估日 + 30 天）；null=还没评估过"
    )
    reassessment_interval_days: int = Field(
        default=30, description="复评周期（自然日），随模板/规则版本变化"
    )
    pending_document: str | None = Field(default=None, description="还缺哪份评估文书（先弹它）")
    pending_document_label: str | None = None
    template_version: int = 1
    soap: list[dict[str, Any]] = Field(default_factory=list, description="四段字段定义，直接渲染")
    frequent_options: dict[str, list[str]] = Field(
        default_factory=dict,
        description=(
            "最常用选项：字段名 → 按使用次数倒序的取值。"
            "App 用它把长列表的前 N 项置顶、其余折叠（2026-10-06）"
        ),
    )
    prefill: dict[str, Any] = Field(default_factory=dict)
    prefill_source: dict[str, str] = Field(default_factory=dict)
    footer: list[str] = Field(default_factory=list)
    existing: RecordOut | None = Field(default=None, description="已存在的那条，用于继续编辑")


# --------------------------------------------------------------------------- #
# 治疗记录
# --------------------------------------------------------------------------- #
class RecordOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    patient_no: str
    patient_name: str | None = None
    therapist_id: int
    therapist_name: str | None = None

    # 查询时推导（记录人 ≠ 该患者当时的归属人），**不是存储列**——
    # 存一份就会与事实不一致。见 app/models/treatment.py::temporary_expr。
    is_temporary: int = 0
    record_date: str
    discipline: str
    discipline_name: str | None = None
    kind: str
    kind_label: str | None = None
    seq_no: int | None = Field(default=None, description="第几次日常；只有 daily 有")
    body: dict[str, Any] = Field(default_factory=dict, description="{field_key: value}")
    rendered_text: str = Field(default="", description="生成时冻结的 SOAP 纯文本")
    note: str | None = None
    status: str
    edit_count: int = 0
    locked_at: str | None = None
    created_at: str | None = None
    submitted_at: str | None = None
    updated_at: str | None = None
    revision: int = 1
    client_uuid: str | None = None


class RecordListItemOut(BaseModel):
    """列表项：`rendered_text` 给全文，`rendered_excerpt` 给列表里的一行摘要。"""

    model_config = ConfigDict(extra="ignore")

    id: int
    patient_no: str
    patient_name: str | None = None
    therapist_id: int
    therapist_name: str | None = None
    is_temporary: int = 0
    record_date: str
    discipline: str
    discipline_name: str | None = None
    kind: str
    kind_label: str | None = None
    seq_no: int | None = None
    status: str
    edit_count: int = 0
    rendered_text: str = ""
    rendered_excerpt: str = ""


class RecordListOut(BaseModel):
    items: list[RecordListItemOut]
    total: int
    page: int
    page_size: int


class RecordCreateRequest(BaseModel):
    patient_no: str = Field(min_length=1)
    record_date: str | None = Field(default=None, description="不传则用当天")
    discipline: str = Field(description="PT / OT / ST_SW / ST_SP")
    kind: str = Field(description=" / ".join(KINDS))
    body: dict[str, Any] = Field(default_factory=dict, description="{field_key: value}")
    status: str = Field(default="draft", description=" / ".join(STATUSES))
    note: str | None = None
    client_uuid: str | None = Field(default=None, description="离线幂等标识（可选）")
    therapist_id: int | None = Field(default=None, description="不传则为当前用户（管理员可代录）")


class RecordUpdateRequest(BaseModel):
    body: dict[str, Any] | None = Field(default=None, description="传了就整体替换答案并重新渲染")
    status: str | None = Field(default=None, description="只允许向前：draft → submitted → locked")
    record_date: str | None = None
    note: str | None = None


class TimelineItemOut(RecordListItemOut):
    pass


class TimelineOut(BaseModel):
    items: list[TimelineItemOut]
    total: int
    page: int
    page_size: int


class RecordEnumsOut(BaseModel):
    statuses: list[str] = Field(default_factory=lambda: list(STATUSES))
    kinds: list[str] = Field(default_factory=lambda: list(KINDS))
    disciplines: list[dict[str, Any]] = Field(default_factory=list)


RecordFormOut.model_rebuild()

__all__ = [
    "KINDS",
    "RecordCreateRequest",
    "RecordEnumsOut",
    "RecordFormOut",
    "RecordFormPatientOut",
    "RecordListOut",
    "RecordListItemOut",
    "RecordOut",
    "RecordUpdateRequest",
    "TimelineItemOut",
    "TimelineOut",
]
