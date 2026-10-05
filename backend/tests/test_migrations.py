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
    # 2026-10-05：`appointment` / `rest_block` / `leave_record` 随排期功能下线一并删除。
    "audit_log",
    "auth_session",
    "change_log",
    "main_item",
    "option_item",
    "option_set",
    "patient",
    "patient_assignment_history",
    "record_item",
    "record_template",
    "record_template_item",
    "response_def",
    "schema_migrations",
    "sub_item",
    "sub_item_param_def",
    "temporary_assignment",
    "treatment_record",
    "user",
}

EXPECTED_VIEWS = {
    # `v_patient_next_appointment` → `v_patient_last_treated`（迁移 007/008）：
    # 患者列表排序依据从"下一个排期"换成"我最近一次已提交治疗"。
    "v_patient_last_treated",
    "v_open_temporary_assignment",
    "v_patient_visibility",
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
        # 2026-10-05：原来拿 appointment 验这条，排期表已随功能下线删除；
        # 改用 temporary_assignment（保留表，触发器同样只在状态变化时刷新 updated_at）。
        self.add_patient("ZY001")
        therapist = self.add_user("T001")
        cur = self.conn.execute(
            "INSERT INTO temporary_assignment"
            " (patient_no, original_therapist_id, date, period, status)"
            " VALUES ('ZY001', ?, '2026-10-05', 'am', 'open')",
            (therapist,),
        )
        temp_id = int(cur.lastrowid)
        self.conn.execute("UPDATE temporary_assignment SET status = 'closed' WHERE id = ?", (temp_id,))
        updated = self.conn.execute(
            "SELECT updated_at FROM temporary_assignment WHERE id = ?", (temp_id,)
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
        # 2026-10-05：原用 appointment 验外键，该表已删除；
        # 改用 treatment_record（同样有 patient_no / therapist_id 两条外键）。
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO treatment_record (patient_no, therapist_id, record_date)"
                " VALUES (?, ?, ?)",
                ("NOT_EXIST", 999, "2026-10-05"),
            )

    def test_wal_mode_enabled(self) -> None:
        self.assertEqual(
            str(self.conn.execute("PRAGMA journal_mode").fetchone()[0]).lower(),
            "wal",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
