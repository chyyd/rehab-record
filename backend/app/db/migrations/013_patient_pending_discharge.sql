-- 013_patient_pending_discharge.sql
--
-- 给 `patient.status` 增加一个取值：`pending_discharge`（待出院）。
--
-- ## 为什么需要它
--
-- 用户 2026-10-05：
--   * 「填完小结即待出院」—— 治疗师提交出院小结后，患者进入"待出院"；
--   * 「1 周后自动出院」+「真的自动」—— 满 7 天由 `app.cli auto-discharge` 真正出院；
--   * 出院小结模板里已经写明：「提交后患者置 pending_discharge（对普通治疗师不可见），
--     管理员确认或满 7 天后真正出院（用户要求：防止患者临时反悔）」。
--
-- `pending_discharge` **刻意不在** `ACTIVE_STATUSES` 里（见 `app/models/patient.py`）：
-- 患者已经填完小结、等着办手续，不该再出现在治疗师白板上。
--
-- ## 为什么必须新建迁移而不是改 001
--
-- `patient.status` 的 CHECK 定义在迁移 001 里，而**已应用的迁移不得修改**
-- （`storage.migrate()` 会逐字比对校验和，改了就拒绝启动）。
-- SQLite 又不支持 `ALTER TABLE ... DROP CONSTRAINT`，所以只能走标准的
-- 「建新表 → 拷数据 → 换名」重建。
--
-- ## 重建步骤与坑
--
-- 1. `patient` 被两个视图引用（`v_patient_visibility`、`v_patient_last_treated`），
--    重建期间旧表会被 DROP，视图会变成悬空引用 → **必须先删视图**，重建完再建回。
-- 2. `PRAGMA foreign_keys` 在事务内是 no-op，**必须在 BEGIN 之前**关掉
--    （参考迁移 008/009/011 的写法）。
-- 3. 004 给 `patient` 加过 `client_uuid` 列、002 建过 `trg_patient_updated_at`
--    触发器、001/004 建过三个索引 —— 重建表会一并丢掉，这里逐一建回。
-- 4. `patient_assignment_history` / `treatment_record` 的外键指向 `patient`：
--    外键关闭期间换名，换回同名表后引用关系依旧成立。
--
-- ## 7 天倒计时从哪里算
--
-- **不新增列**：真源是出院小结的提交时间 `treatment_record.submitted_at`
-- （业务上"进入待出院"的时刻就是"小结提交"的时刻）。
-- `app/models/patient.py::pending_discharge_since()` 负责取它，
-- 找不到小结时退回 `patient.updated_at`。

PRAGMA foreign_keys = OFF;

BEGIN;

-- --------------------------------------------------------------------------- --
-- 1) 先删视图（否则重建表会留下悬空引用，整个迁移会失败）
-- --------------------------------------------------------------------------- --
DROP VIEW IF EXISTS v_patient_visibility;
DROP VIEW IF EXISTS v_patient_last_treated;

-- --------------------------------------------------------------------------- --
-- 2) 重建 patient（唯一变化：status 的 CHECK 多一个 'pending_discharge'）
-- --------------------------------------------------------------------------- --
DROP TRIGGER IF EXISTS trg_patient_updated_at;

CREATE TABLE patient_new (
    inpatient_no           TEXT PRIMARY KEY,                            -- 住院编号
    name                   TEXT NOT NULL,
    diagnosis              TEXT,
    admin_note             TEXT,                                        -- 注意事项：仅管理员可写
    assigned_therapist_id  INTEGER,                                     -- 归属治疗师（单日假期间永不修改，M09）
    status                 TEXT NOT NULL DEFAULT 'in_hospital'
                               CHECK (status IN ('in_hospital', 'discharged', 'paused',
                                                 'pending_discharge')),  -- M13 统一枚举 + 013 待出院
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    revision               INTEGER NOT NULL DEFAULT 1,                  -- M06 乐观锁
    client_uuid            TEXT,                                        -- 004 幂等标识
    FOREIGN KEY (assigned_therapist_id) REFERENCES user (id)
);

INSERT INTO patient_new
    (inpatient_no, name, diagnosis, admin_note, assigned_therapist_id, status,
     created_at, updated_at, revision, client_uuid)
SELECT
     inpatient_no, name, diagnosis, admin_note, assigned_therapist_id, status,
     created_at, updated_at, revision, client_uuid
FROM patient;

DROP TABLE patient;
ALTER TABLE patient_new RENAME TO patient;

-- --------------------------------------------------------------------------- --
-- 3) 索引与触发器按原定义（001/002/004）原样建回
-- --------------------------------------------------------------------------- --
CREATE INDEX ix_patient_assigned ON patient (assigned_therapist_id);
CREATE INDEX ix_patient_status ON patient (status);
CREATE UNIQUE INDEX ux_patient_client_uuid
    ON patient (client_uuid) WHERE client_uuid IS NOT NULL;

CREATE TRIGGER trg_patient_updated_at AFTER UPDATE ON patient
BEGIN UPDATE patient SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE inpatient_no = NEW.inpatient_no; END;

-- --------------------------------------------------------------------------- --
-- 4) 视图按 010 / 011 的定义建回（逐字一致）
--    010：可见归属直接等于原归属（临时指派删除后的简化形态）
--    011：我最近一次已提交的**日常**治疗（评估文书不计入排序依据）
-- --------------------------------------------------------------------------- --
CREATE VIEW v_patient_visibility AS
SELECT p.inpatient_no,
       p.assigned_therapist_id,
       p.assigned_therapist_id AS visible_therapist_id
FROM patient p;

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
