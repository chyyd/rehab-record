"""端到端验收脚本的公共设施。

## 为什么需要这个模块

验收脚本要能在**同一个数据库上重复运行**（跑一次通过、再跑一次还得通过）。
最早就吃过亏：脚本按"干净库"写，删患者时没有先清依赖行，
第二次运行必定 `FOREIGN KEY constraint failed`；而每次换新库跑就永远发现不了。

因此删除一律走 :func:`purge_patients`，由它按外键依赖顺序清理，
脚本自己不要手写 DELETE 语句。

## 依赖顺序（子表 → 父表）

    treatment_record ┐
    patient_assignment_history ┘→ patient

`change_log` 用实体名+字符串 id 记录，没有外键，可以最后按 entity_id 清。

## 历史

> 2026-10-05：`appointment` / `rest_block` / `leave_record` 三张表随排期功能下线删除（迁移 008），
> `temporary_assignment` 随后也被彻底删除（迁移 009）。
>
> 2026-10-05（SOAP 改造）：`record_item` 随迁移 011 删除（记录只存 `body_json` +
> `rendered_text`），字典/选项集/反应定义六张表随迁移 012 删除。
> 曾经在本文件里的 `purge_option_sets()` 与 `purge_templates()` 也随之**删除** ——
> 它们要删的表已经不存在了，留着只会在运行时报 `no such table`。
> 记录模板现在是 `templates/*.json` **文件**，不进数据库，所以没有任何"清理模板"的需求。
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

    # 治疗记录（SOAP 模型：一条记录一行，不再有 record_item 子表）
    record_ids = [
        str(row["id"])
        for row in conn.execute(
            f"SELECT id FROM treatment_record WHERE patient_no IN ({marks})", nos
        ).fetchall()
    ]
    conn.execute(f"DELETE FROM treatment_record WHERE patient_no IN ({marks})", nos)

    # 归属历史
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


def purge_users(conn: sqlite3.Connection, employee_nos: Iterable[str]) -> None:
    """删除用户及其会话等关联行（按外键顺序）。

    验收脚本一般不删用户（改为重置密码），保留此函数供特殊场景使用。
    """
    nos = [str(n) for n in employee_nos]
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
    conn.execute(f"DELETE FROM user WHERE id IN ({id_marks})", ids)


__all__ = ["purge_patients", "purge_users"]
