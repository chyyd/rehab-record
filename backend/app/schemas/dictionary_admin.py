"""字典管理的请求/响应模型（后台"字典管理"模块 / `开发计划.md` 4.5）。

列名与库表严格对应（`sub_item_param_def` **没有** `value_min`/`value_max`/`status`，
它们属于 `response_def`，见 `设计.md` 4.1）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.dictionary_admin import INPUT_TYPES

INPUT_TYPE_DESC = " / ".join(INPUT_TYPES)


# --------------------------------------------------------------------------- #
# 主项目
# --------------------------------------------------------------------------- #
class MainItemAdminOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    code: str
    alias: str | None = None
    sort: int = 0
    status: str = "active"


class MainItemCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=1, max_length=64, description="业务键，唯一，历史数据靠它关联")
    alias: str | None = Field(default=None, max_length=64)
    sort: int = 0


class MainItemUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    code: str | None = Field(default=None, min_length=1, max_length=64)
    alias: str | None = None
    sort: int | None = None
    status: str | None = Field(default=None, description="active / disabled")


class DeleteResultOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    deleted: bool = Field(description="是否物理删除")
    soft_deleted: bool = Field(default=False, description="为 true 时表示改为停用而未删除")
    reason: str | None = Field(default=None, description="软删时说明原因")
    name: str | None = None
    code: str | None = None
    status: str | None = None


# --------------------------------------------------------------------------- #
# 子项目
# --------------------------------------------------------------------------- #
class SubItemAdminOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    main_item_id: int
    name: str
    code: str
    alias: str | None = None
    sort: int = 0
    status: str = "active"


class SubItemCreateRequest(BaseModel):
    main_item_id: int
    name: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=1, max_length=64)
    alias: str | None = Field(default=None, max_length=64)
    sort: int = 0


class SubItemUpdateRequest(BaseModel):
    main_item_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=64)
    code: str | None = Field(default=None, min_length=1, max_length=64)
    alias: str | None = None
    sort: int | None = None
    status: str | None = Field(default=None, description="active / disabled")


# --------------------------------------------------------------------------- #
# 参数定义
# --------------------------------------------------------------------------- #
class ParamAdminOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    sub_item_id: int
    param_key: str
    param_name: str
    input_type: str
    options: list[str] = Field(default_factory=list)
    default_value: str | None = Field(
        default=None,
        description="存储形式：选择题为 JSON 数组（单选也是长度 1），数字/文本为裸字符串",
    )
    required: int = 0
    unit: str | None = None
    sort: int = 0


class ParamCreateRequest(BaseModel):
    param_key: str = Field(min_length=1, max_length=64, description="JSON 参数以此作键，子项目内唯一")
    param_name: str = Field(min_length=1, max_length=64)
    input_type: str = Field(description=INPUT_TYPE_DESC)
    options: list[str] = Field(default_factory=list, description="仅选择题使用")
    default_value: Any = Field(
        default=None,
        description="选择题可传数组（单选传长度 1 的数组或裸值），数字型传数字",
    )
    required: int = Field(default=0, description="0 / 1")
    unit: str | None = Field(default=None, max_length=16)
    sort: int = 0


class ParamUpdateRequest(BaseModel):
    """PUT 为整体替换语义：未传的字段按"不修改"处理，`default_value` 传 null 表示清空默认值。"""

    param_key: str | None = Field(default=None, min_length=1, max_length=64)
    param_name: str | None = Field(default=None, min_length=1, max_length=64)
    input_type: str | None = Field(default=None, description=INPUT_TYPE_DESC)
    options: list[str] | None = None
    default_value: Any = None
    required: int | None = None
    unit: str | None = None
    sort: int | None = None


__all__ = [
    "DeleteResultOut",
    "MainItemAdminOut",
    "MainItemCreateRequest",
    "MainItemUpdateRequest",
    "ParamAdminOut",
    "ParamCreateRequest",
    "ParamUpdateRequest",
    "SubItemAdminOut",
    "SubItemCreateRequest",
    "SubItemUpdateRequest",
]
