"""refresh token 的 httpOnly Cookie 通道（管理后台 Web 用）。

> 2026-10-05：本文件原为 `test_dict_admin_and_cookies.py`，前半部分是**字典管理写接口**
> 测试（`/api/v1/dict/**`）。记录改 SOAP 模板驱动后，字典六张表随迁移 012 删除、
> 字典读写接口整组删除，那部分用例已无被测对象；**Cookie 这一半原样保留下来**
> （它与记录模型无关，且是管理后台登录态的关键回归）。
"""

from __future__ import annotations

import unittest

from tests.api_base import ApiTestCase


class TestCookieAuth(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.user = self.make_user("T001", "张三")
        self.cookie_name = self.settings.refresh_cookie_name

    def test_login_sets_httponly_cookie(self) -> None:
        resp = self.client.post(
            "/api/v1/auth/login", json={"employee_no": "T001", "password": self.password}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn(self.cookie_name, resp.cookies)
        # 响应体仍带 refresh_token（安卓端继续用），协议未破坏
        self.assertIn("refresh_token", resp.json())

    def test_cookie_attributes(self) -> None:
        resp = self.client.post(
            "/api/v1/auth/login", json={"employee_no": "T001", "password": self.password}
        )
        header = resp.headers.get("set-cookie", "")
        self.assertIn("HttpOnly", header, "必须是 HttpOnly，否则 XSS 能偷走长期凭证")
        self.assertIn("Path=/api/v1/auth", header, "限定路径以缩小暴露面")
        self.assertIn("SameSite=lax", header)

    def test_refresh_with_cookie_only(self) -> None:
        """Web 端不传 refresh_token，只靠 Cookie 就能刷新。"""
        self.client.post("/api/v1/auth/login", json={"employee_no": "T001", "password": self.password})
        resp = self.client.post("/api/v1/auth/refresh", json={})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("access_token", resp.json())

    def test_refresh_without_any_token_is_400(self) -> None:
        resp = self.client.post("/api/v1/auth/refresh", json={})
        self.assert_error(resp, 400, "MISSING_REFRESH_TOKEN")

    def test_cookie_takes_precedence_over_body(self) -> None:
        """两者同时存在时以 Cookie 为准。

        这样管理后台不必把 refresh token 交给 JS，同时安卓端协议不变。
        """
        login = self.client.post(
            "/api/v1/auth/login", json={"employee_no": "T001", "password": self.password}
        ).json()
        cookie_token = self.client.cookies.get(self.cookie_name)
        self.assertIsNotNone(cookie_token)
        # 请求体塞一个无效值；Cookie 有效 → 应该成功（说明用的是 Cookie）
        resp = self.client.post("/api/v1/auth/refresh", json={"refresh_token": "invalid.token.value"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertNotEqual(resp.json()["refresh_token"], login["refresh_token"], "应发生轮换")

    def test_logout_clears_cookie(self) -> None:
        login = self.client.post(
            "/api/v1/auth/login", json={"employee_no": "T001", "password": self.password}
        ).json()
        headers = {"Authorization": f"Bearer {login['access_token']}"}
        resp = self.client.post("/api/v1/auth/logout", headers=headers)
        self.assertEqual(resp.status_code, 204, resp.text)
        header = resp.headers.get("set-cookie", "")
        self.assertIn(self.cookie_name, header)
        self.assertTrue("Max-Age=0" in header or "max-age=0" in header, header)

    def test_logout_revokes_cookie_token(self) -> None:
        login = self.client.post(
            "/api/v1/auth/login", json={"employee_no": "T001", "password": self.password}
        ).json()
        cookie_token = self.client.cookies.get(self.cookie_name)
        headers = {"Authorization": f"Bearer {login['access_token']}"}
        self.client.post("/api/v1/auth/logout", headers=headers)
        self.clear_cookies()
        resp = self.client.post("/api/v1/auth/refresh", json={"refresh_token": cookie_token})
        self.assert_error(resp, 403, "REFRESH_REVOKED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
