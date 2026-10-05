-- 010_drop_visibility_state.sql
--
-- 删掉 `v_patient_visibility.visibility_state` —— 它已退化成恒为 'assigned' 的死列。
--
-- ## 为什么现在可以删
--
-- 迁移 009 删掉临时指派后，这个视图只剩两种状态（`assigned` / `temp_*`）里的第一种，
-- 于是该列**恒为 'assigned'**。当时选择保留，理由是"怕旧客户端拿不到预期字段"。
-- 2026-10-05 复查后确认这个理由不成立：
--
--   - 安卓端 Drift 本地库的 `patients.visibility_state` 列**已经删掉**
--     （`schemaVersion 3 → 4`），代码里只剩注释，没有任何读取点；
--   - 管理后台的 TS 类型里它只是个**可选**字段，没有任何页面渲染它；
--   - 后端只有 `schemas/patient.py::PatientOut` 声明它。
--
-- 也就是说：**没有任何真实消费者**。留着它的代价是"一个看起来有意义、实际恒定的字段"
-- ——后来人会以为它表达状态，进而写出基于它的判断（这正是它当初退化的原因）。
--
-- ## 为什么视图仍然保留
--
-- `v_patient_visibility` 本身**不删**：它仍是"归属解析"的单点实现
-- （`visible_therapist_id` 是查询与 `mine`/`unassigned` 筛选的判据）。
-- 本次只删列，不删视图，也不改变 `visible_therapist_id` 的取值。
--
-- ⚠ 视图必须先 DROP 再重建：SQLite 不支持 `ALTER VIEW`。
-- ⚠ 本段 CREATE VIEW 必须与 `app/models/patient.py::VISIBILITY_VIEW_SQL` 逐字一致
--   （`scripts/check_docs_consistency.py` 会比对两者）。

BEGIN;

DROP VIEW IF EXISTS v_patient_visibility;

CREATE VIEW v_patient_visibility AS
SELECT p.inpatient_no,
       p.assigned_therapist_id,
       p.assigned_therapist_id AS visible_therapist_id
FROM patient p;

COMMIT;
