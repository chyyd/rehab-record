"""时间工具：**全系统统一的时间戳格式**。

约定（`设计.md` 4.1.3 / 4.2.5）：

- **时间戳**（created_at / updated_at / expires_at / 审计时间）：
  UTC ISO8601 带毫秒与 ``Z``：``2026-10-05T03:12:44.123Z``
- **日期**（排期日期、记录日期）：本地日历日 ``YYYY-MM-DD``
- **时刻**（作息、可选计划时间）：本地墙钟 ``HH:MM``

为什么时间戳必须带 ``Z`` 且**不能**用 ``datetime('now','localtime')``：
SQLite 没有时区概念，``'localtime'`` 修饰符会按 UTC 计算再套本地偏移，
在 +08:00 时区下写出比真实时间快 8 小时的值。

**为什么要有这个模块**：这些字符串会参与 SQL 比较（如
``expires_at > strftime('%Y-%m-%dT%H:%M:%fZ','now')``），
格式必须严格一致 —— 一旦某处写成 ``'2026-10-05 11:30:00'``（空格而非 ``T``、无 ``Z``），
字符串比较就会得出错误结论（空格字符小于 ``T``，会被判成"已过期"）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

UTC = UTC


def utc_now() -> datetime:
    """当前的 UTC 时间（带时区）。"""
    return datetime.now(UTC)


def to_utc_timestamp(moment: datetime) -> str:
    """把 ``datetime`` 归一化成库里的时间戳格式（UTC + 毫秒 + Z）。

    naive 的 ``datetime`` 一律**按本地时区**解释（因为作息、请假到期时点都是本地墙钟），
    再转换到 UTC 输出。这样"11:30 到期"这种本地语义不会被错当成 UTC 11:30。
    """
    if moment.tzinfo is None:
        moment = moment.astimezone()  # 视为本地时间
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def utc_timestamp_now() -> str:
    """当前时间的时间戳字符串，用于「现在」的写入。"""
    return to_utc_timestamp(utc_now())


def period_expiry(day: date, period: str, worktime: object | None = None) -> str:
    """请假到期恢复时点（M09 + Q11），返回**库格式**的 UTC 时间戳。

    上午假 → 当日 11:30；下午假 → 当日 17:30；全天假 → 次日 00:00（本地墙钟语义）。
    """
    from app.core.worktime import period_end_datetime

    local_moment = period_end_datetime(day, period, worktime)  # type: ignore[arg-type]
    return to_utc_timestamp(local_moment)


def add_seconds(moment: datetime, seconds: int) -> datetime:
    return moment + timedelta(seconds=seconds)


def combine(day: date, clock: time) -> datetime:
    return datetime.combine(day, clock)


__all__ = [
    "UTC",
    "add_seconds",
    "combine",
    "period_expiry",
    "to_utc_timestamp",
    "utc_now",
    "utc_timestamp_now",
]
