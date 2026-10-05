"""健康检查（T0.3 验收）：把"能不能开工"变成可查询的事实。"""

from __future__ import annotations

import os
import unittest

from app.core.config import Settings, get_settings
from app.core.health import collect_health
from app.db import storage
from tests.support import DbTestCase


class TestHealthWithFreshDatabase(DbTestCase):
    def test_reports_degraded_before_init(self) -> None:
        """库文件在、但一个迁移都没跑：能打开，所以不是 down；但没表可用，必须是 degraded。"""
        payload = collect_health(self.settings)
        self.assertEqual(payload["status"], "degraded")
        self.assertTrue(payload["database"]["reachable"])
        self.assertEqual(payload["database"]["schema_version"], 0)
        self.assertTrue(any("迁移" in p for p in payload["database"]["problems"]))

    def test_reports_ok_after_migration(self) -> None:
        self.migrate()
        payload = collect_health(self.settings)
        self.assertEqual(payload["status"], "ok")
        db = payload["database"]
        self.assertTrue(db["reachable"])
        self.assertTrue(db["json1"])
        self.assertTrue(db["foreign_keys"])
        self.assertEqual(str(db["journal_mode"]).lower(), "wal")
        self.assertEqual(db["foreign_key_violations"], 0)
        self.assertEqual(db["pending_migrations"], [])
        self.assertEqual(db["problems"], [])
        # 2026-10-05：排期下线删掉 appointment / rest_block / leave_record 三张表，
        # 20 → 18。这里只做"迁移确实建了东西"的下界断言，不锁死具体数量。
        self.assertGreaterEqual(db["table_count"], 18)

    def test_health_exposes_q11_worktime(self) -> None:
        """前端排期页据此渲染半日边界，避免前端硬编码时间。"""
        self.migrate()
        payload = collect_health(self.settings)
        self.assertEqual(payload["worktime"]["morning"]["start"], "06:00")
        self.assertEqual(payload["worktime"]["morning"]["end"], "11:30")
        self.assertEqual(payload["worktime"]["afternoon"]["start"], "13:00")
        self.assertEqual(payload["worktime"]["afternoon"]["end"], "17:30")
        self.assertEqual(payload["periods"]["am"], {"label": "上午", "start": "06:00", "end": "11:30"})

    def test_health_has_no_worktime_when_disabled(self) -> None:
        self.migrate()
        payload = collect_health(self.settings, include_periods=False)
        self.assertNotIn("worktime", payload)

    def test_degraded_when_wal_disabled(self) -> None:
        """非 WAL 不是致命错误，但必须被标成 degraded 让人看见。"""
        self.migrate()
        self.conn.execute("PRAGMA journal_mode = DELETE")
        payload = collect_health(self.settings)
        self.assertEqual(payload["status"], "degraded")
        self.assertTrue(any("journal_mode" in p for p in payload["database"]["problems"]))

    def test_down_when_json1_missing(self) -> None:
        """JSON1 是 4.2 节硬依赖，不可用时必须拒绝服务。"""
        self.migrate()
        original = storage.json1_available
        storage.json1_available = lambda conn: False  # type: ignore[assignment]
        try:
            payload = collect_health(self.settings)
        finally:
            storage.json1_available = original  # type: ignore[assignment]
        self.assertEqual(payload["status"], "down")
        self.assertTrue(any("JSON1" in p for p in payload["database"]["problems"]))


class TestHealthPayloadShape(DbTestCase):
    def test_payload_has_expected_keys(self) -> None:
        self.migrate()
        payload = collect_health(self.settings)
        for key in ("service", "version", "checked_at", "timezone", "database", "status", "worktime", "periods"):
            self.assertIn(key, payload)

    def test_settings_singleton_can_be_reset(self) -> None:
        first = get_settings()
        get_settings.cache_clear()
        self.assertIsNot(first, get_settings())


class TestSettingsFromEnv(unittest.TestCase):
    """配置错误要早暴露：非法数值不能静默回退成默认值。"""

    def tearDown(self) -> None:
        for key in ("KB_SQLITE_BUSY_TIMEOUT_MS", "KB_SQLITE_WAL", "KB_DB_PATH"):
            os.environ.pop(key, None)
        get_settings.cache_clear()

    def test_defaults(self) -> None:
        settings = Settings()
        self.assertEqual(settings.sqlite_busy_timeout_ms, 5000)
        self.assertTrue(settings.sqlite_wal)
        self.assertEqual(settings.api_prefix, "/api/v1")
        self.assertEqual(settings.timezone, "Asia/Shanghai")

    def test_invalid_int_env_raises(self) -> None:
        os.environ["KB_SQLITE_BUSY_TIMEOUT_MS"] = "abc"
        get_settings.cache_clear()
        with self.assertRaises(ValueError):
            get_settings()

    def test_env_overrides_are_applied(self) -> None:
        os.environ["KB_SQLITE_BUSY_TIMEOUT_MS"] = "1500"
        os.environ["KB_SQLITE_WAL"] = "off"
        settings = Settings()
        self.assertEqual(settings.sqlite_busy_timeout_ms, 1500)
        self.assertFalse(settings.sqlite_wal)


if __name__ == "__main__":
    unittest.main(verbosity=2)
