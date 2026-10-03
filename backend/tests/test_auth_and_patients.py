"""阶段 1 测试：认证、用户管理、患者与归属（`开发计划.md` 阶段 1）。

覆盖重点是**权限边界**——这类 bug 不会让系统崩，但会让治疗师看到别人的患者，
或让无关的人改到别人的数据，属于必须逐条钉死的用例。

用例分组：
1. 登录 / 令牌（含 refresh 轮换、类型混用、停用账号）
2. 用户管理权限（管理员专属、不许消灭最后一个管理员）
3. 患者数据级权限（D10：治疗师只能看自己/未分配/临时相关）
4. 归属变更（认领 / 放弃 / 管理员指定 / 归属历史）
5. 归属解析可见归属（单日假临时释放与临时认领）
"""

from __future__ import annotations

import unittest
from datetime import date

from app.core import security
from app.core.clock import period_expiry
from app.core.config import WorkTimeConfig
from app.models import patient as patient_model
from app.models import user as user_model
from tests.api_base import DEFAULT_PASSWORD, ApiTestCase


class TestLogin(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.therapist = self.make_user("T001", "张三")

    def test_login_success_returns_tokens_and_user(self) -> None:
        resp = self.client.post(
            "/api/v1/auth/login", json={"employee_no": "T001", "password": DEFAULT_PASSWORD}
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("access_token", body)
        self.assertIn("refresh_token", body)
        self.assertEqual(body["token_type"], "bearer")
        self.assertGreater(body["expires_in"], 0)
        self.assertEqual(body["user"]["employee_no"], "T001")
        self.assertEqual(body["user"]["role"], "therapist")

    def test_login_never_leaks_password_hash(self) -> None:
        resp = self.client.post(
            "/api/v1/auth/login", json={"employee_no": "T001", "password": DEFAULT_PASSWORD}
        )
        self.assertNotIn("password_hash", resp.text)
        self.assertNotIn("argon2", resp.text)

    def test_wrong_password_and_unknown_user_give_same_message(self) -> None:
        """不能把工号变成可枚举的信息。"""
        wrong_pw = self.client.post(
            "/api/v1/auth/login", json={"employee_no": "T001", "password": "wrong-password"}
        )
        no_user = self.client.post(
            "/api/v1/auth/login", json={"employee_no": "NOPE", "password": DEFAULT_PASSWORD}
        )
        self.assertEqual(wrong_pw.status_code, 403)
        self.assertEqual(no_user.status_code, 403)
        self.assertEqual(wrong_pw.json()["message"], no_user.json()["message"])

    def test_empty_password_hash_cannot_login(self) -> None:
        """没有设置密码的账号不能靠空哈希蒙过去。"""
        self.make_user("T002", "李四", password=None)
        resp = self.client.post(
            "/api/v1/auth/login", json={"employee_no": "T002", "password": ""}
        )
        self.assertIn(resp.status_code, {403, 422})

    def test_disabled_account_cannot_login(self) -> None:
        user_model.update_user(self.conn, int(self.therapist["id"]), status=user_model.STATUS_DISABLED)
        resp = self.client.post(
            "/api/v1/auth/login", json={"employee_no": "T001", "password": DEFAULT_PASSWORD}
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["code"], "ACCOUNT_DISABLED")

    def test_login_is_audited(self) -> None:
        self.client.post("/api/v1/auth/login", json={"employee_no": "T001", "password": DEFAULT_PASSWORD})
        row = self.conn.execute(
            "SELECT action, target_type FROM audit_log WHERE action = 'login'"
        ).fetchone()
        self.assertIsNotNone(row, "登录必须留痕")
        self.assertEqual(row["target_type"], "user")

    def test_validation_error_on_missing_fields(self) -> None:
        resp = self.client.post("/api/v1/auth/login", json={"employee_no": "T001"})
        self.assert_error(resp, 422, "VALIDATION_ERROR")


class TestAuthenticationRequired(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.migrate()

    def test_me_without_token_is_401(self) -> None:
        resp = self.client.get("/api/v1/auth/me")
        body = self.assert_error(resp, 401, "AUTH_REQUIRED")
        self.assertIn("WWW-Authenticate", resp.headers)
        self.assertIn("header", body["details"])

    def test_garbage_token_is_401(self) -> None:
        resp = self.client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
        self.assert_error(resp, 401, "TOKEN_INVALID")

    def test_refresh_token_cannot_be_used_as_access_token(self) -> None:
        """典型漏洞：refresh token 被当 access token 用。必须按类型拒绝。"""
        self.make_user("T001")
        tokens = self.login_tokens("T001")
        resp = self.client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}
        )
        self.assert_error(resp, 401, "TOKEN_WRONG_TYPE")

    def test_disabled_user_token_becomes_invalid_immediately(self) -> None:
        user = self.make_user("T001")
        headers = self.login_headers("T001")
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=headers).status_code, 200)

        user_model.update_user(self.conn, int(user["id"]), status=user_model.STATUS_DISABLED)
        resp = self.client.get("/api/v1/auth/me", headers=headers)
        self.assert_error(resp, 401, "ACCOUNT_DISABLED")


class TestTokenRefresh(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.make_user("T001")

    def test_refresh_rotates_and_old_token_stops_working(self) -> None:
        tokens = self.login_tokens("T001")
        self.clear_cookies()
        first = self.client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        self.assertEqual(first.status_code, 200)
        new_refresh = first.json()["refresh_token"]
        self.assertNotEqual(new_refresh, tokens["refresh_token"])

        # 轮换后旧 token 的会话已被标记吊销，再次使用必须失败
        self.clear_cookies()
        replay = self.client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        self.assert_error(replay, 403, "REFRESH_REVOKED")

        # 新 token 可用
        self.clear_cookies()
        again = self.client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
        self.assertEqual(again.status_code, 200)

    def test_access_token_cannot_be_used_to_refresh(self) -> None:
        tokens = self.login_tokens("T001")
        # 清掉登录写入的 httpOnly Cookie，确保测的是**请求体**路径
        self.clear_cookies()
        resp = self.client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]})
        self.assert_error(resp, 403, "TOKEN_WRONG_TYPE")

    def test_logout_revokes_refresh_token(self) -> None:
        tokens = self.login_tokens("T001")
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        out = self.client.post(
            "/api/v1/auth/logout",
            params={"refresh_token": tokens["refresh_token"]},
            headers=headers,
        )
        self.assertEqual(out.status_code, 204)
        self.clear_cookies()
        after = self.client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        self.assert_error(after, 403)

    def test_logout_without_token_revokes_all_sessions(self) -> None:
        first = self.login_tokens("T001")
        second = self.login_tokens("T001")
        headers = {"Authorization": f"Bearer {first['access_token']}"}
        # 必须清 Cookie：否则 logout 会从 Cookie 取到 `second` 的 refresh token，
        # 只吊销那一个会话（这是正确的 Cookie 优先语义），就测不到"不传 token 时吊销全部"。
        self.clear_cookies()
        self.assertEqual(self.client.post("/api/v1/auth/logout", headers=headers).status_code, 204)
        for tokens in (first, second):
            resp = self.client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
            self.assert_error(resp, 403, "REFRESH_REVOKED")

    def test_change_password_invalidates_sessions(self) -> None:
        tokens = self.login_tokens("T001")
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        resp = self.client.put(
            "/api/v1/auth/password",
            json={"old_password": DEFAULT_PASSWORD, "new_password": "BrandNew#2026"},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 204)
        # 旧 refresh token 失效
        self.assert_error(
            self.client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}), 403
        )
        # 新密码可登录
        self.login_headers("T001", "BrandNew#2026")

    def test_change_password_requires_correct_old_password(self) -> None:
        headers = self.login_headers("T001")
        resp = self.client.put(
            "/api/v1/auth/password",
            json={"old_password": "not-the-password", "new_password": "BrandNew#2026"},
            headers=headers,
        )
        self.assert_error(resp, 400, "OLD_PASSWORD_WRONG")


class TestPasswordHashing(ApiTestCase):
    """不依赖接口的纯函数级验证。"""

    def test_hash_and_verify_roundtrip(self) -> None:
        encoded = security.hash_password("s3cret-password")
        self.assertTrue(security.verify_password("s3cret-password", encoded))
        self.assertFalse(security.verify_password("wrong", encoded))

    def test_hash_is_salted(self) -> None:
        self.assertNotEqual(security.hash_password("same"), security.hash_password("same"))

    def test_verify_rejects_empty_and_none(self) -> None:
        """空哈希绝不能变成"万能密码"。"""
        self.assertFalse(security.verify_password("anything", None))
        self.assertFalse(security.verify_password("anything", ""))
        self.assertFalse(security.verify_password("", security.hash_password("x")))

    def test_verify_handles_corrupt_hash_gracefully(self) -> None:
        for bad in ("garbage", "$argon2$broken", "scrypt$n=1,r=1,p=1$!!!$!!!"):
            self.assertFalse(security.verify_password("x", bad))

    def test_uses_argon2_when_available(self) -> None:
        """环境里装了 argon2-cffi，就应该用它（比 scrypt 抗 GPU 更好）。"""
        if not security.argon2_available():
            self.skipTest("未安装 argon2-cffi")
        self.assertTrue(security.hash_password("x").startswith("$argon2"))


class TestUserManagement(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.admin = self.make_admin("A001")
        self.therapist = self.make_user("T001", "张三")

    def test_admin_can_create_and_list_users(self) -> None:
        headers = self.login_headers("A001")
        resp = self.client.post(
            "/api/v1/users",
            json={"employee_no": "T002", "name": "李四", "role": "therapist", "password": "Another#2026"},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertEqual(resp.json()["employee_no"], "T002")
        self.assertNotIn("password_hash", resp.text)

        listed = self.client.get("/api/v1/users", headers=headers)
        self.assertEqual(listed.status_code, 200)
        self.assertGreaterEqual(listed.json()["total"], 3)

    def test_therapist_cannot_access_user_management(self) -> None:
        headers = self.login_headers("T001")
        self.assert_error(self.client.get("/api/v1/users", headers=headers), 403, "ADMIN_REQUIRED")
        self.assert_error(
            self.client.post(
                "/api/v1/users",
                json={"employee_no": "X", "name": "X", "role": "therapist"},
                headers=headers,
            ),
            403,
            "ADMIN_REQUIRED",
        )

    def test_duplicate_employee_no_rejected(self) -> None:
        headers = self.login_headers("A001")
        resp = self.client.post(
            "/api/v1/users",
            json={"employee_no": "T001", "name": "重复", "role": "therapist"},
            headers=headers,
        )
        self.assert_error(resp, 409)

    def test_cannot_demote_last_active_admin(self) -> None:
        """把最后一个管理员降级会让系统没人能管理。"""
        headers = self.login_headers("A001")
        resp = self.client.put(
            f"/api/v1/users/{self.admin['id']}", json={"role": "therapist"}, headers=headers
        )
        self.assert_error(resp, 409)

    def test_can_demote_admin_when_another_exists(self) -> None:
        self.make_admin("A002", "第二管理员")
        headers = self.login_headers("A001")
        resp = self.client.put(
            f"/api/v1/users/{self.admin['id']}", json={"role": "therapist"}, headers=headers
        )
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_unknown_user_is_404(self) -> None:
        headers = self.login_headers("A001")
        self.assert_error(self.client.get("/api/v1/users/9999", headers=headers), 404, "USER_NOT_FOUND")

    def test_reset_password_lets_user_login_with_new_password(self) -> None:
        headers = self.login_headers("A001")
        resp = self.client.post(
            f"/api/v1/users/{self.therapist['id']}/reset-password",
            json={"new_password": "Reset#2026x"},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 204)
        self.login_headers("T001", "Reset#2026x")

    def test_therapist_can_only_revoke_own_sessions(self) -> None:
        headers = self.login_headers("T001")
        resp = self.client.delete(f"/api/v1/users/{self.admin['id']}/sessions", headers=headers)
        self.assert_error(resp, 403)
        own = self.client.delete(f"/api/v1/users/{self.therapist['id']}/sessions", headers=headers)
        self.assertEqual(own.status_code, 204)


class TestPatientVisibility(ApiTestCase):
    """D10：数据级权限。治疗师可见 = 归属自己 ∪ 临时认领自己 ∪ 未分配 ∪ 与我有关的临时指派。"""

    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.t1 = self.make_user("T001", "张三")
        self.t2 = self.make_user("T002", "李四")
        self.admin = self.make_admin("A001")
        self.mine = patient_model.create_patient(
            self.conn, inpatient_no="ZY001", name="我的患者", assigned_therapist_id=int(self.t1["id"])
        )
        self.others = patient_model.create_patient(
            self.conn, inpatient_no="ZY002", name="别人的患者", assigned_therapist_id=int(self.t2["id"])
        )
        self.free = patient_model.create_patient(self.conn, inpatient_no="ZY003", name="未分配患者")

    def test_therapist_sees_only_allowed_patients(self) -> None:
        headers = self.login_headers("T001")
        resp = self.client.get("/api/v1/patients", headers=headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        numbers = {item["inpatient_no"] for item in resp.json()["items"]}
        self.assertEqual(numbers, {"ZY001", "ZY003"}, "不应看到别人的患者")

    def test_scope_mine_and_unassigned(self) -> None:
        headers = self.login_headers("T001")
        mine = self.client.get("/api/v1/patients", params={"scope": "mine"}, headers=headers).json()
        self.assertEqual({i["inpatient_no"] for i in mine["items"]}, {"ZY001"})
        free = self.client.get("/api/v1/patients", params={"scope": "unassigned"}, headers=headers).json()
        self.assertEqual({i["inpatient_no"] for i in free["items"]}, {"ZY003"})

    def test_therapist_cannot_use_scope_all(self) -> None:
        headers = self.login_headers("T001")
        resp = self.client.get("/api/v1/patients", params={"scope": "all"}, headers=headers)
        self.assert_error(resp, 403, "SCOPE_FORBIDDEN")

    def test_admin_sees_all_patients(self) -> None:
        headers = self.login_headers("A001")
        resp = self.client.get("/api/v1/patients", params={"scope": "all"}, headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 3)

    def test_therapist_cannot_read_others_patient_detail(self) -> None:
        headers = self.login_headers("T001")
        resp = self.client.get("/api/v1/patients/ZY002", headers=headers)
        self.assert_error(resp, 403, "PATIENT_NOT_VISIBLE")

    def test_therapist_cannot_see_others_assignment_history(self) -> None:
        headers = self.login_headers("T001")
        self.assert_error(self.client.get("/api/v1/patients/ZY002/assignments", headers=headers), 403)

    def test_unknown_patient_is_404_for_admin(self) -> None:
        headers = self.login_headers("A001")
        self.assert_error(self.client.get("/api/v1/patients/NOPE", headers=headers), 404, "PATIENT_NOT_FOUND")

    def test_patient_list_puts_mine_first(self) -> None:
        """设计.md 3.4.3：我的患者优先。"""
        headers = self.login_headers("T001")
        items = self.client.get("/api/v1/patients", headers=headers).json()["items"]
        self.assertEqual(items[0]["inpatient_no"], "ZY001", "我的患者应排在最前")
        self.assertEqual(items[1]["inpatient_no"], "ZY003", "其次应是未分配")


class TestPatientWritePermissions(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.t1 = self.make_user("T001", "张三")
        self.t2 = self.make_user("T002", "李四")
        self.make_admin("A001")

    def test_only_admin_creates_patients(self) -> None:
        headers = self.login_headers("T001")
        resp = self.client.post(
            "/api/v1/patients", json={"inpatient_no": "ZY100", "name": "新患者"}, headers=headers
        )
        self.assert_error(resp, 403, "ADMIN_REQUIRED")

    def test_admin_creates_patient_with_assignment_recorded(self) -> None:
        headers = self.login_headers("A001")
        resp = self.client.post(
            "/api/v1/patients",
            json={
                "inpatient_no": "ZY100",
                "name": "新患者",
                "diagnosis": "脑卒中",
                "admin_note": "左侧偏瘫，注意跌倒",
                "assigned_therapist_id": int(self.t1["id"]),
            },
            headers=headers,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual(body["visible_therapist_id"], int(self.t1["id"]))
        history = self.conn.execute(
            "SELECT change_type FROM patient_assignment_history WHERE patient_no = 'ZY100'"
        ).fetchall()
        self.assertEqual([r["change_type"] for r in history], ["admin_assign"])

    def test_therapist_cannot_edit_patient(self) -> None:
        patient_model.create_patient(
            self.conn, inpatient_no="ZY001", name="患者", assigned_therapist_id=int(self.t1["id"])
        )
        headers = self.login_headers("T001")
        resp = self.client.put(
            "/api/v1/patients/ZY001", json={"admin_note": "偷偷改注意事项"}, headers=headers
        )
        self.assert_error(resp, 403, "ADMIN_REQUIRED")

    def test_admin_can_edit_admin_note(self) -> None:
        patient_model.create_patient(self.conn, inpatient_no="ZY001", name="患者")
        headers = self.login_headers("A001")
        resp = self.client.put(
            "/api/v1/patients/ZY001", json={"admin_note": "注意跌倒"}, headers=headers
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["admin_note"], "注意跌倒")

    def test_discharge_is_irreversible(self) -> None:
        """Q9：出院不可逆。"""
        patient_model.create_patient(
            self.conn, inpatient_no="ZY001", name="患者", status=patient_model.STATUS_DISCHARGED
        )
        headers = self.login_headers("A001")
        resp = self.client.put("/api/v1/patients/ZY001", json={"status": "in_hospital"}, headers=headers)
        self.assert_error(resp, 403, "PATIENT_DISCHARGED_IMMUTABLE")

    def test_cannot_create_already_discharged_patient(self) -> None:
        headers = self.login_headers("A001")
        resp = self.client.post(
            "/api/v1/patients",
            json={"inpatient_no": "ZY200", "name": "患者", "status": "discharged"},
            headers=headers,
        )
        self.assert_error(resp, 403, "PATIENT_DISCHARGED_IMMUTABLE")

    def test_invalid_status_rejected(self) -> None:
        headers = self.login_headers("A001")
        resp = self.client.post(
            "/api/v1/patients",
            json={"inpatient_no": "ZY201", "name": "患者", "status": "在院"},
            headers=headers,
        )
        # 状态是英文码，中文属于非法取值
        self.assert_error(resp, 409)


class TestClaimAndAssignment(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.t1 = self.make_user("T001", "张三")
        self.t2 = self.make_user("T002", "李四")
        self.make_admin("A001")
        self.free = patient_model.create_patient(self.conn, inpatient_no="ZY003", name="未分配")

    def test_claim_unassigned_patient(self) -> None:
        headers = self.login_headers("T001")
        resp = self.client.post("/api/v1/patients/claim", params={"inpatient_no": "ZY003"}, headers=headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["assigned_therapist_id"], int(self.t1["id"]))
        history = self.conn.execute(
            "SELECT change_type FROM patient_assignment_history WHERE patient_no = 'ZY003'"
        ).fetchall()
        self.assertEqual([r["change_type"] for r in history], ["claim"])

    def test_cannot_claim_others_patient(self) -> None:
        patient_model.create_patient(
            self.conn, inpatient_no="ZY002", name="别人的", assigned_therapist_id=int(self.t1["id"])
        )
        headers = self.login_headers("T002")
        resp = self.client.post("/api/v1/patients/claim", params={"inpatient_no": "ZY002"}, headers=headers)
        self.assert_error(resp, 409)

    def test_release_own_patient(self) -> None:
        patient_model.create_patient(
            self.conn, inpatient_no="ZY001", name="我的", assigned_therapist_id=int(self.t1["id"])
        )
        headers = self.login_headers("T001")
        resp = self.client.post("/api/v1/patients/ZY001/release", headers=headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIsNone(resp.json()["assigned_therapist_id"])

    def test_cannot_release_others_patient(self) -> None:
        patient_model.create_patient(
            self.conn, inpatient_no="ZY001", name="张三的", assigned_therapist_id=int(self.t1["id"])
        )
        headers = self.login_headers("T002")
        self.assert_error(self.client.post("/api/v1/patients/ZY001/release", headers=headers), 403)

    def test_admin_can_assign_and_clear(self) -> None:
        patient_model.create_patient(self.conn, inpatient_no="ZY001", name="患者")
        headers = self.login_headers("A001")
        assigned = self.client.post(
            "/api/v1/patients/ZY001/assign", json={"therapist_id": int(self.t2["id"])}, headers=headers
        )
        self.assertEqual(assigned.status_code, 200, assigned.text)
        self.assertEqual(assigned.json()["assigned_therapist_id"], int(self.t2["id"]))

        cleared = self.client.post(
            "/api/v1/patients/ZY001/assign", json={"therapist_id": None}, headers=headers
        )
        self.assertIsNone(cleared.json()["assigned_therapist_id"])
        types = [
            r["change_type"]
            for r in self.conn.execute(
                "SELECT change_type FROM patient_assignment_history WHERE patient_no = 'ZY001' ORDER BY id"
            ).fetchall()
        ]
        self.assertEqual(types, ["admin_assign", "admin_assign"])

    def test_assign_to_unknown_therapist_rejected(self) -> None:
        patient_model.create_patient(self.conn, inpatient_no="ZY001", name="患者")
        headers = self.login_headers("A001")
        resp = self.client.post(
            "/api/v1/patients/ZY001/assign", json={"therapist_id": 9999}, headers=headers
        )
        self.assert_error(resp, 404, "USER_NOT_FOUND")

    def test_therapist_cannot_assign(self) -> None:
        """assign 是管理员接口，治疗师走 claim。"""
        headers = self.login_headers("T001")
        resp = self.client.post(
            "/api/v1/patients/ZY003/assign", json={"therapist_id": int(self.t1["id"])}, headers=headers
        )
        self.assert_error(resp, 403, "ADMIN_REQUIRED")


class TestVisibleTherapistResolution(ApiTestCase):
    """M09 / 3.5.5：单日假临时释放与临时认领期间的归属解析。

    这是本系统最关键的一条业务规则，用模型层直接验证（不经过 HTTP）。
    """

    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.original = self.make_user("T001", "原归属")
        self.cover = self.make_user("T002", "临时接管")
        self.patient_no = "ZY001"
        patient_model.create_patient(
            self.conn, inpatient_no=self.patient_no, name="患者",
            assigned_therapist_id=int(self.original["id"]),
        )

    def _open_temp(self, temporary_therapist_id: int | None, period: str = "am") -> int:
        # 必须用与模型一致的 UTC+毫秒格式（core.clock.period_expiry）；
        # 写成 '2026-10-05 11:30:00' 会因为 ' ' < 'T' 而被判定成"已过期"
        expires = period_expiry(date(2026, 10, 5), period, WorkTimeConfig())
        cur = self.conn.execute(
            "INSERT INTO temporary_assignment"
            " (patient_no, original_therapist_id, temporary_therapist_id, date, period, expires_at)"
            " VALUES (?, ?, ?, '2026-10-05', ?, ?)",
            (self.patient_no, self.original["id"], temporary_therapist_id, period, expires),
        )
        return int(cur.lastrowid)

    def test_plain_assignment_visible_is_original(self) -> None:
        patient = patient_model.get_patient_or_raise(self.conn, self.patient_no)
        self.assertEqual(patient["visible_therapist_id"], int(self.original["id"]))
        self.assertEqual(patient["visibility_state"], "assigned")

    def test_temp_release_keeps_original_but_hides_visibility(self) -> None:
        """临时释放：原归属不变，可见归属变为 NULL。"""
        self._open_temp(None)
        patient = patient_model.get_patient_or_raise(self.conn, self.patient_no)
        self.assertEqual(patient["assigned_therapist_id"], int(self.original["id"]), "原归属不得修改")
        self.assertIsNone(patient["visible_therapist_id"])
        self.assertEqual(patient["visibility_state"], "temp_released")

    def test_temp_claim_sets_visible_to_claimer(self) -> None:
        self._open_temp(int(self.cover["id"]))
        patient = patient_model.get_patient_or_raise(self.conn, self.patient_no)
        self.assertEqual(patient["assigned_therapist_id"], int(self.original["id"]), "原归属不得修改")
        self.assertEqual(patient["visible_therapist_id"], int(self.cover["id"]))
        self.assertEqual(patient["visibility_state"], "temp_claimed")

    def test_expired_temp_assignment_is_ignored(self) -> None:
        """读时兜底：即使定时清理没跑，过期的临时指派也不能影响归属（R8）。"""
        temp_id = self._open_temp(None)
        self.conn.execute(
            "UPDATE temporary_assignment SET expires_at = '2020-01-01T00:00:00.000Z' WHERE id = ?",
            (temp_id,),
        )
        patient = patient_model.get_patient_or_raise(self.conn, self.patient_no)
        self.assertEqual(patient["visible_therapist_id"], int(self.original["id"]), "过期应回落到原归属")
        self.assertEqual(patient["visibility_state"], "assigned")

    def test_closed_temp_assignment_is_ignored(self) -> None:
        temp_id = self._open_temp(None)
        self.conn.execute("UPDATE temporary_assignment SET status = 'closed' WHERE id = ?", (temp_id,))
        patient = patient_model.get_patient_or_raise(self.conn, self.patient_no)
        self.assertEqual(patient["visible_therapist_id"], int(self.original["id"]))

    def test_temp_released_patient_cannot_be_claimed_formally(self) -> None:
        """临时释放中的患者要走 temp-claim，不能直接把原归属改掉。"""
        self._open_temp(None)
        from app.models.base import Conflict

        with self.assertRaises(Conflict) as ctx:
            patient_model.claim_patient(self.conn, self.patient_no, int(self.cover["id"]))
        self.assertEqual(ctx.exception.details.get("hint"), "temp-claim")

    def test_scheduling_permission_follows_visible_therapist(self) -> None:
        """Q3：排期权限看**可见归属**，不看原归属。"""
        # 正常情况：原归属者可以排
        self.assertTrue(patient_model.can_schedule(self.conn, self.patient_no, int(self.original["id"])))

        # 临时释放后：可见归属变成 NULL（未分配），因此**任何人都可排**——
        # 这正是"临时释放"的意义：原归属者休假，患者不能被"锁死"在一个不在岗的人名下。
        self._open_temp(None)
        self.assertIsNone(
            patient_model.get_patient_or_raise(self.conn, self.patient_no)["visible_therapist_id"]
        )
        self.assertTrue(patient_model.can_schedule(self.conn, self.patient_no, int(self.original["id"])))
        self.assertTrue(patient_model.can_schedule(self.conn, self.patient_no, int(self.cover["id"])))

        # 被临时认领后：只有认领者能排，原归属者与其他人都不能
        self.conn.execute(
            "UPDATE temporary_assignment SET temporary_therapist_id = ? WHERE patient_no = ?",
            (self.cover["id"], self.patient_no),
        )
        self.assertFalse(patient_model.can_schedule(self.conn, self.patient_no, int(self.original["id"])))
        self.assertTrue(patient_model.can_schedule(self.conn, self.patient_no, int(self.cover["id"])))
        third = self.make_user("T003", "王五")
        self.assertFalse(patient_model.can_schedule(self.conn, self.patient_no, int(third["id"])))

    def test_temp_related_patients_appear_in_temp_scope(self) -> None:
        """原归属者与临时认领者都能在 scope=temp 里看到该患者。"""
        self._open_temp(int(self.cover["id"]))
        for employee_no in ("T001", "T002"):
            headers = self.login_headers(employee_no)
            body = self.client.get(
                "/api/v1/patients", params={"scope": "temp"}, headers=headers
            ).json()
            numbers = {i["inpatient_no"] for i in body["items"]}
            self.assertIn(self.patient_no, numbers, f"{employee_no} 应看到与自己相关的临时指派")

    def test_multi_day_release_clears_assignment(self) -> None:
        """多日假：正式排空，且写归属历史。"""
        # 该患者由 setUp 以「带归属」方式创建，因此先清掉建表时的 admin_assign 记录，
        # 让本用例只关注 multi_day_release 这一次变更
        self.conn.execute(
            "DELETE FROM patient_assignment_history WHERE patient_no = ?", (self.patient_no,)
        )
        released = patient_model.release_all_for_therapist(
            self.conn, int(self.original["id"]), int(self.original["id"])
        )
        self.assertEqual(released, [self.patient_no])
        patient = patient_model.get_patient_or_raise(self.conn, self.patient_no)
        self.assertIsNone(patient["assigned_therapist_id"])
        self.assertIsNone(patient["visible_therapist_id"])
        types = [
            r["change_type"]
            for r in self.conn.execute(
                "SELECT change_type FROM patient_assignment_history WHERE patient_no = ?",
                (self.patient_no,),
            ).fetchall()
        ]
        self.assertEqual(types, ["multi_day_release"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
