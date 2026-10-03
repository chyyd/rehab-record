-- 002_triggers.sql
-- 全部触发器与时间戳策略的**唯一来源**。
--
-- 为什么单独成一个迁移：
--   1) 001 只负责表/索引/视图结构，002 只负责行为（updated_at 维护、提交后修改留痕），职责清晰；
--   2) 避免同一批触发器在多个迁移里重复定义造成漂移；
--   3) 时间戳策略集中在一处，便于审查。
--
-- 时间戳策略（重要）：
--   统一 UTC ISO8601 带毫秒与 Z 后缀：strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
--   * 禁止 datetime('now','localtime')：SQLite 无时区概念，该修饰符按 UTC 计算再套本地偏移，
--     在 +08:00 时区下写出比真实时间快 8 小时的脏时间戳，会让"谁在何时改了什么"全部失真；
--   * 带毫秒：同一秒内的多次修改必须能区分先后（updated_at 判重与同步游标都依赖它）。
--
-- 判空比较注意（踩过的坑）：
--   SQLite **没有** `IS NOT` 这个不等式运算符。写 `OLD.x IS NOT NEW.x` 不会报错，
--   但会被当作 `IS` + `NOT` 解析成恒假/恒真，导致 WHEN 条件失效（触发器静默不工作）。
--   这里统一用 `COALESCE(a,-1) <> COALESCE(b,-1)` 做 null-safe 不等于。
--
-- 刷新策略：
--   * 实体表（patient/appointment/treatment_record/...）无条件刷新 updated_at；
--   * leave_record / temporary_assignment 只在"状态或归属真正变化"时刷新，
--     否则后台定时扫描会把 updated_at 刷成噪声，让同步端误判有变更。

BEGIN;

-- ------------------------------------------------------------------------ --
-- 1. updated_at 自动维护
-- ------------------------------------------------------------------------ --
CREATE TRIGGER trg_user_updated_at AFTER UPDATE ON user
BEGIN UPDATE user SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER trg_patient_updated_at AFTER UPDATE ON patient
BEGIN UPDATE patient SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE inpatient_no = NEW.inpatient_no; END;

CREATE TRIGGER trg_appointment_updated_at AFTER UPDATE ON appointment
BEGIN UPDATE appointment SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER trg_treatment_record_updated_at AFTER UPDATE ON treatment_record
BEGIN UPDATE treatment_record SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER trg_record_item_updated_at AFTER UPDATE ON record_item
BEGIN UPDATE record_item SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER trg_main_item_updated_at AFTER UPDATE ON main_item
BEGIN UPDATE main_item SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER trg_sub_item_updated_at AFTER UPDATE ON sub_item
BEGIN UPDATE sub_item SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER trg_param_def_updated_at AFTER UPDATE ON sub_item_param_def
BEGIN UPDATE sub_item_param_def SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER trg_option_set_updated_at AFTER UPDATE ON option_set
BEGIN UPDATE option_set SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER trg_response_def_updated_at AFTER UPDATE ON response_def
BEGIN UPDATE response_def SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER trg_template_updated_at AFTER UPDATE ON record_template
BEGIN UPDATE record_template SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

-- 只在状态/归属真正变化时刷新（null-safe 不等于，见文件头说明）
CREATE TRIGGER trg_leave_updated_at AFTER UPDATE ON leave_record
WHEN COALESCE(OLD.status, '') <> COALESCE(NEW.status, '')
  OR COALESCE(OLD.cancelled_at, '') <> COALESCE(NEW.cancelled_at, '')
  OR COALESCE(OLD.released_at, '') <> COALESCE(NEW.released_at, '')
BEGIN UPDATE leave_record SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER trg_temp_assign_updated_at AFTER UPDATE ON temporary_assignment
WHEN COALESCE(OLD.status, '') <> COALESCE(NEW.status, '')
  OR COALESCE(OLD.temporary_therapist_id, -1) <> COALESCE(NEW.temporary_therapist_id, -1)
  OR COALESCE(OLD.closed_at, '') <> COALESCE(NEW.closed_at, '')
  OR COALESCE(OLD.closed_reason, '') <> COALESCE(NEW.closed_reason, '')
BEGIN UPDATE temporary_assignment SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;


-- ------------------------------------------------------------------------ --
-- 2. 提交后修改留痕（4.3 关键业务规则 / M11）
--    draft 阶段随便改，不产生审计噪声；
--    submitted / locked 阶段的任何实质修改都写 audit_log 并累加 edit_count。
-- ------------------------------------------------------------------------ --
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

COMMIT;
