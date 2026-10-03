"""字典管理写接口测试（后台"字典管理"模块 / `开发计划.md` 4.5 第 580–582 行）。

覆盖重点：
1. **权限**：只有管理员能改字典；治疗师调用一律 403。
2. **CRUD 正确性**：主项目 / 子项目 / 参数的增改删，以及 `code`、`param_key` 唯一性。
3. **删除安全**（本模块最需要想清楚的部分）：
   - 没被用过的子项目 → 物理删除；
   - 已被治疗记录引用的子项目 → **改为停用**而不是删除（历史记录必须继续可读）；
   - 仍被模板引用的子项目 → 同样退化为停用（外键会拦，不能硬删）；
   - 主项目下还有启用子项目时 → 409，不允许连带删掉在用字典。
4. **参数校验**：类型、选项、默认值必须自洽；且与字典种子的校验口径一致。
5. **只读接口不受影响**：管理端写完之后，治疗师读字典仍正常。
"""

from __future__ import annotations

import unittest

from app.models import dictionary_admin as admin_model
from app.models import template as template_model
from seed.dictionary import seed_dictionary
from tests.api_base import ApiTestCase


class DictAdminTestCase(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        seed_dictionary(self.conn)
        self.admin = self.make_admin("A001")
        self.therapist = self.make_user("T001", "张三")
        self.ha = self.login_headers("A001")
        self.ht = self.login_headers("T001")

        self.motor_main = int(
            self.conn.execute("SELECT id FROM main_item WHERE code = 'motor_function'").fetchone()["id"]
        )
        self.motor_sub = int(
            self.conn.execute(
                "SELECT id FROM sub_item WHERE code = 'motor_function_01'"
            ).fetchone()["id"]
        )

    def row(self, sql: str, params: tuple = ()):
        return self.conn.execute(sql, params).fetchone()


class TestDictAdminPermissions(DictAdminTestCase):
    """字典是全局引用数据，写入必须限定管理员。"""

    def test_therapist_cannot_create_main_item(self) -> None:
        resp = self.client.post(
            "/api/v1/dict/main-items", json={"name": "私自加的项目", "code": "rogue"}, headers=self.ht
        )
        self.assert_error(resp, 403)

    def test_therapist_cannot_update_main_item(self) -> None:
        resp = self.client.put(
            f"/api/v1/dict/main-items/{self.motor_main}", json={"name": "改名"}, headers=self.ht
        )
        self.assert_error(resp, 403)

    def test_therapist_cannot_delete_main_item(self) -> None:
        resp = self.client.delete(f"/api/v1/dict/main-items/{self.motor_main}", headers=self.ht)
        self.assert_error(resp, 403)

    def test_therapist_cannot_create_sub_item(self) -> None:
        resp = self.client.post(
            "/api/v1/dict/sub-items",
            json={"main_item_id": self.motor_main, "name": "x", "code": "rogue_sub"},
            headers=self.ht,
        )
        self.assert_error(resp, 403)

    def test_therapist_cannot_create_param(self) -> None:
        resp = self.client.post(
            f"/api/v1/dict/sub-items/{self.motor_sub}/params",
            json={"param_key": "rogue", "param_name": "x", "input_type": "text"},
            headers=self.ht,
        )
        self.assert_error(resp, 403)

    def test_therapist_cannot_delete_param(self) -> None:
        param_id = int(self.row(
            "SELECT id FROM sub_item_param_def WHERE sub_item_id = ? LIMIT 1", (self.motor_sub,)
        )["id"])
        resp = self.client.delete(f"/api/v1/dict/params/{param_id}", headers=self.ht)
        self.assert_error(resp, 403)

    def test_read_still_allowed_for_therapist(self) -> None:
        """写接口加了管理员限制，读接口不能跟着收紧 —— 治疗师要拿字典渲染表单。"""
        resp = self.client.get("/api/v1/dict/tree", headers=self.ht)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(len(resp.json()), 4)

    def test_write_requires_auth(self) -> None:
        resp = self.client.post("/api/v1/dict/main-items", json={"name": "x", "code": "y"})
        self.assert_error(resp, 401, "AUTH_REQUIRED")


class TestMainItemCrud(DictAdminTestCase):
    def test_create(self) -> None:
        resp = self.client.post(
            "/api/v1/dict/main-items",
            json={"name": "物理治疗", "code": "physio", "alias": "PT", "sort": 40},
            headers=self.ha,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual(body["name"], "物理治疗")
        self.assertEqual(body["code"], "physio")
        self.assertEqual(body["alias"], "PT")
        self.assertEqual(body["status"], "active")

    def test_create_rejects_duplicate_code(self) -> None:
        resp = self.client.post(
            "/api/v1/dict/main-items", json={"name": "重名", "code": "motor_function"}, headers=self.ha
        )
        self.assert_error(resp, 409, "CONFLICT")

    def test_create_appears_in_read_api(self) -> None:
        self.client.post(
            "/api/v1/dict/main-items", json={"name": "新项目", "code": "brand_new"}, headers=self.ha
        )
        tree = self.client.get("/api/v1/dict/tree", headers=self.ht).json()
        self.assertIn("brand_new", {m["code"] for m in tree})

    def test_update(self) -> None:
        resp = self.client.put(
            f"/api/v1/dict/main-items/{self.motor_main}",
            json={"name": "运动功能训练（改名）", "alias": "MOTO"},
            headers=self.ha,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["name"], "运动功能训练（改名）")
        self.assertEqual(resp.json()["alias"], "MOTO")
        # 未传的字段保持原值
        self.assertEqual(resp.json()["code"], "motor_function")

    def test_update_can_disable(self) -> None:
        resp = self.client.put(
            f"/api/v1/dict/main-items/{self.motor_main}", json={"status": "disabled"}, headers=self.ha
        )
        self.assertEqual(resp.json()["status"], "disabled")
        tree = self.client.get("/api/v1/dict/tree", headers=self.ht).json()
        self.assertNotIn("motor_function", {m["code"] for m in tree}, "停用后不应出现在字典树里")

    def test_update_rejects_invalid_status(self) -> None:
        resp = self.client.put(
            f"/api/v1/dict/main-items/{self.motor_main}", json={"status": "gone"}, headers=self.ha
        )
        self.assert_error(resp, 422, "INVALID")

    def test_update_rejects_duplicate_code(self) -> None:
        resp = self.client.put(
            f"/api/v1/dict/main-items/{self.motor_main}", json={"code": "adl_skill"}, headers=self.ha
        )
        self.assert_error(resp, 409, "CONFLICT")

    def test_update_unknown_is_404(self) -> None:
        resp = self.client.put("/api/v1/dict/main-items/99999", json={"name": "x"}, headers=self.ha)
        self.assert_error(resp, 404, "NOT_FOUND")

    def test_delete_blocked_while_active_sub_items_exist(self) -> None:
        """主项目下还有启用子项目时拒绝删除 —— 否则会把在用字典连带弄没。"""
        resp = self.client.delete(f"/api/v1/dict/main-items/{self.motor_main}", headers=self.ha)
        self.assert_error(resp, 409, "CONFLICT")
        self.assertIn("active_sub_items", resp.json()["details"])
        self.assertIsNotNone(self.row("SELECT id FROM main_item WHERE id = ?", (self.motor_main,)))

    def test_delete_after_disabling_sub_items(self) -> None:
        self.conn.execute("UPDATE sub_item SET status = 'disabled' WHERE main_item_id = ?",
                          (self.motor_main,))
        resp = self.client.delete(f"/api/v1/dict/main-items/{self.motor_main}", headers=self.ha)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json()["deleted"])
        self.assertIsNone(self.row("SELECT id FROM main_item WHERE id = ?", (self.motor_main,)))


class TestSubItemCrud(DictAdminTestCase):
    def test_create(self) -> None:
        resp = self.client.post(
            "/api/v1/dict/sub-items",
            json={"main_item_id": self.motor_main, "name": "新训练", "code": "motor_function_99", "sort": 99},
            headers=self.ha,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertEqual(resp.json()["main_item_id"], self.motor_main)

    def test_create_unknown_main_item_is_404(self) -> None:
        resp = self.client.post(
            "/api/v1/dict/sub-items",
            json={"main_item_id": 99999, "name": "x", "code": "y"}, headers=self.ha,
        )
        self.assert_error(resp, 404)

    def test_create_rejects_duplicate_code(self) -> None:
        resp = self.client.post(
            "/api/v1/dict/sub-items",
            json={"main_item_id": self.motor_main, "name": "x", "code": "motor_function_01"},
            headers=self.ha,
        )
        self.assert_error(resp, 409, "CONFLICT")

    def test_update_can_move_to_another_main_item(self) -> None:
        adl_main = int(self.row("SELECT id FROM main_item WHERE code = 'adl_skill'")["id"])
        resp = self.client.put(
            f"/api/v1/dict/sub-items/{self.motor_sub}", json={"main_item_id": adl_main}, headers=self.ha
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["main_item_id"], adl_main)

    def test_hard_delete_when_never_used(self) -> None:
        created = self.client.post(
            "/api/v1/dict/sub-items",
            json={"main_item_id": self.motor_main, "name": "没人用的训练", "code": "unused_sub"},
            headers=self.ha,
        ).json()
        resp = self.client.delete(f"/api/v1/dict/sub-items/{created['id']}", headers=self.ha)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json()["deleted"])
        self.assertFalse(resp.json()["soft_deleted"])
        self.assertIsNone(self.row("SELECT id FROM sub_item WHERE id = ?", (created["id"],)))

    def test_soft_delete_when_used_by_treatment_record(self) -> None:
        """用过的子项目只停用 —— 历史记录必须继续可读。"""
        from app.models import patient as patient_model

        patient_model.create_patient(self.conn, inpatient_no="ZY001", name="患者甲")
        # 走 API 建记录：**两层快照是在 API 层生成的**（`_prepare_items`），
        # 直接调模型不会写快照，那样就测不到"历史仍可读"这件事。
        created = self.client.post(
            "/api/v1/records",
            json={
                "patient_no": "ZY001", "record_date": "2027-08-01", "session_period": "am",
                "status": "submitted",
                "items": [{"main_item_id": self.motor_main, "sub_item_id": self.motor_sub,
                           "params": {"side": "左"}}],
            },
            headers=self.ht,
        )
        self.assertEqual(created.status_code, 201, created.text)

        resp = self.client.delete(f"/api/v1/dict/sub-items/{self.motor_sub}", headers=self.ha)
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertFalse(body["deleted"], "用过的子项目不应物理删除")
        self.assertTrue(body["soft_deleted"])
        self.assertIn("已有治疗记录引用", body["reason"])

        row = self.row("SELECT status FROM sub_item WHERE id = ?", (self.motor_sub,))
        self.assertEqual(row["status"], "disabled")
        # 历史记录仍可读（快照起作用）
        snap = self.row("SELECT sub_item_name_snapshot FROM record_item")
        self.assertEqual(snap["sub_item_name_snapshot"], "偏瘫肢体综合训练")
        reread = self.client.get(
            f"/api/v1/records/{created.json()['id']}", headers=self.ht
        ).json()
        self.assertEqual(reread["items"][0]["sub_item_name_snapshot"], "偏瘫肢体综合训练")

    def test_soft_delete_when_referenced_by_template(self) -> None:
        """仍被模板引用时也会退化为停用（外键会拦，不能硬删）。"""
        template = template_model.create_template(
            self.conn, scope="dept", name="引用模板", main_item_id=self.motor_main,
            items=[{"sub_item_id": self.motor_sub}],
        )
        self.assertIsNotNone(template)
        resp = self.client.delete(f"/api/v1/dict/sub-items/{self.motor_sub}", headers=self.ha)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertFalse(resp.json()["deleted"])
        self.assertIn("模板", resp.json()["reason"])

    def test_delete_unknown_is_404(self) -> None:
        resp = self.client.delete("/api/v1/dict/sub-items/99999", headers=self.ha)
        self.assert_error(resp, 404)


class TestParamCrud(DictAdminTestCase):
    def test_create_text_param(self) -> None:
        resp = self.client.post(
            f"/api/v1/dict/sub-items/{self.motor_sub}/params",
            json={"param_key": "remark", "param_name": "补充说明", "input_type": "text",
                  "unit": None, "sort": 90},
            headers=self.ha,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual(body["param_key"], "remark")
        self.assertEqual(body["input_type"], "text")

    def test_create_select_with_default(self) -> None:
        resp = self.client.post(
            f"/api/v1/dict/sub-items/{self.motor_sub}/params",
            json={"param_key": "mood", "param_name": "情绪", "input_type": "select",
                  "options": ["平稳", "焦虑"], "default_value": "平稳"},
            headers=self.ha,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertEqual(resp.json()["options"], ["平稳", "焦虑"])
        # 单选默认值统一按数组存储（与字典种子格式一致）
        self.assertEqual(resp.json()["default_value"], '["平稳"]')

    def test_create_select_without_options_rejected(self) -> None:
        resp = self.client.post(
            f"/api/v1/dict/sub-items/{self.motor_sub}/params",
            json={"param_key": "mood", "param_name": "情绪", "input_type": "select"}, headers=self.ha,
        )
        self.assert_error(resp, 422, "INVALID")

    def test_default_must_be_in_options(self) -> None:
        resp = self.client.post(
            f"/api/v1/dict/sub-items/{self.motor_sub}/params",
            json={"param_key": "mood", "param_name": "情绪", "input_type": "select",
                  "options": ["平稳"], "default_value": "焦虑"},
            headers=self.ha,
        )
        self.assert_error(resp, 422, "INVALID")

    def test_single_select_rejects_multiple_defaults(self) -> None:
        resp = self.client.post(
            f"/api/v1/dict/sub-items/{self.motor_sub}/params",
            json={"param_key": "mood", "param_name": "情绪", "input_type": "select",
                  "options": ["平稳", "焦虑"], "default_value": ["平稳", "焦虑"]},
            headers=self.ha,
        )
        self.assert_error(resp, 422, "INVALID")

    def test_text_param_rejects_options(self) -> None:
        resp = self.client.post(
            f"/api/v1/dict/sub-items/{self.motor_sub}/params",
            json={"param_key": "note", "param_name": "备注", "input_type": "text",
                  "options": ["a"]},
            headers=self.ha,
        )
        self.assert_error(resp, 422, "INVALID")

    def test_number_param_default_must_be_number(self) -> None:
        resp = self.client.post(
            f"/api/v1/dict/sub-items/{self.motor_sub}/params",
            json={"param_key": "load", "param_name": "负荷", "input_type": "number",
                  "default_value": "不重"},
            headers=self.ha,
        )
        self.assert_error(resp, 422, "INVALID")

    def test_number_default_stored_as_string(self) -> None:
        resp = self.client.post(
            f"/api/v1/dict/sub-items/{self.motor_sub}/params",
            json={"param_key": "rounds", "param_name": "轮数", "input_type": "number",
                  "default_value": 4},
            headers=self.ha,
        )
        self.assertEqual(resp.json()["default_value"], "4")

    def test_duplicate_param_key_rejected(self) -> None:
        resp = self.client.post(
            f"/api/v1/dict/sub-items/{self.motor_sub}/params",
            json={"param_key": "side", "param_name": "侧别", "input_type": "text"}, headers=self.ha,
        )
        self.assert_error(resp, 409, "CONFLICT")

    def test_invalid_input_type_rejected(self) -> None:
        resp = self.client.post(
            f"/api/v1/dict/sub-items/{self.motor_sub}/params",
            json={"param_key": "x", "param_name": "x", "input_type": "checkbox"}, headers=self.ha,
        )
        self.assert_error(resp, 422, "INVALID")

    def test_update_param(self) -> None:
        param_id = int(self.row(
            "SELECT id FROM sub_item_param_def WHERE sub_item_id = ? AND param_key = 'position'",
            (self.motor_sub,),
        )["id"])
        resp = self.client.put(
            f"/api/v1/dict/params/{param_id}",
            json={"param_name": "体位（改名）"},
            headers=self.ha,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["param_name"], "体位（改名）")
        # 未传的字段保持原值
        self.assertEqual(resp.json()["input_type"], "select")
        self.assertIn("坐位", resp.json()["options"])

    def test_update_param_key_to_existing_rejected(self) -> None:
        param_id = int(self.row(
            "SELECT id FROM sub_item_param_def WHERE sub_item_id = ? AND param_key = 'position'",
            (self.motor_sub,),
        )["id"])
        resp = self.client.put(
            f"/api/v1/dict/params/{param_id}", json={"param_key": "side"}, headers=self.ha
        )
        self.assert_error(resp, 409, "CONFLICT")

    def test_delete_param(self) -> None:
        param_id = int(self.row(
            "SELECT id FROM sub_item_param_def WHERE sub_item_id = ? AND param_key = 'sets'",
            (self.motor_sub,),
        )["id"])
        resp = self.client.delete(f"/api/v1/dict/params/{param_id}", headers=self.ha)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json()["deleted"])
        self.assertIsNone(self.row("SELECT id FROM sub_item_param_def WHERE id = ?", (param_id,)))

    def test_create_param_on_unknown_sub_item_is_404(self) -> None:
        resp = self.client.post(
            "/api/v1/dict/sub-items/99999/params",
            json={"param_key": "x", "param_name": "x", "input_type": "text"}, headers=self.ha,
        )
        self.assert_error(resp, 404)


class TestNewlyCreatedDictIsUsable(DictAdminTestCase):
    """后台新建的字典项必须能真的用于记录（否则管理页面等于摆设）。"""

    def test_new_sub_item_with_params_can_be_used_in_record(self) -> None:
        from app.models import patient as patient_model
        from app.models import treatment as treatment_model

        sub = self.client.post(
            "/api/v1/dict/sub-items",
            json={"main_item_id": self.motor_main, "name": "体外反搏", "code": "motor_function_98"},
            headers=self.ha,
        ).json()
        self.client.post(
            f"/api/v1/dict/sub-items/{sub['id']}/params",
            json={"param_key": "duration", "param_name": "时长", "input_type": "number",
                  "default_value": 20, "unit": "分钟"},
            headers=self.ha,
        )
        patient_model.create_patient(self.conn, inpatient_no="ZY002", name="患者乙")
        record = treatment_model.create_record(
            self.conn, patient_no="ZY002", therapist_id=int(self.therapist["id"]),
            record_date="2027-08-02", session_period="am",
            items=[{"main_item_id": self.motor_main, "sub_item_id": sub["id"],
                    "params": {"duration": 25}}],
        )
        self.assertEqual(len(record["items"]), 1)
        self.assertEqual(record["items"][0]["params"], {"duration": 25})


class TestValidationHelperMatchesSeedRules(DictAdminTestCase):
    """校验函数与字典种子口径一致：两处规则不一致会让"种子能过、后台过不了"极难排查。"""

    def test_duplicate_options_rejected(self) -> None:
        from app.models.base import Invalid

        with self.assertRaises(Invalid):
            admin_model.validate_param_payload(
                param_key="k", param_name="n", input_type="select",
                options=["a", "a"], default_value=None,
            )

    def test_multi_select_allows_multiple_defaults(self) -> None:
        options_json, default = admin_model.validate_param_payload(
            param_key="k", param_name="n", input_type="multi_select",
            options=["a", "b", "c"], default_value=["a", "b"],
        )
        self.assertIsNotNone(options_json)
        self.assertEqual(default, '["a", "b"]')

    def test_empty_param_key_rejected(self) -> None:
        from app.models.base import Invalid

        with self.assertRaises(Invalid):
            admin_model.validate_param_payload(
                param_key="  ", param_name="n", input_type="text", options=None, default_value=None
            )


class TestCookieAuth(ApiTestCase):
    """refresh token 的 httpOnly Cookie 通道（管理后台 Web 用）。"""

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
        # 清 Cookie 的常见形式是 Max-Age=0 或 expires 在过去
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
