"""数据级权限的统一查询（`开发计划.md` D10）。

**权限判断只在这一处实现。** 路由要按"我能看到哪些患者"过滤其他资源
（例如治疗记录列表）时，必须调用本模块，而不是各自写一遍范围条件——
复制粘贴的权限条件迟早会漏一处，那处就是越权入口。

## 2026-10-03：由"数据隔离"改为"全科白板"

科室确认真实工作流后，患者可见性做了**重大变更**：

- **不再按归属隔离**：原来治疗师只能看到"我的 / 未分配 / 临时认领"的患者，
  现在**科室当前在院（`in_hospital`）与暂停（`paused`）的患者对所有治疗师可见**。
  原因：一个上午里 PT / OT / 言语 / 吞咽 可能各给同一患者做一次治疗，
  归属人只有一个；若按归属隔离，其余治疗师连患者都看不到，业务无法进行。
- **已出院（`discharged`）默认不可见**：它不属于"当前在科室的患者"。
  管理员仍可通过 `scope=all` 查看全表。
- **归属（`assigned_therapist_id`）仍然保留**，但语义从"可见性闸门"降级为
  **优先级 / 文书署名**：患者列表排序、"我的患者"筛选仍然用它。

> 注意区分两个层次：
> - `can_view_patient()` / `visible_patient_numbers()`：**能不能看到**（本模块，已放开为科室级）
> - `patient_model.can_schedule()`：**归属语义**（可见归属解析），仍保留但不再作为排期前置条件
"""

from __future__ import annotations

import sqlite3

from app.models import patient as patient_model
from app.models.patient import ACTIVE_STATUSES
from app.models.user import ROLE_ADMIN


def visible_patient_numbers(conn: sqlite3.Connection, user: dict) -> list[str] | None:
    """返回该用户可见的全部住院编号（**科室级**：在院 + 暂停）。

    **管理员返回 `None`**，表示"不加限制"——调用方据此决定是否拼 IN 条件，
    避免把全表编号读进内存。
    """
    if user.get("role") == ROLE_ADMIN:
        return None
    placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
    rows = conn.execute(
        f"SELECT inpatient_no FROM patient WHERE status IN ({placeholders})",
        ACTIVE_STATUSES,
    ).fetchall()
    return [str(r["inpatient_no"]) for r in rows]


def can_view_patient(conn: sqlite3.Connection, user: dict, patient_no: str) -> bool:
    """单体判断：与 `visible_patient_numbers` 保持同一套语义（科室级）。

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
    # 全科白板：在院 / 暂停对全部治疗师可见；已出院默认不可见
    return str(patient["status"]) in ACTIVE_STATUSES


__all__ = ["can_view_patient", "visible_patient_numbers"]

