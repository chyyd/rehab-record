-- 014_drop_span_seq.sql
--
-- 复评改成「距首评或上一次复评 **30 个自然日**」（用户 2026-10-06），
-- `span_seq`（把评估文书挂到"第几次日常"上）随之彻底失去意义，本迁移删掉它。
--
-- 用户原话：「复评的间隔逻辑需要改一下，设定为距离首评或上一次复评 30 个自然日。
--            如果当日没有治疗，顺延到下一次治疗时评估，也就是 1 个月评一次。」
--
-- 为什么"按日期"就不需要这一列了：
--   原来"某个区间的复评做没做"要靠 `span_seq`（21/41/61…）去查；
--   现在它是 `(上次评估的 record_date + 30 天) <= 本次记录日期` 的纯计算，
--   **不需要任何额外的落库状态**。留着这一列只会让后来的人以为复评还按次数算。
--
-- SQLite 不能 DROP COLUMN（有唯一索引/触发器引用），只能重建表。
-- 手法与 011/013 一致：先删依赖（视图/触发器/索引），重建后再建回来。

PRAGMA foreign_keys = OFF;

BEGIN;

-- --------------------------------------------------------------------------- --
-- 1. 先删依赖（视图引用 treatment_record，重建时会悬空报错）
-- --------------------------------------------------------------------------- --
DROP VIEW IF EXISTS v_patient_last_treated;

DROP TRIGGER IF EXISTS trg_treatment_record_updated_at;
DROP TRIGGER IF EXISTS trg_record_edit_trace;
DROP TRIGGER IF EXISTS trg_record_edit_count;

DROP INDEX IF EXISTS ix_record_patient_date;
DROP INDEX IF EXISTS ix_record_therapist_date;
DROP INDEX IF EXISTS ix_record_status;
DROP INDEX IF EXISTS ix_record_discipline;
DROP INDEX IF EXISTS ux_record_client_uuid;
DROP INDEX IF EXISTS ux_record_daily_seq;
DROP INDEX IF EXISTS ux_record_assessment_span;

-- --------------------------------------------------------------------------- --
-- 2. 重建 treatment_record（19 列 → 18 列：去掉 span_seq）
--
-- ★ 必须**搬数据**。SQLite 删列只能重建表，而重建的默认写法是
--   `DROP TABLE` + `CREATE TABLE` —— 那样存量记录会被静默清空。
--   011 是**有意**清空的（旧模型「主项目+子项目+参数」无法映射到 SOAP `body`），
--   但 014 只是去掉一列，**没有任何理由丢数据**。
--   所以先把旧表改名留着，建好新表再用 `INSERT ... SELECT` 搬过去。
--
-- ⚠ **本迁移在首次落盘后被修正过一次**（加上了上面这段搬数据）。
--   对已经跑过旧版 014 的库，这一步是 no-op（表结构相同），
--   但**账本里的 checksum 会对不上**，`migrate()` 会拒绝运行并提示
--   「已应用的迁移不得修改」。
--   因 014 尚未提交、也无其它库受影响，采取的处理是**对账账本**（把开发库
--   第 14 行的 checksum 更新为当前文件），而不是再叠加一个 015 ——
--   后者会把"同一件事"记两遍，读起来更乱。
--   若将来复制了别的库、又需要重跑，删掉那个库的 `-wal`/`-shm` 后重建即可。
-- --------------------------------------------------------------------------- --
ALTER TABLE treatment_record RENAME TO treatment_record_old;

CREATE TABLE treatment_record (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_no     TEXT    NOT NULL REFERENCES patient (inpatient_no),
    therapist_id   INTEGER NOT NULL REFERENCES user (id),
    record_date    TEXT    NOT NULL,              -- 本地墙钟 YYYY-MM-DD
    discipline     TEXT    NOT NULL,              -- PT / OT / ST_SW / ST_SP
    kind           TEXT    NOT NULL,              -- initial / daily / reassessment / discharge
    seq_no         INTEGER,                       -- 第几次**日常**；只有 daily 有
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

    CHECK (discipline IN ('PT', 'OT', 'ST_SW', 'ST_SP')),
    CHECK (kind IN ('initial', 'daily', 'reassessment', 'discharge')),
    CHECK (status IN ('draft', 'submitted', 'locked')),
    CHECK (json_valid(body_json)),
    -- 日常必须有次数；评估文书不计次（用户：评定不占用日常训练次数）
    CHECK ((kind = 'daily') = (seq_no IS NOT NULL))
);

-- 搬数据：除 span_seq 外的**全部**列按名对应搬过来。
-- 显式列出列名（不用 `SELECT *`）—— 列顺序一旦不同就会静默错位。
INSERT INTO treatment_record (
    id, patient_no, therapist_id, record_date, discipline, kind, seq_no,
    body_json, rendered_text, note, status, edit_count, locked_at,
    created_at, submitted_at, updated_at, revision, client_uuid
)
SELECT
    id, patient_no, therapist_id, record_date, discipline, kind, seq_no,
    body_json, rendered_text, note, status, edit_count, locked_at,
    created_at, submitted_at, updated_at, revision, client_uuid
FROM treatment_record_old;

DROP TABLE treatment_record_old;

CREATE INDEX ix_record_patient_date ON treatment_record (patient_no, record_date);
CREATE INDEX ix_record_therapist_date ON treatment_record (therapist_id, record_date);
CREATE INDEX ix_record_status ON treatment_record (status);
CREATE INDEX ix_record_discipline ON treatment_record (patient_no, discipline, record_date);
CREATE UNIQUE INDEX ux_record_client_uuid
    ON treatment_record (client_uuid) WHERE client_uuid IS NOT NULL;

-- 日常记录的 (患者, 大类, 次数) 唯一 —— 不会出现两条「第 5 次」
CREATE UNIQUE INDEX ux_record_daily_seq
    ON treatment_record (patient_no, discipline, seq_no) WHERE seq_no IS NOT NULL;

-- ★ 每个大类只能有**一份首评**。
--
--   这一条顶替了被删掉的 `ux_record_assessment_span` 里"不能补填第二份首评"那半职责。
--   另半职责（同一区间不能有两份复评）现在由**日期门禁**保证：只要上次评估满 30 天，
--   接口就把 `kind` 折成 `reassessment` 并要求先提交它，所以在应做日之前根本建不出第二份。
--   复评之间**本来就可能有多份**（30 天、60 天、90 天…各一份），所以不能对
--   `kind='reassessment'` 做同样的唯一约束。
CREATE UNIQUE INDEX ux_record_one_initial
    ON treatment_record (patient_no, discipline)
    WHERE kind = 'initial';

-- --------------------------------------------------------------------------- --
-- 3. 触发器（与 011 相同语义）
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
-- 4. 重建排序视图
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

PRAGMA foreign_keys = ON;
