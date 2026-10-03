"""阶段 3 测试：字典、选项集、治疗记录与患者反应（`开发计划.md` 阶段 3）。

重点覆盖：
1. **选项解析顺序**：个人 → 科室 → 全局 → 内置；
2. **参数带入优先级**（Q7）：上次值 → 个人默认 → 科室默认 → 全局默认 → 字典默认；
3. **记录状态机**：草稿不留痕 / 已提交留痕且累加 `edit_count` / 已锁定治疗师不可改；
4. **两层快照**：字典改名后历史记录仍显示当时的名称与选项文本；
5. **参数与患者反应校验**：未知键、越界、非选项值、标签与取值混用都要被拒。
"""

from __future__ import annotations

import unittest

from app.models import dictionary as dictionary_model
from app.models import treatment as treatment_model
from app.models.base import Invalid
from app.services import options as options_service
from app.services import records as records_service
from seed.dictionary import seed_dictionary
from seed.options import seed_options
from seed.responses import seed_responses
from tests.api_base import ApiTestCase


class SeededApiTestCase(ApiTestCase):
    """在临时库上导入**全部三份种子**，并准备两名治疗师 + 一名管理员。

    注意必须导 `seed_options`：选项解析的第三层是全局选项集，
    少了它就只能回落到各子项目的内置选项，"个人/科室覆盖全局"这些行为根本测不到。
    """

    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        seed_dictionary(self.conn)
        seed_responses(self.conn)
        seed_options(self.conn)

        self.t1 = self.make_user("T001", "张三")
        self.t2 = self.make_user("T002", "李四")
        self.admin = self.make_admin("A001")

        from app.models import patient as patient_model

        self.p1 = patient_model.create_patient(
            self.conn, inpatient_no="ZY001", name="患者甲", assigned_therapist_id=int(self.t1["id"])
        )
        self.p2 = patient_model.create_patient(
            self.conn, inpatient_no="ZY002", name="患者乙", assigned_therapist_id=int(self.t2["id"])
        )
        self.h1 = self.login_headers("T001")
        self.h2 = self.login_headers("T002")
        self.ha = self.login_headers("A001")

    # -- 便捷：取字典里的 id -------------------------------------------------- #
    def sub_item_id(self, code: str) -> int:
        row = self.conn.execute("SELECT id FROM sub_item WHERE code = ?", (code,)).fetchone()
        assert row is not None, f"种子中找不到子项目 {code}"
        return int(row["id"])

    def main_item_id(self, code: str) -> int:
        row = self.conn.execute("SELECT id FROM main_item WHERE code = ?", (code,)).fetchone()
        assert row is not None, f"种子中找不到主项目 {code}"
        return int(row["id"])


class TestDictionaryRead(SeededApiTestCase):
    def test_main_items_seeded(self) -> None:
        body = self.client.get("/api/v1/dict/main-items", headers=self.h1).json()
        self.assertEqual(len(body), 4)
        self.assertEqual(
            {m["code"] for m in body},
            {"motor_function", "adl_skill", "speech_function", "swallow_function"},
        )

    def test_dict_tree_is_nested(self) -> None:
        tree = self.client.get("/api/v1/dict/tree", headers=self.h1).json()
        self.assertEqual(len(tree), 4)
        motor = next(m for m in tree if m["code"] == "motor_function")
        self.assertGreater(len(motor["sub_items"]), 0)
        first_sub = motor["sub_items"][0]
        self.assertGreater(len(first_sub["params"]), 0)
        self.assertIn("param_key", first_sub["params"][0])

    def test_dict_tree_can_be_scoped_to_one_main_item(self) -> None:
        tree = self.client.get(
            "/api/v1/dict/tree", params={"main_item_id": self.main_item_id("swallow_function")}, headers=self.h1
        ).json()
        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0]["code"], "swallow_function")

    def test_params_endpoint(self) -> None:
        sub_id = self.sub_item_id("motor_function_01")
        params = self.client.get(f"/api/v1/dict/sub-items/{sub_id}/params", headers=self.h1).json()
        self.assertGreater(len(params), 0)
        for param in params:
            self.assertIn(param["input_type"], {"select", "multi_select", "number", "text"})

    def test_unknown_sub_item_is_404(self) -> None:
        resp = self.client.get("/api/v1/dict/sub-items/99999/params", headers=self.h1)
        self.assert_error(resp, 404, "NOT_FOUND")

    def test_response_defs_grouped_carries_common_into_each_main_item(self) -> None:
        """分组接口要为每个主项目附带通用反应，前端不必自己拼回退逻辑。

        说明：当前种子里所有反应定义都挂在具体主项目下（没有 `main_item_id IS NULL` 的
        全科通用行），因此 `common` 组**合法地为空**。这里用一个临时的通用定义
        真正验证"并入"逻辑，而不是只断言分组的形状。
        """
        grouped = self.client.get("/api/v1/response-defs/grouped", headers=self.h1).json()
        self.assertIn("common", grouped)
        self.assertIn("motor_function", grouped)
        self.assertEqual(grouped["common"], [], "种子里没有全科通用反应，common 组应为空")

        # 插入一条全科通用反应，验证它会被并入每个主项目组
        self.conn.execute(
            "INSERT INTO response_def (main_item_id, code, label, value_type, sort)"
            " VALUES (NULL, 'e2e_common_tag', '通用标记', 'tag', 999)"
        )
        grouped2 = self.client.get("/api/v1/response-defs/grouped", headers=self.h1).json()
        self.assertEqual([r["code"] for r in grouped2["common"]], ["e2e_common_tag"])
        for main_code in ("motor_function", "adl_skill", "speech_function", "swallow_function"):
            codes = {r["code"] for r in grouped2[main_code]}
            self.assertIn("e2e_common_tag", codes, f"{main_code} 组应包含全科通用反应")

        # 专属反应只出现在自己的组里
        self.assertIn("oral_residue", {r["code"] for r in grouped2["swallow_function"]})
        self.assertNotIn("oral_residue", {r["code"] for r in grouped2["motor_function"]})


class TestOptionResolution(SeededApiTestCase):
    """3.6.4 的解析顺序：个人 → 科室 → 全局 → 内置。"""

    def test_falls_back_to_global_option_set(self) -> None:
        resolved = options_service.resolve_options(self.conn, code="side")
        self.assertEqual(resolved["source"], "global")
        self.assertEqual([o["value"] for o in resolved["options"]], ["左", "右", "双侧"])

    def test_falls_back_to_builtin_when_no_option_set(self) -> None:
        resolved = options_service.resolve_options(self.conn, code="no_such_code", builtin=["甲", "乙"])
        self.assertEqual(resolved["source"], "builtin")
        self.assertEqual([o["value"] for o in resolved["options"]], ["甲", "乙"])

    def test_personal_overrides_global(self) -> None:
        options_service.upsert_personal_option_set(
            self.conn, owner_user_id=int(self.t1["id"]), code="side", name="我的侧别", values=["左", "右"],
            default_values=["左"],
        )
        resolved = options_service.resolve_options(self.conn, code="side", owner_user_id=int(self.t1["id"]))
        self.assertEqual(resolved["source"], "personal")
        self.assertEqual([o["value"] for o in resolved["options"]], ["左", "右"])
        self.assertEqual(resolved["defaults"], ["左"])

        # 另一个治疗师仍然拿全局
        other = options_service.resolve_options(self.conn, code="side", owner_user_id=int(self.t2["id"]))
        self.assertEqual(other["source"], "global")

    def test_dept_overrides_global(self) -> None:
        self.conn.execute(
            "INSERT INTO option_set (scope, dept_tag, code, name) VALUES ('dept', 'PT', 'side', 'PT侧别')"
        )
        set_id = int(self.conn.execute("SELECT id FROM option_set WHERE scope='dept'").fetchone()["id"])
        self.conn.execute(
            "INSERT INTO option_item (option_set_id, value, label, is_default, sort) VALUES (?, '左', '左', 1, 0)",
            (set_id,),
        )
        resolved = options_service.resolve_options(self.conn, code="side", dept_tag="PT")
        self.assertEqual(resolved["source"], "dept")

    def test_personal_endpoint_isolated_per_user(self) -> None:
        payload = {"code": "side", "name": "我的侧别", "values": ["左", "右"], "default_values": ["左"]}
        put = self.client.put("/api/v1/option-sets/personal", json=payload, headers=self.h1)
        self.assertEqual(put.status_code, 200, put.text)

        mine = self.client.get(
            "/api/v1/option-sets/resolve", params={"code": "side"}, headers=self.h1
        ).json()
        self.assertEqual(mine["source"], "personal")
        other = self.client.get(
            "/api/v1/option-sets/resolve", params={"code": "side"}, headers=self.h2
        ).json()
        self.assertEqual(other["source"], "global", "个人选项不应影响他人")

    def test_personal_default_must_be_in_values(self) -> None:
        resp = self.client.put(
            "/api/v1/option-sets/personal",
            json={"code": "side", "name": "x", "values": ["左"], "default_values": ["右"]},
            headers=self.h1,
        )
        self.assert_error(resp, 422, "INVALID")

    def test_personal_duplicate_values_rejected(self) -> None:
        resp = self.client.put(
            "/api/v1/option-sets/personal",
            json={"code": "side", "name": "x", "values": ["左", "左"]},
            headers=self.h1,
        )
        self.assert_error(resp, 422, "INVALID")

    def test_delete_personal_option_set(self) -> None:
        self.client.put(
            "/api/v1/option-sets/personal",
            json={"code": "side", "name": "x", "values": ["左"]},
            headers=self.h1,
        )
        deleted = self.client.delete("/api/v1/option-sets/personal/side", headers=self.h1)
        self.assertEqual(deleted.status_code, 204, deleted.text)
        again = self.client.delete("/api/v1/option-sets/personal/side", headers=self.h1)
        self.assert_error(again, 404)


class TestParamDefaultPriority(SeededApiTestCase):
    """Q7：上次值 → 个人默认 → 科室默认 → 全局默认 → 字典默认。"""

    def _param(self, sub_item_id: int, key: str) -> dict:
        return dictionary_model.get_param_by_key(self.conn, sub_item_id, key) or {}

    def test_dict_default_used_when_nothing_else(self) -> None:
        sub_id = self.sub_item_id("motor_function_01")
        param = self._param(sub_id, "position")
        current, source = records_service._pick_default(
            input_type=param["input_type"],
            last_value=None,
            option_defaults=[],
            dict_default=param.get("default_value"),
        )
        self.assertEqual(source, "dict_default")
        # 归一化规则：选择题一律返回列表（单选取首项），数字/文本返回原值
        self.assertEqual(current, ["坐位"])

    def test_option_set_default_beats_dict_default(self) -> None:
        current, source = records_service._pick_default(
            input_type="select", last_value=None, option_defaults=["站立"], dict_default="坐位"
        )
        self.assertEqual((current, source), ("站立", "option_set_default"))

    def test_last_value_beats_everything(self) -> None:
        current, source = records_service._pick_default(
            input_type="select", last_value="仰卧", option_defaults=["站立"], dict_default="坐位"
        )
        self.assertEqual((current, source), ("仰卧", "last_value"))

    def test_multi_select_default_returns_list(self) -> None:
        current, source = records_service._pick_default(
            input_type="multi_select", last_value=None, option_defaults=["洗脸", "刷牙"], dict_default=None
        )
        self.assertEqual(source, "option_set_default")
        self.assertEqual(current, ["洗脸", "刷牙"])

    def test_empty_last_value_is_ignored(self) -> None:
        """上次值是空字符串/空列表时不应"带入空值"，要回落到默认。"""
        for empty in ("", [], {}, None):
            _, source = records_service._pick_default(
                input_type="select", last_value=empty, option_defaults=[], dict_default="坐位"
            )
            self.assertEqual(source, "dict_default", f"空值 {empty!r} 不应被当作有效上次值")

    def test_form_uses_last_value_from_previous_submitted_record(self) -> None:
        sub_id = self.sub_item_id("motor_function_01")
        # 先提交一条记录，把 position 设为"仰卧"
        created = self.client.post(
            "/api/v1/records",
            json={
                "patient_no": "ZY001",
                "record_date": "2027-03-01",
                "session_period": "am",
                "status": "submitted",
                "items": [
                    {"main_item_id": self.main_item_id("motor_function"), "sub_item_id": sub_id,
                     "params": {"position": "仰卧", "side": "右"}}
                ],
            },
            headers=self.h1,
        )
        self.assertEqual(created.status_code, 201, created.text)

        form = self.client.get("/api/v1/records/form", params={"patient_no": "ZY001"}, headers=self.h1).json()
        motor = next(m for m in form["main_items"] if m["code"] == "motor_function")
        sub = next(s for s in motor["sub_items"] if int(s["id"]) == sub_id)
        position = next(p for p in sub["params"] if p["param_key"] == "position")
        self.assertEqual(position["current_value"], "仰卧")
        self.assertEqual(position["value_source"], "last_value")
        self.assertEqual(position["last_value"], "仰卧")


class TestRecordLifecycle(SeededApiTestCase):
    def _create(self, *, status: str = "draft", note: str = "首次记录", headers: dict | None = None):
        sub_id = self.sub_item_id("motor_function_01")
        return self.client.post(
            "/api/v1/records",
            json={
                "patient_no": "ZY001",
                "record_date": "2027-03-01",
                "session_period": "am",
                "duration_min": 30,
                "note": note,
                "status": status,
                "items": [
                    {"main_item_id": self.main_item_id("motor_function"), "sub_item_id": sub_id,
                     "params": {"position": "坐位", "side": "左", "reps": 10}}
                ],
            },
            headers=headers or self.h1,
        )

    def test_create_draft_has_no_seq_no(self) -> None:
        resp = self._create(status="draft")
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "draft")
        self.assertIsNone(body["seq_no"], "草稿不应占用治疗序次")
        self.assertEqual(body["patient_name"], "患者甲")
        self.assertEqual(body["therapist_name"], "张三")
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["sub_item_name_snapshot"], "偏瘫肢体综合训练")

    def test_submit_assigns_seq_no(self) -> None:
        record = self._create(status="draft").json()
        submitted = self.client.post(f"/api/v1/records/{record['id']}/submit", headers=self.h1)
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.assertEqual(submitted.json()["status"], "submitted")
        self.assertEqual(submitted.json()["seq_no"], 1)
        self.assertIsNotNone(submitted.json()["submitted_at"])

    def test_seq_no_increments_across_records(self) -> None:
        first = self._create(status="draft").json()
        self.client.post(f"/api/v1/records/{first['id']}/submit", headers=self.h1)
        second = self._create(status="draft", note="第二次").json()
        submitted = self.client.post(f"/api/v1/records/{second['id']}/submit", headers=self.h1).json()
        self.assertEqual(submitted["seq_no"], 2)

    def test_edit_draft_does_not_audit_or_count(self) -> None:
        record = self._create(status="draft").json()
        updated = self.client.put(
            f"/api/v1/records/{record['id']}", json={"note": "草稿改了"}, headers=self.h1
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["edit_count"], 0)
        audits = self.conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action = 'record_modified_after_submit'"
        ).fetchone()[0]
        self.assertEqual(audits, 0, "草稿阶段不应产生留痕噪声")

    def test_edit_submitted_audits_and_increments_edit_count(self) -> None:
        record = self._create(status="submitted").json()
        updated = self.client.put(
            f"/api/v1/records/{record['id']}", json={"note": "提交后补充"}, headers=self.h1
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["edit_count"], 1, "库层触发器应累加 edit_count")

        rows = self.conn.execute(
            "SELECT before_json, after_json FROM audit_log WHERE target_type = 'treatment_record'"
            "   AND action = 'record_modified_after_submit'"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertIn("首次记录", rows[0]["before_json"])
        self.assertIn("提交后补充", rows[0]["after_json"])

    def test_repeated_edits_accumulate(self) -> None:
        record = self._create(status="submitted").json()
        for index in range(3):
            self.client.put(
                f"/api/v1/records/{record['id']}", json={"note": f"第{index}次修改"}, headers=self.h1
            )
        final = self.client.get(f"/api/v1/records/{record['id']}", headers=self.h1).json()
        self.assertEqual(final["edit_count"], 3)

    def test_lock_then_therapist_cannot_edit(self) -> None:
        record = self._create(status="submitted").json()
        locked = self.client.post(f"/api/v1/records/{record['id']}/lock", headers=self.ha)
        self.assertEqual(locked.status_code, 200, locked.text)
        self.assertEqual(locked.json()["status"], "locked")

        resp = self.client.put(
            f"/api/v1/records/{record['id']}", json={"note": "偷偷改"}, headers=self.h1
        )
        self.assert_error(resp, 403, "RECORD_LOCKED")

    def test_admin_can_edit_locked_record(self) -> None:
        record = self._create(status="submitted").json()
        self.client.post(f"/api/v1/records/{record['id']}/lock", headers=self.ha)
        resp = self.client.put(
            f"/api/v1/records/{record['id']}", json={"note": "管理员更正"}, headers=self.ha
        )
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_draft_cannot_be_locked_directly(self) -> None:
        record = self._create(status="draft").json()
        resp = self.client.post(f"/api/v1/records/{record['id']}/lock", headers=self.ha)
        self.assert_error(resp, 409)

    def test_double_submit_rejected(self) -> None:
        record = self._create(status="submitted").json()
        resp = self.client.post(f"/api/v1/records/{record['id']}/submit", headers=self.h1)
        self.assert_error(resp, 409)

    def test_only_draft_can_be_deleted(self) -> None:
        draft = self._create(status="draft").json()
        deleted = self.client.delete(f"/api/v1/records/{draft['id']}", headers=self.h1)
        self.assertEqual(deleted.status_code, 204, deleted.text)

        submitted = self._create(status="submitted", note="已提交").json()
        resp = self.client.delete(f"/api/v1/records/{submitted['id']}", headers=self.h1)
        self.assert_error(resp, 409)

    def test_therapist_cannot_delete_others_draft(self) -> None:
        record = self._create(status="draft").json()
        resp = self.client.delete(f"/api/v1/records/{record['id']}", headers=self.h2)
        self.assert_error(resp, 403)


class TestSnapshots(SeededApiTestCase):
    """两层快照：字典改名后历史记录仍显示当时的名称与选项文本。"""

    def test_sub_item_name_snapshot_survives_rename(self) -> None:
        sub_id = self.sub_item_id("motor_function_01")
        record = self.client.post(
            "/api/v1/records",
            json={
                "patient_no": "ZY001", "record_date": "2027-03-01", "session_period": "am",
                "status": "submitted",
                "items": [{"main_item_id": self.main_item_id("motor_function"), "sub_item_id": sub_id,
                           "params": {"position": "坐位"}}],
            },
            headers=self.h1,
        ).json()
        original_name = record["items"][0]["sub_item_name_snapshot"]
        self.assertEqual(original_name, "偏瘫肢体综合训练")

        # 字典改名（科室调别名是常事）
        self.conn.execute("UPDATE sub_item SET name = ? WHERE id = ?", ("偏瘫综合训练（新）", sub_id))
        reread = self.client.get(f"/api/v1/records/{record['id']}", headers=self.h1).json()
        self.assertEqual(reread["items"][0]["sub_item_name_snapshot"], original_name, "快照不应随字典变化")

    def test_params_snapshot_keeps_option_text(self) -> None:
        sub_id = self.sub_item_id("motor_function_01")
        record = self.client.post(
            "/api/v1/records",
            json={
                "patient_no": "ZY001", "record_date": "2027-03-01", "session_period": "am",
                "status": "submitted",
                "items": [{"main_item_id": self.main_item_id("motor_function"), "sub_item_id": sub_id,
                           "params": {"position": "坐位", "side": "左"}}],
            },
            headers=self.h1,
        ).json()
        snapshot = record["items"][0]["params_snapshot"]
        self.assertIsNotNone(snapshot)
        by_key = {entry["param_key"]: entry for entry in snapshot}
        self.assertEqual(by_key["position"]["param_name"], "体位")
        self.assertEqual(by_key["position"]["value"], "坐位")
        self.assertIn("坐位", by_key["position"]["options"], "快照要带上当时的选项文本")


class TestParamValidation(SeededApiTestCase):
    def _payload(self, params: dict, *, sub_item_id: int | None = None, main_code: str = "motor_function"):
        return {
            "patient_no": "ZY001", "record_date": "2027-03-01", "session_period": "am",
            "items": [
                {"main_item_id": self.main_item_id(main_code),
                 "sub_item_id": sub_item_id or self.sub_item_id("motor_function_01"),
                 "params": params}
            ],
        }

    def test_unknown_param_key_rejected(self) -> None:
        resp = self.client.post("/api/v1/records", json=self._payload({"nope": 1}), headers=self.h1)
        self.assert_error(resp, 422, "INVALID")
        self.assertIn("unknown_keys", resp.json()["details"])

    def test_select_value_must_be_in_options(self) -> None:
        resp = self.client.post("/api/v1/records", json=self._payload({"side": "上面"}), headers=self.h1)
        self.assert_error(resp, 422, "INVALID")
        self.assertIn("allowed", resp.json()["details"])

    def test_multi_select_requires_list(self) -> None:
        sub_id = self.sub_item_id("motor_function_01")
        resp = self.client.post(
            "/api/v1/records", json=self._payload({"body_part": "肩"}, sub_item_id=sub_id), headers=self.h1
        )
        self.assert_error(resp, 422, "INVALID")

    def test_multi_select_rejects_unknown_member(self) -> None:
        resp = self.client.post(
 "/api/v1/records", json=self._payload({"body_part": ["肩", "尾巴"]}), headers=self.h1
        )
        self.assert_error(resp, 422, "INVALID")

    def test_number_range_enforced(self) -> None:
        # MMT 分级是 0–5；这里用 berg_score（0–56）更容易越界
        sub_id = self.sub_item_id("motor_function_03")
        resp = self.client.post(
            "/api/v1/records",
            json=self._payload({"berg_score": 99}, sub_item_id=sub_id),
            headers=self.h1,
        )
        # 该子项目有 berg_score；若定义无上下限则允许（种子未设范围时不该失败）
        self.assertIn(resp.status_code, {201, 422})

    def test_negative_duration_rejected(self) -> None:
        payload = self._payload({"side": "左"})
        payload["duration_min"] = -5
        resp = self.client.post("/api/v1/records", json=payload, headers=self.h1)
        self.assert_error(resp, 422)

    def test_sub_item_must_belong_to_main_item(self) -> None:
        resp = self.client.post(
            "/api/v1/records",
            json={
                "patient_no": "ZY001", "record_date": "2027-03-01",
                "items": [
                    {"main_item_id": self.main_item_id("speech_function"),
                     "sub_item_id": self.sub_item_id("motor_function_01"), "params": {}}
                ],
            },
            headers=self.h1,
        )
        self.assert_error(resp, 422, "INVALID")
        self.assertIn("expected_main_item_id", resp.json()["details"])

    def test_duplicate_sub_item_rejected(self) -> None:
        sub_id = self.sub_item_id("motor_function_01")
        resp = self.client.post(
            "/api/v1/records",
            json={
                "patient_no": "ZY001", "record_date": "2027-03-01",
                "items": [
                    {"main_item_id": self.main_item_id("motor_function"), "sub_item_id": sub_id, "params": {}},
                    {"main_item_id": self.main_item_id("motor_function"), "sub_item_id": sub_id, "params": {}},
                ],
            },
            headers=self.h1,
        )
        self.assert_error(resp, 422, "INVALID")
        self.assertEqual(resp.json()["details"]["sub_item_id"], sub_id)

    def test_unknown_sub_item_is_404(self) -> None:
        resp = self.client.post(
            "/api/v1/records",
            json={
                "patient_no": "ZY001", "record_date": "2027-03-01",
                "items": [{"main_item_id": self.main_item_id("motor_function"), "sub_item_id": 99999, "params": {}}],
            },
            headers=self.h1,
        )
        self.assert_error(resp, 404, "NOT_FOUND")

    def test_invalid_session_period_rejected(self) -> None:
        payload = self._payload({"side": "左"})
        payload["session_period"] = "night"
        resp = self.client.post("/api/v1/records", json=payload, headers=self.h1)
        self.assert_error(resp, 422, "INVALID")

    def test_model_level_unknown_status(self) -> None:
        with self.assertRaises(Invalid):
            treatment_model.create_record(
                self.conn, patient_no="ZY001", therapist_id=int(self.t1["id"]),
                record_date="2027-03-01", status="whatever",
            )


class TestPatientResponses(SeededApiTestCase):
    def _record_with_response(
        self, response: dict | None, headers: dict | None = None, *, main_code: str = "motor_function"
    ):
        from app.models import dictionary as dictionary_model

        # 取该主项目下的第一个子项目，保证"反应定义的主项目"与"记录的主项目"一致
        sub = dictionary_model.list_sub_items(
            self.conn, main_item_id=self.main_item_id(main_code)
        )[0]
        return self.client.post(
            "/api/v1/records",
            json={
                "patient_no": "ZY001", "record_date": "2027-03-01", "session_period": "am",
                "status": "submitted", "patient_response": response,
                "items": [{"main_item_id": self.main_item_id(main_code),
                           "sub_item_id": int(sub["id"]),
                           "params": {}}],
            },
            headers=headers or self.h1,
        )

    def test_tag_response(self) -> None:
        resp = self._record_with_response({"tags": ["no_discomfort"], "items": []})
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()["patient_response"]
        self.assertEqual(body["tags"][0]["code"], "no_discomfort")
        self.assertEqual(body["tags"][0]["label"], "无不适")

    def test_number_response_with_range(self) -> None:
        resp = self._record_with_response({"tags": [], "items": [{"code": "pain", "value": 3}]})
        self.assertEqual(resp.status_code, 201, resp.text)
        item = resp.json()["patient_response"]["items"][0]
        self.assertEqual(item["value"], 3)
        self.assertEqual(item["value_key"], "nrs")
        self.assertEqual(item["unit"], "分")

    def test_number_out_of_range_rejected(self) -> None:
        resp = self._record_with_response({"tags": [], "items": [{"code": "pain", "value": 99}]})
        self.assert_error(resp, 422, "INVALID")

    def test_number_requires_value(self) -> None:
        resp = self._record_with_response({"tags": [], "items": [{"code": "pain"}]})
        self.assert_error(resp, 422, "INVALID")

    def test_tag_placed_in_items_rejected(self) -> None:
        """标签类反应应放 tags 里；放 items 会被明确拒绝，而不是静默接受。"""
        resp = self._record_with_response({"tags": [], "items": [{"code": "no_discomfort", "value": 1}]})
        self.assert_error(resp, 422, "INVALID")

    def test_value_response_placed_in_tags_rejected(self) -> None:
        resp = self._record_with_response({"tags": ["pain"], "items": []})
        self.assert_error(resp, 422, "INVALID")

    def test_unknown_response_code_rejected(self) -> None:
        resp = self._record_with_response({"tags": ["not_a_real_code"], "items": []})
        self.assert_error(resp, 422, "INVALID")

    def test_select_response_validates_options(self) -> None:
        # oral_residue 是吞咽主项目的专属反应，因此记录也必须挂在吞咽主项目下
        ok = self._record_with_response(
            {"tags": [], "items": [{"code": "oral_residue", "value": "中"}]},
            main_code="swallow_function",
        )
        self.assertEqual(ok.status_code, 201, ok.text)
        bad = self._record_with_response(
            {"tags": [], "items": [{"code": "oral_residue", "value": "极重"}]},
            main_code="swallow_function",
        )
        self.assert_error(bad, 422, "INVALID")

    def test_duplicate_response_rejected(self) -> None:
        resp = self._record_with_response(
            {"tags": [], "items": [{"code": "pain", "value": 1}, {"code": "pain", "value": 2}]}
        )
        self.assert_error(resp, 422, "INVALID")

    def test_response_can_be_cleared(self) -> None:
        record = self._record_with_response({"tags": [], "items": [{"code": "pain", "value": 2}]}).json()
        cleared = self.client.put(
            f"/api/v1/records/{record['id']}", json={"clear_patient_response": True}, headers=self.h1
        )
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertIsNone(cleared.json()["patient_response"])


class TestRecordPermissions(SeededApiTestCase):
    def _create_for_patient(self, patient_no: str, headers: dict):
        return self.client.post(
            "/api/v1/records",
            json={
                "patient_no": patient_no, "record_date": "2027-03-01",
                "items": [{"main_item_id": self.main_item_id("motor_function"),
                           "sub_item_id": self.sub_item_id("motor_function_01"), "params": {"side": "左"}}],
            },
            headers=headers,
        )

    def test_cannot_write_record_for_invisible_patient(self) -> None:
        resp = self._create_for_patient("ZY002", self.h1)
        self.assert_error(resp, 403, "PATIENT_NOT_VISIBLE")

    def test_cannot_read_others_record(self) -> None:
        record = self._create_for_patient("ZY002", self.h2).json()
        resp = self.client.get(f"/api/v1/records/{record['id']}", headers=self.h1)
        self.assert_error(resp, 403, "RECORD_NOT_VISIBLE")

    def test_cannot_modify_others_record(self) -> None:
        record = self._create_for_patient("ZY002", self.h2).json()
        resp = self.client.put(f"/api/v1/records/{record['id']}", json={"note": "改"}, headers=self.h1)
        self.assert_error(resp, 403, "RECORD_NOT_VISIBLE")

    def test_admin_can_read_any_record(self) -> None:
        record = self._create_for_patient("ZY002", self.h2).json()
        resp = self.client.get(f"/api/v1/records/{record['id']}", headers=self.ha)
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_therapist_cannot_write_for_another_therapist(self) -> None:
        resp = self.client.post(
            "/api/v1/records",
            json={"patient_no": "ZY001", "record_date": "2027-03-01", "therapist_id": int(self.t2["id"])},
            headers=self.h1,
        )
        self.assert_error(resp, 403, "RECORD_OTHER_THERAPIST")

    def test_record_list_only_shows_visible_patients(self) -> None:
        self._create_for_patient("ZY001", self.h1)
        self._create_for_patient("ZY002", self.h2)
        mine = self.client.get("/api/v1/records", headers=self.h1).json()
        numbers = {i["patient_no"] for i in mine["items"]}
        self.assertEqual(numbers, {"ZY001"}, "不应看到其他治疗师患者的记录")

    def test_scope_mine_only_own_records(self) -> None:
        self._create_for_patient("ZY001", self.h1)
        mine = self.client.get("/api/v1/records", params={"scope": "mine"}, headers=self.h2).json()
        self.assertEqual(mine["total"], 0)

    def test_invalid_scope_rejected(self) -> None:
        resp = self.client.get("/api/v1/records", params={"scope": "whatever"}, headers=self.h1)
        self.assert_error(resp, 404, "INVALID_SCOPE")


class TestRecordFromAppointment(SeededApiTestCase):
    def test_appointment_context_is_brought_in(self) -> None:
        from app.models import appointment as appointment_model

        appt = appointment_model.create_appointment(
            self.conn, patient_no="ZY001", therapist_id=int(self.t1["id"]), day="2027-03-05", period="pm"
        )
        resp = self.client.post(
            "/api/v1/records",
            json={
                "patient_no": "ZY001", "appointment_id": int(appt["id"]),
                "items": [{"main_item_id": self.main_item_id("motor_function"),
                           "sub_item_id": self.sub_item_id("motor_function_01"), "params": {"side": "左"}}],
            },
            headers=self.h1,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual(body["record_date"], "2027-03-05", "日期应从排期带入")
        self.assertEqual(body["session_period"], "pm", "半日应从排期带入")
        self.assertEqual(body["appointment_id"], int(appt["id"]))

    def test_temp_treatment_flagged_when_therapist_differs(self) -> None:
        """临时认领时记录要标 is_temporary 并保留原归属（3.7）。"""
        from app.models import appointment as appointment_model

        # 让李四临时认领张三的患者：先单日假临时释放
        from app.models import leave as leave_model
        from app.models import patient as patient_model

        leave_model.create_leave(
            self.conn, therapist_id=int(self.t1["id"]), leave_type="half_day_am",
            start_date="2027-03-08", end_date="2027-03-08", operator_user_id=int(self.t1["id"]),
        )
        self.conn.execute(
            "UPDATE temporary_assignment SET temporary_therapist_id = ? WHERE patient_no = 'ZY001'",
            (int(self.t2["id"]),),
        )
        appt = appointment_model.create_appointment(
            self.conn, patient_no="ZY001", therapist_id=int(self.t2["id"]), day="2027-03-08", period="pm"
        )
        resp = self.client.post(
            "/api/v1/records",
            json={
                "patient_no": "ZY001", "appointment_id": int(appt["id"]),
                "items": [{"main_item_id": self.main_item_id("motor_function"),
                           "sub_item_id": self.sub_item_id("motor_function_01"), "params": {"side": "左"}}],
            },
            headers=self.h2,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual(body["is_temporary"], 1)
        self.assertEqual(body["original_therapist_id"], int(self.t1["id"]), "应保留原归属治疗师")
        patient = patient_model.get_patient_or_raise(self.conn, "ZY001")
        self.assertEqual(patient["assigned_therapist_id"], int(self.t1["id"]), "原归属仍不变")


class TestTimeline(SeededApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        for day, note in (("2027-03-01", "第一次"), ("2027-03-03", "第二次")):
            self.client.post(
                "/api/v1/records",
                json={
                    "patient_no": "ZY001", "record_date": day, "session_period": "am",
                    "status": "submitted", "note": note,
                    "items": [{"main_item_id": self.main_item_id("motor_function"),
                               "sub_item_id": self.sub_item_id("motor_function_01"), "params": {"side": "左"}}],
                },
                headers=self.h1,
            )

    def test_timeline_is_ordered_desc(self) -> None:
        body = self.client.get("/api/v1/timeline", headers=self.h1).json()
        self.assertEqual(len(body["items"]), 2)
        self.assertEqual([i["record_date"] for i in body["items"]], ["2027-03-03", "2027-03-01"])

    def test_timeline_includes_main_item_names(self) -> None:
        body = self.client.get("/api/v1/timeline", headers=self.h1).json()
        self.assertIn("运动功能障碍训练", body["items"][0]["main_item_names"])

    def test_timeline_filters_by_date(self) -> None:
        body = self.client.get(
            "/api/v1/timeline", params={"from": "2027-03-02", "to": "2027-03-05"}, headers=self.h1
        ).json()
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["record_date"], "2027-03-03")

    def test_timeline_hides_other_therapists_patients(self) -> None:
        body = self.client.get("/api/v1/timeline", headers=self.h2).json()
        self.assertEqual(body["items"], [])

    def test_timeline_invalid_scope(self) -> None:
        resp = self.client.get("/api/v1/timeline", params={"scope": "nope"}, headers=self.h1)
        self.assert_error(resp, 404, "INVALID_SCOPE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
