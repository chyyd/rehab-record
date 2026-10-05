"""患者反应（M04）、记录留痕（M11）与选项集（M03）等库层规则。

> 2026-10-05：请假（`leave_record`）随排期功能整体下线被删除 ——
> 本文件原本的 `TestLeaveRecord` 整组用例随之删除（被测的表已经不存在了）。
> 随后 `temporary_assignment`（临时指派）也被**彻底删除**（迁移 009）——
> 归属简化成两层，`v_open_temporary_assignment` 视图与
> `TestTemporaryAssignment` 整组用例（临时释放 / 临时认领 / 到期时点 /
> 关闭后腾出时段 / updated_at 触发器）一并删除。
>
> ⚠ 文件名保留了历史名字（任务按文件名指定改动位置），但它现在**不再包含**
> 任何临时指派用例。
>
> ⚠ 另外注意**两件事不要混淆**（用户 2026-10-05 决定）：
> `scope=temp` 这个**筛选**已全部删除（患者列表 + 时间轴/记录列表 + App 时间轴页签）；
> 但 `is_temporary` 这个**记录级标记**仍然保留 —— 它由
> `treatment_model.temporary_expr()` 查询时推导，PDF / 患者每日汇总 / 后台记录列表
> 三处消费方都在用，与已删除的 `temporary_assignment` 从来没有依赖关系。
> 这**不是**"临时治疗功能整体下线"。
"""

from __future__ import annotations

import sqlite3
import unittest

from tests.support import DbTestCase


class TestPatientStatusAndJson(DbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.t1 = self.add_user("T001", "张三")

    def test_patient_status_enum(self) -> None:
        """M13：统一为 in_hospital / discharged / paused。"""
        for good in ("in_hospital", "discharged", "paused"):
            self.conn.execute(
                "INSERT INTO patient (inpatient_no, name, status) VALUES (?, ?, ?)",
                (f"ZY-{good}", "测试", good),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO patient (inpatient_no, name, status) VALUES ('ZY-BAD', '测试', '在院')"
            )

    def test_unknown_column_status_rejected(self) -> None:
        """设计文档 3.2 写的是中文枚举，库层只接受英文码（P-13）。"""
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO patient (inpatient_no, name, status) VALUES ('ZY-X', '测试', '出院')")

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

    def test_json_columns_reject_invalid_json(self) -> None:
        """P-17/M04：JSON 字段必须有 json_valid 兜底，否则读取期才爆炸。"""
        self.add_patient("ZY001")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO treatment_record (patient_no, therapist_id, record_date, patient_response_json)"
                " VALUES ('ZY001', ?, '2026-10-05', '不是 JSON')",
                (self.t1,),
            )
        # 合法 JSON 应当写入成功
        self.conn.execute(
            "INSERT INTO treatment_record (patient_no, therapist_id, record_date, patient_response_json)"
            " VALUES ('ZY001', ?, '2026-10-05', ?)",
            (self.t1, '{"items":[{"code":"pain","value":3}],"tags":["no_discomfort"]}'),
        )

    def test_json_path_query_works(self) -> None:
        """4.2 节要求能用 json_extract 查询（JSON1）。"""
        self.add_patient("ZY001")
        self.conn.execute(
            "INSERT INTO treatment_record (patient_no, therapist_id, record_date, patient_response_json)"
            " VALUES ('ZY001', ?, '2026-10-05', ?)",
            (self.t1, '{"items":[{"code":"pain","value":3}]}'),
        )
        value = self.conn.execute(
            "SELECT json_extract(patient_response_json, '$.items[0].value') FROM treatment_record"
        ).fetchone()[0]
        self.assertEqual(value, 3)


class TestRecordEditTrace(DbTestCase):
    """4.3 关键规则：提交后修改必须留痕（M11，由库层触发器兜底）。"""

    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.t1 = self.add_user("T001", "张三")
        self.p1 = self.add_patient("ZY001", "王五")
        cur = self.conn.execute(
            "INSERT INTO treatment_record (patient_no, therapist_id, record_date, status, note, duration_min,"
            " submitted_at) VALUES (?, ?, '2026-10-05', 'submitted', '首次记录', 30, datetime('now','localtime'))",
            (self.p1, self.t1),
        )
        self.record_id = int(cur.lastrowid)

    def test_draft_edit_does_not_audit(self) -> None:
        """草稿阶段随便改，不该产生审计噪声。"""
        cur = self.conn.execute(
            "INSERT INTO treatment_record (patient_no, therapist_id, record_date, status, note)"
            " VALUES (?, ?, '2026-10-06', 'draft', '草稿')",
            (self.p1, self.t1),
        )
        draft_id = int(cur.lastrowid)
        self.conn.execute("UPDATE treatment_record SET note = '草稿改了' WHERE id = ?", (draft_id,))
        count = self.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        self.assertEqual(count, 0)
        self.assertEqual(
            self.conn.execute("SELECT edit_count FROM treatment_record WHERE id = ?", (draft_id,)).fetchone()[0], 0
        )

    def test_submitted_edit_audits_and_increments(self) -> None:
        self.conn.execute("UPDATE treatment_record SET note = '改成 40 分钟' WHERE id = ?", (self.record_id,))
        logs = self.conn.execute(
            "SELECT action, target_type, target_id, before_json, after_json FROM audit_log"
        ).fetchall()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["action"], "record_modified_after_submit")
        self.assertEqual(logs[0]["target_type"], "treatment_record")
        self.assertEqual(logs[0]["target_id"], str(self.record_id))
        self.assertIn("首次记录", logs[0]["before_json"])
        self.assertIn("改成 40 分钟", logs[0]["after_json"])

        edit_count = self.conn.execute(
            "SELECT edit_count FROM treatment_record WHERE id = ?", (self.record_id,)
        ).fetchone()[0]
        self.assertEqual(edit_count, 1)

    def test_repeated_edits_accumulate(self) -> None:
        for i in range(3):
            self.conn.execute("UPDATE treatment_record SET note = ? WHERE id = ?", (f"第{i}次修改", self.record_id))
        edit_count = self.conn.execute(
            "SELECT edit_count FROM treatment_record WHERE id = ?", (self.record_id,)
        ).fetchone()[0]
        self.assertEqual(edit_count, 3)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0], 3)

    def test_locked_record_still_audited(self) -> None:
        """锁定态的治疗师改动会被记下来（权限拦截在 service 层，留痕在库层）。"""
        self.conn.execute(
            "UPDATE treatment_record SET status = 'locked', locked_at = datetime('now','localtime') WHERE id = ?",
            (self.record_id,),
        )
        logs = self.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        self.assertGreaterEqual(logs, 1)


class TestChangeLogAndSeedStructures(DbTestCase):
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

    def test_option_set_scope_requires_owner_for_personal(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO option_set (scope, code, name) VALUES ('personal', 'mmt_grade', 'MMT')")
        self.conn.execute(
            "INSERT INTO option_set (scope, owner_user_id, code, name) VALUES ('personal', ?, 'mmt_grade', 'MMT')",
            (self.t1,),
        )

    def test_global_option_set_cannot_have_owner(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO option_set (scope, owner_user_id, code, name) VALUES ('global', ?, 'mmt_grade', 'MMT')",
                (self.t1,),
            )

    def test_template_scope_requires_owner_for_personal(self) -> None:
        self.conn.execute("INSERT INTO main_item (id, name, code) VALUES (1, '运动功能障碍训练', 'motor')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO record_template (scope, main_item_id, name) VALUES ('personal', 1, '我的常用')"
            )

    def test_param_def_rejects_duplicate_key_within_sub_item(self) -> None:
        """M16：同一子项目内 param_key 必须唯一，否则 JSON 参数会互相覆盖。"""
        self.conn.execute("INSERT INTO main_item (id, name, code) VALUES (1, '运动', 'motor')")
        self.conn.execute(
            "INSERT INTO sub_item (id, main_item_id, name, code)"
            " VALUES (1, 1, '偏瘫肢体综合训练', 'hemi')"
        )
        self.conn.execute(
            "INSERT INTO sub_item_param_def (sub_item_id, param_key, param_name, input_type)"
            " VALUES (1, 'mmt_grade', 'MMT 分级', 'select')"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO sub_item_param_def (sub_item_id, param_key, param_name, input_type)"
                " VALUES (1, 'mmt_grade', '重复键', 'select')"
            )

    def test_param_def_options_json_validated(self) -> None:
        self.conn.execute("INSERT INTO main_item (id, name, code) VALUES (1, '运动', 'motor')")
        self.conn.execute("INSERT INTO sub_item (id, main_item_id, name, code) VALUES (1, 1, '子项目', 'sub')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO sub_item_param_def (sub_item_id, param_key, param_name, input_type, options_json)"
                " VALUES (1, 'position', '体位', 'select', '坐位,站立')"
            )

    def test_response_def_tag_has_no_value_key(self) -> None:
        """M04：tag 类反应（如"无不适"）不该带 value_key。"""
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO response_def (code, label, value_type, value_key)"
                " VALUES ('no_discomfort', '无不适', 'tag', 'x')"
            )
        self.conn.execute(
            "INSERT INTO response_def (code, label, value_type, value_key, value_min, value_max, value_unit)"
            " VALUES ('pain', '疼痛', 'number', 'nrs', 0, 10, '分')"
        )

    def test_response_def_duplicate_code_per_main_item(self) -> None:
        self.conn.execute("INSERT INTO response_def (code, label, value_type) VALUES ('fatigue', '疲劳', 'tag')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO response_def (code, label, value_type) VALUES ('fatigue', '疲劳2', 'tag')")


if __name__ == "__main__":
    unittest.main(verbosity=2)
