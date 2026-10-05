"""半日制作息语义（Q11 + S1）。这是全系统"半日"边界的唯一时间真源，必须严格。"""

from __future__ import annotations

import unittest
from datetime import date, datetime, time

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


class TestPeriodLabelsAndNormalize(unittest.TestCase):
    def test_labels(self) -> None:
        self.assertEqual(wt.period_label("am"), "上午")
        self.assertEqual(wt.period_label("pm"), "下午")
        self.assertEqual(wt.period_label("full"), "全天")

    def test_normalize_accepts_variants(self) -> None:
        self.assertEqual(wt.normalize_period("AM"), "am")
        self.assertEqual(wt.normalize_period(" 上午 "), "am")
        self.assertEqual(wt.normalize_period("PM"), "pm")
        self.assertEqual(wt.normalize_period("下午"), "pm")
        self.assertEqual(wt.normalize_period("full"), "full")
        self.assertEqual(wt.normalize_period("全天"), "full")

    def test_normalize_rejects_garbage(self) -> None:
        for bad in ("夜里", "abc", "", 123):
            with self.assertRaises(wt.WorkTimeError):
                wt.normalize_period(bad)  # type: ignore[arg-type]


class TestExpiryPerQ11(unittest.TestCase):
    """M09 临时指派到期时点必须取所属半日区间的结束时刻（Q11）。"""

    def setUp(self) -> None:
        self.cfg = WorkTimeConfig()
        self.day = date(2026, 10, 5)

    def test_half_day_morning_expires_at_1130(self) -> None:
        self.assertEqual(wt.period_end_datetime(self.day, "am", self.cfg), datetime(2026, 10, 5, 11, 30))

    def test_half_day_afternoon_expires_at_1730(self) -> None:
        self.assertEqual(wt.period_end_datetime(self.day, "pm", self.cfg), datetime(2026, 10, 5, 17, 30))

    def test_full_day_expires_next_midnight(self) -> None:
        self.assertEqual(wt.period_end_datetime(self.day, "full", self.cfg), datetime(2026, 10, 6, 0, 0))

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
