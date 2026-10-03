"""审计日志写入（`设计.md` 3.11 / `开发计划.md` M11）。

**为什么需要一个统一入口**：审计是"事后追责"的唯一依据，最怕的是
"有的地方记了、有的地方忘了"。所有需要留痕的操作都必须调用 ``write_audit``。

注意库里还有触发器 `trg_record_edit_trace` 负责治疗记录的提交后修改留痕——
那是**库层兜底**（防止有人绕过 service 直接改数据），与本模块互补：
- 库层触发器：治疗记录被改就一定留痕，不依赖应用代码自觉；
- 本模块：记录"是谁主动发起了这个操作"，含登录、改密码、归属变更等非记录类操作。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.core.jsonutil import dumps


def write_audit(
    conn: sqlite3.Connection,
    *,
    user_id: int | None,
    action: str,
    target_type: str,
    target_id: str,
    before: Any = None,
    after: Any = None,
) -> None:
    """写一条审计日志。**不抛异常**——审计失败不应让业务操作失败。

    这里刻意吞掉异常：如果审计写入失败就回滚业务，会让治疗师在床旁莫名其妙地保存不了记录。
    代价是极端情况下可能丢一条审计，可接受。
    """
    try:
        conn.execute(
            "INSERT INTO audit_log (user_id, action, target_type, target_id, before_json, after_json)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, action, target_type, str(target_id), dumps(before), dumps(after)),
        )
    except sqlite3.Error:
        # 审计是辅助能力，不能影响主流程；真实部署应额外做告警。
        # 这个空 except 是刻意的（ruff SIM105 已按项目配置忽略），
        # 为的是让人读到这里就注意到"异常被吞掉了"这一取舍。
        pass


__all__ = ["write_audit"]
