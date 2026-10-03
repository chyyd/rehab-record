"""患者反应定义与选项集种子（`设计.md` 3.6.4 / 3.6.5）。

覆盖点：
- 两份种子能加载并通过结构校验；
- 反应定义与库层 CHECK 自洽（tag 不带 value_key、select 必须有选项、范围不颠倒）；
- **幂等**：重复导入不新增行；
- 反应定义引用的 `main_item.code` 必须先存在（导入顺序依赖）；
- 选项集回归：`(scope, dept_tag, code)` 唯一，非主变体被跳过并计数；
- 整体失败回滚。
"""

from __future__ import annotations

import json
import unittest

from seed import dictionary, options, responses
from tests.support import DbTestCase


class TestResponseSeedIntegrity(DbTestCase):
    def test_seed_loads_and_validates(self) -> None:
        data = responses.load_seed_data()
        responses.validate(data)
        self.assertGreaterEqual(len(data["response_defs"]), 20, "反应定义数量异常偏少")

    def test_covers_all_four_main_items(self) -> None:
        data = responses.load_seed_data()
        covered = {d["main_item_code"] for d in data["response_defs"]}
        self.assertEqual(covered, {"motor_function", "adl_skill", "speech_function", "swallow_function"})

    def test_has_expected_value_types(self) -> None:
        """疼痛 NRS 是 number、残留程度是 select、无不适是 tag —— 三类都必须存在。"""
        data = responses.load_seed_data()
        by_code = {d["code"]: d for d in data["response_defs"]}
        self.assertEqual(by_code["pain"]["value_type"], "number")
        self.assertEqual(by_code["pain"]["value_key"], "nrs")
        self.assertEqual((by_code["pain"]["value_min"], by_code["pain"]["value_max"]), (0, 10))
        self.assertEqual(by_code["no_discomfort"]["value_type"], "tag")
        self.assertIsNone(by_code["no_discomfort"]["value_key"])
        self.assertEqual(by_code["oral_residue"]["value_type"], "select")
        self.assertEqual(by_code["oral_residue"]["options"], ["轻", "中", "重"])
        self.assertEqual(by_code["choke"]["value_key"], "count")

    def test_tag_with_value_key_rejected(self) -> None:
        bad = {"response_defs": [{"code": "x", "main_item_code": "m", "value_type": "tag", "value_key": "k"}]}
        with self.assertRaises(responses.ResponseSeedError):
            responses.validate(bad)

    def test_select_without_options_rejected(self) -> None:
        bad = {"response_defs": [{"code": "x", "main_item_code": "m", "value_type": "select"}]}
        with self.assertRaises(responses.ResponseSeedError):
            responses.validate(bad)

    def test_inverted_range_rejected(self) -> None:
        bad = {
            "response_defs": [
                {"code": "x", "main_item_code": "m", "value_type": "number", "value_min": 10, "value_max": 0}
            ]
        }
        with self.assertRaises(responses.ResponseSeedError):
            responses.validate(bad)

    def test_duplicate_code_within_main_item_rejected(self) -> None:
        bad = {
            "response_defs": [
                {"code": "x", "main_item_code": "m", "value_type": "tag"},
                {"code": "x", "main_item_code": "m", "value_type": "tag"},
            ]
        }
        with self.assertRaises(responses.ResponseSeedError):
            responses.validate(bad)


class TestResponseSeedImport(DbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.migrate()

    def test_requires_dictionary_first(self) -> None:
        """字典未导入时，反应定义无法解析 main_item.code，必须给出可读的错误。"""
        with self.assertRaises(responses.ResponseSeedError) as ctx:
            responses.seed_responses(self.conn)
        self.assertIn("字典种子", str(ctx.exception))

    def test_import_creates_rows(self) -> None:
        dictionary.seed_dictionary(self.conn)
        stats = responses.seed_responses(self.conn)
        expected = len(responses.load_seed_data()["response_defs"])
        self.assertEqual(stats.total, expected)
        self.assertEqual(stats.created, expected)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM response_def").fetchone()[0], expected
        )

    def test_import_is_idempotent(self) -> None:
        dictionary.seed_dictionary(self.conn)
        first = responses.seed_responses(self.conn)
        count_after_first = self.conn.execute("SELECT COUNT(*) FROM response_def").fetchone()[0]
        second = responses.seed_responses(self.conn)
        count_after_second = self.conn.execute("SELECT COUNT(*) FROM response_def").fetchone()[0]
        self.assertEqual(count_after_first, count_after_second)
        self.assertEqual(second.created, 0)
        self.assertEqual(second.updated, first.total)

    def test_number_response_stores_range_and_unit(self) -> None:
        dictionary.seed_dictionary(self.conn)
        responses.seed_responses(self.conn)
        row = self.conn.execute(
            "SELECT label, value_type, value_key, value_min, value_max, value_unit FROM response_def"
            " WHERE code = 'spo2_drop'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["value_type"], "number")
        self.assertEqual(row["value_key"], "spo2")
        self.assertEqual(row["value_unit"], "%")

    def test_select_options_are_json_queryable(self) -> None:
        dictionary.seed_dictionary(self.conn)
        responses.seed_responses(self.conn)
        value = self.conn.execute(
            "SELECT json_extract(options_json, '$[2]') FROM response_def WHERE code = 'oral_residue'"
        ).fetchone()[0]
        self.assertEqual(value, "重")

    def test_import_failure_rolls_back(self) -> None:
        dictionary.seed_dictionary(self.conn)
        bad = self.tmp_path / "bad_resp.json"
        bad.write_text(
            json.dumps(
                {"response_defs": [{"code": "x", "main_item_code": "NOT_EXIST", "value_type": "tag"}]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        with self.assertRaises(responses.ResponseSeedError):
            responses.seed_responses(self.conn, bad)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM response_def").fetchone()[0], 0)


class TestOptionSeedIntegrity(DbTestCase):
    def test_seed_loads_and_validates(self) -> None:
        data = options.load_seed_data()
        options.validate(data)
        self.assertGreaterEqual(len(data["option_sets"]), 30, "选项集数量异常偏少")

    def test_every_set_has_items_and_unique_values(self) -> None:
        data = options.load_seed_data()
        for item in data["option_sets"]:
            values = [i["value"] for i in item["items"]]
            self.assertEqual(len(values), len(set(values)), f"{item['code']} 选项值重复")

    def test_duplicate_primary_rejected(self) -> None:
        bad = {
            "option_sets": [
                {"code": "k", "scope": "global", "is_primary": True, "items": [{"value": "a"}]},
                {"code": "k", "scope": "global", "is_primary": True, "items": [{"value": "b"}]},
            ]
        }
        with self.assertRaises(options.OptionSeedError):
            options.validate(bad)

    def test_empty_items_rejected(self) -> None:
        bad = {"option_sets": [{"code": "k", "scope": "global", "is_primary": True, "items": []}]}
        with self.assertRaises(options.OptionSeedError):
            options.validate(bad)


class TestOptionSeedImport(DbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.migrate()

    def test_import_creates_global_sets(self) -> None:
        stats = options.seed_options(self.conn)
        self.assertGreater(stats.sets, 30)
        self.assertGreater(stats.items, 100)
        rows = self.conn.execute("SELECT COUNT(*) FROM option_set WHERE scope = 'global'").fetchone()[0]
        self.assertEqual(rows, stats.sets)

    def test_import_is_idempotent(self) -> None:
        first = options.seed_options(self.conn)
        sets_after_first = self.conn.execute("SELECT COUNT(*) FROM option_set").fetchone()[0]
        items_after_first = self.conn.execute("SELECT COUNT(*) FROM option_item").fetchone()[0]
        second = options.seed_options(self.conn)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM option_set").fetchone()[0], sets_after_first)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM option_item").fetchone()[0], items_after_first)
        self.assertEqual(second.created_sets, 0)
        self.assertEqual(second.created_items, 0)
        self.assertEqual(second.updated_sets, first.sets)

    def test_variants_are_skipped_and_counted(self) -> None:
        """同一 code 的多套选项变体在全局层只保留主变体，其余必须被计数而不是静默丢弃。

        `variants` 是 code → 被跳过的变体数；`skipped_variants` 是总数。
        """
        stats = options.seed_options(self.conn)
        self.assertGreater(stats.skipped_variants, 0, "应当存在需要跳过的变体")
        self.assertEqual(sum(stats.variants.values()), stats.skipped_variants,
                         "variants 各 code 的计数之和必须等于被跳过总数")
        self.assertLess(len(stats.variants), stats.skipped_variants,
                        "存在同一 code 有多个变体的情况")
        # 抽一个已知有多套选项的参数核对：辅助程度有 6 项与 4 项两套
        self.assertIn("assistance_level", stats.variants)

    def test_no_duplicate_scope_code(self) -> None:
        options.seed_options(self.conn)
        dupes = self.conn.execute(
            "SELECT scope, IFNULL(dept_tag,'') d, code, COUNT(*) c FROM option_set"
            " GROUP BY scope, IFNULL(dept_tag,''), code HAVING c > 1"
        ).fetchall()
        self.assertEqual(dupes, [], "同一 scope 下 code 必须唯一")

    def test_personal_owner_constraint_respected(self) -> None:
        """全局选项集不得带 owner（库层 CHECK），种子里也不应有。"""
        options.seed_options(self.conn)
        rows = self.conn.execute("SELECT owner_user_id FROM option_set").fetchall()
        for r in rows:
            self.assertIsNone(r["owner_user_id"])


class TestFullSeedPipeline(DbTestCase):
    """按 CLI 的顺序一次导完三份种子，并验证整体幂等。"""

    def setUp(self) -> None:
        super().setUp()
        self.migrate()

    def _seed_all(self):
        return (
            dictionary.seed_dictionary(self.conn),
            responses.seed_responses(self.conn),
            options.seed_options(self.conn),
        )

    def test_pipeline_succeeds(self) -> None:
        d, r, o = self._seed_all()
        self.assertEqual(d.main_items, 4)
        self.assertGreater(r.total, 20)
        self.assertGreater(o.sets, 30)

    def test_pipeline_is_idempotent_end_to_end(self) -> None:
        self._seed_all()
        snapshot = {
            t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("main_item", "sub_item", "sub_item_param_def", "response_def", "option_set", "option_item")
        }
        d2, r2, o2 = self._seed_all()
        after = {
            t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("main_item", "sub_item", "sub_item_param_def", "response_def", "option_set", "option_item")
        }
        self.assertEqual(snapshot, after, "重复导入全套种子不得新增行")
        self.assertEqual(d2.created["params"], 0)
        self.assertEqual(r2.created, 0)
        self.assertEqual(o2.created_sets, 0)
        self.assertEqual(o2.created_items, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
