"""领域模型与数据访问层。

分层约定（依赖方向只能向下）：
    api（路由） → services（业务规则唯一落点） → models / core
"""

from app.models.base import DomainError, entity_to_dict, row_to_dict

__all__ = ["DomainError", "entity_to_dict", "row_to_dict"]
