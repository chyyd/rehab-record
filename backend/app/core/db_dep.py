"""数据库连接依赖（阶段 1）。

用 FastAPI 依赖注入提供连接，好处是测试可以用
``app.dependency_overrides[get_db]`` 换成临时库，不必全局改环境变量。

注意：这是同步依赖函数，FastAPI 会把它放到线程池里执行（`def` 而非 `async def`），
所以内部的阻塞 SQLite 调用不会卡住事件循环。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.db import storage


def get_db(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[sqlite3.Connection]:
    """每个请求一个连接，请求结束即关闭。

    用 ``Annotated[...]`` 而不是把 ``Depends(...)`` 写在默认值里：
    后者会被 ruff 的 B008 判为「在参数默认值里调用函数」，而 Annotated 也是 FastAPI 官方推荐写法。
    """
    conn = storage.connect(settings)
    try:
        yield conn
    finally:
        conn.close()


__all__ = ["get_db"]
