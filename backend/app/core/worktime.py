"""半日制作息的时间语义（《开发计划.md》S1 + Q11）。

**这是全系统"半日"边界的唯一时间真源。** 任何模块都不允许自己写
"上午到 11:30"这类字面量，必须调用本模块。

> 2026-10-05 排期、休息块、请假整体下线（迁移 008），临时指派随后也删除
> （迁移 009）。现在这里服务的对象**只剩一类**：治疗记录的 `session_period`
> （"这条记录属于哪个半日"）。"上午 11:30 结束"本身没有变，
> 也不再用于任何排班判定。

约定：
- ``period`` 取值：``"am"``（上午）、``"pm"``（下午）、``"full"``（全天）。
- ``"full"`` **不是半日单位**（治疗记录的 `session_period` 不接受它）。
  它现在**没有任何存储列在用**（`temporary_assignment.period` 已随表删除），
  仅作为历史输入值继续被 ``normalize_period`` 接受、并被 ``cli periods`` 打印，
  保留是因为删掉它会改变既有调用方的可接受输入集合，收益不明确。
- 所有时间都是"本地墙钟时间"（Asia/Shanghai，依据 D07），不带时区偏移。
"""

from __future__ import annotations

import re
from datetime import datetime, time

from app.core.config import WorkTimeConfig, get_settings

PERIOD_AM = "am"
PERIOD_PM = "pm"
PERIOD_FULL = "full"

# 真正的"半日"单位（治疗记录的 `session_period`）：上午 / 下午，两格。
# 常量名来自已下线的排期功能（2026-10-05，`appointment` 表已删除），
# 保留是为了不破坏既有导入 —— 它现在表达的就是"一天分两个半日"。
APPOINTMENT_PERIODS: tuple[str, ...] = (PERIOD_AM, PERIOD_PM)
# 允许的 ``period`` 全集：比半日多一个 ``full``（全天）。
# ``full`` 现在**没有任何存储列在用**：它原本是请假（`leave_record.period`）与
# 临时指派（`temporary_assignment.period`）的粒度，两者都已在迁移 008/009 删除。
# 保留它（连同 ``PERIOD_FULL``）是因为 `normalize_period` 仍然接受 "full"/"全天"
# 作为兼容输入、`cli periods` 也会打印全天区间的结束时刻；
# 删掉它会收窄既有调用方的可接受输入集合，而收益不明确，故**保留并说明**。
LEAVE_PERIODS: tuple[str, ...] = (PERIOD_AM, PERIOD_PM, PERIOD_FULL)

PERIOD_LABELS: dict[str, str] = {
    PERIOD_AM: "上午",
    PERIOD_PM: "下午",
    PERIOD_FULL: "全天",
}

_TIME_FORMAT = "%H:%M"
# 零填充的 24 小时制；"6:0"、"25:00"、"abc" 一律拒绝
_HM_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class WorkTimeError(ValueError):
    """作息相关的取值非法。"""


def parse_hm(value: str) -> time:
    """把 ``"HH:MM"`` 解析成 ``datetime.time``；非法输入直接报错，不做兜底。

    必须严格校验格式：``strptime("6:0", "%H:%M")`` 在部分平台上会被接受，
    而作息配置一旦被写成 ``"6:0"``，后续所有半日边界比较都会悄悄错位。
    """
    if not isinstance(value, str):
        raise WorkTimeError(f"时间必须是字符串 'HH:MM'，收到 {type(value).__name__}")
    text = value.strip()
    if not _HM_PATTERN.match(text):
        raise WorkTimeError(f"时间格式非法（应为零填充的 HH:MM）：{value!r}")
    parsed = datetime.strptime(text, _TIME_FORMAT).time()
    return parsed


def period_interval(period: str, config: WorkTimeConfig | None = None) -> tuple[time, time]:
    """返回该半日的 ``(开始, 结束)``。``full`` 返回上午开始到下午结束。"""
    cfg = config or get_settings().worktime
    if period == PERIOD_AM:
        return parse_hm(cfg.morning_start), parse_hm(cfg.morning_end)
    if period == PERIOD_PM:
        return parse_hm(cfg.afternoon_start), parse_hm(cfg.afternoon_end)
    if period == PERIOD_FULL:
        return parse_hm(cfg.morning_start), parse_hm(cfg.afternoon_end)
    raise WorkTimeError(f"未知的半日取值：{period!r}，合法值为 {LEAVE_PERIODS}")


def period_start(period: str, config: WorkTimeConfig | None = None) -> time:
    return period_interval(period, config)[0]


def period_end(period: str, config: WorkTimeConfig | None = None) -> time:
    return period_interval(period, config)[1]


def normalize_period(value: str) -> str:
    """容忍前端传来大写的 ``AM``/``PM``、以及中文"上午/下午"。"""
    if not isinstance(value, str):
        raise WorkTimeError(f"半日取值必须是字符串，收到 {type(value).__name__}")
    raw = value.strip()
    alias = {
        "am": PERIOD_AM, "上午": PERIOD_AM, "早": PERIOD_AM, "morning": PERIOD_AM,
        "pm": PERIOD_PM, "下午": PERIOD_PM, "晚": PERIOD_PM, "afternoon": PERIOD_PM,
        "full": PERIOD_FULL, "全天": PERIOD_FULL, "all": PERIOD_FULL,
    }
    key = raw.lower()
    if key in alias:
        return alias[key]
    if raw in alias:
        return alias[raw]
    raise WorkTimeError(f"无法识别的半日取值：{value!r}")


def classify_period(moment: time, config: WorkTimeConfig | None = None) -> str | None:
    """判断某个时刻落在哪个半日。

    - 落入上午或下午区间 → 返回 ``"am"`` / ``"pm"``
    - 落在午休或作息之外（如 12:00、18:00、05:00）→ 返回 ``None``

    边界取**闭区间**：``06:00`` 属于上午，``11:30`` 也属于上午（结束时刻含在内）。
    """
    cfg = config or get_settings().worktime
    m_start, m_end = parse_hm(cfg.morning_start), parse_hm(cfg.morning_end)
    a_start, a_end = parse_hm(cfg.afternoon_start), parse_hm(cfg.afternoon_end)
    if m_start <= moment <= m_end:
        return PERIOD_AM
    if a_start <= moment <= a_end:
        return PERIOD_PM
    return None


def is_within_period(moment: time, period: str, config: WorkTimeConfig | None = None) -> bool:
    """校验某个时刻是否落在指定半日区间内（S1 处置第 2 条要用）。"""
    start, end = period_interval(period, config)
    return start <= moment <= end


def day_period_bounds(config: WorkTimeConfig | None = None) -> dict[str, dict[str, str]]:
    """半日边界描述，供调用方（`/api/v1/health` 的 `periods`、`cli.py periods`）使用。

    这样调用方不必自己硬编码"上午 06:00–11:30"。现在主要是健康检查的自描述与运维查看。
    """
    cfg = config or get_settings().worktime
    return {
        PERIOD_AM: {"label": PERIOD_LABELS[PERIOD_AM], "start": cfg.morning_start, "end": cfg.morning_end},
        PERIOD_PM: {"label": PERIOD_LABELS[PERIOD_PM], "start": cfg.afternoon_start, "end": cfg.afternoon_end},
    }


__all__ = [
    "APPOINTMENT_PERIODS",
    "LEAVE_PERIODS",
    "PERIOD_AM",
    "PERIOD_FULL",
    "PERIOD_PM",
    "PERIOD_LABELS",
    "WorkTimeError",
    "classify_period",
    "day_period_bounds",
    "is_within_period",
    "normalize_period",
    "parse_hm",
    "period_end",
    "period_interval",
    "period_start",
]
