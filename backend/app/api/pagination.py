"""列表分页参数（`开发计划.md` D09）。

统一 `?page=1&page_size=20`，响应统一 `{"items": ..., "total": ..., "page": ..., "page_size": ...}`。
`page_size` 设上限，避免客户端一次拉全表把服务端拖死。
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Query

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 20


@dataclass(frozen=True)
class Page:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


def page_params(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="每页条数"),
) -> Page:
    return Page(page=page, page_size=page_size)


__all__ = ["DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE", "Page", "page_params"]
