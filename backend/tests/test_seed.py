"""字典种子文件的**纯文件**校验（不碰数据库）。

> 2026-10-05：记录改 SOAP 模板驱动后，字典六张表（`main_item` / `sub_item` /
> `sub_item_param_def` / `option_set` / `option_item` / `response_def`）随迁移 012 删除，
> `app.cli seed` 也改成"打印一句废弃说明并返回 0"。
>
> 因此本文件**只保留不依赖数据库的部分**（种子 JSON 能加载、结构校验能拦住坏数据）——
> 那些导入用例的被测表已经不存在了，留着只会全线报错。种子导入器与种子 JSON 仍保留在
> `backend/seed/`（迁移 012 的说法：等确认没有任何功能依赖后再清理）。
"""

from __future__ import annotations

import unittest

from seed import dictionary


class TestSeedFileIntegrity(unittest.TestCase):
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


class TestSeedCommandIsDeprecated(unittest.TestCase):
    """`app.cli seed` 必须**不再碰数据库**（它指向的表已被迁移 012 删除）。"""

    def test_seed_command_prints_deprecation_and_returns_zero(self) -> None:
        import io
        from contextlib import redirect_stdout

        from app.cli import main

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["seed"])
        self.assertEqual(code, 0)
        output = buffer.getvalue()
        self.assertIn("废弃", output)
        self.assertIn("JSON 模板", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
