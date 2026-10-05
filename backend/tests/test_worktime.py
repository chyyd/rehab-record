"""半日制作息语义（Q11 + S1）。这是全系统"半日"边界的唯一时间真源，必须严格。"""

from __future__ import annotations

import unittest
from datetime import time

from app.core import worktime as wt
from app.core.config import WorkTimeConfig, get_settings
from tests.support import DbTestCase  # noqa: F401  （沿用统一的测试基类与路径）


class TestWorkTimeConfig(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = WorkTimeConfig()  # Q11 定稿值

    def test_intervals_match_q11(self) -> None:
        self.assertEqual(wt.period_interval("am", self.cfg), (time(6, 0), time(11, 30)))
        self.assertEqual(wt.period_interval("pm", self.cfg), (time(13, 0), time(17, 30)))
        # 全天 = 上午开始 → 下午结束
        self.assertEqual(wt.period_interval("full", self.cfg), (time(6, 0), time(17, 30)))

    def test_default_settings_use_q11_values(self) -> None:
        cfg = get_settings().worktime
        self.assertEqual((cfg.morning_start, cfg.morning_end), ("06:00", "11:30"))
        self.assertEqual((cfg.afternoon_start, cfg.afternoon_end), ("13:00", "17:30"))

    def test_unknown_period_raises(self) -> None:
        for bad in ("", "night", "AM_PM", None):
            with self.assertRaises(wt.WorkTimeError):
                wt.period_interval(bad, self.cfg)  # type: ignore[arg-type]


class TestClassifyPeriod(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = WorkTimeConfig()

    def test_boundaries_are_inclusive(self) -> None:
        cases = {
            time(6, 0): "am",      # 上午开始（闭）
            time(11, 30): "am",    # 上午结束（闭）
            time(13, 0): "pm",     # 下午开始（闭）
            time(17, 30): "pm",    # 下午结束（闭）
        }
        for moment, expected in cases.items():
            self.assertEqual(wt.classify_period(moment, self.cfg), expected, f"{moment} 判定错误")

    def test_gaps_return_none(self) -> None:
        # 午休、以及作息之外的时间都不属于任何半日
        for moment in (time(0, 0), time(5, 59), time(11, 31), time(12, 30), time(17, 31), time(23, 59)):
            self.assertIsNone(wt.classify_period(moment, self.cfg), f"{moment} 不应属于任何半日")

    def test_is_within_period(self) -> None:
        self.assertTrue(wt.is_within_period(time(6, 0), "am", self.cfg))
        self.assertFalse(wt.is_within_period(time(6, 0), "pm", self.cfg))
        self.assertTrue(wt.is_within_period(time(17, 30), "pm", self.cfg))
        self.assertFalse(wt.is_within_period(time(12, 0), "pm", self.cfg))


class TestNormalizePeriod(unittest.TestCase):
    """`normalize_period` 仍容忍大小写与中文别名（历史输入值照旧接受）。

    > 2026-10-05：`period_label()` 与 `TestExpiryPerQ11` 已随临时指派删除。
    > `period_label` 唯一的生产调用方是 `cli periods` 打印"到期时点"那段，
    > 而那个用途（临时指派 `expires_at`）已不存在；`period_end_datetime` 同理。
    > `normalize_period` 保留 —— 它仍在容忍旧客户端传来的别名。
    """

    def test_normalize_accepts_variants(self) -> None:
        self.assertEqual(wt.normalize_period("AM"), "am")
        self.assertEqual(wt.normalize_period(" 上午 "), "am")
        self.assertEqual(wt.normalize_period("PM"), "pm")
        self.assertEqual(wt.normalize_period("下午"), "pm")

    def test_normalize_still_accepts_legacy_full(self) -> None:
        # "full" 不再是任何存储列的取值（治疗记录只接受 am/pm），
        # 但历史输入仍被接受，避免旧客户端直接 500。
        self.assertEqual(wt.normalize_period("full"), "full")
        self.assertEqual(wt.normalize_period("全天"), "full")

    def test_normalize_rejects_garbage(self) -> None:
        for bad in ("夜里", "abc", "", 123):
            with self.assertRaises(wt.WorkTimeError):
                wt.normalize_period(bad)  # type: ignore[arg-type]


class TestParseHm(unittest.TestCase):
    def test_parse_hm_rejects_bad_input(self) -> None:
        for bad in ("6:0", "25:00", "abc", ""):
            with self.assertRaises(wt.WorkTimeError):
                wt.parse_hm(bad)


class TestDayPeriodBounds(unittest.TestCase):
    def test_bounds_payload_for_frontend(self) -> None:
        bounds = wt.day_period_bounds()
        self.assertEqual(bounds["am"], {"label": "上午", "start": "06:00", "end": "11:30"})
        self.assertEqual(bounds["pm"], {"label": "下午", "start": "13:00", "end": "17:30"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
