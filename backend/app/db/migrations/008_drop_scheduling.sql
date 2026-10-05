-- 008_drop_scheduling.sql
-- 排期功能整体下线（业务决策变更，2026-10-05）。
--
-- 背景：科室确认 **排班不是本系统的职责** ——
--   「本系统只记录每天做了哪些治疗、每次治疗干了什么；排班在纸质/口头流程里
--     就能解决，不该变成治疗师的录入负担。」
--
-- 于是本次删除三类相互层叠的东西：
--   1. 排期本身：appointment 表 + 3 条索引 + 1 条触发器 + 1 个视图；
--   2. 休息块 rest_block：它存在的唯一目的是"判断某个半日能不能排期"，
--      没有排期就没有"格子"，这张表失去意义；
--   3. 请假 leave_record：同理，它原本要产生"临时释放"这个排期副作用。
--      注意**临时指派 temporary_assignment 保留** —— 它是**归属解析**，
--      v_patient_visibility 依赖它，与排班无关（详见 app/models/temporary_assignment.py）。
--
-- 同时清掉三个语义已空的字段（`treatment_record`）：
--   * appointment_id        —— 排期没了，且此前从未有人写入（恒 NULL）；
--   * is_temporary          —— 恒为 0：它只在"从排期进入"那条路径上被赋值；
--   * original_therapist_id —— 配合 is_temporary 使用，同样恒 NULL。
--   `is_temporary` 改为**查询时从归属推导**（见 app/models/treatment.py），
--   这样少一个可能与事实不一致的存储列。
--
-- 排序迁移：患者列表原本按 `v_patient_next_appointment`（下一个排期）排序，
-- 已在 007 换成 `v_patient_last_treated`（我最近一次已提交治疗）。本文件删掉旧视图。
--
-- 已应用的迁移不得修改，故新开本文件。

-- ---------------------------------------------------------------------------
-- 0) 外键检查必须在事务之外关闭
--    SQLite 的 `PRAGMA foreign_keys` 在事务内是 no-op，所以放在 BEGIN 之前。
--    executescript 会隐式提交先前事务，因此这里的位置是安全的。
-- ---------------------------------------------------------------------------
PRAGMA foreign_keys = OFF;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1) 删除排期相关的视图
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS v_patient_next_appointment;

-- `v_patient_last_treated` 引用 treatment_record，而下面要"重建"那张表
--（重建期间旧表会被 DROP，视图会变成悬空引用并让整个迁移失败）。
-- 所以这里先删掉，重建完成后再按 007 的定义原样建回来。
DROP VIEW IF EXISTS v_patient_last_treated;

-- ---------------------------------------------------------------------------
-- 2) 删除排期、休息块、请假（及各自的索引与触发器）
--    索引随表一起消失，无需单独 DROP。
-- ---------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_appointment_updated_at;
DROP TABLE IF EXISTS appointment;

DROP TABLE IF EXISTS rest_block;

DROP TRIGGER IF EXISTS trg_leave_updated_at;
DROP TABLE IF EXISTS leave_record;

-- ---------------------------------------------------------------------------
-- 3) 重建 treatment_record，去掉三个已无语义的字段
--
--    SQLite 3.x 不支持 DROP COLUMN 的组合删除（且列上还挂着外键），
--    所以走标准的"建新表 → 拷数据 → 换名"。
--    两个业务触发器会引用旧表，必须先删再在换名后重建。
-- ---------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_treatment_record_updated_at;
DROP TRIGGER IF EXISTS trg_record_edit_trace;
DROP TRIGGER IF EXISTS trg_record_edit_count;

CREATE TABLE treatment_record_new (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_no            TEXT    NOT NULL,
    therapist_id          INTEGER NOT NULL,
    record_date           TEXT    NOT NULL,
    session_period        TEXT    CHECK (session_period IN ('am', 'pm')),
    seq_no                INTEGER,
    duration_min          INTEGER CHECK (duration_min IS NULL OR duration_min >= 0),
    patient_response_json TEXT CHECK (patient_response_json IS NULL OR json_valid(patient_response_json)),
    note                  TEXT,
    status                TEXT NOT NULL DEFAULT 'draft'
                             CHECK (status IN ('draft', 'submitted', 'locked')),
    edit_count            INTEGER NOT NULL DEFAULT 0,
    locked_at             TEXT,
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    submitted_at          TEXT,
    updated_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    revision              INTEGER NOT NULL DEFAULT 1,
    client_uuid           TEXT,
    FOREIGN KEY (patient_no) REFERENCES patient (inpatient_no),
    FOREIGN KEY (therapist_id) REFERENCES user (id)
);

INSERT INTO treatment_record_new
    (id, patient_no, therapist_id, record_date, session_period, seq_no, duration_min,
     patient_response_json, note, status, edit_count, locked_at, created_at,
     submitted_at, updated_at, revision, client_uuid)
SELECT
     id, patient_no, therapist_id, record_date, session_period, seq_no, duration_min,
     patient_response_json, note, status, edit_count, locked_at, created_at,
     submitted_at, updated_at, revision, client_uuid
FROM treatment_record;

DROP TABLE treatment_record;
ALTER TABLE treatment_record_new RENAME TO treatment_record;

-- 索引与触发器按原定义重建（内容与 001/002/004 保持一致）
CREATE INDEX ix_record_patient_date ON treatment_record (patient_no, record_date);
CREATE INDEX ix_record_therapist_date ON treatment_record (therapist_id, record_date);
CREATE INDEX ix_record_status ON treatment_record (status);
CREATE UNIQUE INDEX ux_record_client_uuid
    ON treatment_record (client_uuid) WHERE client_uuid IS NOT NULL;

CREATE TRIGGER trg_treatment_record_updated_at AFTER UPDATE ON treatment_record
BEGIN UPDATE treatment_record SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER trg_record_edit_trace BEFORE UPDATE ON treatment_record
WHEN COALESCE(OLD.status, '') <> 'draft'
  AND (COALESCE(OLD.note, '') <> COALESCE(NEW.note, '')
    OR COALESCE(OLD.duration_min, -1) <> COALESCE(NEW.duration_min, -1)
    OR COALESCE(OLD.patient_response_json, '') <> COALESCE(NEW.patient_response_json, '')
    OR COALESCE(OLD.record_date, '') <> COALESCE(NEW.record_date, '')
    OR COALESCE(OLD.session_period, '') <> COALESCE(NEW.session_period, '')
    OR COALESCE(OLD.status, '') <> COALESCE(NEW.status, ''))
BEGIN
    INSERT INTO audit_log (user_id, action, target_type, target_id, before_json, after_json, created_at)
    VALUES (NEW.therapist_id, 'record_modified_after_submit', 'treatment_record', CAST(NEW.id AS TEXT),
            json_object('status', OLD.status, 'note', OLD.note, 'duration_min', OLD.duration_min,
                        'patient_response_json', OLD.patient_response_json, 'edit_count', OLD.edit_count),
            json_object('status', NEW.status, 'note', NEW.note, 'duration_min', NEW.duration_min,
                        'patient_response_json', NEW.patient_response_json, 'edit_count', NEW.edit_count + 1),
            strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
END;

CREATE TRIGGER trg_record_edit_count AFTER UPDATE ON treatment_record
WHEN COALESCE(OLD.status, '') <> 'draft'
  AND (COALESCE(OLD.note, '') <> COALESCE(NEW.note, '')
    OR COALESCE(OLD.duration_min, -1) <> COALESCE(NEW.duration_min, -1)
    OR COALESCE(OLD.patient_response_json, '') <> COALESCE(NEW.patient_response_json, '')
    OR COALESCE(OLD.record_date, '') <> COALESCE(NEW.record_date, '')
    OR COALESCE(OLD.session_period, '') <> COALESCE(NEW.session_period, ''))
BEGIN
    UPDATE treatment_record SET edit_count = OLD.edit_count + 1 WHERE id = NEW.id;
END;

-- ---------------------------------------------------------------------------
-- 4) 把 007 建的"我最近一次已提交治疗"视图建回来（定义与 007 完全一致）
-- ---------------------------------------------------------------------------
CREATE VIEW v_patient_last_treated AS
SELECT
    r.patient_no                AS patient_no,
    r.therapist_id              AS therapist_id,
    MAX(r.record_date)          AS last_date,
    MIN(CASE r.session_period WHEN 'am' THEN 0 WHEN 'pm' THEN 1 ELSE 2 END) AS last_period_rank
FROM treatment_record r
WHERE r.status = 'submitted'
GROUP BY r.patient_no, r.therapist_id;

-- ---------------------------------------------------------------------------
-- 5) 清掉 change_log 里排期的历史游标
--    这些行的 entity='appointment' 已经没有对应表了，留着会让客户端
--    在增量拉取时收到"找不到实体"的变更。游标本身是单调 id，删行不影响连续性。
-- ---------------------------------------------------------------------------
DELETE FROM change_log WHERE entity = 'appointment';

COMMIT;

PRAGMA foreign_keys = ON;
