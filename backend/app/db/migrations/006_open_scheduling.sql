-- 006_open_scheduling.sql
-- 放开排期的两条"半日唯一"约束（业务决策变更，2026-10-03）。
--
-- 背景：科室确认了真实工作流 ——
--   「一个上午里，不同治疗师可能给同一个患者做多次相同或不同名目的治疗，
--     一次治疗最多 1 小时」
-- 并明确：**本系统只做"记录"（今天做了哪些治疗、每次治疗干了什么），
-- 不做时间合规判定**（时间合规由另一个患者签字系统负责）。
--
-- 因此一条半日格子可以容纳多台排期，"占位唯一"不再是正确的模型。
--
-- 本次删除的两条索引：
--
--   1) ux_appt_patient_slot (patient_no, date, period)
--      原本实现"不变量 2：患者半日 = 一名治疗师"（Q2）。
--      新工作流下一个患者一个上午可能被 PT/OT/言语/吞咽等多个治疗师各做一次，
--      这条约束会直接挡住正常业务，因此**放弃 Q2**。
--
--   2) ux_appt_therapist_slot (therapist_id, date, period)
--      原本实现"不变量 1：治疗师半日 = 一台"（S1）。
--      它同样会挡住上述场景：甲上午已排了他的患者 P 之后，甲这个上午就被占满，
--      乙再想给 P 排期时甲已"无空"。既然治疗时长最长 1 小时，半日内容纳多台是正常的。
--
-- 保留不变的约束（仍然生效）：
--
--   * ux_temp_assign_open (patient_no, date, period) WHERE status = 'open'
--     请假/临时释放**仍是整半日粒度**（业务已确认），这条继续成立。
--   * ux_rest_block_weekly / ux_rest_block_date
--     休息块仍是"治疗师 × 半日"一条。
--   * ux_appt_client_uuid / ux_record_client_uuid / ux_patient_client_uuid
--     同步幂等键，与本次无关。
--
-- 改动后的冲突模型（排期只剩两类硬冲突，均在业务层判定）：
--   a. 休息块命中；
--   b. 该治疗师该半日处于已生效请假。
--   —— 见 app/models/appointment.py::detect_conflicts。
--
-- 注意：`start_time` / `end_time` 列保留但**不参与任何约束**，
-- 本系统不采集也不校验具体时间，仅为将来可能的排序/展示留字段。
--
-- 已应用的迁移不得修改，故新开本文件。

BEGIN;

DROP INDEX IF EXISTS ux_appt_patient_slot;
DROP INDEX IF EXISTS ux_appt_therapist_slot;

COMMIT;
