"""端到端验收脚本的公共设施。

## 为什么需要这个模块

验收脚本要能在**同一个数据库上重复运行**（跑一次通过、再跑一次还得通过）。
最早就吃过亏：脚本按"干净库"写，删患者时没有先清依赖行，
第二次运行必定 `FOREIGN KEY constraint failed`；而每次换新库跑就永远发现不了。

因此删除一律走 :func:`purge_patients`，由它按外键依赖顺序清理，
脚本自己不要手写 DELETE 语句。

## 依赖顺序（子表 → 父表）

    record_item → treatment_record ┐
    temporary_assignment           ├→ patient
    patient_assignment_history     ┘

`change_log` 用实体名+字符串 id 记录，没有外键，可以最后按 entity_id 清。

> 2026-10-05：`appointment` / `rest_block` / `leave_record` 三张表随排期功能下线删除，
> 本文件的清理顺序里不再包含它们。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable


def purge_patients(conn: sqlite3.Connection, patient_nos: Iterable[str]) -> None:
    """彻底删除这些患者及其全部关联数据（按外键顺序）。"""
    nos = [str(no) for no in patient_nos]
    if not nos:
        return
    marks = ", ".join("?" for _ in nos)

    # 治疗记录与明细
    conn.execute(
        "DELETE FROM record_item WHERE record_id IN"
        f" (SELECT id FROM treatment_record WHERE patient_no IN ({marks}))",
        nos,
    )
    record_ids = [
        str(row["id"])
        for row in conn.execute(
            f"SELECT id FROM treatment_record WHERE patient_no IN ({marks})", nos
        ).fetchall()
    ]
    conn.execute(f"DELETE FROM treatment_record WHERE patient_no IN ({marks})", nos)

    # 临时指派、归属历史
    # （`appointment` 表已于 2026-10-05 随排期功能下线删除，不再需要清理）
    conn.execute(f"DELETE FROM temporary_assignment WHERE patient_no IN ({marks})", nos)
    conn.execute(f"DELETE FROM patient_assignment_history WHERE patient_no IN ({marks})", nos)

    # 变更日志（无外键，按实体名 + 字符串 id 清）
    if record_ids:
        id_marks = ", ".join("?" for _ in record_ids)
        conn.execute(
            f"DELETE FROM change_log WHERE entity = 'treatment_record'"
            f" AND entity_id IN ({id_marks})",
            record_ids,
        )

    conn.execute(f"DELETE FROM patient WHERE inpatient_no IN ({marks})", nos)


def purge_option_sets(
    conn: sqlite3.Connection, *, scope: str, owner_user_id: int | None = None
) -> None:
    """删除某个范围（通常是某人的 personal）的选项集。

    **必须先删 option_item**：它有外键指向 option_set，
    直接删 option_set 会 `FOREIGN KEY constraint failed`（重跑验收脚本时踩到过）。
    """
    where = ["scope = ?"]
    params: list[object] = [scope]
    if owner_user_id is not None:
        where.append("owner_user_id = ?")
        params.append(owner_user_id)
    clause = " AND ".join(where)
    conn.execute(
        f"DELETE FROM option_item WHERE option_set_id IN"
        f" (SELECT id FROM option_set WHERE {clause})",
        params,
    )
    conn.execute(f"DELETE FROM option_set WHERE {clause}", params)


def purge_templates(conn: sqlite3.Connection, names: Iterable[str] | None = None) -> None:
    """删除模板（先子表后父表）。``names`` 为空则清空全部模板。"""
    if names is None:
        conn.execute("DELETE FROM record_template_item")
        conn.execute("DELETE FROM record_template")
        return
    wanted = [str(n) for n in names]
    if not wanted:
        return
    marks = ", ".join("?" for _ in wanted)
    ids = [
        str(row["id"])
        for row in conn.execute(
            f"SELECT id FROM record_template WHERE name IN ({marks})", wanted
        ).fetchall()
    ]
    if not ids:
        return
    id_marks = ", ".join("?" for _ in ids)
    conn.execute(f"DELETE FROM record_template_item WHERE template_id IN ({id_marks})", ids)
    conn.execute(f"DELETE FROM record_template WHERE id IN ({id_marks})", ids)


def purge_users(conn: sqlite3.Connection, employee_nos: Iterable[str]) -> None:
    """删除用户及其会话等关联行（按外键顺序）。

    验收脚本一般不删用户（改为重置密码），保留此函数供特殊场景使用。
    """
    nos = [str(no) for no in employee_nos]
    if not nos:
        return
    marks = ", ".join("?" for _ in nos)
    ids = [
        str(row["id"])
        for row in conn.execute(f"SELECT id FROM user WHERE employee_no IN ({marks})", nos).fetchall()
    ]
    if not ids:
        return
    id_marks = ", ".join("?" for _ in ids)
    conn.execute(f"DELETE FROM auth_session WHERE user_id IN ({id_marks})", ids)
    # `rest_block` / `leave_record` / `appointment` 三张表已于 2026-10-05 随排期功能下线删除。
    conn.execute(f"DELETE FROM user WHERE id IN ({id_marks})", ids)


__all__ = ["purge_option_sets", "purge_patients", "purge_templates", "purge_users"]
