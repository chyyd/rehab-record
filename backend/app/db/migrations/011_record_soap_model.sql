-- 011_record_soap_model.sql
--
-- 治疗记录数据模型改造：参数表格 → SOAP 模板。
--
-- ## 为什么改
--
-- 用户 2026-10-05：「患者详情中的治疗记录部分…现在太过于繁琐，需要点好多次，
-- 不容易使用，改成类似模板这样…使用 json 格式保存模板，不进数据库。」
--
-- 旧模型是围绕「字典」设计的：一条记录拆成 `record_item` 多行，每行引用
-- `main_item` / `sub_item`，参数走 `params_json` + `params_snapshot_json` 两层快照，
-- 还要 `option_set` 解析、`response_def` 患者反应定义、`record_template` 科室模板。
-- 录入要在 4 主项目 / 29 子项目 / 89 参数里一层层展开，所以「点好多次」。
--
-- 新模型：**模板是 JSON 文件**（`templates/<大类>/<形态>.json`），记录只存两样东西：
--   - `body_json`     结构化答案（`{field_key: value}`）—— 用于回显、预填、复查
--   - `rendered_text` 生成那一刻的**纯文本** —— 用于打印与归档
--
-- ## 为什么 rendered_text 要冻结存储
--
-- 用户以后会手改模板。如果每次打印都从 JSON 重算，**旧病历的措辞会跟着变** ——
-- 病历是法律文书，不行。所以生成时渲染一次、存下来。
--
-- ## 四大类分开记录
--
-- 用户：运动/吞咽/言语/生活技能「考虑到可能是不同的治疗师操作，所以分开记录」。
-- 于是记录带 `discipline`，唯一性也从「半日」改为「同一患者 + 同一天 + 同一大类 +
-- 不分「草稿/已提交」」。
--
-- ## 次数怎么算（用户 2026-10-05 纠正）
--
-- 「评定并不占用日常训练的次数，比如第一次首评后，当天还是要有一个日常记录用来
-- 记录当天的训练。复评和出院小结也是。」
-- → **只有 `kind='daily'` 计入 `seq_no`**；首评/复评/出院小结是独立文书，
--   用 `span_seq` 记录「它挂在哪一次日常上」（首评挂 1，复评挂 21/41/61…）。

BEGIN;

-- --------------------------------------------------------------------------- --
-- 1. 清掉旧记录（用户 2026-10-05 确认「清掉重来」，全是测试数据）
-- --------------------------------------------------------------------------- --
DELETE FROM record_item;
DELETE FROM treatment_record;
DELETE FROM change_log WHERE entity = 'treatment_record';

-- --------------------------------------------------------------------------- --
-- 2. 删掉只服务旧模型的辅助表
-- --------------------------------------------------------------------------- --
-- 记录模板改由 JSON 文件承载（用户要求「不进数据库，以便以后我手动修改」）。
DROP TABLE IF EXISTS record_template_item;
DROP TABLE IF EXISTS record_template;

-- --------------------------------------------------------------------------- --
-- 3. record_item：不再需要
-- --------------------------------------------------------------------------- --
DROP INDEX IF EXISTS ix_record_item_record;
DROP TABLE IF EXISTS record_item;

-- --------------------------------------------------------------------------- --
-- 4. treatment_record 重建
-- --------------------------------------------------------------------------- --
-- 视图先删（若有视图引用 treatment_record，重建表时会悬空报错）
DROP VIEW IF EXISTS v_patient_last_treated;

-- 触发器与表：直接重建（SQLite 不支持给表加 NOT NULL 列/改 CHECK，只能重建）
DROP TRIGGER IF EXISTS trg_treatment_record_updated_at;
DROP TRIGGER IF EXISTS trg_record_edit_trace;
DROP TRIGGER IF EXISTS trg_record_edit_count;
DROP TABLE IF EXISTS treatment_record;

DROP INDEX IF EXISTS ix_record_patient_date;
DROP INDEX IF EXISTS ix_record_therapist_date;
DROP INDEX IF EXISTS ix_record_status;
DROP INDEX IF EXISTS ux_record_client_uuid;

CREATE TABLE treatment_record (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_no     TEXT    NOT NULL REFERENCES patient (inpatient_no),
    therapist_id   INTEGER NOT NULL REFERENCES user (id),
    record_date    TEXT    NOT NULL,              -- 本地墙钟 YYYY-MM-DD
    discipline     TEXT    NOT NULL,              -- PT / OT / ST_SW / ST_SP
    kind           TEXT    NOT NULL,              -- initial / daily / reassessment / discharge
    seq_no         INTEGER,                       -- 第几次**日常**；只有 daily 有
    span_seq       INTEGER,                       -- 评估挂在哪一次日常上；只有评估文书有
    body_json      TEXT    NOT NULL DEFAULT '{}', -- {field_key: value}
    rendered_text  TEXT    NOT NULL DEFAULT '',   -- 生成时的纯文本，冻结保存
    note           TEXT,
    status         TEXT    NOT NULL DEFAULT 'draft',
    edit_count     INTEGER NOT NULL DEFAULT 0,
    locked_at      TEXT,
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    submitted_at   TEXT,
    updated_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    revision       INTEGER NOT NULL DEFAULT 1,
    client_uuid    TEXT,

    -- 枚举与旧表保持同一风格：库层 CHECK 兜底，业务层仍需校验（双重保护）
    CHECK (discipline IN ('PT', 'OT', 'ST_SW', 'ST_SP')),
    CHECK (kind IN ('initial', 'daily', 'reassessment', 'discharge')),
    CHECK (status IN ('draft', 'submitted', 'locked')),
    CHECK (json_valid(body_json)),
    -- 日常必须有次数；评估文书不计次（用户：评定不占用日常训练次数）
    CHECK ((kind = 'daily') = (seq_no IS NOT NULL))
);

CREATE INDEX ix_record_patient_date ON treatment_record (patient_no, record_date);
CREATE INDEX ix_record_therapist_date ON treatment_record (therapist_id, record_date);
CREATE INDEX ix_record_status ON treatment_record (status);
CREATE INDEX ix_record_discipline ON treatment_record (patient_no, discipline, record_date);
CREATE UNIQUE INDEX ux_record_client_uuid
    ON treatment_record (client_uuid) WHERE client_uuid IS NOT NULL;

-- ★ 同一患者 + 同一天 + 同一大类 **至多 2 条**
--   （用户 2026-10-05：「去掉半日约束，同一天同一大类只允许至多2条」）
--   SQLite 没有「至多 N 行」的约束语法，而且评估文书与日常记录当天并存、
--   条数是动态的。所以这里只保证**结构上的一致性**：
--     · 日常记录的 (患者, 大类, 次数) 唯一 —— 不会出现两条「第 5 次」
--     · 每个评估区间标识下同一形态唯一 —— 不会有两份首评／两份复评
--   而「一天至多 2 条」由**业务层**校验（见 api/v1/records.py）。
CREATE UNIQUE INDEX ux_record_daily_seq
    ON treatment_record (patient_no, discipline, seq_no) WHERE seq_no IS NOT NULL;

-- ★ 每个评估区间标识下，同一形态只能有一份（首评挂 1、复评挂 21/41/61…）
--   这同时封掉了「同一个序号下两份复评」和「补填第二份首评」。
CREATE UNIQUE INDEX ux_record_assessment_span
    ON treatment_record (patient_no, discipline, kind, span_seq)
    WHERE span_seq IS NOT NULL;

-- --------------------------------------------------------------------------- --
-- 5. 触发器：updated_at 与修订留痕（沿用 008 重建的语义）
-- --------------------------------------------------------------------------- --
CREATE TRIGGER trg_treatment_record_updated_at
AFTER UPDATE ON treatment_record
FOR EACH ROW
WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE treatment_record
       SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
     WHERE id = NEW.id;
END;

CREATE TRIGGER trg_record_edit_trace
AFTER UPDATE ON treatment_record
FOR EACH ROW
WHEN NEW.status = 'submitted' AND OLD.status = 'submitted'
     AND (NEW.body_json <> OLD.body_json OR NEW.rendered_text <> OLD.rendered_text)
BEGIN
    UPDATE treatment_record
       SET edit_count = OLD.edit_count + 1,
           revision   = OLD.revision + 1
     WHERE id = NEW.id;
END;

-- --------------------------------------------------------------------------- --
-- 6. 重建排序视图（008 建过，本迁移重建表时删掉了）
-- --------------------------------------------------------------------------- --
CREATE VIEW v_patient_last_treated AS
SELECT r.patient_no                AS patient_no,
       r.therapist_id              AS therapist_id,
       MAX(r.record_date)          AS last_date
FROM treatment_record r
WHERE r.status = 'submitted'
  AND r.kind = 'daily'
GROUP BY r.patient_no, r.therapist_id;

COMMIT;
