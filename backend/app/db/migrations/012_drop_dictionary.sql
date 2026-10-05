-- 012_drop_dictionary.sql
--
-- 删掉字典/选项集/患者反应定义六张表 —— 记录改由 JSON 模板驱动后，它们没有被删干净。
--
-- ## 为什么可以删
--
-- 迁移 011 把治疗记录改成 SOAP 模板驱动（模板是 `templates/*.json` 文件），
-- `record_item` 与 `record_template` 已随之删除。剩下这六张表原本只服务旧模型：
--
--   main_item / sub_item / sub_item_param_def   「4 主项目 / 29 子项目 / 89 参数」的参数表
--   option_set / option_item                    选项集（给参数提供候选值）
--   response_def                                患者反应定义（27 条）
--
-- 新模型里「本次训练项目」的候选值来自 `templates/disciplines.json` 的 `therapy_options`，
-- 其余字段直接写在模板 JSON 里 —— 都不查库。
--
-- ## 数据会丢，但可重建
--
-- 这六张表共 403 行，**全部来自 `app.cli seed`**（种子 JSON：`seed/dict_seed.json`、
-- `seed/option_seed.json`、`seed/responses.py`），不是用户录入的业务数据。
-- 用户 2026-10-05 已确认「清掉重来」。
--
-- ## 为什么 foreign_keys 要在 BEGIN 之前关掉
--
-- `PRAGMA foreign_keys` 在事务内是 no-op（SQLite 明确如此），必须在 BEGIN 前设置。
-- 这几张表之间有外键（sub_item → main_item 等），DROP 顺序会触发约束检查。
--
-- ## 顺带：seed 导入器要不要删？
--
-- 本迁移只删表。`backend/seed/` 下的导入器与 `app.cli seed` 子命令**保留但不调用**
-- （见 CHANGELOG 的说明）：它们无害，而删掉代码容易误伤 `seed/` 里仍被别处引用的
-- 常量。等确认没有任何功能依赖后再清理。

PRAGMA foreign_keys = OFF;

BEGIN;

-- 记录改由 JSON 模板驱动后，变更日志里不该再留下这些实体的游标
DELETE FROM change_log WHERE entity IN
    ('main_item', 'sub_item', 'sub_item_param_def', 'option_set', 'option_item', 'response_def');

-- 子表先删，父表后删（外键方向：sub_item → main_item 等）
DROP TRIGGER IF EXISTS trg_param_def_updated_at;
DROP TRIGGER IF EXISTS trg_sub_item_updated_at;
DROP TRIGGER IF EXISTS trg_main_item_updated_at;
DROP TRIGGER IF EXISTS trg_option_set_updated_at;
DROP TRIGGER IF EXISTS trg_response_def_updated_at;

DROP INDEX IF EXISTS ix_param_def_sub;
DROP INDEX IF EXISTS ix_sub_item_main;
DROP INDEX IF EXISTS ix_option_item_set;
DROP INDEX IF EXISTS ux_option_set_scope;
DROP INDEX IF EXISTS ux_response_def_code;

DROP TABLE IF EXISTS sub_item_param_def;
DROP TABLE IF EXISTS sub_item;
DROP TABLE IF EXISTS response_def;
DROP TABLE IF EXISTS main_item;
DROP TABLE IF EXISTS option_item;
DROP TABLE IF EXISTS option_set;

COMMIT;

PRAGMA foreign_keys = ON;
