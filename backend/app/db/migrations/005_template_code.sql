-- 005_template_code.sql
-- 给记录模板加稳定的业务键 `code`（阶段 5 补种子时发现的需要）。
--
-- 为什么需要：
--   种子导入必须幂等且"种子为准"。原本按 (scope, main_item_id, name) 查找模板，
--   而唯一索引 ux_template_scope 恰好包含 name —— 于是**一旦有人改了模板名，
--   再导种子就会查不到旧行、又插一行**，产生重复模板（实测踩到）。
--   名称是可改的展示字段，不能当身份键；这正是字典种子用 `code` 而非 name 的原因。
--
-- 语义约定：
--   - `code IS NOT NULL` → **种子/标准模板**，身份稳定，可被种子重复导入更新（含改名）；
--   - `code IS NULL`     → 管理员或治疗师自建模板，属于用户数据，种子不碰。
--
-- 已应用的迁移不得修改，故新开本文件。

BEGIN;

ALTER TABLE record_template ADD COLUMN code TEXT;

-- 部分唯一索引：只约束有 code 的行，自建模板（code IS NULL）不受影响
CREATE UNIQUE INDEX ux_template_code
    ON record_template (code) WHERE code IS NOT NULL;

COMMIT;
