"""排期约束（2026-10-03 起改为"半日格子不互斥"）。

变更依据：科室确认真实工作流 —— **一个上午里不同治疗师可能给同一患者做多次治疗，
一次最多 1 小时**；本系统只做记录、不做时间合规判定。故迁移 `006_open_scheduling.sql`
删除了 `ux_appt_therapist_slot` 与 `ux_appt_patient_slot` 两条唯一索引，**放弃 Q2、
放开 S1**。

当前仍然成立的库层约束：
  1. `date` 必须是合法日期、`period` 只能是 am/pm（CHECK 约束）；
  2. 同一休息块（治疗师 × 星期/日期 × 半日）唯一；
  3. `client_uuid` 幂等键唯一。

**不再成立**（原两条不变量）：
  - ~~治疗师半日 = 一台~~
  - ~~患者半日 = 一名治疗师~~
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

    def test_same_therapist_same_half_day_allows_multiple(self) -> None:
        """一个治疗师同一半日可以有多台（原先只允许一台）。"""
        self.add_appointment(self.p1, self.t1, "2026-10-05", "am")
        self.add_appointment(self.p2, self.t1, "2026-10-05", "am")
        total = self.conn.execute("SELECT COUNT(*) FROM appointment").fetchone()[0]
        self.assertEqual(total, 2)

    def test_same_therapist_other_period_is_allowed(self) -> None:
        """上午与下午是两个独立格子。"""
        self.add_appointment(self.p1, self.t1, "2026-10-05", "am")
        self.add_appointment(self.p2, self.t1, "2026-10-05", "pm")
        total = self.conn.execute("SELECT COUNT(*) FROM appointment").fetchone()[0]
        self.assertEqual(total, 2)

    def test_same_patient_same_half_day_allows_multiple_therapists(self) -> None:
        """Q2 已放弃：同一患者同一半日可以被多个治疗师各排一台。

        这是科室真实工作流（PT / OT / 言语 / 吞咽 在同一个上午各做一次）。
        """
        self.add_appointment(self.p1, self.t1, "2026-10-05", "am")
        self.add_appointment(self.p1, self.t2, "2026-10-05", "am")
        rows = self.conn.execute(
            "SELECT COUNT(*) FROM appointment WHERE patient_no = ?", (self.p1,)
        ).fetchone()[0]
        self.assertEqual(rows, 2)

    def test_same_patient_different_periods_allowed(self) -> None:
        self.add_appointment(self.p1, self.t1, "2026-10-05", "am")
        self.add_appointment(self.p1, self.t2, "2026-10-05", "pm")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM appointment").fetchone()[0], 2)

    def test_cancelled_still_deletable_and_rebookable(self) -> None:
        """取消后仍可再排（格子本来就不互斥，这里守住状态流转）。"""
        first = self.add_appointment(self.p1, self.t1, "2026-10-05", "am")
        self.conn.execute("UPDATE appointment SET status = 'cancelled' WHERE id = ?", (first,))
        self.add_appointment(self.p2, self.t1, "2026-10-05", "am")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM appointment").fetchone()[0], 2)

    def test_rescheduled_status_accepted(self) -> None:
        first = self.add_appointment(self.p1, self.t1, "2026-10-05", "am")
        self.conn.execute("UPDATE appointment SET status = 'rescheduled' WHERE id = ?", (first,))
        self.add_appointment(self.p2, self.t1, "2026-10-05", "am")

    def test_period_must_be_am_or_pm(self) -> None:
        """排期单位只有上午/下午；full 是请假专用，不能用于排期。"""
        for bad in ("full", "night", "AM"):
            with self.assertRaises(sqlite3.IntegrityError):
                self.add_appointment(self.p1, self.t1, "2026-10-06", bad)

    def test_client_uuid_is_unique(self) -> None:
        """幂等键仍受唯一索引保护（`ux_appt_client_uuid`）。"""
        self.conn.execute(
            "INSERT INTO appointment (patient_no, therapist_id, date, period, client_uuid)"
            " VALUES (?, ?, ?, ?, ?)",
            (self.p1, self.t1, "2026-10-05", "am", "11111111-1111-4111-8111-111111111111"),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO appointment (patient_no, therapist_id, date, period, client_uuid)"
                " VALUES (?, ?, ?, ?, ?)",
                (self.p2, self.t2, "2026-10-06", "pm", "11111111-1111-4111-8111-111111111111"),
            )

    def test_optional_planned_time_is_stored(self) -> None:
        """start_time/end_time 是可选的展示字段，**不参与任何约束**（本系统不做时间合规）。"""
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
