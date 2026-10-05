"""项目统一的 APIRouter。

**为什么需要它**：FastAPI 在 `status_code=204` 时断言路由**不能有响应体**，
否则在**导入路由模块时**就抛 ``AssertionError: Status code 204 must not have a response body``。

触发条件很反直觉：断言检查的是 ``self.response_model`` 是否为真值，
而 FastAPI 会从返回注解推断响应模型 —— 注解写成 ``-> None`` 时，
推断出的是 ``NoneType`` **类本身**，它在布尔判断里是**真**的，于是断言失败。
（也就是说，即使你的函数什么都不返回，只要注解是 `-> None` 且没显式给 `response_model`，204 就不成立。）

这个坑在本项目踩了四次（logout / password / reset-password，以及已下线的"删休息块"接口），
所以在这里一次性解决：**只要 status_code 是 204，就自动把 `response_model` 设为 None**。
路由代码从此不必再记得这件事，也不会再因为漏写而在导入期炸掉整个应用。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from starlette.routing import Route


class ApiRouter(APIRouter):
    """自动处理 204「不能有响应体」约束的 APIRouter。"""

    def add_api_route(self, path: str, endpoint: Any, **kwargs: Any) -> Route:  # type: ignore[override]
        if kwargs.get("status_code") in (204, "204"):
            # 必须**显式赋值** None：
            # 若只是"不传"，继承实现会把它换成 Default(None) 占位符，
            # 而占位符对象在布尔判断里是真值，断言照样失败。
            kwargs["response_model"] = None
        return super().add_api_route(path, endpoint, **kwargs)


__all__ = ["ApiRouter"]

