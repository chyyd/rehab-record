"""四大高频模板种子测试（`开发计划.md` D04 / T3.2、`设计.md` 8.2）。

覆盖重点：
1. **四套模板齐全**，且每套归属对应主项目、含该主项目下的全部子项目；
2. **与 `设计.md` 8.2 一致**：模板里的子项目就是字典里的子项目，不另立一套；
3. **参数预填值正确**：取自字典默认值，且**类型正确**（数字是数字、单选是标量、多选是数组）；
4. **幂等**：重复导入不产生重复行，明细是替换而非追加；
5. **可套用**：套用返回的参数能直接通过记录创建接口的参数校验。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.models import template as template_model
from seed.dictionary import seed_dictionary
from seed.templates import SEED_FILE, load_templates, seed_templates
from tests.support import DbTestCase

# 设计.md 8.2 的四大子项目清单（作为独立对照，不引用种子自身，避免"自己证明自己"）
EXPECTED = {
    "motor_function": [
        "偏瘫肢体综合训练", "关节松动训练", "平衡功能训练",
        "步态训练", "神经发育疗法", "肌力训练",
    ],
    "adl_skill": [
        "进食训练", "穿衣训练", "修饰训练", "如厕训练",
        "洗澡训练", "转移训练", "家务劳动训练", "社交技能训练",
    ],
    "speech_function": [
        "失语症治疗", "构音障碍治疗", "口吃治疗",
        "儿童语言康复", "发声障碍治疗", "实用交流能力训练",
    ],
    "swallow_function": [
        "口腔感觉训练", "口腔运动训练", "吞咽手法训练", "姿势治疗", "呼吸功能训练",
        "导管球囊扩张", "摄食训练", "吞咽电刺激", "说话瓣膜佩戴",
    ],
}


class TemplateSeedTestCase(DbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        seed_dictionary(self.conn)
        self.stats = seed_templates(self.conn)

    def templates(self) -> list[dict]:
        return template_model.list_templates(self.conn, owner_user_id=None)

    def template_for(self, main_code: str) -> dict:
        main_id = int(
            self.conn.execute("SELECT id FROM main_item WHERE code = ?", (main_code,)).fetchone()["id"]
        )
        found = [t for t in self.templates() if int(t["main_item_id"]) == main_id]
        self.assertEqual(len(found), 1, f"{main_code} 应有且仅有一套模板")
        return template_model.get_template_or_raise(self.conn, int(found[0]["id"]))


class TestTemplateSeedShape(TemplateSeedTestCase):
    def test_seeds_four_templates(self) -> None:
        self.assertEqual(self.stats.templates, 4)
        self.assertEqual(self.stats.created, 4)
        self.assertEqual(len(self.templates()), 4)

    def test_all_templates_are_dept_scope_without_owner(self) -> None:
        """种子只导入科室模板：个人模板属于治疗师私有数据，不该由种子产生。"""
        for template in self.templates():
            self.assertEqual(template["scope"], "dept")
            self.assertIsNone(template["owner_user_id"])

    def test_each_main_item_has_exactly_one_template(self) -> None:
        rows = self.conn.execute(
            "SELECT m.code, COUNT(t.id) AS n FROM main_item m"
            " LEFT JOIN record_template t ON t.main_item_id = m.id"
            " GROUP BY m.id ORDER BY m.sort"
        ).fetchall()
        self.assertEqual(len(rows), 4)
        for row in rows:
            self.assertEqual(int(row["n"]), 1, f"{row['code']} 应有一套模板")

    def test_total_items_match_sub_item_count(self) -> None:
        """四套模板合计明细数应等于 29 个子项目（每套含该主项目全部子项目）。"""
        total = self.conn.execute("SELECT COUNT(*) FROM record_template_item").fetchone()[0]
        subs = self.conn.execute("SELECT COUNT(*) FROM sub_item").fetchone()[0]
        self.assertEqual(subs, 29)
        self.assertEqual(total, subs)
        self.assertEqual(self.stats.items, 29)

    def test_sub_items_match_design_doc_8_2(self) -> None:
        """逐套核对子项目与 `设计.md` 8.2.1–8.2.4 的清单一致。"""
        for main_code, expected_names in EXPECTED.items():
            template = self.template_for(main_code)
            actual = []
            for item in template["items"]:
                row = self.conn.execute(
                    "SELECT name FROM sub_item WHERE id = ?", (int(item["sub_item_id"]),)
                ).fetchone()
                actual.append(row["name"])
            self.assertEqual(actual, expected_names, f"{main_code} 的子项目清单与设计文档不一致")

    def test_item_sort_follows_dictionary_order(self) -> None:
        """明细顺序应与字典里的子项目顺序一致，前端展示才稳定。"""
        for main_code in EXPECTED:
            template = self.template_for(main_code)
            sorts = [int(i["sort"]) for i in template["items"]]
            self.assertEqual(sorts, sorted(sorts))
            self.assertEqual(sorts, [i * 10 for i in range(len(sorts))])


class TestTemplateSeedParams(TemplateSeedTestCase):
    def test_params_sourced_from_dictionary_defaults(self) -> None:
        """预填参数必须等于字典里的默认值 —— 两者同源，不应各写一套。"""
        template = self.template_for("motor_function")
        first = template["items"][0]  # 偏瘫肢体综合训练
        sub_item_id = int(first["sub_item_id"])
        defaults: dict[str, object] = {}
        for row in self.conn.execute(
            "SELECT param_key, default_value, input_type FROM sub_item_param_def"
            " WHERE sub_item_id = ? AND default_value IS NOT NULL",
            (sub_item_id,),
        ).fetchall():
            raw = row["default_value"]
            if row["input_type"] == "number":
                number = float(raw)
                defaults[row["param_key"]] = int(number) if number.is_integer() else number
            elif row["input_type"] == "select":
                defaults[row["param_key"]] = json.loads(raw)[0]
            else:
                defaults[row["param_key"]] = json.loads(raw)
        self.assertEqual(first["params"], defaults)

    def test_number_params_are_numbers_not_strings(self) -> None:
        """字典里默认值以字符串存储（`'10'`），模板参数必须是数字 10。

        直接把存储形式塞进模板会让表单收到字符串，数字参数校验与统计都会出问题。
        """
        params = self.template_for("motor_function")["items"][0]["params"]
        self.assertIsInstance(params["reps"], int)
        self.assertIsInstance(params["sets"], int)
        self.assertEqual(params["reps"], 10)
        self.assertEqual(params["sets"], 3)
        # 米数也是数字
        walk = next(
            i for i in self.template_for("motor_function")["items"]
            if i["sub_item_id"] == self._sub_id("motor_function_04")
        )
        self.assertIsInstance(walk["params"]["walk_distance"], int)

    def test_single_select_params_are_scalars(self) -> None:
        """单选参数存标量：字典里是 `["坐位"]`，模板里应是 `"坐位"`。"""
        params = self.template_for("motor_function")["items"][0]["params"]
        self.assertEqual(params["position"], "坐位")
        self.assertEqual(params["side"], "左")
        self.assertNotIsInstance(params["position"], list)

    def test_multi_select_params_stay_lists(self) -> None:
        template = self.template_for("adl_skill")
        grooming = next(
            i for i in template["items"] if i["sub_item_id"] == self._sub_id("adl_skill_03")
        )
        self.assertEqual(grooming["params"]["items"], ["洗脸", "刷牙"])

    def test_params_without_default_are_omitted(self) -> None:
        """没有默认值的参数不写入 —— 预填 None 会在表单上显示成"已填"。"""
        params = self.template_for("swallow_function")["items"]
        for item in params:
            for value in item["params"].values():
                self.assertIsNotNone(value)
        # 导管球囊扩张的球囊容量/扩张次数在设计里没有默认值
        balloon = next(
            i for i in params if i["sub_item_id"] == self._sub_id("swallow_function_06")
        )
        self.assertNotIn("balloon_volume", balloon["params"])
        self.assertNotIn("dilation_count", balloon["params"])
        self.assertEqual(balloon["params"], {"insertion_route": "经鼻"})

    def _sub_id(self, code: str) -> int:
        return int(self.conn.execute("SELECT id FROM sub_item WHERE code = ?", (code,)).fetchone()["id"])


class TestTemplateSeedIdempotency(TemplateSeedTestCase):
    def test_rerun_updates_instead_of_duplicating(self) -> None:
        again = seed_templates(self.conn)
        self.assertEqual(again.created, 0)
        self.assertEqual(again.updated, 4)
        self.assertEqual(len(self.templates()), 4)
        total = self.conn.execute("SELECT COUNT(*) FROM record_template_item").fetchone()[0]
        self.assertEqual(total, 29, "明细应整体替换，不能追加成 58 条")

    def test_three_runs_stable(self) -> None:
        for _ in range(3):
            seed_templates(self.conn)
        self.assertEqual(len(self.templates()), 4)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM record_template_item").fetchone()[0], 29)

    def test_manual_rename_is_restored_by_seed(self) -> None:
        """种子是"标准模板"：改过名称后再导一次会**恢复原名**而不是新增一套。

        这条断言的是身份键的正确性：早先按 (scope, main_item_id, name) 查找，
        而唯一索引含 name，改名后重导会查不到旧行、再插一行 → 5 套模板（实测踩到）。
        改用稳定的 `code` 后仍命中同一行。
        """
        template_id = int(self.templates()[0]["id"])
        self.conn.execute("UPDATE record_template SET name = '被改过的名字' WHERE id = ?", (template_id,))
        seed_templates(self.conn)
        row = self.conn.execute("SELECT name FROM record_template WHERE id = ?", (template_id,)).fetchone()
        self.assertTrue(row["name"].endswith("·常规"), row["name"])
        self.assertEqual(len(self.templates()), 4, "改名后重导不应产生第 5 套模板")

    def test_seeded_templates_carry_stable_code(self) -> None:
        codes = {t["code"] for t in self.templates()}
        self.assertEqual(
            codes,
            {"tpl_motor_function", "tpl_adl_skill", "tpl_speech_function", "tpl_swallow_function"},
        )

    def test_personal_template_with_same_name_is_untouched(self) -> None:
        """个人模板与科室模板同名时互不影响（唯一键含 scope 与 owner）。"""
        main_id = int(self.templates()[0]["main_item_id"])
        user_id = self._make_user()
        self.conn.execute(
            "INSERT INTO record_template (scope, owner_user_id, main_item_id, name, sort)"
            " VALUES ('personal', ?, ?, '运动功能障碍训练·常规', 0)",
            (user_id, main_id),
        )
        seed_templates(self.conn)
        personal = self.conn.execute(
            "SELECT COUNT(*) FROM record_template WHERE scope = 'personal'"
        ).fetchone()[0]
        self.assertEqual(personal, 1)
        self.assertEqual(len(self.templates()), 4, "科室模板仍应是 4 套")

    def _make_user(self) -> int:
        from app.models import user as user_model

        user = user_model.create_user(
            self.conn, employee_no="T999", name="测试治疗师",
            role=user_model.ROLE_THERAPIST, password="Test#2026pass",
        )
        return int(user["id"])


class TestTemplateSeedErrors(TemplateSeedTestCase):
    def test_missing_dictionary_raises_clear_error(self) -> None:
        """字典没导时导入模板要明确报错，而不是产生半套数据。"""
        from app.core.config import Settings
        from app.db import storage
        from seed.dictionary import SeedError

        # 借同一个临时目录建一个**空库**（只有表、没有字典），tearDown 会清掉
        empty_path = Path(str(self.db_file) + "-emptydict.db")
        self._scratch.append(empty_path)
        empty_settings = Settings(db_path=empty_path)
        conn2 = storage.connect(empty_settings)
        try:
            storage.migrate(conn2, storage.discover_migrations(settings=empty_settings))
            with self.assertRaises(SeedError) as ctx:
                seed_templates(conn2)
            self.assertIn("主项目不存在", str(ctx.exception))
        finally:
            conn2.close()

    def test_bad_template_missing_main_code(self) -> None:
        from seed.dictionary import SeedError

        bad = self._write_seed({"templates": [{"code": "x", "name": "x", "sub_item_codes": ["a"]}]})
        with self.assertRaises(SeedError):
            load_templates(bad)

    def test_bad_template_missing_code(self) -> None:
        """code 是身份键，缺了必须报错 —— 否则幂等性与改名恢复都会失效。"""
        from seed.dictionary import SeedError

        bad = self._write_seed(
            {"templates": [{"name": "x", "main_item_code": "motor_function",
                            "sub_item_codes": ["motor_function_01"]}]}
        )
        with self.assertRaises(SeedError) as ctx:
            load_templates(bad)
        self.assertIn("code", str(ctx.exception))

    def test_bad_template_duplicate_code(self) -> None:
        from seed.dictionary import SeedError

        bad = self._write_seed(
            {
                "templates": [
                    {"code": "same", "name": "a", "main_item_code": "motor_function",
                     "sub_item_codes": ["motor_function_01"]},
                    {"code": "same", "name": "b", "main_item_code": "adl_skill",
                     "sub_item_codes": ["adl_skill_01"]},
                ]
            }
        )
        with self.assertRaises(SeedError) as ctx:
            load_templates(bad)
        self.assertIn("code 重复", str(ctx.exception))

    def test_bad_template_duplicate_name_in_same_main(self) -> None:
        from seed.dictionary import SeedError

        bad = self._write_seed(
            {
                "templates": [
                    {"code": "c1", "name": "x", "main_item_code": "motor_function",
                     "sub_item_codes": ["motor_function_01"]},
                    {"code": "c2", "name": "x", "main_item_code": "motor_function",
                     "sub_item_codes": ["motor_function_02"]},
                ]
            }
        )
        with self.assertRaises(SeedError) as ctx:
            load_templates(bad)
        self.assertIn("重复", str(ctx.exception))

    def test_bad_template_empty_sub_items(self) -> None:
        from seed.dictionary import SeedError

        bad = self._write_seed(
            {"templates": [{"code": "c1", "name": "x", "main_item_code": "motor_function",
                            "sub_item_codes": []}]}
        )
        with self.assertRaises(SeedError):
            load_templates(bad)

    def test_bad_template_duplicate_sub_items(self) -> None:
        from seed.dictionary import SeedError

        bad = self._write_seed(
            {
                "templates": [
                    {
                        "code": "c1", "name": "x", "main_item_code": "motor_function",
                        "sub_item_codes": ["motor_function_01", "motor_function_01"],
                    }
                ]
            }
        )
        with self.assertRaises(SeedError) as ctx:
            load_templates(bad)
        self.assertIn("重复", str(ctx.exception))

    def test_non_dept_scope_rejected(self) -> None:
        """种子只导科室模板；写 personal 会被拒绝（个人模板不该由种子产生）。"""
        from seed.dictionary import SeedError

        bad = self._write_seed(
            {
                "templates": [
                    {
                        "code": "c1", "name": "x", "scope": "personal",
                        "main_item_code": "motor_function",
                        "sub_item_codes": ["motor_function_01"],
                    }
                ]
            }
        )
        with self.assertRaises(SeedError) as ctx:
            load_templates(bad)
        self.assertIn("科室模板", str(ctx.exception))

    def test_unknown_sub_item_raises(self) -> None:
        from seed.dictionary import SeedError

        bad = self._write_seed(
            {
                "templates": [
                    {"code": "c1", "name": "x", "main_item_code": "motor_function",
                     "sub_item_codes": ["no_such_code"]}
                ]
            }
        )
        with self.assertRaises(SeedError) as ctx:
            seed_templates(self.conn, bad)
        self.assertIn("子项目不存在", str(ctx.exception))

    def _write_seed(self, extra: dict) -> Path:
        """基于真实种子改一份临时种子文件（放 data/ 下，tearDown 清理）。"""
        data = json.loads(SEED_FILE.read_text(encoding="utf-8"))
        data.update(extra)
        path = self.tmp_path / "bad_template_seed.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path


class TestSeededTemplateIsUsable(TemplateSeedTestCase):
    """种子模板必须真的能用：套用 → 参数能通过记录创建校验。"""

    def test_apply_returns_prefill_for_every_template(self) -> None:
        for template in self.templates():
            applied = template_model.apply_template(self.conn, int(template["id"]))
            self.assertEqual(len(applied["items"]), len(
                template_model.get_template_or_raise(self.conn, int(template["id"]))["items"]
            ))
            for item in applied["items"]:
                self.assertIsInstance(item["main_item_id"], int)
                self.assertIsInstance(item["sub_item_id"], int)

    def test_applied_params_pass_record_validation(self) -> None:
        """最关键的一条：套用出来的参数直接建记录必须成功。

        这条能一次性抓住"类型错、键名错、选项不在集合内"等所有漂移问题。
        """
        from app.models import patient as patient_model
        from app.models import treatment as treatment_model
        from app.models import user as user_model

        patient_model.create_patient(self.conn, inpatient_no="ZY900", name="模板验证患者")
        therapist = user_model.create_user(
            self.conn, employee_no="T900", name="模板验证治疗师",
            role=user_model.ROLE_THERAPIST, password="Test#2026pass",
        )
        for template in self.templates():
            applied = template_model.apply_template(self.conn, int(template["id"]))
            record = treatment_model.create_record(
                self.conn,
                patient_no="ZY900",
                therapist_id=int(therapist["id"]),
                record_date="2027-08-01",
                session_period="am",
                items=[
                    {
                        "main_item_id": item["main_item_id"],
                        "sub_item_id": item["sub_item_id"],
                        "params": item["params"],
                    }
                    for item in applied["items"]
                ],
            )
            self.assertEqual(len(record["items"]), len(applied["items"]), template["name"])

    def test_applied_params_keys_are_known_params(self) -> None:
        """预填参数的键必须是该子项目真实存在的 param_key。"""
        for template in self.templates():
            applied = template_model.apply_template(self.conn, int(template["id"]))
            for item in applied["items"]:
                known = {
                    row["param_key"]
                    for row in self.conn.execute(
                        "SELECT param_key FROM sub_item_param_def WHERE sub_item_id = ?",
                        (item["sub_item_id"],),
                    ).fetchall()
                }
                unknown = set(item["params"]) - known
                self.assertEqual(unknown, set(), f"{item['sub_item_name']} 有未知参数键 {unknown}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
