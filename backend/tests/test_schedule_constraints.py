"""S1 排期不变量与约束。

不变量（《开发计划.md》M07）：
  1. 治疗师半日 = 一台
  2. 患者半日 = 一名治疗师（Q2：明确不允许同时段多人排期）
  3. cancelled / rescheduled 不占格子
另外验证 rest_block 的 scope 自洽性。
"""

from __future__ import annotations

import sqlite3
import unittest

from tests.support import DbTestCase


class TestAppointmentInvariants(DbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.t1 = self.add_user("T001", "张三")
        self.t2 = self.add_user("T002", "李四")
        self.p1 = self.add_patient("ZY001", "王五")
        self.p2 = self.add_patient("ZY002", "赵六")

    def test_therapist_half_day_is_single_slot(self) -> None:
        """同一治疗师同一天同一半日不能排第二台。"""
        self.add_appointment(self.p1, self.t1, "2026-10-05", "am")
        with self.assertRaises(sqlite3.IntegrityError):
            self.add_appointment(self.p2, self.t1, "2026-10-05", "am")

    def test_same_therapist_other_period_is_allowed(self) -> None:
        """上午与下午是两个独立格子，可以各排一台。"""
        self.add_appointment(self.p1, self.t1, "2026-10-05", "am")
        self.add_appointment(self.p2, self.t1, "2026-10-05", "pm")
        total = self.conn.execute("SELECT COUNT(*) FROM appointment").fetchone()[0]
        self.assertEqual(total, 2)

    def test_patient_half_day_is_single_therapist(self) -> None:
        """Q2：同一患者同一半日不能被两个治疗师同时排期。"""
        self.add_appointment(self.p1, self.t1, "2026-10-05", "am")
        with self.assertRaises(sqlite3.IntegrityError):
            self.add_appointment(self.p1, self.t2, "2026-10-05", "am")

    def test_same_patient_different_periods_allowed(self) -> None:
        self.add_appointment(self.p1, self.t1, "2026-10-05", "am")
        self.add_appointment(self.p1, self.t2, "2026-10-05", "pm")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM appointment").fetchone()[0], 2)

    def test_cancelled_frees_the_slot(self) -> None:
        """取消后格子必须能被重新占用，否则排期页会出现"卡死"的格子。"""
        first = self.add_appointment(self.p1, self.t1, "2026-10-05", "am")
        self.conn.execute("UPDATE appointment SET status = 'cancelled' WHERE id = ?", (first,))
        self.add_appointment(self.p2, self.t1, "2026-10-05", "am")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM appointment").fetchone()[0], 2)

    def test_rescheduled_frees_the_slot(self) -> None:
        first = self.add_appointment(self.p1, self.t1, "2026-10-05", "am")
        self.conn.execute("UPDATE appointment SET status = 'rescheduled' WHERE id = ?", (first,))
        self.add_appointment(self.p2, self.t1, "2026-10-05", "am")

    def test_period_must_be_am_or_pm(self) -> None:
        """排期单位只有上午/下午；full 是请假专用，不能用于排期。"""
        for bad in ("full", "night", "AM"):
            with self.assertRaises(sqlite3.IntegrityError):
                self.add_appointment(self.p1, self.t1, "2026-10-06", bad)

    def test_optional_planned_time_is_stored(self) -> None:
        """start_time/end_time 是可选"计划时间"，仅作同级排序，不参与唯一约束。"""
        self.conn.execute(
            "INSERT INTO appointment (patient_no, therapist_id, date, period, start_time, end_time, slot_label)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (self.p1, self.t1, "2026-10-05", "am", "08:00", "08:40", "上午第1台"),
        )
        row = self.conn.execute("SELECT start_time, end_time, slot_label FROM appointment").fetchone()
        self.assertEqual((row["start_time"], row["end_time"], row["slot_label"]), ("08:00", "08:40", "上午第1台"))

    def test_updated_at_trigger_fires(self) -> None:
        appt_id = self.add_appointment(self.p1, self.t1, "2026-10-05", "am")
        before = self.conn.execute("SELECT updated_at FROM appointment WHERE id = ?", (appt_id,)).fetchone()[0]
        self.conn.execute("UPDATE appointment SET note = '改期到下午' WHERE id = ?", (appt_id,))
        after = self.conn.execute("SELECT updated_at FROM appointment WHERE id = ?", (appt_id,)).fetchone()[0]
        self.assertIsNotNone(before)
        self.assertIsNotNone(after)


class TestRestBlock(DbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.t1 = self.add_user("T001", "张三")

    def test_weekly_rest_block(self) -> None:
        self.conn.execute(
            "INSERT INTO rest_block (therapist_id, scope, weekday, period, note)"
            " VALUES (?, 'weekly', 2, 'pm', '业务学习')",
            (self.t1,),
        )
        row = self.conn.execute("SELECT scope, weekday, period FROM rest_block").fetchone()
        self.assertEqual((row["scope"], row["weekday"], row["period"]), ("weekly", 2, "pm"))

    def test_date_rest_block(self) -> None:
        self.conn.execute(
            "INSERT INTO rest_block (therapist_id, scope, specific_date, period)"
            " VALUES (?, 'date', '2026-10-05', 'am')",
            (self.t1,),
        )

    def test_scope_must_be_consistent_with_fields(self) -> None:
        """weekly 不该带日期，date 不该带星期，否则排期页无法判断该看哪个字段。"""
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO rest_block (therapist_id, scope, weekday, specific_date, period)"
                " VALUES (?, 'weekly', 2, '2026-10-05', 'pm')",
                (self.t1,),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO rest_block (therapist_id, scope, period) VALUES (?, 'date', 'pm')",
                (self.t1,),
            )

    def test_duplicate_weekly_block_rejected(self) -> None:
        self.conn.execute(
            "INSERT INTO rest_block (therapist_id, scope, weekday, period) VALUES (?, 'weekly', 3, 'am')",
            (self.t1,),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO rest_block (therapist_id, scope, weekday, period) VALUES (?, 'weekly', 3, 'am')",
                (self.t1,),
            )


class TestNextAppointmentView(DbTestCase):
    """M15：排序视图必须按半日给出下一次排期。"""

    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.t1 = self.add_user("T001", "张三")
        self.p1 = self.add_patient("ZY001", "王五")

    def test_view_returns_earliest_slot(self) -> None:
        today = self.conn.execute("SELECT date('now', 'localtime')").fetchone()[0]
        self.add_appointment(self.p1, self.t1, today, "pm")
        self.add_appointment(self.p1, self.t1, today, "am")  # 更早的半日
        row = self.conn.execute(
            "SELECT next_date, next_period_rank FROM v_patient_next_appointment WHERE patient_no = ?",
            (self.p1,),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["next_date"], today)
        # rank 0 = 上午，必须取到 0 而不是 1
        self.assertEqual(row["next_period_rank"], 0)

    def test_cancelled_appointment_excluded_from_view(self) -> None:
        today = self.conn.execute("SELECT date('now', 'localtime')").fetchone()[0]
        appt = self.add_appointment(self.p1, self.t1, today, "am")
        self.conn.execute("UPDATE appointment SET status = 'cancelled' WHERE id = ?", (appt,))
        rows = self.conn.execute("SELECT * FROM v_patient_next_appointment").fetchall()
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
