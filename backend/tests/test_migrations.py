"""迁移与数据库自检。"""

from __future__ import annotations

import shutil
import sqlite3
import unittest
from datetime import UTC
from pathlib import Path

from app.db import storage
from tests.support import DbTestCase

EXPECTED_TABLES = {
    # 2026-10-05：`appointment` / `rest_block` / `leave_record` 随排期功能下线删除（008），
    # `temporary_assignment` 随临时指派功能删除（009）。
    # 2026-10-05（记录改 SOAP 模板驱动）：`record_item` / `record_template` /
    # `record_template_item` 随迁移 011 删除，字典六表（`main_item` / `sub_item` /
    # `sub_item_param_def` / `option_set` / `option_item` / `response_def`）
    # 随迁移 012 删除 —— 模板与选项现在是 `templates/*.json` 文件。
    "audit_log",
    "auth_session",
    "change_log",
    "patient",
    "patient_assignment_history",
    "schema_migrations",
    "treatment_record",
    "user",
}

EXPECTED_VIEWS = {
    # `v_patient_next_appointment` → `v_patient_last_treated`（迁移 007/008/011）：
    # 患者列表排序依据从"下一个排期"换成"我最近一次已提交**日常**治疗"。
    # `v_open_temporary_assignment` 随临时指派删除（迁移 009）。
    "v_patient_last_treated",
    "v_patient_visibility",
}

# 迁移 011 之后 `treatment_record` 的列（新契约的"落地形态"）
EXPECTED_RECORD_COLUMNS = {
    "id", "patient_no", "therapist_id", "record_date", "discipline", "kind", "seq_no",
    "body_json", "rendered_text", "note", "status", "edit_count", "locked_at",
    "created_at", "submitted_at", "updated_at", "revision", "client_uuid",
}


class TestMigrations(DbTestCase):
    def test_initial_migration_creates_all_tables(self) -> None:
        expected = [m.label for m in storage.discover_migrations(settings=self.settings)]
        result = self.migrate()
        # 不硬编码迁移清单：新增迁移不该让这个测试失败，但"全部应用了"必须成立
        self.assertEqual(result.applied, expected)
        self.assertEqual(result.skipped, [])

        names = {
            row["name"]
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        self.assertEqual(EXPECTED_TABLES - names, set(), "有表未创建")
        self.assertEqual(names - EXPECTED_TABLES, set(), "创建了计划外的表")

        views = {
            row["name"] for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'view'")
        }
        self.assertEqual(views, EXPECTED_VIEWS)

    def test_migrate_is_idempotent(self) -> None:
        expected = [m.label for m in storage.discover_migrations(settings=self.settings)]
        self.migrate()
        second = self.migrate()
        self.assertEqual(second.applied, [])
        self.assertEqual(second.skipped, expected)
        latest = max(m.version for m in storage.discover_migrations(settings=self.settings))
        self.assertEqual(storage.schema_version(self.conn), latest)
        self.assertEqual(self.conn.execute("PRAGMA user_version").fetchone()[0], latest)

    def test_modified_applied_migration_is_rejected(self) -> None:
        """已应用的迁移被改动过必须报错，而不是静默跳过（否则线上库与代码永久漂移）。"""
        self.migrate()
        migrations = storage.discover_migrations(settings=self.settings)
        tampered = storage.Migration(
            version=migrations[0].version, name=migrations[0].name, path=migrations[0].path
        )
        # 伪造一个校验和，模拟文件内容已变
        self.conn.execute("UPDATE schema_migrations SET checksum = 'deadbeef'")
        with self.assertRaises(storage.MigrationError):
            storage.migrate(self.conn, [tampered])

    def test_migration_filename_validation(self) -> None:
        # 用 tests/fixtures/ 作为临时迁移目录，并且用完即删，
        # 不要把测试残留物丢进 app/db/（那会被当成真实迁移目录的一部分）。
        bad = Path(__file__).resolve().parent / "fixtures" / "bad_migrations"
        bad.mkdir(parents=True, exist_ok=True)
        (bad / "oops.sql").write_text("SELECT 1;", encoding="utf-8")
        try:
            with self.assertRaises(storage.MigrationError):
                storage.discover_migrations(migrations_dir=bad, settings=self.settings)
        finally:
            shutil.rmtree(bad, ignore_errors=True)

    def test_inspect_reports_healthy_database(self) -> None:
        self.migrate()
        info = storage.inspect(self.settings)
        self.assertTrue(info["reachable"])
        self.assertTrue(info["json1"])
        self.assertTrue(info["foreign_keys"])
        self.assertEqual(str(info["journal_mode"]).lower(), "wal")
        self.assertEqual(info["foreign_key_violations"], 0)
        self.assertEqual(info["pending_migrations"], [])
        self.assertEqual(info["status"], "ok")
        # 健康检查用只读连接，不应干扰业务连接
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM user").fetchone()[0], 0)

    def test_inspect_reports_missing_database(self) -> None:
        """探针不得顺手把空库创建出来 —— 一次健康检查不应产生副作用。"""
        from app.core.config import Settings

        missing_path = self.tmp_path / "nope.db"
        missing = Settings(db_path=missing_path)
        info = storage.inspect(missing)
        self.assertFalse(info["reachable"])
        self.assertEqual(info["status"], "down")
        self.assertFalse(missing_path.exists(), "inspect 不应创建数据库文件")

    def test_inspect_reports_degraded_for_empty_database(self) -> None:
        """文件存在但没有 schema：能打开，但必须被标成 degraded 并给出原因。"""
        info = storage.inspect(self.settings)
        self.assertTrue(info["reachable"])
        self.assertEqual(info["status"], "degraded")
        self.assertEqual(info["schema_version"], 0)
        self.assertTrue(any("迁移" in p for p in info["problems"]))


class TestTreatmentRecordModel(DbTestCase):
    """迁移 011 之后 `treatment_record` 的新契约（列、约束、触发器）。"""

    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.t1 = self.add_user("T001", "张三")
        self.add_patient("ZY001", "王五")

    def insert(self, **overrides):
        values = {
            "patient_no": "ZY001",
            "therapist_id": self.t1,
            "record_date": "2026-10-05",
            "discipline": "PT",
            "kind": "daily",
            "seq_no": 1,
        }
        values.update(overrides)
        columns = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        cur = self.conn.execute(
            f"INSERT INTO treatment_record ({columns}) VALUES ({marks})", tuple(values.values())
        )
        return int(cur.lastrowid)

    def test_columns_match_new_contract(self) -> None:
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(treatment_record)")}
        self.assertEqual(columns, EXPECTED_RECORD_COLUMNS)

    def test_daily_must_have_seq_no(self) -> None:
        """CHECK ((kind = 'daily') = (seq_no IS NOT NULL))：日常必须有次数。"""
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(seq_no=None)
        # 评估文书反过来不能有次数
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(kind="initial", seq_no=1)

    def test_assessment_kinds_have_no_seq_no(self) -> None:
        record_id = self.insert(kind="initial", seq_no=None)
        row = self.conn.execute(
            "SELECT seq_no FROM treatment_record WHERE id = ?", (record_id,)
        ).fetchone()
        self.assertIsNone(row["seq_no"])

    def test_discipline_and_kind_enums_are_enforced(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(discipline="XZ")
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(kind="weekly", seq_no=None)

    def test_body_json_must_be_valid_json(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(body_json="不是 JSON")

    def test_daily_seq_is_unique_per_patient_and_discipline(self) -> None:
        self.insert(seq_no=1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(seq_no=1)
        # 换一个大类就可以（不同大类分开计数）
        self.insert(seq_no=1, discipline="OT")

    def test_only_one_initial_per_patient_and_discipline(self) -> None:
        """`ux_record_one_initial`：每个大类只能有一份首评。

        这条索引顶替了被删掉的 `ux_record_assessment_span` 里"不能补填第二份首评"
        那半职责 —— 复评之间**本来就可能有多份**（30 天、60 天、90 天各一份），
        所以不能对 `kind='reassessment'` 做同样的唯一约束；
        复评的唯一性由**日期门禁**保证（未到应做日就折不成复评形态）。
        """
        self.insert(kind="initial", seq_no=None, record_date="2026-10-05")
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(kind="initial", seq_no=None, record_date="2026-11-05")
        # 换大类就可以（首评是按大类各一份）
        self.insert(kind="initial", seq_no=None, discipline="OT")

    def test_reassessment_can_repeat_over_months(self) -> None:
        """复评按月产生 → 同一大类可以有多份，不能被唯一索引挡住。"""
        self.insert(kind="initial", seq_no=None, record_date="2026-10-05")
        self.insert(kind="reassessment", seq_no=None, record_date="2026-11-05")
        self.insert(kind="reassessment", seq_no=None, record_date="2026-12-05")
        count = self.conn.execute(
            "SELECT COUNT(*) FROM treatment_record WHERE kind = 'reassessment'"
        ).fetchone()[0]
        self.assertEqual(count, 2)


class TestPatientPendingDischarge(DbTestCase):
    """迁移 013：`patient.status` 增加 `pending_discharge`，且重建后什么都没丢。"""

    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.t1 = self.add_user("T001", "张三")

    def test_pending_discharge_is_accepted(self) -> None:
        self.conn.execute(
            "INSERT INTO patient (inpatient_no, name, status) VALUES ('ZY-P', '待出院', 'pending_discharge')"
        )
        status = self.conn.execute(
            "SELECT status FROM patient WHERE inpatient_no = 'ZY-P'"
        ).fetchone()[0]
        self.assertEqual(status, "pending_discharge")

    def test_old_enum_still_rejected(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO patient (inpatient_no, name, status) VALUES ('ZY-X', '错的', '出院')"
            )

    def test_rebuild_kept_columns_indexes_and_trigger(self) -> None:
        """重建表最容易悄悄丢东西：004 的 client_uuid、001/004 的索引、002 的触发器。"""
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(patient)")}
        self.assertIn("client_uuid", columns, "004 加的 client_uuid 列不能在重建时丢掉")
        indexes = {
            row["name"]
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'patient'"
            )
        }
        for expected in ("ix_patient_assigned", "ix_patient_status", "ux_patient_client_uuid"):
            self.assertIn(expected, indexes)
        triggers = {
            row["name"]
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'patient'"
            )
        }
        self.assertIn("trg_patient_updated_at", triggers)

    def test_rebuild_kept_foreign_keys_and_views(self) -> None:
        self.add_patient("ZY001")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO patient_assignment_history (patient_no, change_type)"
                " VALUES ('NOPE', 'claim')"
            )
        views = {
            row["name"] for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'view'")
        }
        self.assertEqual(views, EXPECTED_VIEWS)


class TestTimestamps(DbTestCase):
    """时间戳必须落在 UTC ISO8601 + 毫秒，且不得使用 datetime('now','localtime')。

    这是一条回归防线：SQLite 无时区概念，'localtime' 会按 UTC 计算再套本地偏移，
    在 +08:00 下写出比真实时间快 8 小时的脏时间戳（M0 阶段真实踩过，见 CHANGELOG）。
    """

    def setUp(self) -> None:
        super().setUp()
        self.migrate()

    def test_default_timestamp_is_utc_iso_with_millis(self) -> None:
        from datetime import datetime, timedelta

        self.add_user("T001")
        created = self.conn.execute("SELECT created_at FROM user").fetchone()[0]
        self.assertRegex(created, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", f"格式不符：{created}")

        # 与真实 UTC 时间相差不应超过 5 分钟（若误用 localtime，+08:00 下会差约 8 小时）
        parsed = datetime.strptime(created, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
        delta = abs(datetime.now(UTC) - parsed)
        self.assertLess(delta, timedelta(minutes=5), f"时间戳基准错误，偏差 {delta}")

    def test_updated_at_trigger_uses_utc_with_millis(self) -> None:
        # 2026-10-05：原来拿 appointment 验这条，排期表已随功能下线删除（008），
        # 之后改用 temporary_assignment，它又随临时指派功能删除（009）。
        # 现在改用 patient —— `trg_patient_updated_at` 同样无条件刷新 updated_at。
        self.add_patient("ZY001")
        self.conn.execute("UPDATE patient SET name = '改名' WHERE inpatient_no = 'ZY001'")
        updated = self.conn.execute(
            "SELECT updated_at FROM patient WHERE inpatient_no = 'ZY001'"
        ).fetchone()[0]
        self.assertRegex(updated, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

    def test_no_localtime_in_migration_sql(self) -> None:
        """迁移 SQL 中不得出现 datetime('now','localtime') 或 date('now','localtime')。"""
        for migration in storage.discover_migrations(settings=self.settings):
            sql = migration.path.read_text(encoding="utf-8")
            for line_no, line in enumerate(sql.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("--"):
                    continue  # 注释里提到它是为了警示，允许
                self.assertNotIn(
                    "'localtime'",
                    line,
                    f"{migration.path.name}:{line_no} 使用了 'localtime'，会写出错误的时间戳：{stripped}",
                )


class TestSqliteEnvironment(DbTestCase):
    def test_json1_available(self) -> None:
        self.assertTrue(storage.json1_available(self.conn))

    def test_foreign_keys_are_enforced(self) -> None:
        self.migrate()
        # 2026-10-05：原用 appointment 验外键，该表已删除；改用 treatment_record
        # （同样有 patient_no / therapist_id 两条外键）。
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO treatment_record (patient_no, therapist_id, record_date, discipline, kind, seq_no)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                ("NOT_EXIST", 999, "2026-10-05", "PT", "daily", 1),
            )

    def test_wal_mode_enabled(self) -> None:
        self.assertEqual(
            str(self.conn.execute("PRAGMA journal_mode").fetchone()[0]).lower(),
            "wal",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
