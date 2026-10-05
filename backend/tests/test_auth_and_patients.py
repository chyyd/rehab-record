"""阶段 1 测试：认证、用户管理、患者与归属（`开发计划.md` 阶段 1）。

覆盖重点是**权限边界**——这类 bug 不会让系统崩，但会让治疗师看到别人的患者，
或让无关的人改到别人的数据，属于必须逐条钉死的用例。

用例分组：
1. 登录 / 令牌（含 refresh 轮换、类型混用、停用账号）
2. 用户管理权限（管理员专属、不许消灭最后一个管理员）
3. 患者数据级权限（D10：全科白板——在院/暂停对所有治疗师可见，已出院仅管理员）
4. 归属变更（认领 / 放弃 / 管理员指定 / 归属历史）
5. 归属解析（2026-10-05 起归属只有两层：可见归属直接等于原归属；
   临时释放/临时认领与 `scope=temp` 已随临时指派删除）
6. 患者列表排序（"我最近一次已提交治疗"降序，不再是下一个排期）
"""

from __future__ import annotations

import unittest

from app.core import security
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
    """D10：数据级权限。

    **2026-10-03 起改为全科白板**：治疗师默认（`scope=dept`）能看见科室当前**在院/暂停**
    的全部患者，不再按归属隔离；`mine` / `unassigned` 保留为**筛选**语义
    （`temp` 已于 2026-10-05 随临时指派从患者列表删除）；
    `all`（含已出院）仍**仅管理员**。
    """

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

    def test_therapist_sees_whole_department(self) -> None:
        """白板：别人的患者在院也可见（这是本次业务变更的核心）。"""
        headers = self.login_headers("T001")
        resp = self.client.get("/api/v1/patients", headers=headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        numbers = {item["inpatient_no"] for item in body["items"]}
        self.assertEqual(numbers, {"ZY001", "ZY002", "ZY003"})
        self.assertEqual(body["scope"], "dept", "治疗师默认范围应为科室白板")

    def test_discharged_hidden_by_default(self) -> None:
        """已出院默认不在白板上（它不属于"当前在科室的患者"）。"""
        patient_model.update_patient(
            self.conn, "ZY002", status=patient_model.STATUS_DISCHARGED
        )
        headers = self.login_headers("T001")
        numbers = {
            i["inpatient_no"]
            for i in self.client.get("/api/v1/patients", headers=headers).json()["items"]
        }
        self.assertEqual(numbers, {"ZY001", "ZY003"}, "已出院患者应从白板消失")
        # 管理员仍可用 scope=all 看到全表
        admin_numbers = {
            i["inpatient_no"]
            for i in self.client.get(
                "/api/v1/patients", params={"scope": "all"}, headers=self.login_headers("A001")
            ).json()["items"]
        }
        self.assertEqual(admin_numbers, {"ZY001", "ZY002", "ZY003"})

    def test_dept_scope_explicit(self) -> None:
        headers = self.login_headers("T001")
        resp = self.client.get("/api/v1/patients", params={"scope": "dept"}, headers=headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["total"], 3)

    def test_scope_mine_and_unassigned(self) -> None:
        """`mine` / `unassigned` 仍是有效筛选（用于"我的患者"页签）。"""
        headers = self.login_headers("T001")
        mine = self.client.get("/api/v1/patients", params={"scope": "mine"}, headers=headers).json()
        self.assertEqual({i["inpatient_no"] for i in mine["items"]}, {"ZY001"})
        free = self.client.get("/api/v1/patients", params={"scope": "unassigned"}, headers=headers).json()
        self.assertEqual({i["inpatient_no"] for i in free["items"]}, {"ZY003"})

    def test_therapist_cannot_use_scope_all(self) -> None:
        """`all`（全表含已出院）仍仅管理员——这条约定不变。"""
        headers = self.login_headers("T001")
        resp = self.client.get("/api/v1/patients", params={"scope": "all"}, headers=headers)
        self.assert_error(resp, 403, "SCOPE_FORBIDDEN")

    def test_admin_sees_all_patients(self) -> None:
        headers = self.login_headers("A001")
        resp = self.client.get("/api/v1/patients", params={"scope": "all"}, headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 3)

    def test_therapist_can_read_others_patient_detail(self) -> None:
        """白板：别人的患者在院时，详情可读。"""
        headers = self.login_headers("T001")
        resp = self.client.get("/api/v1/patients/ZY002", headers=headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["inpatient_no"], "ZY002")

    def test_therapist_can_see_others_assignment_history(self) -> None:
        """白板：归属历史也可读（协作时需要知道"当前谁主要负责"）。"""
        headers = self.login_headers("T001")
        resp = self.client.get("/api/v1/patients/ZY002/assignments", headers=headers)
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_unknown_patient_is_404_for_admin(self) -> None:
        headers = self.login_headers("A001")
        self.assert_error(self.client.get("/api/v1/patients/NOPE", headers=headers), 404, "PATIENT_NOT_FOUND")


class TestPatientListOrdering(ApiTestCase):
    """设计.md 3.4.3：患者列表排序。

    2026-10-05 起排序依据从"下一个排期"换成"我最近一次已提交治疗"
    （视图 `v_patient_last_treated`）：

        组 0 = 可见归属是我 → 组 1 = 无人负责 → 组 2 = 其他治疗师；
        组内按我最近一次**已提交**治疗的日期降序，从没治过的排最后（再按住院号）。

    所以这些用例一律用**治疗记录**构造顺序 —— 排期已经不存在了，
    而"我刚治过谁"才是治疗师打开列表时真正关心的。
    """

    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.t1 = self.make_user("T001", "张三")
        self.t2 = self.make_user("T002", "李四")
        self.make_admin("A001")
        self.h1 = self.login_headers("T001")
        self.h2 = self.login_headers("T002")
        self.ha = self.login_headers("A001")
        # ZY001 我的 / ZY002 别人的 / ZY003 未分配 —— 三者都还没被我治过
        patient_model.create_patient(
            self.conn, inpatient_no="ZY001", name="我的患者", assigned_therapist_id=int(self.t1["id"])
        )
        patient_model.create_patient(
            self.conn, inpatient_no="ZY002", name="别人的患者", assigned_therapist_id=int(self.t2["id"])
        )
        patient_model.create_patient(self.conn, inpatient_no="ZY003", name="未分配患者")

    def _add_patient(self, inpatient_no: str, name: str, therapist_id: int | None) -> None:
        patient_model.create_patient(
            self.conn, inpatient_no=inpatient_no, name=name, assigned_therapist_id=therapist_id
        )

    def _record(
        self,
        patient_no: str,
        record_date: str,
        headers: dict,
        *,
        status: str = "submitted",
    ) -> dict:
        """写一条**日常**记录：只有 `submitted` 的日常记录会进 `v_patient_last_treated`。

        这里直接落库（不走 API）—— 本组用例测的是患者列表排序，
        只需要"该患者在该日期被我治疗过"这个事实；走 API 还要先补首评、
        受"同一天至多 2 条"与门禁约束，噪声太大。
        """
        seq = int(
            self.conn.execute(
                "SELECT COUNT(*) FROM treatment_record WHERE patient_no = ? AND discipline = 'PT'"
                "   AND kind = 'daily'",
                (patient_no,),
            ).fetchone()[0]
        ) + 1
        cur = self.conn.execute(
            "INSERT INTO treatment_record"
            " (patient_no, therapist_id, record_date, discipline, kind, seq_no, body_json,"
            "  rendered_text, status, submitted_at)"
            " VALUES (?, ?, ?, 'PT', 'daily', ?, '{}', '康复治疗记录', ?, ?)",
            (
                patient_no,
                int(self.t1["id"]),
                record_date,
                seq,
                status,
                "2027-03-01T00:00:00.000Z" if status == "submitted" else None,
            ),
        )
        return {"id": int(cur.lastrowid)}

    def _order(self, headers: dict | None = None) -> list[str]:
        resp = self.client.get("/api/v1/patients", headers=headers or self.h1)
        self.assertEqual(resp.status_code, 200, resp.text)
        return [item["inpatient_no"] for item in resp.json()["items"]]

    def test_groups_are_mine_then_unassigned_then_others(self) -> None:
        """谁都没治过时，顺序完全由归属分组决定。"""
        self.assertEqual(self._order(), ["ZY001", "ZY003", "ZY002"])

    def test_within_group_most_recently_treated_first(self) -> None:
        """组内按"我最近一次已提交治疗"降序 —— 而不是按排期日期。"""
        self._add_patient("ZY004", "我的另一个患者", int(self.t1["id"]))
        self._record("ZY001", "2027-03-01", self.h1)
        self._record("ZY004", "2027-03-05", self.h1)  # 更近 → 更靠前
        # 别人的患者即便我刚治过（且日期最新），也仍归"其他"组，排最后
        self._record("ZY002", "2027-03-09", self.h1)
        self.assertEqual(self._order(), ["ZY004", "ZY001", "ZY003", "ZY002"])

    def test_same_day_orders_by_patient_no(self) -> None:
        """同一天只按住院编号稳定排序。

        > 旧行为是"同一天上午在下午之前"（视图取当天最早的半日）。迁移 011 删掉了
        > `session_period`，`v_patient_last_treated` 只剩 `last_date`，
        > 所以这条排序规则**已随半日概念一起消失**。
        """
        self._add_patient("ZY004", "我的另一个患者", int(self.t1["id"]))
        self._record("ZY001", "2027-03-01", self.h1)
        self._record("ZY004", "2027-03-01", self.h1)
        self.assertEqual(self._order(), ["ZY001", "ZY004", "ZY003", "ZY002"])

    def test_draft_and_locked_records_do_not_count_as_treatment(self) -> None:
        """口径（迁移 007 明确写定）：只算 `submitted`。

        - 草稿是"写了一半还没提交"，在汇总/时间轴里都还不存在，不该把患者顶到最前；
        - 已锁定代表这条记录已被归档封存，不代表"我最近在治他"。
        """
        self._add_patient("ZY005", "只有草稿的患者", int(self.t1["id"]))
        self._add_patient("ZY006", "记录已锁定的患者", int(self.t1["id"]))
        self._record("ZY001", "2027-03-01", self.h1)
        self._record("ZY005", "2027-12-01", self.h1, status="draft")

        locked = self._record("ZY006", "2027-12-02", self.h1)
        resp = self.client.post(f"/api/v1/records/{locked['id']}/lock", headers=self.ha)
        self.assertEqual(resp.status_code, 200, resp.text)

        # ZY005 / ZY006 的日期都远晚于 ZY001，但都不算"治疗过" → 排在 ZY001 之后
        self.assertEqual(self._order()[:3], ["ZY001", "ZY005", "ZY006"])
        self.assertEqual(self._order()[3:], ["ZY003", "ZY002"])


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

    def test_therapist_cannot_restore_discharged_patient(self) -> None:
        """Q9 的真正含义：**治疗师**不能自行恢复出院的患者，恢复留给管理员。

        这条替代了原先的 `test_discharge_is_irreversible` —— 那条断言的是"管理员也不能改回"，
        与 `设计.md` 3.1「出院不可逆（**需管理员手动改回**）」和实际需求相矛盾，
        等于把管理员自己的权限也挡死了（提示"请联系系统管理员"，而调用者就是管理员）。
        """
        patient_model.create_patient(
            self.conn, inpatient_no="ZY001", name="患者",
            assigned_therapist_id=int(self.t1["id"]),
            status=patient_model.STATUS_DISCHARGED,
        )
        headers = self.login_headers("T001")
        resp = self.client.put(
            "/api/v1/patients/ZY001", json={"status": "in_hospital"}, headers=headers
        )
        self.assert_error(resp, 403, "ADMIN_REQUIRED")
        # 确认状态确实没被改动
        row = self.conn.execute("SELECT status FROM patient WHERE inpatient_no = 'ZY001'").fetchone()
        self.assertEqual(row["status"], "discharged")

    def test_admin_can_restore_discharged_patient(self) -> None:
        """管理员可以把已出院改回在院（Q9：需管理员手动改回）。"""
        patient_model.create_patient(
            self.conn, inpatient_no="ZY001", name="患者",
            status=patient_model.STATUS_DISCHARGED,
        )
        headers = self.login_headers("A001")
        resp = self.client.put(
            "/api/v1/patients/ZY001", json={"status": "in_hospital"}, headers=headers
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["status"], "in_hospital")
        row = self.conn.execute("SELECT status FROM patient WHERE inpatient_no = 'ZY001'").fetchone()
        self.assertEqual(row["status"], "in_hospital")

    def test_admin_can_restore_to_paused(self) -> None:
        """恢复的目标状态不限于在院：暂停治疗同样可以（暂停也可逆）。"""
        patient_model.create_patient(
            self.conn, inpatient_no="ZY001", name="患者",
            status=patient_model.STATUS_DISCHARGED,
        )
        headers = self.login_headers("A001")
        resp = self.client.put(
            "/api/v1/patients/ZY001", json={"status": "paused"}, headers=headers
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["status"], "paused")

    def test_restore_is_flagged_in_audit_log(self) -> None:
        """恢复动作要单独记为 `restore`，否则会被淹没在普通 update 里难以追溯。"""
        patient_model.create_patient(
            self.conn, inpatient_no="ZY001", name="患者",
            status=patient_model.STATUS_DISCHARGED,
        )
        headers = self.login_headers("A001")
        self.client.put("/api/v1/patients/ZY001", json={"status": "in_hospital"}, headers=headers)

        row = self.conn.execute(
            "SELECT action, before_json, after_json FROM audit_log"
            " WHERE target_type = 'patient' AND target_id = 'ZY001'"
            " ORDER BY id DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(row["action"], "restore")
        self.assertIn("discharged", row["before_json"])
        self.assertIn("in_hospital", row["after_json"])

    def test_normal_edit_is_not_flagged_as_restore(self) -> None:
        """只有在院外的状态变化才算 restore；普通改备注仍是 update。"""
        patient_model.create_patient(self.conn, inpatient_no="ZY001", name="患者")
        headers = self.login_headers("A001")
        self.client.put("/api/v1/patients/ZY001", json={"admin_note": "注意跌倒"}, headers=headers)
        row = self.conn.execute(
            "SELECT action FROM audit_log WHERE target_type = 'patient' AND target_id = 'ZY001'"
            " ORDER BY id DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(row["action"], "update")

    def test_restoring_does_not_change_assignment(self) -> None:
        """恢复只改状态，不应顺手改动归属（归属有独立的分配/认领接口）。"""
        patient_model.create_patient(
            self.conn, inpatient_no="ZY001", name="患者",
            assigned_therapist_id=int(self.t1["id"]),
            status=patient_model.STATUS_DISCHARGED,
        )
        headers = self.login_headers("A001")
        resp = self.client.put(
            "/api/v1/patients/ZY001", json={"status": "in_hospital"}, headers=headers
        )
        self.assertEqual(resp.json()["assigned_therapist_id"], int(self.t1["id"]))

    def test_cannot_create_already_discharged_patient(self) -> None:
        """不允许凭空建一个"已出院"的患者（与"能否改回"是两件事）。"""
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
    """M18 / 3.5.5：归属解析的**可观察行为**。

    2026-10-05 起归属只有**两层**：`visible_therapist_id` **直接等于**
    `patient.assigned_therapist_id` —— 临时指派及其"临时释放 → 可见归属变 NULL →
    他人临时认领"三层语义已彻底删除（迁移 009，`temporary_assignment` 表已删）。

    本组用例钉的仍是"归属变更之后调用方能从 `scope` 筛选上观察到什么"，
    那是权限与"我的患者"页签真正依赖的东西：

    - `scope=mine`       ⟺ 「该治疗师就是归属者」；
    - `scope=unassigned` ⟺ 「归属为空」（谁都不负责，谁都可能接手）。

    > 原先的 `test_temp_release_*` / `test_temp_claim_*` / `test_expired_temp_assignment_*` /
    > `test_closed_temp_assignment_*` / `test_temp_released_patient_cannot_be_claimed_formally` /
    > `test_temp_related_patients_appear_in_temp_scope` 与 `_open_temp` fixture
    > 随临时指派一并删除。`_open_temp` 曾有一个"日期必须取远未来"的修复
    >（`expires_at` 参与 SQL 字符串比较）；fixture 删掉后这个时间依赖自然消失 ——
    > 本类现在没有任何用例依赖"当前时刻"。
    """

    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.original = self.make_user("T001", "归属者")
        self.cover = self.make_user("T002", "接手者")
        self.make_admin("A001")
        self.patient_no = "ZY001"
        patient_model.create_patient(
            self.conn, inpatient_no=self.patient_no, name="患者",
            assigned_therapist_id=int(self.original["id"]),
        )

    def _list_scope(self, employee_no: str, scope: str) -> set[str]:
        """按数据范围查询患者列表（走真实接口），返回住院编号集合。"""
        body = self.client.get(
            "/api/v1/patients", params={"scope": scope}, headers=self.login_headers(employee_no)
        ).json()
        return {item["inpatient_no"] for item in body["items"]}

    def _admin_assign(self, therapist_id: int | None) -> None:
        resp = self.client.post(
            f"/api/v1/patients/{self.patient_no}/assign",
            json={"therapist_id": therapist_id},
            headers=self.login_headers("A001"),
        )
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_plain_assignment_visible_is_original(self) -> None:
        patient = patient_model.get_patient_or_raise(self.conn, self.patient_no)
        self.assertEqual(patient["visible_therapist_id"], int(self.original["id"]))
        self.assertEqual(patient["assigned_therapist_id"], int(self.original["id"]))
        # 2026-10-05（迁移 010）：`visibility_state` 列已删除 —— 它在 009 之后恒为
        # 'assigned'，没有任何真实消费者。这里断言它**不再出现**，防止被误加回来。
        self.assertNotIn("visibility_state", patient)

    def test_visible_resolution_is_observable_in_patient_scopes(self) -> None:
        """归属解析必须能从接口的 `scope` 筛选上**观察到**（不再直接调模型函数）。

        本用例替代原先直接调用 `patient_model.covers_patient()` 的写法 —— 那个函数
        **已随排期下线按死代码删除**（它唯一的生产调用方是已删除的 `api/v1/schedule.py`）。
        断言的可观察等价关系：

        - `scope=mine`       ⟺ 「该治疗师就是归属者」；
        - `scope=unassigned` ⟺ 「归属为空」（谁都不负责，谁都可能接手）。

        归属变更**只有三条路**（全部要求直接改 `assigned_therapist_id`）：
        管理员指定（`admin_assign`）/ 管理员或本人放弃（`admin_release`）/ 认领（`claim`）。
        曾经还有"临时释放不改原归属"的第四条路，随临时指派一起删了。
        """
        self.make_user("T003", "王五")

        # 正常：可见归属 = 归属者
        self.assertIn(self.patient_no, self._list_scope("T001", "mine"))
        self.assertNotIn(self.patient_no, self._list_scope("T002", "mine"))
        self.assertNotIn(self.patient_no, self._list_scope("T003", "unassigned"))

        # 管理员清空归属（admin_release）：可见归属变 NULL —— 原归属者的 mine 里不再有它，
        # 但它落到 unassigned，因此**任何治疗师**都可以接手。
        self._admin_assign(None)
        patient = patient_model.get_patient_or_raise(self.conn, self.patient_no)
        self.assertIsNone(patient["assigned_therapist_id"])
        self.assertIsNone(patient["visible_therapist_id"], "可见归属必须跟着原归属一起变 NULL")
        self.assertNotIn(self.patient_no, self._list_scope("T001", "mine"))
        self.assertIn(self.patient_no, self._list_scope("T001", "unassigned"))
        self.assertIn(self.patient_no, self._list_scope("T003", "unassigned"))

        # 认领（claim）：只有认领者能看到"自己负责它"
        claimed = self.client.post(
            "/api/v1/patients/claim",
            params={"inpatient_no": self.patient_no},
            headers=self.login_headers("T002"),
        )
        self.assertEqual(claimed.status_code, 200, claimed.text)
        self.assertIn(self.patient_no, self._list_scope("T002", "mine"))
        self.assertNotIn(self.patient_no, self._list_scope("T001", "mine"))
        self.assertNotIn(self.patient_no, self._list_scope("T003", "mine"))
        self.assertNotIn(self.patient_no, self._list_scope("T003", "unassigned"))

        # 管理员改派（admin_assign）：可见归属跟着走到新归属者
        self._admin_assign(int(self.original["id"]))
        self.assertIn(self.patient_no, self._list_scope("T001", "mine"))
        self.assertNotIn(self.patient_no, self._list_scope("T002", "mine"))
        self.assertNotIn(self.patient_no, self._list_scope("T001", "unassigned"))

    def test_scope_temp_is_no_longer_accepted_for_patients(self) -> None:
        """`scope=temp` 已从**患者列表**的范围白名单里删除（迁移 009）。

        > 用户 2026-10-05 追加决定：「时间轴 / 记录列表」（`/api/v1/records`）的
        > `scope=temp` 也一并删除（现在只接受 `mine` / `visible`）。
        > 但 `is_temporary`（**记录级**标记，"记录人 ≠ 该患者当时的归属人"）
        > **仍然保留** —— 打印 PDF、患者每日汇总、后台记录列表三处都在用它，
        > 它由 `treatment_model.temporary_expr()` 查询时推导，与本次删除无关。
        > 自测覆盖见 `test_records.py::TestTemporaryTreatmentFlag`。
        """
        resp = self.client.get(
            "/api/v1/patients", params={"scope": "temp"}, headers=self.login_headers("T001")
        )
        self.assert_error(resp, 409)

    def test_multi_day_release_clears_assignment(self) -> None:
        """批量排空：把该治疗师名下患者正式清空，且写归属历史。

        这个模型函数原名来自"多日假"（请假功能已下线），但排空本身仍是
        管理员会用到的归属操作，故保留并继续验证。
        """
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
