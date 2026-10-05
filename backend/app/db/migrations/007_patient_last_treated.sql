-- 007_patient_last_treated.sql
-- 患者列表改用"我最近一次已提交治疗"排序（业务决策变更，2026-10-05）。
--
-- 背景：科室确认**排期不是本系统的职责** ——
--   「本系统只记录每天做了哪些治疗、每次治疗干了什么；
--     排班这件事在纸质/口头流程里就能解决，不该变成治疗师的录入负担。」
-- 于是排期功能整体下线，患者列表的排序依据必须从"下一个排期"换成"实际治疗"。
--
-- 改动前（001 建视图 v_patient_next_appointment + patient.py 的 ORDER BY）：
--     排序 = 归属(我的 → 未分配 → 其他) → 下一个排期日期升序 → 半日 → 住院号
-- 改动后：
--     排序 = 归属(我的 → 未分配 → 其他) → 我最近一次治疗该患者的日期**降序**（越近越前）
--            → 半日（同一天上午在下午之前）→ 住院号
--
-- 几个刻意的口径决定：
--
--   1) 只算 `status = 'submitted'`。
--      草稿不算 —— 否则"写了一半没提交"会把患者顶到最前面，
--      而那条记录在汇总/时间轴里都还不存在，看起来像系统错乱。
--      `locked`（已锁定）也排除：锁定意味着这条记录已被归档封存，
--      不代表"我最近在治他"。
--
--   2) 按 (patient_no, therapist_id) 分组，查询时按 therapist_id 过滤。
--      视图不假设"某个用户"，由调用方 JOIN 时带上自己的 id。
--
--   3) 取 MAX(record_date) 与对应的半日。半日用窗口函数取"最近那天的半日"，
--      而不是 MAX(session_period) —— 否则同一天上午下午都有记录时会错。
--
-- 索引：`ix_record_therapist_date (therapist_id, record_date)` 已存在，
-- 这个 GROUP BY 走它即可，无需新增索引。
--
-- 已应用的迁移不得修改，故新开本文件。

BEGIN;

DROP VIEW IF EXISTS v_patient_next_appointment;

CREATE VIEW v_patient_last_treated AS
SELECT
    r.patient_no                AS patient_no,
    r.therapist_id              AS therapist_id,
    MAX(r.record_date)          AS last_date,
    -- 最近那一天的半日（am 排在 pm 之前，取最小的那个即当天最早的一次；
    -- 排序时"上午"应排在"下午"之前，与原来 next_period_rank 的方向相反，
    -- 因为这里是"最近一次"而非"下一次"）。
    MIN(CASE r.session_period WHEN 'am' THEN 0 WHEN 'pm' THEN 1 ELSE 2 END) AS last_period_rank
FROM treatment_record r
WHERE r.status = 'submitted'
GROUP BY r.patient_no, r.therapist_id;

COMMIT;
