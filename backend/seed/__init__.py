"""字典种子数据（幂等，按 code upsert，不按 id）。

三份种子，导入顺序有依赖（后两者要解析 `main_item.code`）：

| 模块 | 种子文件 | 内容 | 对应设计 |
|---|---|---|---|
| `dictionary` | `dict_seed.json` | 4 主项目 / 29 子项目 / 89 参数 | `设计.md` 3.6.2–3.6.3、8.2 |
| `responses` | `response_seed.json` | 27 条患者反应定义（tag 14 / number 9 / select 4） | `设计.md` 3.6.5 |
| `options` | `option_seed.json` | 全局选项集（按 `param_key` 汇总） | `设计.md` 3.6.4 |

导入方式（一条命令按正确顺序全部导入）：

    python -m app.cli seed

生成方式：`backend/data/_gen_seed.py` 与 `_gen_resp.py` 从 `设计.md` 解析生成
（一次性脚本，用完即删；如需重生成请从 CHANGELOG 的历史记录里找回它们的结构说明）。

遗留待办：`option_set` 目前只支持每个 `code` 一套全局选项。同一 `param_key`
在不同子项目下的选项差异（如「辅助程度」有 6 项与 4 项两套）完整保留在各子项目的
`sub_item_param_def.options_json` 中，但"全局统一层"只保留了主变体。
若要支持多变体，需给 `option_set` 增加 `variant` 列。
"""

from seed.dictionary import SEED_FILE, SeedError, SeedStats, load_seed_data, seed_dictionary
from seed.options import OptionSeedError, OptionSeedStats, seed_options
from seed.responses import ResponseSeedError, ResponseSeedStats, seed_responses

__all__ = [
    "SEED_FILE",
    "OptionSeedError",
    "OptionSeedStats",
    "ResponseSeedError",
    "ResponseSeedStats",
    "SeedError",
    "SeedStats",
    "load_seed_data",
    "seed_dictionary",
    "seed_options",
    "seed_responses",
]
