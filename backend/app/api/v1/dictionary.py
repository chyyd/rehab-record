"""字典、选项集与患者反应定义接口（阶段 3 / `开发计划.md` 4.5）。

字典是只读引用数据；**科室/全局选项集与反应定义由种子与管理员维护**，
治疗师只能维护自己的"个人快捷"选项集（`设计.md` 3.6.4）。

这些接口存在的意义：记录页需要一次性拿到「主项目 → 子项目 → 参数 → 选项」的结构，
以及可用的患者反应。让前端自己拼会重复实现字典层级与选项解析规则。
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import Depends, Query, Response

from app.api.router import ApiRouter
from app.core.db_dep import get_db
from app.core.security_deps import CurrentUser
from app.models import dictionary as dictionary_model
from app.models import response_def as response_def_model
from app.schemas.records import (
    MainItemOut,
    OptionSetOut,
    ParamDefOut,
    PersonalOptionSetRequest,
    ResolvedOptionsOut,
    ResponseDefOut,
    SubItemOut,
)
from app.services import options as options_service

router = ApiRouter(tags=["字典"])


# --------------------------------------------------------------------------- #
# 字典（只读）
# --------------------------------------------------------------------------- #
@router.get("/dict/tree", response_model=list[MainItemOut], summary="完整字典树（主项目→子项目→参数）")
def dict_tree(
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    main_item_id: int | None = None,
) -> list[dict[str, Any]]:
    return dictionary_model.dictionary_tree(conn, main_item_id=main_item_id)


@router.get("/dict/main-items", response_model=list[MainItemOut], summary="主项目")
def list_main_items(user: CurrentUser, conn: Annotated[sqlite3.Connection, Depends(get_db)]) -> list[dict[str, Any]]:
    return dictionary_model.list_main_items(conn)


@router.get("/dict/sub-items", response_model=list[SubItemOut], summary="子项目")
def list_sub_items(
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    main_item_id: int | None = None,
) -> list[dict[str, Any]]:
    return dictionary_model.list_sub_items(conn, main_item_id=main_item_id)


@router.get("/dict/sub-items/{sub_item_id}/params", response_model=list[ParamDefOut], summary="参数定义")
def list_params(
    sub_item_id: int,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> list[dict[str, Any]]:
    dictionary_model.get_sub_item_or_raise(conn, sub_item_id)
    return dictionary_model.list_params(conn, sub_item_id)


# --------------------------------------------------------------------------- #
# 选项集
# --------------------------------------------------------------------------- #
@router.get("/option-sets", response_model=list[OptionSetOut], summary="对我有效的选项集")
def list_option_sets(
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    dept_tag: str | None = None,
) -> list[dict[str, Any]]:
    return options_service.list_option_sets(
        conn, owner_user_id=int(user["id"]), dept_tag=dept_tag
    )


@router.get("/option-sets/resolve", response_model=ResolvedOptionsOut, summary="解析某个 code 的有效选项")
def resolve_options(
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    code: str = Query(..., description="与参数的 param_key 对应"),
    sub_item_id: int | None = Query(None, description="传入则把该子项目的内置选项作为最后回退"),
    dept_tag: str | None = None,
) -> dict[str, Any]:
    builtin: list[str] = []
    if sub_item_id is not None:
        definition = dictionary_model.get_param_by_key(conn, sub_item_id, code)
        builtin = (definition or {}).get("options") or []
    return options_service.resolve_options(
        conn, code=code, builtin=builtin, owner_user_id=int(user["id"]), dept_tag=dept_tag
    )


@router.put("/option-sets/personal", response_model=OptionSetOut, summary="维护我的个人快捷选项")
def upsert_personal_option_set(
    payload: PersonalOptionSetRequest,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    """个人快捷选项：治疗师把自己常用的一组选项存下来，下次直接可用。

    写的是 `scope='personal'`，因此**只会影响自己**，不改变科室标准。
    """
    return options_service.upsert_personal_option_set(
        conn,
        owner_user_id=int(user["id"]),
        code=payload.code,
        name=payload.name,
        values=payload.values,
        default_values=payload.default_values,
    )


@router.delete(
    "/option-sets/personal/{code}",
    status_code=204,
    response_class=Response,
    summary="删除我的个人快捷选项",
)
def delete_personal_option_set(
    code: str,
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> Response:
    options_service.delete_personal_option_set(conn, owner_user_id=int(user["id"]), code=code)
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# 患者反应定义
# --------------------------------------------------------------------------- #
@router.get("/response-defs", response_model=list[ResponseDefOut], summary="患者反应定义")
def list_response_defs(
    user: CurrentUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    main_item_id: int | None = Query(None, description="传入则含该主项目专属 + 全科通用"),
) -> list[dict[str, Any]]:
    return response_def_model.list_response_defs(conn, main_item_id=main_item_id)


@router.get("/response-defs/grouped", summary="按主项目分组的患者反应定义")
def response_defs_grouped(
    user: CurrentUser, conn: Annotated[sqlite3.Connection, Depends(get_db)]
) -> dict[str, Any]:
    return response_def_model.response_defs_by_main_item(conn)


__all__ = ["router"]
