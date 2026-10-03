-- 004_sync_support.sql
-- 离线同步所需的客户端幂等标识（阶段 4 / 开发计划.md M06）。
--
-- 为什么需要 client_uuid：
--   离线场景下治疗师可能在弱网/断网时反复提交同一条记录，网络恢复后重试。
--   只用自增主键做不到"幂等 upsert"——服务端无法判断这条数据是不是已经收过。
--   客户端在本地生成 UUIDv4 并随每次变更一起上报，服务端据此去重。
--
-- 唯一性用 (client_uuid, entity 所在的表) 表达：
--   SQLite 的部分唯一索引里 client_uuid 可以为 NULL（历史数据与服务端直接创建的数据没有它），
--   因此唯一索引要带 WHERE client_uuid IS NOT NULL，否则多行 NULL 不算冲突（SQLite 行为），
--   写上条件更明确，也避免将来换库时行为不一致。
--
-- 已应用的迁移不得修改，故新开本文件。

BEGIN;

ALTER TABLE patient ADD COLUMN client_uuid TEXT;
ALTER TABLE appointment ADD COLUMN client_uuid TEXT;
ALTER TABLE treatment_record ADD COLUMN client_uuid TEXT;

CREATE UNIQUE INDEX ux_patient_client_uuid
    ON patient (client_uuid) WHERE client_uuid IS NOT NULL;
CREATE UNIQUE INDEX ux_appt_client_uuid
    ON appointment (client_uuid) WHERE client_uuid IS NOT NULL;
CREATE UNIQUE INDEX ux_record_client_uuid
    ON treatment_record (client_uuid) WHERE client_uuid IS NOT NULL;

-- 增量拉取按游标（change_log.id）扫描，同时经常按实体反查，补一个复合索引
CREATE INDEX IF NOT EXISTS ix_change_log_created ON change_log (created_at, id);

COMMIT;
