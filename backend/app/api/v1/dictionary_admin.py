"""字典管理写接口（阶段 5 后台的"字典管理"模块 / `开发计划.md` 4.5 第 580–582 行）。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /dict/main-items | 新建主项目 |
| PUT | /dict/main-items/{id} | 修改主项目 |
| DELETE | /dict/main-items/{id} | 删除主项目（下有启用子项目时 409） |
| POST | /dict/sub-items | 新建子项目 |
| PUT | /dict/sub-items/{id} | 修改子项目 |
| DELETE | /dict/sub-items/{id} | 删除子项目（用过则改为停用） |
| POST | /dict/sub-items/{id}/params | 新建参数定义 |
| PUT | /dict/params/{id} | 修改参数定义 |
| DELETE | /dict/params/{id} | 删除参数定义 |

读取接口仍在 `app/api/v1/dictionary.py`（治疗师渲染记录表单也要用）。

**注册顺序**：本模块必须**先于**只读的 `dictionary.router` 注册。
只读模块定义了 `GET /dict/main-items`，而这里定义 `POST /dict/main-items` ——
路径相同但方法不同，FastAPI 能区分；然而 `GET /dict/sub-items` 与
`GET /dict/sub-items/{sub_item_id}/params` 这类路径在两边都有，
先注册写接口能保证管理端的语义优先，避免将来路径调整时误匹配。
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import Depends, status

from app.api.router import ApiRouter
from app.core.db_dep import get_db
from app.core.security_deps import AdminUser
from app.models import dictionary as dictionary_model
from app.models import dictionary_admin as admin_model
from app.schemas.dictionary_admin import (
    DeleteResultOut,
    MainItemAdminOut,
    MainItemCreateRequest,
    MainItemUpdateRequest,
    ParamAdminOut,
    ParamCreateRequest,
    ParamUpdateRequest,
    SubItemAdminOut,
    SubItemCreateRequest,
    SubItemUpdateRequest,
)
from app.services.audit import write_audit

router = ApiRouter(tags=["字典管理"])


def _audit(conn: sqlite3.Connection, admin: dict[str, Any], action: str, target: str, target_id: Any,
           after: Any = None) -> None:
    write_audit(conn, user_id=int(admin["id"]), action=action, target_type=target,
                target_id=str(target_id), after=after)


# --------------------------------------------------------------------------- #
# 主项目
# --------------------------------------------------------------------------- #
@router.post(
    "/dict/main-items",
    response_model=MainItemAdminOut,
    status_code=status.HTTP_201_CREATED,
    summary="新建主项目（管理员）",
)
def create_main_item(
    payload: MainItemCreateRequest,
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    created = admin_model.create_main_item(
        conn, name=payload.name, code=payload.code, alias=payload.alias, sort=payload.sort
    )
    _audit(conn, admin, "create", "main_item", created["id"], created)
    return created


@router.put("/dict/main-items/{main_item_id}", response_model=MainItemAdminOut, summary="修改主项目")
def update_main_item(
    main_item_id: int,
    payload: MainItemUpdateRequest,
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    before = dictionary_model.get_main_item_or_raise(conn, main_item_id)
    updated = admin_model.update_main_item(
        conn, main_item_id, name=payload.name, code=payload.code, alias=payload.alias,
        sort=payload.sort, status=payload.status,
    )
    write_audit(conn, user_id=int(admin["id"]), action="update", target_type="main_item",
                target_id=str(main_item_id), before=before, after=updated)
    return updated


@router.delete("/dict/main-items/{main_item_id}", response_model=DeleteResultOut, summary="删除主项目")
def delete_main_item(
    main_item_id: int,
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    result = admin_model.delete_main_item(conn, main_item_id)
    _audit(conn, admin, "delete", "main_item", main_item_id, result)
    return result


# --------------------------------------------------------------------------- #
# 子项目
# --------------------------------------------------------------------------- #
@router.post(
    "/dict/sub-items",
    response_model=SubItemAdminOut,
    status_code=status.HTTP_201_CREATED,
    summary="新建子项目",
)
def create_sub_item(
    payload: SubItemCreateRequest,
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    created = admin_model.create_sub_item(
        conn, main_item_id=payload.main_item_id, name=payload.name, code=payload.code,
        alias=payload.alias, sort=payload.sort,
    )
    _audit(conn, admin, "create", "sub_item", created["id"], created)
    return created


@router.put("/dict/sub-items/{sub_item_id}", response_model=SubItemAdminOut, summary="修改子项目")
def update_sub_item(
    sub_item_id: int,
    payload: SubItemUpdateRequest,
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    before = dictionary_model.get_sub_item_or_raise(conn, sub_item_id)
    updated = admin_model.update_sub_item(
        conn, sub_item_id, main_item_id=payload.main_item_id, name=payload.name,
        code=payload.code, alias=payload.alias, sort=payload.sort, status=payload.status,
    )
    write_audit(conn, user_id=int(admin["id"]), action="update", target_type="sub_item",
                target_id=str(sub_item_id), before=before, after=updated)
    return updated


@router.delete("/dict/sub-items/{sub_item_id}", response_model=DeleteResultOut, summary="删除子项目")
def delete_sub_item(
    sub_item_id: int,
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    """删除子项目。

    **用过的子项目不会真的删掉，而是改为 `disabled`**：历史记录靠快照仍能显示，
    但新记录不该再选它。响应里的 `soft_deleted` / `reason` 会说明发生了什么，
    前端应据此提示管理员（而不是显示"删除成功"却在列表里又看到它）。
    """
    result = admin_model.delete_sub_item(conn, sub_item_id)
    _audit(conn, admin, "delete" if result.get("deleted") else "disable", "sub_item",
           sub_item_id, result)
    return result


# --------------------------------------------------------------------------- #
# 参数定义
# --------------------------------------------------------------------------- #
@router.post(
    "/dict/sub-items/{sub_item_id}/params",
    response_model=ParamAdminOut,
    status_code=status.HTTP_201_CREATED,
    summary="新建参数定义",
)
def create_param(
    sub_item_id: int,
    payload: ParamCreateRequest,
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    created = admin_model.create_param(
        conn, sub_item_id=sub_item_id, param_key=payload.param_key, param_name=payload.param_name,
        input_type=payload.input_type, options=payload.options, default_value=payload.default_value,
        required=payload.required, unit=payload.unit, sort=payload.sort,
    )
    _audit(conn, admin, "create", "sub_item_param_def", created["id"], created)
    return created


@router.put("/dict/params/{param_id}", response_model=ParamAdminOut, summary="修改参数定义")
def update_param(
    param_id: int,
    payload: ParamUpdateRequest,
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    """修改参数定义（PUT 整体替换语义）。

    `default_value` 传 `null` 表示**清空默认值** —— 与"不传该字段"在当前实现里
    都是"目标值为空"，因为前端表单始终提交完整对象。
    """
    before = None
    row = conn.execute(
        "SELECT id, sub_item_id, param_key, param_name, input_type, options_json, default_value,"
        " required, unit, sort FROM sub_item_param_def WHERE id = ?",
        (param_id,),
    ).fetchone()
    if row is not None:
        before = dict(row)
    updated = admin_model.update_param(
        conn, param_id, param_key=payload.param_key, param_name=payload.param_name,
        input_type=payload.input_type, options=payload.options,
        default_value=payload.default_value, required=payload.required,
        unit=payload.unit, sort=payload.sort,
    )
    write_audit(conn, user_id=int(admin["id"]), action="update", target_type="sub_item_param_def",
                target_id=str(param_id), before=before, after=updated)
    return updated


@router.delete("/dict/params/{param_id}", response_model=DeleteResultOut, summary="删除参数定义")
def delete_param(
    param_id: int,
    admin: AdminUser,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict[str, Any]:
    result = admin_model.delete_param(conn, param_id)
    _audit(conn, admin, "delete", "sub_item_param_def", param_id, result)
    return result


__all__ = ["router"]
