-- 003_patient_visibility_view.sql
-- 新增视图 v_patient_visibility：全系统唯一的「当前谁负责这个患者」解析实现。
--
-- 为什么单独成一个迁移而不是改 002：
--   已应用的迁移不得修改（校验和会不匹配，storage.migrate 会直接报错）。
--   新增能力一律新开迁移文件。
--
-- 语义（对应 设计.md 3.3 / 3.5.5 与 开发计划.md M09）：
--   原归属  = patient.assigned_therapist_id        （单日假期间永不修改）
--   可见归属 = visible_therapist_id
--       - 无有效临时指派            → 原归属
--       - 临时指派且已被认领        → 认领者
--       - 临时指派但未被认领        → NULL（谁都不负责，他人可临时认领）
--
-- 判定"临时指派是否仍有效"同时看 status 与 expires_at，是**读时兜底**：
-- 即使定时清理任务漏跑（服务重启等），归属显示也不会错（开发计划.md R8）。

BEGIN;

CREATE VIEW v_patient_visibility AS
WITH active_temp AS (
    SELECT ta.*
    FROM temporary_assignment ta
    WHERE ta.status = 'open'
      AND (ta.expires_at IS NULL OR ta.expires_at > strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
),
picked_temp AS (
    SELECT * FROM active_temp t
    WHERE t.id = (SELECT MAX(x.id) FROM active_temp x WHERE x.patient_no = t.patient_no)
)
SELECT p.inpatient_no,
       p.assigned_therapist_id,
       pt.id                     AS temp_assignment_id,
       pt.temporary_therapist_id AS temp_therapist_id,
       pt.original_therapist_id  AS temp_original_therapist_id,
       pt.date                   AS temp_date,
       pt.period                 AS temp_period,
       pt.expires_at             AS temp_expires_at,
       CASE
           WHEN pt.id IS NULL THEN p.assigned_therapist_id
           WHEN pt.temporary_therapist_id IS NOT NULL THEN pt.temporary_therapist_id
           ELSE NULL
       END AS visible_therapist_id,
       CASE
           WHEN pt.id IS NULL THEN 'assigned'
           WHEN pt.temporary_therapist_id IS NOT NULL THEN 'temp_claimed'
           ELSE 'temp_released'
       END AS visibility_state
FROM patient p
LEFT JOIN picked_temp pt ON pt.patient_no = p.inpatient_no;

COMMIT;
