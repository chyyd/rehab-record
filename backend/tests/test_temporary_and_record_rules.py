"""库层规则：患者状态枚举、记录留痕触发器、变更日志（M04 / M11 / M06）。

> 2026-10-05：请假（`leave_record`）随排期功能下线删除，`temporary_assignment`
> 随临时指派删除（迁移 009）；记录改 SOAP 模板驱动后（迁移 011/012），
> 字典 / 选项集 / 患者反应定义六张表也一并删除 —— 本文件里针对它们的库层用例
> 已整组移除（被测对象不存在了）。
>
> ⚠ 文件名保留了历史名字（任务按文件名指定改动位置）。
>
> ⚠ `scope=temp` 这个**筛选**已全部删除；但 `is_temporary` 这个**记录级标记**
> 仍然保留（查询时推导），它的用例在 `test_records.py::TestTemporaryTreatmentFlag`。
"""

from __future__ import annotations

import sqlite3
import unittest

from app.models import patient as patient_model
from tests.support import DbTestCase


class TestPatientStatusAndJson(DbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.t1 = self.add_user("T001", "张三")

    def test_patient_status_enum(self) -> None:
        """M13 + 迁移 013：in_hospital / discharged / paused / pending_discharge。"""
        for good in ("in_hospital", "discharged", "paused", "pending_discharge"):
            self.conn.execute(
                "INSERT INTO patient (inpatient_no, name, status) VALUES (?, ?, ?)",
                (f"ZY-{good}", "测试", good),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO patient (inpatient_no, name, status) VALUES ('ZY-BAD', '测试', '在院')"
            )

    def test_pending_discharge_is_not_active(self) -> None:
        """待出院**不在** `ACTIVE_STATUSES` 里：治疗师白板上看不到（管理员可查）。"""
        from app.models.patient import ACTIVE_STATUSES

        self.assertNotIn(patient_model.STATUS_PENDING_DISCHARGE, ACTIVE_STATUSES)
        self.assertIn(patient_model.STATUS_PENDING_DISCHARGE, patient_model.PATIENT_STATUSES)

    def test_user_role_not_null_and_enum(self) -> None:
        """M14：role 必须非空且只能是 therapist/admin。"""
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO user (employee_no, name) VALUES ('T009', '无角色')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO user (employee_no, name, role) VALUES ('T010', '错角色', 'doctor')")

    def test_employee_no_unique(self) -> None:
        self.add_user("T100")
        with self.assertRaises(sqlite3.IntegrityError):
            self.add_user("T100", "同名工号")

    def test_body_json_column_validates_json(self) -> None:
        """P-17/M04 的同类兜底（迁移 011 把它挪到 `body_json` 上）。"""
        self.add_patient("ZY001")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO treatment_record (patient_no, therapist_id, record_date, discipline,"
                " kind, seq_no, body_json) VALUES ('ZY001', ?, '2026-10-05', 'PT', 'daily', 1, '不是 JSON')",
                (self.t1,),
            )
        # 合法 JSON 应当写入成功，并且能用 json_extract 查
        self.conn.execute(
            "INSERT INTO treatment_record (patient_no, therapist_id, record_date, discipline,"
            " kind, seq_no, body_json) VALUES ('ZY001', ?, '2026-10-05', 'PT', 'daily', 1, ?)",
            (self.t1, '{"vas": 3, "therapy_items": ["偏瘫肢体综合训练"]}'),
        )
        value = self.conn.execute(
            "SELECT json_extract(body_json, '$.vas') FROM treatment_record"
        ).fetchone()[0]
        self.assertEqual(value, 3)

    def test_seq_no_check_matches_kind(self) -> None:
        """CHECK ((kind = 'daily') = (seq_no IS NOT NULL))。"""
        self.add_patient("ZY001")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO treatment_record (patient_no, therapist_id, record_date, discipline,"
                " kind, seq_no) VALUES ('ZY001', ?, '2026-10-05', 'PT', 'daily', NULL)",
                (self.t1,),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO treatment_record (patient_no, therapist_id, record_date, discipline,"
                " kind, seq_no, span_seq) VALUES ('ZY001', ?, '2026-10-05', 'PT', 'initial', 1, 1)",
                (self.t1,),
            )


class TestRecordEditTrace(DbTestCase):
    """4.3 关键规则：提交后修改必须留痕（M11，由库层触发器兜底）。

    迁移 011 之后，触发器盯的是 `body_json` 与 `rendered_text` 的变化
    （旧模型盯的是 `note` / `duration_min` / `patient_response_json` 等列）。
    """

    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.t1 = self.add_user("T001", "张三")
        self.p1 = self.add_patient("ZY001", "王五")
        cur = self.conn.execute(
            "INSERT INTO treatment_record (patient_no, therapist_id, record_date, discipline, kind,"
            " seq_no, body_json, rendered_text, status, submitted_at)"
            " VALUES (?, ?, '2026-10-05', 'PT', 'daily', 1, ?, ?, 'submitted',"
            "         '2026-10-05T00:00:00.000Z')",
            (self.p1, self.t1, '{"vas": 2}', "康复治疗记录\n疼痛VAS：2分"),
        )
        self.record_id = int(cur.lastrowid)

    def test_draft_edit_does_not_audit(self) -> None:
        """草稿阶段随便改，不该产生审计噪声。"""
        cur = self.conn.execute(
            "INSERT INTO treatment_record (patient_no, therapist_id, record_date, discipline, kind,"
            " seq_no, body_json, status) VALUES (?, ?, '2026-10-06', 'PT', 'daily', 2, '{}', 'draft')",
            (self.p1, self.t1),
        )
        draft_id = int(cur.lastrowid)
        self.conn.execute(
            "UPDATE treatment_record SET body_json = '{\"vas\": 5}' WHERE id = ?", (draft_id,)
        )
        count = self.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        self.assertEqual(count, 0)
        self.assertEqual(
            self.conn.execute(
                "SELECT edit_count FROM treatment_record WHERE id = ?", (draft_id,)
            ).fetchone()[0],
            0,
        )

    def test_submitted_edit_increments_edit_count(self) -> None:
        self.conn.execute(
            "UPDATE treatment_record SET body_json = '{\"vas\": 4}', rendered_text = ? WHERE id = ?",
            ("康复治疗记录\n疼痛VAS：4分", self.record_id),
        )
        edit_count = self.conn.execute(
            "SELECT edit_count FROM treatment_record WHERE id = ?", (self.record_id,)
        ).fetchone()[0]
        self.assertEqual(edit_count, 1, "库层触发器应累加 edit_count")
        revision = self.conn.execute(
            "SELECT revision FROM treatment_record WHERE id = ?", (self.record_id,)
        ).fetchone()[0]
        self.assertEqual(revision, 2, "留痕时同时推进 revision（离线客户端靠它判断过期）")

    def test_repeated_edits_accumulate(self) -> None:
        for i in range(3):
            self.conn.execute(
                "UPDATE treatment_record SET body_json = ? WHERE id = ?",
                (f'{{"vas": {i}}}', self.record_id),
            )
        edit_count = self.conn.execute(
            "SELECT edit_count FROM treatment_record WHERE id = ?", (self.record_id,)
        ).fetchone()[0]
        self.assertEqual(edit_count, 3)

    def test_note_only_edit_does_not_count_as_content_change(self) -> None:
        """`note` 是备注，不是文书内容：改它不该被判成"篡改病历"。"""
        self.conn.execute(
            "UPDATE treatment_record SET note = '补一句备注' WHERE id = ?", (self.record_id,)
        )
        edit_count = self.conn.execute(
            "SELECT edit_count FROM treatment_record WHERE id = ?", (self.record_id,)
        ).fetchone()[0]
        self.assertEqual(edit_count, 0)


class TestChangeLog(DbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.t1 = self.add_user("T001", "张三")

    def test_change_log_cursor_is_monotonic(self) -> None:
        """M06：change_log.id 即同步游标，必须单调递增。"""
        for i in range(5):
            self.conn.execute(
                "INSERT INTO change_log (entity, entity_id, op, revision, payload_json)"
                " VALUES ('patient', ?, 'update', 1, '{}')",
                (f"ZY00{i}",),
            )
        ids = [row[0] for row in self.conn.execute("SELECT id FROM change_log ORDER BY id")]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(set(ids)), 5)

    def test_change_log_op_enum(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO change_log (entity, entity_id, op, revision) VALUES ('patient', 'ZY1', 'merge', 1)"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
