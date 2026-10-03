"""FastAPI 骨架的接口测试（阶段 0 / T0.2、D08）。

覆盖点：
- `/api/v1/health` 与 `/health` 都可用，且**响应体结构与 M0 阶段一致**（前端不用改）；
- 库未初始化时健康检查返回 `degraded`、库不可用时返回 503（编排系统能正确判死）；
- **统一错误响应体**（D08）：404 / 405 都是 `{code, message, details}`，而不是 FastAPI 默认的 `{"detail": ...}`；
- 未预期异常返回 500 且**不泄露内部细节**；
- OpenAPI 文档可生成（客户端 SDK 与接口评审依赖它）。
"""

from __future__ import annotations

import json
import unittest

from app.core.errors import AppError, ConflictError, register_exception_handlers
from tests.api_base import ApiTestCase


class TestRootEndpoints(ApiTestCase):
    def test_root_returns_service_info(self) -> None:
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["api_prefix"], "/api/v1")
        self.assertEqual(body["docs"], "/docs")
        self.assertEqual(body["health"], "/api/v1/health")

    def test_openapi_schema_is_generated(self) -> None:
        resp = self.client.get("/openapi.json")
        self.assertEqual(resp.status_code, 200)
        schema = resp.json()
        self.assertIn("/api/v1/health", schema["paths"])
        self.assertIn("/health", schema["paths"])


class TestHealthEndpoint(ApiTestCase):
    def test_health_returns_ok_after_migration(self) -> None:
        self.migrate()
        resp = self.client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["database"]["json1"])
        self.assertTrue(body["database"]["foreign_keys"])
        self.assertEqual(body["database"]["pending_migrations"], [])

    def test_health_response_shape_unchanged_from_m0(self) -> None:
        """M0 时期前端与部署脚本依赖这些字段，迁移到 FastAPI 后不得改名。"""
        self.migrate()
        body = self.client.get("/api/v1/health").json()
        expected_keys = (
            "service",
            "version",
            "checked_at",
            "timezone",
            "database",
            "status",
            "worktime",
            "periods",
        )
        for key in expected_keys:
            self.assertIn(key, body)
        self.assertEqual(body["worktime"]["morning"]["start"], "06:00")
        self.assertEqual(body["worktime"]["afternoon"]["end"], "17:30")
        self.assertEqual(body["periods"]["am"]["label"], "上午")

    def test_unprefixed_health_is_available(self) -> None:
        """容器编排探活走 /health，不带版本前缀。"""
        self.migrate()
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_health_is_degraded_before_init(self) -> None:
        """库文件在但零迁移 → degraded（不是 503，服务本身可用）。"""
        resp = self.client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "degraded")
        self.assertEqual(body["database"]["schema_version"], 0)

    def test_health_returns_503_when_database_missing(self) -> None:
        """库不存在 → 503，让编排系统判定不可用。"""
        self.conn.close()
        self.db_file.unlink(missing_ok=True)
        resp = self.client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["status"], "down")

    def test_health_content_type_is_utf8_json(self) -> None:
        self.migrate()
        resp = self.client.get("/api/v1/health")
        self.assertIn("application/json", resp.headers["content-type"])
        # 中文必须可读（ensure_ascii=False），否则前端要额外解码
        self.assertIn("康复科", resp.content.decode("utf-8"))


class TestUnifiedErrorShape(ApiTestCase):
    """D08：所有错误出口必须是同一种结构。"""

    def test_unknown_path_is_structured_404(self) -> None:
        resp = self.client.get("/api/v1/does-not-exist")
        self.assertEqual(resp.status_code, 404)
        body = resp.json()
        self.assertEqual(body["code"], "NOT_FOUND")
        self.assertIn("message", body)
        self.assertIn("details", body)
        self.assertNotIn("detail", body, "不应出现 FastAPI 默认的 detail 字段")

    def test_method_not_allowed_is_structured_405(self) -> None:
        resp = self.client.post("/api/v1/health")
        self.assertEqual(resp.status_code, 405)
        body = resp.json()
        self.assertEqual(body["code"], "METHOD_NOT_ALLOWED")
        self.assertNotIn("detail", body)

    def test_validation_error_is_structured_422(self) -> None:
        """临时挂一个需要查询参数的路由，验证 422 也走统一格式。"""
        from fastapi import Query

        @self.app.get("/api/v1/_probe")
        def probe(page: int = Query(..., ge=1)) -> dict[str, int]:
            return {"page": page}

        resp = self.client.get("/api/v1/_probe", params={"page": 0})
        self.assertEqual(resp.status_code, 422)
        body = resp.json()
        self.assertEqual(body["code"], "VALIDATION_ERROR")
        self.assertIn("fields", body["details"])
        self.assertIn("page", body["details"]["fields"])

    def test_app_error_maps_to_status_and_code(self) -> None:
        @self.app.get("/api/v1/_conflict")
        def conflict() -> None:
            raise ConflictError("SLOT_TAKEN", "该半日已被占用", details={"date": "2026-10-05", "period": "am"})

        resp = self.client.get("/api/v1/_conflict")
        self.assertEqual(resp.status_code, 409)
        body = resp.json()
        self.assertEqual(body["code"], "SLOT_TAKEN")
        self.assertEqual(body["message"], "该半日已被占用")
        self.assertEqual(body["details"]["period"], "am")

    def test_unhandled_exception_returns_500_without_leaking_details(self) -> None:
        @self.app.get("/api/v1/_boom")
        def boom() -> None:
            raise RuntimeError("内部数据库连接串 postgres://secret")

        resp = self.client.get("/api/v1/_boom")
        self.assertEqual(resp.status_code, 500)
        body = resp.json()
        self.assertEqual(body["code"], "INTERNAL_ERROR")
        # 绝不把内部异常信息回给客户端
        self.assertNotIn("secret", json.dumps(body, ensure_ascii=False))
        self.assertNotIn("postgres", json.dumps(body, ensure_ascii=False))


class TestErrorHelpers(unittest.TestCase):
    def test_app_error_defaults(self) -> None:
        err = AppError("SOMETHING", "出错了", details={"a": 1})
        self.assertEqual(err.status_code, 400)
        self.assertEqual(err.to_payload(), {"code": "SOMETHING", "message": "出错了", "details": {"a": 1}})

    def test_app_error_status_override(self) -> None:
        err = AppError("X", "y", status_code=409)
        self.assertEqual(err.status_code, 409)

    def test_subclass_defaults(self) -> None:
        self.assertEqual(ConflictError().status_code, 409)
        self.assertEqual(ConflictError().code, "CONFLICT")

    def test_register_exception_handlers_is_idempotent_per_app(self) -> None:
        from fastapi import FastAPI

        app = FastAPI()
        register_exception_handlers(app)
        self.assertIn(AppError, app.exception_handlers)


if __name__ == "__main__":
    unittest.main(verbosity=2)
