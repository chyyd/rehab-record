"""API 测试基类：在临时库上构造应用实例，并提供登录与带鉴权的请求辅助方法。

把"怎么拿 token"这一步收在一处，好处是**测试自己不会绕开鉴权**——
所有需要认证的请求都必须显式用某个身份的 headers，越权用例也因此写得出来。
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.main import create_app
from app.models import user as user_model
from tests.support import DbTestCase

DEFAULT_PASSWORD = "Therapist#2026"


class ApiTestCase(DbTestCase):
    """在临时库上构建独立的应用实例，并把配置指向该临时库。

    关键点：`create_app()` 内部的 `get_db` 依赖解析的是 `get_settings()`，
    而 `DbTestCase.setUp` 已把 `KB_DB_PATH` 指向临时库 —— 所以接口看到的就是测试库。
    """

    password: str = DEFAULT_PASSWORD

    def setUp(self) -> None:
        super().setUp()
        self.app = create_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)

    # -- 用户与登录 -------------------------------------------------------- #
    def make_user(
        self,
        employee_no: str = "T001",
        name: str = "张三",
        role: str = user_model.ROLE_THERAPIST,
        password: str | None = None,
    ) -> dict[str, Any]:
        """直接建用户（绕过接口），用于准备测试数据。"""
        return user_model.create_user(
            self.conn,
            employee_no=employee_no,
            name=name,
            role=role,
            password=password if password is not None else self.password,
        )

    def make_admin(self, employee_no: str = "A001", name: str = "管理员") -> dict[str, Any]:
        return self.make_user(employee_no, name, role=user_model.ROLE_ADMIN)

    def login_headers(self, employee_no: str, password: str | None = None) -> dict[str, str]:
        """走真实登录接口拿 token，返回可直接用于请求的 headers。"""
        resp = self.client.post(
            "/api/v1/auth/login",
            json={"employee_no": employee_no, "password": password if password is not None else self.password},
        )
        assert resp.status_code == 200, f"登录失败：{resp.status_code} {resp.text}"
        token = resp.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def login_tokens(self, employee_no: str, password: str | None = None) -> dict[str, Any]:
        resp = self.client.post(
            "/api/v1/auth/login",
            json={"employee_no": employee_no, "password": password if password is not None else self.password},
        )
        assert resp.status_code == 200, f"登录失败：{resp.status_code} {resp.text}"
        return resp.json()

    def clear_cookies(self) -> None:
        """清掉测试客户端携带的 Cookie。

        登录接口会给浏览器写 httpOnly 的 refresh Cookie，而 `TestClient` 会**记住**它并
        自动随后续请求发送。于是"请求体里的 refresh token"这一类测试会被 Cookie 里的
        有效凭证抢先命中（服务端 Cookie 优先，这是正确行为），断言就不再检验它本意要测的路径。
        凡是针对**请求体路径**的断言，先调本方法隔离 Cookie。
        """
        self.client.cookies.clear()

    # -- 便捷断言 ---------------------------------------------------------- #
    def assert_error(self, resp: Any, status_code: int, code: str | None = None) -> dict[str, Any]:
        """断言响应是 D08 的统一错误结构。"""
        self.assertEqual(resp.status_code, status_code, f"{resp.status_code} {resp.text}")
        body = resp.json()
        self.assertIn("code", body)
        self.assertIn("message", body)
        self.assertIn("details", body)
        self.assertNotIn("detail", body, "不应出现 FastAPI 默认的 detail 字段")
        if code is not None:
            self.assertEqual(body["code"], code, body)
        return body


__all__ = ["ApiTestCase", "DEFAULT_PASSWORD"]
