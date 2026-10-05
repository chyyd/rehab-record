"""临时指派（`temporary_assignment`）—— 归属解析的一部分，**与请假无关**。

## 这个模块为什么独立存在

原名叫 `leave.py`（请假数据访问 + 释放副作用）。2026-10-05 排期功能整体下线时，
请假（`leave_record`）随之删除 —— 它存在的唯一目的是"判断某个半日能不能排期"。

但**临时指派不能跟着删**：它表达的是"某个患者在某半日暂时不归原治疗师管"，
`v_patient_visibility` 视图依赖它算 `visible_therapist_id`，
而患者可见性、认领、记录权限全都建立在这个视图上。所以把这一小块抽出来独立成模块，
剩下的请假逻辑整体删除。

## 与旧实现的行为差异（有意为之）

旧实现里临时指派只有两个来源：单日请假自动释放、以及手动认领。
请假没了之后，**自动释放这条路消失**，临时指派只剩下：

- 管理员/治疗师按业务需要手工建立的临时指派（仍由 `v_patient_visibility` 认）；
- **到期清理**（本模块唯一的自动化逻辑）。

也就是说这件事从"请假副作用"变成了"归属数据的日常维护" —— 这正是它本来的意义。
"""

from __future__ import annotations

import sqlite3

from app.core.clock import utc_timestamp_now

# 临时指派的关闭原因。`leave_cancelled` 随请假功能下线而移除，
# 但**已有数据里可能还有这个值**，所以不做数据迁移改写（历史原因保持可读）。
CLOSED_REASON_EXPIRED = "expired"

__all__ = [
    "CLOSED_REASON_EXPIRED",
    "close_expired_temporary_assignments",
]


def close_expired_temporary_assignments(conn: sqlite3.Connection) -> int:
    """把已过期的临时指派置为 closed，返回处理条数。

    **这只是清理，不是判定依据**：`v_patient_visibility` 视图在读取时也检查
    `expires_at`，所以即使这个任务漏跑，归属显示依然正确（`开发计划.md` R8）。
    """
    now = utc_timestamp_now()
    cur = conn.execute(
        "UPDATE temporary_assignment SET status = 'closed', closed_at = ?, closed_reason = ?"
        " WHERE status = 'open' AND expires_at IS NOT NULL AND expires_at <= ?",
        (now, CLOSED_REASON_EXPIRED, now),
    )
    return int(cur.rowcount or 0)
