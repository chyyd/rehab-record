"""字典种子导入（`开发计划.md` 阶段 3 / T3.2 / 风险 R1）。

覆盖点：
- 种子文件能加载且通过结构校验；
- **幂等**：连续导入两次，第二次全部走更新，行数不增长；
- 导入结果与库层约束自洽（参数键唯一，靠 `UNIQUE(sub_item_id, param_key)` 兜底）；
- 选择题默认值以 JSON 列表存储，且每个默认值都来自选项集；
- 同一子项目内参数键唯一（`设计.md` 4.1.3）。
"""

from __future__ import annotations

import json
import unittest

from seed import dictionary
from tests.support import DbTestCase


class TestSeedFileIntegrity(DbTestCase):
    def test_seed_file_loads_and_validates(self) -> None:
        data = dictionary.load_seed_data()
        # 四套高频模板：运动 / 生活 / 言语 / 吞咽
        self.assertEqual(len(data["main_items"]), 4)
        codes = {m["code"] for m in data["main_items"]}
        self.assertEqual(codes, {"motor_function", "adl_skill", "speech_function", "swallow_function"})
        dictionary._validate(data)  # 不应抛错

    def test_seed_has_expected_scale(self) -> None:
        data = dictionary.load_seed_data()
        sub_items = [s for m in data["main_items"] for s in m["sub_items"]]
        params = [p for s in sub_items for p in s["params"]]
        # 规模下限保护：避免后续误删数据而无人发现
        self.assertGreaterEqual(len(sub_items), 25, "子项目数量异常偏少")
        self.assertGreaterEqual(len(params), 70, "参数数量异常偏少")
        self.assertEqual(len({s["code"] for s in sub_items}), len(sub_items), "子项目 code 必须唯一")

    def test_invalid_seed_is_rejected(self) -> None:
        """重复 param_key 必须在导入前被拦住（库层 UNIQUE 是最后防线）。"""
        bad = {
            "main_items": [
                {
                    "code": "x",
                    "name": "测试",
                    "sub_items": [
                        {
                            "code": "x_01",
                            "name": "子项目",
                            "params": [
                                {"param_key": "k", "param_name": "A", "input_type": "number"},
                                {"param_key": "k", "param_name": "B", "input_type": "number"},
                            ],
                        }
                    ],
                }
            ]
        }
        with self.assertRaises(dictionary.SeedError):
            dictionary._validate(bad)

    def test_default_must_be_in_options(self) -> None:
        bad = {
            "main_items": [
                {
                    "code": "x",
                    "name": "测试",
                    "sub_items": [
                        {
                            "code": "x_01",
                            "name": "子项目",
                            "params": [
                                {
                                    "param_key": "k",
                                    "param_name": "A",
                                    "input_type": "select",
                                    "options": ["甲", "乙"],
                                    "default_value": ["丙"],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        with self.assertRaises(dictionary.SeedError):
            dictionary._validate(bad)


class TestSeedImport(DbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.migrate()

    def test_import_creates_all_rows(self) -> None:
        stats = dictionary.seed_dictionary(self.conn)
        data = dictionary.load_seed_data()
        n_main = len(data["main_items"])
        n_sub = sum(len(m["sub_items"]) for m in data["main_items"])
        n_param = sum(len(s["params"]) for m in data["main_items"] for s in m["sub_items"])

        self.assertEqual(stats.main_items, n_main)
        self.assertEqual(stats.sub_items, n_sub)
        self.assertEqual(stats.params, n_param)
        self.assertEqual(stats.created["main_items"], n_main)
        self.assertEqual(stats.created["sub_items"], n_sub)
        self.assertEqual(stats.created["params"], n_param)

        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM main_item").fetchone()[0], n_main)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sub_item").fetchone()[0], n_sub)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sub_item_param_def").fetchone()[0], n_param)

    def test_import_is_idempotent(self) -> None:
        """核心要求：重复导入不产生重复行，第二次应全部走"更新"。"""
        first = dictionary.seed_dictionary(self.conn)
        counts_after_first = {
            t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("main_item", "sub_item", "sub_item_param_def")
        }

        second = dictionary.seed_dictionary(self.conn)
        counts_after_second = {
            t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("main_item", "sub_item", "sub_item_param_def")
        }

        self.assertEqual(counts_after_first, counts_after_second, "重复导入不得新增行")
        self.assertEqual(second.created["main_items"], 0)
        self.assertEqual(second.created["sub_items"], 0)
        self.assertEqual(second.created["params"], 0)
        self.assertEqual(second.updated["params"], first.params)

    def test_choice_defaults_stored_as_json_list(self) -> None:
        """选择题默认值是列表（多选可能多个默认值），存库时编码为 JSON。"""
        dictionary.seed_dictionary(self.conn)
        row = self.conn.execute(
            "SELECT options_json, default_value, input_type FROM sub_item_param_def"
            " WHERE param_key = 'items' AND param_name = '项目' LIMIT 1"
        ).fetchone()
        self.assertIsNotNone(row, "未找到「修饰训练.项目」参数")
        self.assertEqual(row["input_type"], "multi_select")
        defaults = json.loads(row["default_value"])
        self.assertEqual(defaults, ["洗脸", "刷牙"], "多选默认值应完整保留")
        options = json.loads(row["options_json"])
        for d in defaults:
            self.assertIn(d, options)

    def test_numeric_parameter_has_unit_and_no_options(self) -> None:
        dictionary.seed_dictionary(self.conn)
        row = self.conn.execute(
            "SELECT input_type, options_json, unit, default_value FROM sub_item_param_def"
            " WHERE param_key = 'reps' LIMIT 1"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["input_type"], "number")
        self.assertIsNone(row["options_json"])
        self.assertEqual(row["unit"], "次")
        self.assertEqual(row["default_value"], "10")

    def test_placeholder_default_is_null(self) -> None:
        """设计文档里的 ——（破折号占位）必须落成 NULL，而不是字符串 '—'。"""
        dictionary.seed_dictionary(self.conn)
        rows = self.conn.execute(
            "SELECT default_value FROM sub_item_param_def WHERE default_value IS NOT NULL"
        ).fetchall()
        for r in rows:
            self.assertNotIn(r["default_value"], {"—", "-", ""}, "占位符未被归一为 NULL")

    def test_param_key_unique_within_sub_item(self) -> None:
        dictionary.seed_dictionary(self.conn)
        dupes = self.conn.execute(
            "SELECT sub_item_id, param_key, COUNT(*) c FROM sub_item_param_def"
            " GROUP BY sub_item_id, param_key HAVING c > 1"
        ).fetchall()
        self.assertEqual(dupes, [], "同一子项目内 param_key 必须唯一")

    def test_json_options_are_queryable(self) -> None:
        """4.2 节要求参数选项可按 JSON1 查询（记录页要按选项渲染表单）。"""
        dictionary.seed_dictionary(self.conn)
        value = self.conn.execute(
            "SELECT json_extract(options_json, '$[0]') FROM sub_item_param_def"
            " WHERE param_key = 'side' LIMIT 1"
        ).fetchone()[0]
        self.assertEqual(value, "左")

    def test_import_failure_rolls_back(self) -> None:
        """导入中途失败必须整体回滚，不能留下半套字典。"""
        bad_seed = self.tmp_path / "bad_seed.json"
        bad_seed.write_text(
            json.dumps(
                {
                    "main_items": [
                        {
                            "code": "m1",
                            "name": "主项目一",
                            "sub_items": [{"code": "m1_01", "name": "子", "params": []}],
                        },
                        {"code": "m1", "name": "重复主项目", "sub_items": []},  # code 重复 → 校验失败
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        with self.assertRaises(dictionary.SeedError):
            dictionary.seed_dictionary(self.conn, bad_seed)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM main_item").fetchone()[0], 0)

    def test_missing_seed_file_raises(self) -> None:
        with self.assertRaises(dictionary.SeedError):
            dictionary.load_seed_data(self.tmp_path / "nope.json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
