"""数据级权限的统一查询（`开发计划.md` D10）。

**权限判断只在这一处实现。** 路由要按"我能看到哪些患者"过滤其他资源
（例如治疗记录列表）时，必须调用本模块，而不是各自写一遍范围条件——
复制粘贴的权限条件迟早会漏一处，那处就是越权入口。
"""

from __future__ import annotations

import sqlite3

from app.models import patient as patient_model
from app.models.user import ROLE_ADMIN


def visible_patient_numbers(conn: sqlite3.Connection, user: dict) -> list[str] | None:
    """返回该用户可见的全部住院编号。

    **管理员返回 `None`**，表示"不加限制"——调用方据此决定是否拼 IN 条件，
    避免把全表编号读进内存（患者量大时那是明显的浪费）。
    """
    if user.get("role") == ROLE_ADMIN:
        return None
    rows = conn.execute(
        "SELECT inpatient_no FROM v_patient_visibility v"
        " WHERE v.visible_therapist_id = ?"
        "    OR v.visible_therapist_id IS NULL"
        "    OR (v.temp_assignment_id IS NOT NULL"
        "        AND (v.temp_therapist_id = ? OR v.temp_original_therapist_id = ?))",
        (int(user["id"]), int(user["id"]), int(user["id"])),
    ).fetchall()
    return [str(r["inpatient_no"]) for r in rows]


def can_view_patient(conn: sqlite3.Connection, user: dict, patient_no: str) -> bool:
    """单体判断：与 `visible_patient_numbers` 保持同一套语义。

    两个函数必须同源——列表过滤与单条判断若不一致，就会出现
    "列表里看不到、但直接猜 URL 能拿到"的越权。
    """
    from app.models.base import NotFound

    patient = patient_model.get_patient(conn, patient_no)
    if patient is None:
        # 不存在与无权限对调用方的处理不同，这里交给调用方决定提示方式
        raise NotFound("患者不存在", details={"inpatient_no": patient_no})
    if user.get("role") == ROLE_ADMIN:
        return True
    uid = int(user["id"])
    visible = patient["visible_therapist_id"]
    if visible is None or int(visible) == uid:
        return True
    if patient.get("temp_assignment_id") is not None:
        return uid in {patient.get("temp_therapist_id"), patient.get("temp_original_therapist_id")}
    return False


__all__ = ["can_view_patient", "visible_patient_numbers"]
