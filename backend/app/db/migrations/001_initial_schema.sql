-- 001_initial_schema.sql
-- 初始表结构：落地《开发计划.md》2.2 节的 S1 与 M01–M18。
-- 执行方式：由 app.db.storage.migrate() 调 executescript，脚本自带事务，失败由 SQLite 回滚。
--
-- 约定：
--   * 日期 YYYY-MM-DD、时刻 HH:MM（本地墙钟，用于排期与作息）
--   * 时间戳一律 UTC ISO8601 带毫秒与 Z 后缀：strftime('%Y-%m-%dT%H:%M:%fZ','now')
--     **禁止使用 datetime('now','localtime')**：SQLite 没有时区概念，该修饰符按 UTC 计算再套
--     本地偏移，在 +08:00 时区下会写出比真实时间快 8 小时的脏时间戳。
--   * 枚举用 CHECK 约束在库层兜底，业务层仍要校验，双重保护
--   * JSON 字段用 json_valid() 兜底，防止写入非 JSON 导致读取期爆炸
--
-- 触发器（updated_at 维护、提交后修改留痕）**统一放在 002**，保持单一来源，避免两处漂移。

BEGIN;

-- ======================================================================== --
-- 1. 用户与认证（M01 / M02 / M14）
-- ======================================================================== --
CREATE TABLE user (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_no   TEXT    NOT NULL UNIQUE,                              -- 工号，登录名（M01）
    name          TEXT    NOT NULL,
    password_hash TEXT,                                                -- argon2 哈希（M01）
    phone         TEXT,
    role          TEXT    NOT NULL CHECK (role IN ('therapist', 'admin')),  -- M14：非空
    status        TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- refresh token 只存哈希，支持退出登录与管理员踢下线（M02 / D01）
CREATE TABLE auth_session (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            INTEGER NOT NULL,
    refresh_token_hash TEXT    NOT NULL,
    device_info        TEXT,
    expires_at         TEXT    NOT NULL,
    revoked_at         TEXT,
    created_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES user (id)
);
CREATE INDEX ix_auth_session_user ON auth_session (user_id, expires_at);


-- ======================================================================== --
-- 2. 患者与归属（M12 / M13）
-- ======================================================================== --
CREATE TABLE patient (
    inpatient_no           TEXT PRIMARY KEY,                            -- 住院编号
    name                   TEXT NOT NULL,
    diagnosis              TEXT,
    admin_note             TEXT,                                        -- 注意事项：仅管理员可写
    assigned_therapist_id  INTEGER,                                     -- 单日假期间**永不修改**（M09）
    status                 TEXT NOT NULL DEFAULT 'in_hospital'
                               CHECK (status IN ('in_hospital', 'discharged', 'paused')),  -- M13 统一枚举
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    revision               INTEGER NOT NULL DEFAULT 1,                  -- M06 乐观锁
    FOREIGN KEY (assigned_therapist_id) REFERENCES user (id)
);
CREATE INDEX ix_patient_assigned ON patient (assigned_therapist_id);
CREATE INDEX ix_patient_status ON patient (status);

-- 归属变更历史（M12）：回答"谁管过这个患者"
CREATE TABLE patient_assignment_history (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_no          TEXT NOT NULL,
    from_therapist_id   INTEGER,
    to_therapist_id     INTEGER,
    change_type         TEXT NOT NULL CHECK (change_type IN
                            ('claim', 'admin_assign', 'admin_release',
                             'multi_day_release', 'temp_claim', 'temp_release')),
    operator_user_id    INTEGER,
    effective_date      TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (patient_no) REFERENCES patient (inpatient_no),
    FOREIGN KEY (from_therapist_id) REFERENCES user (id),
    FOREIGN KEY (to_therapist_id) REFERENCES user (id),
    FOREIGN KEY (operator_user_id) REFERENCES user (id)
);
CREATE INDEX ix_pah_patient ON patient_assignment_history (patient_no, created_at);


-- ======================================================================== --
-- 3. 排期与休息（S1 / M07 / M15）
-- ======================================================================== --
-- period 是排期的核心单位：一个治疗师同一半日只能有一台；
-- 一个患者同一半日只能被一名治疗师排期（Q1 / Q2）。
-- start_time / end_time 降级为可选"计划时间"，仅用于同日排序与显示，不参与唯一约束。
CREATE TABLE appointment (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_no   TEXT    NOT NULL,
    therapist_id INTEGER NOT NULL,
    date         TEXT    NOT NULL,                                      -- YYYY-MM-DD
    period       TEXT    NOT NULL CHECK (period IN ('am', 'pm')),       -- S1：上午 / 下午
    start_time   TEXT,
    end_time     TEXT,
    slot_label   TEXT,
    status       TEXT    NOT NULL DEFAULT 'planned' CHECK (status IN
                     ('planned', 'arrived', 'in_progress', 'done',
                      'cancelled', 'no_show', 'rescheduled')),
    note         TEXT,
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    revision     INTEGER NOT NULL DEFAULT 1,                            -- M06
    FOREIGN KEY (patient_no) REFERENCES patient (inpatient_no),
    FOREIGN KEY (therapist_id) REFERENCES user (id)
);

CREATE INDEX ix_appt_therapist_date ON appointment (therapist_id, date);
CREATE INDEX ix_appt_patient_date   ON appointment (patient_no, date);
CREATE INDEX ix_appt_date_period    ON appointment (date, period);

-- 不变量 1：治疗师半日 = 一台
CREATE UNIQUE INDEX ux_appt_therapist_slot
    ON appointment (therapist_id, date, period)
    WHERE status NOT IN ('cancelled', 'rescheduled');

-- 不变量 2：患者半日 = 一名治疗师（Q2 明确不允许同时段多人排期）
CREATE UNIQUE INDEX ux_appt_patient_slot
    ON appointment (patient_no, date, period)
    WHERE status NOT IN ('cancelled', 'rescheduled');

-- 休息块：按半日（S1）。weekly=每周固定某天某半日；date=指定日期的某半日
CREATE TABLE rest_block (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    therapist_id  INTEGER NOT NULL,
    scope         TEXT    NOT NULL CHECK (scope IN ('weekly', 'date')),
    weekday       INTEGER CHECK (weekday BETWEEN 0 AND 6),
    specific_date TEXT,
    period        TEXT    NOT NULL CHECK (period IN ('am', 'pm')),
    note          TEXT,
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    -- scope 与字段必须自洽，否则会出现"指定日期却没填日期"的脏数据
    CHECK ((scope = 'weekly' AND weekday IS NOT NULL AND specific_date IS NULL)
        OR (scope = 'date'   AND specific_date IS NOT NULL AND weekday IS NULL)),
    FOREIGN KEY (therapist_id) REFERENCES user (id)
);
CREATE UNIQUE INDEX ux_rest_block_weekly
    ON rest_block (therapist_id, weekday, period) WHERE scope = 'weekly';
CREATE UNIQUE INDEX ux_rest_block_date
    ON rest_block (therapist_id, specific_date, period) WHERE scope = 'date';


-- ======================================================================== --
-- 4. 请假与临时指派（M08 / M09）
-- ======================================================================== --
-- Q6：无审批流，登记即生效。治疗师自己请 or 管理员代录，靠 source 区分。
CREATE TABLE leave_record (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    therapist_id   INTEGER NOT NULL,
    start_date     TEXT    NOT NULL,
    end_date       TEXT    NOT NULL,
    leave_type     TEXT    NOT NULL CHECK (leave_type IN
                       ('half_day_am', 'half_day_pm', 'full_day', 'multi_day')),
    period         TEXT    CHECK (period IN ('am', 'pm', 'full')),     -- M09 明确语义
    source         TEXT    NOT NULL DEFAULT 'therapist_self'
                       CHECK (source IN ('therapist_self', 'admin_entry')),
    status         TEXT    NOT NULL DEFAULT 'active'
                       CHECK (status IN ('active', 'cancelled')),
    reason         TEXT,
    created_by     INTEGER,
    recorded_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    applied_at     TEXT,
    cancelled_at   TEXT,
    cancel_reason  TEXT,
    released_at    TEXT,
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (end_date >= start_date),
    FOREIGN KEY (therapist_id) REFERENCES user (id),
    FOREIGN KEY (created_by) REFERENCES user (id)
);
CREATE INDEX ix_leave_therapist_date ON leave_record (therapist_id, start_date, end_date);
CREATE INDEX ix_leave_active ON leave_record (status, start_date);

-- 单日假：临时释放 / 临时认领。原归属保留在 patient.assigned_therapist_id。
CREATE TABLE temporary_assignment (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_no            TEXT    NOT NULL,
    original_therapist_id INTEGER NOT NULL,
    temporary_therapist_id INTEGER,
    date                  TEXT    NOT NULL,
    period                TEXT    NOT NULL CHECK (period IN ('am', 'pm', 'full')),
    status                TEXT    NOT NULL DEFAULT 'open'
                             CHECK (status IN ('open', 'closed', 'converted')),
    expires_at            TEXT,                                        -- M09：按 Q11 作息取半日区间结束时刻
    released_at           TEXT,
    closed_at             TEXT,
    closed_reason         TEXT,
    created_at            TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at            TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (patient_no) REFERENCES patient (inpatient_no),
    FOREIGN KEY (original_therapist_id) REFERENCES user (id),
    FOREIGN KEY (temporary_therapist_id) REFERENCES user (id)
);
CREATE INDEX ix_temp_assign_open ON temporary_assignment (status, expires_at);
CREATE INDEX ix_temp_assign_patient ON temporary_assignment (patient_no, date);
-- 同一患者同一时段最多一条未关闭的临时指派，防止定时任务/重复提交产生重复行
CREATE UNIQUE INDEX ux_temp_assign_open
    ON temporary_assignment (patient_no, date, period) WHERE status = 'open';


-- ======================================================================== --
-- 5. 治疗项目字典（M03 / M04 / M05）
-- ======================================================================== --
CREATE TABLE main_item (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    code       TEXT UNIQUE,                          -- 语义键，种子脚本按它 upsert（D04）
    alias      TEXT,
    sort       INTEGER NOT NULL DEFAULT 0,
    status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE sub_item (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    main_item_id INTEGER NOT NULL,
    name         TEXT NOT NULL,
    code         TEXT UNIQUE,
    alias        TEXT,
    sort         INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (main_item_id) REFERENCES main_item (id)
);
CREATE INDEX ix_sub_item_main ON sub_item (main_item_id, sort);

-- 参数定义。注意 options_json 的含义**只有一种**：该参数的预制选项（P-17 澄清）
CREATE TABLE sub_item_param_def (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sub_item_id   INTEGER NOT NULL,
    param_key     TEXT NOT NULL,                     -- M16：JSON 里一律用 param_key 作键
    param_name    TEXT NOT NULL,
    input_type    TEXT NOT NULL CHECK (input_type IN ('select', 'multi_select', 'number', 'text')),
    options_json  TEXT CHECK (options_json IS NULL OR json_valid(options_json)),
    default_value TEXT,
    required      INTEGER NOT NULL DEFAULT 0 CHECK (required IN (0, 1)),
    unit          TEXT,
    sort          INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (sub_item_id, param_key),
    FOREIGN KEY (sub_item_id) REFERENCES sub_item (id)
);
CREATE INDEX ix_param_def_sub ON sub_item_param_def (sub_item_id, sort);

-- 选项集（M03）：落地 3.6.4 的全局 / 科室 / 个人三层
CREATE TABLE option_set (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    scope         TEXT NOT NULL CHECK (scope IN ('global', 'dept', 'personal')),
    owner_user_id INTEGER,
    dept_tag      TEXT,
    code          TEXT NOT NULL,                     -- 与 sub_item_param_def.param_key 呼应
    name          TEXT NOT NULL,
    alias         TEXT,
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    sort          INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    -- 个人选项集必须归属到人；科室/全局必须没有 owner
    CHECK ((scope = 'personal' AND owner_user_id IS NOT NULL)
        OR (scope IN ('global', 'dept') AND owner_user_id IS NULL)),
    FOREIGN KEY (owner_user_id) REFERENCES user (id)
);
CREATE UNIQUE INDEX ux_option_set_scope ON option_set (scope, IFNULL(owner_user_id, -1), IFNULL(dept_tag, ''), code);

CREATE TABLE option_item (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    option_set_id INTEGER NOT NULL,
    value         TEXT NOT NULL,
    label         TEXT NOT NULL,
    is_default    INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
    sort          INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (option_set_id) REFERENCES option_set (id)
);
CREATE INDEX ix_option_item_set ON option_item (option_set_id, sort);

-- 患者反应定义（M04）。8.2 节里"疼痛 + NRS""疲劳 + Borg""呛咳 + 次数"等都在这里有据可依
CREATE TABLE response_def (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    main_item_id  INTEGER,                           -- NULL = 全科通用
    code          TEXT NOT NULL,
    label         TEXT NOT NULL,
    value_type    TEXT NOT NULL CHECK (value_type IN ('tag', 'number', 'select', 'text')),
    value_key     TEXT,
    value_unit    TEXT,
    value_min     REAL,
    value_max     REAL,
    options_json  TEXT CHECK (options_json IS NULL OR json_valid(options_json)),
    sort          INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK ((value_type = 'tag' AND value_key IS NULL) OR (value_type <> 'tag')),
    CHECK (value_min IS NULL OR value_max IS NULL OR value_max >= value_min),
    FOREIGN KEY (main_item_id) REFERENCES main_item (id)
);
CREATE UNIQUE INDEX ux_response_def_code ON response_def (IFNULL(main_item_id, -1), code);

-- 记录模板（M05）：科室模板 + 个人模板，一键套用
CREATE TABLE record_template (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    scope         TEXT NOT NULL CHECK (scope IN ('dept', 'personal')),
    owner_user_id INTEGER,
    main_item_id  INTEGER NOT NULL,
    name          TEXT NOT NULL,
    sort          INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK ((scope = 'personal' AND owner_user_id IS NOT NULL)
        OR (scope = 'dept' AND owner_user_id IS NULL)),
    FOREIGN KEY (owner_user_id) REFERENCES user (id),
    FOREIGN KEY (main_item_id) REFERENCES main_item (id)
);
CREATE UNIQUE INDEX ux_template_scope ON record_template (scope, IFNULL(owner_user_id, -1), main_item_id, name);

CREATE TABLE record_template_item (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id INTEGER NOT NULL,
    sub_item_id INTEGER NOT NULL,
    params_json TEXT CHECK (params_json IS NULL OR json_valid(params_json)),
    sort        INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (template_id) REFERENCES record_template (id),
    FOREIGN KEY (sub_item_id) REFERENCES sub_item (id)
);
CREATE INDEX ix_template_item ON record_template_item (template_id, sort);


-- ======================================================================== --
-- 6. 治疗记录（M10 / M11 / M17）
-- ======================================================================== --
CREATE TABLE treatment_record (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    appointment_id        INTEGER,
    patient_no            TEXT    NOT NULL,
    therapist_id          INTEGER NOT NULL,
    original_therapist_id INTEGER,                   -- 临时认领时记录原归属（3.7）
    is_temporary          INTEGER NOT NULL DEFAULT 0 CHECK (is_temporary IN (0, 1)),
    record_date           TEXT    NOT NULL,
    session_period        TEXT    CHECK (session_period IN ('am', 'pm')),  -- 与排期 period 对齐
    seq_no                INTEGER,                   -- M10：第几次治疗
    duration_min          INTEGER CHECK (duration_min IS NULL OR duration_min >= 0),
    patient_response_json TEXT CHECK (patient_response_json IS NULL OR json_valid(patient_response_json)),
    note                  TEXT,
    status                TEXT NOT NULL DEFAULT 'draft'
                             CHECK (status IN ('draft', 'submitted', 'locked')),
    edit_count            INTEGER NOT NULL DEFAULT 0,  -- M11
    locked_at             TEXT,
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    submitted_at          TEXT,
    updated_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    revision              INTEGER NOT NULL DEFAULT 1,  -- M06
    FOREIGN KEY (appointment_id) REFERENCES appointment (id),
    FOREIGN KEY (patient_no) REFERENCES patient (inpatient_no),
    FOREIGN KEY (therapist_id) REFERENCES user (id),
    FOREIGN KEY (original_therapist_id) REFERENCES user (id)
);
CREATE INDEX ix_record_patient_date ON treatment_record (patient_no, record_date);
CREATE INDEX ix_record_therapist_date ON treatment_record (therapist_id, record_date);
CREATE INDEX ix_record_status ON treatment_record (status);

-- 记录明细：一条记录可含多个主项目下的多个子项目
CREATE TABLE record_item (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id              INTEGER NOT NULL,
    main_item_id           INTEGER NOT NULL,
    sub_item_id            INTEGER NOT NULL,
    sub_item_name_snapshot TEXT,                     -- 字典改名不影响历史（4.3）
    params_json            TEXT CHECK (params_json IS NULL OR json_valid(params_json)),
    params_snapshot_json   TEXT CHECK (params_snapshot_json IS NULL OR json_valid(params_snapshot_json)),  -- M17
    sort                   INTEGER NOT NULL DEFAULT 0,
    revision               INTEGER NOT NULL DEFAULT 1,  -- M11
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (record_id) REFERENCES treatment_record (id),
    FOREIGN KEY (main_item_id) REFERENCES main_item (id),
    FOREIGN KEY (sub_item_id) REFERENCES sub_item (id)
);
CREATE INDEX ix_record_item_record ON record_item (record_id, sort);


-- ======================================================================== --
-- 7. 审计与同步（M06）
-- ======================================================================== --
CREATE TABLE audit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER,
    action       TEXT NOT NULL,                      -- create / update / submit / lock / approve ...
    target_type  TEXT NOT NULL,                      -- treatment_record / patient / leave_record ...
    target_id    TEXT NOT NULL,
    before_json  TEXT CHECK (before_json IS NULL OR json_valid(before_json)),
    after_json   TEXT CHECK (after_json IS NULL OR json_valid(after_json)),
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES user (id)
);
CREATE INDEX ix_audit_target ON audit_log (target_type, target_id, created_at);
CREATE INDEX ix_audit_user ON audit_log (user_id, created_at);

-- 服务端变更日志：增量拉取的唯一数据源，id 即同步游标（M06）
CREATE TABLE change_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    entity        TEXT NOT NULL,
    entity_id     TEXT NOT NULL,
    op            TEXT NOT NULL CHECK (op IN ('insert', 'update', 'delete')),
    revision      INTEGER NOT NULL,
    actor_user_id INTEGER,
    payload_json  TEXT CHECK (payload_json IS NULL OR json_valid(payload_json)),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX ix_change_log_entity ON change_log (entity, entity_id);


-- ======================================================================== --
-- 8. 视图
-- ======================================================================== --
-- "我的患者优先"排序所需的最近排期（M15 + S1）
CREATE VIEW v_patient_next_appointment AS
SELECT a.patient_no                                   AS patient_no,
       MIN(a.date)                                    AS next_date,
       MIN(CASE a.period WHEN 'am' THEN 0 ELSE 1 END)  AS next_period_rank
FROM appointment a
WHERE a.status IN ('planned', 'arrived', 'in_progress')
  AND a.date >= date('now')          -- 排期日期是本地日历日，直接与当前日期比较
GROUP BY a.patient_no;

-- 未关闭的临时指派（供 visible_therapist() 归属解析使用，M09 规则 1/2）
CREATE VIEW v_open_temporary_assignment AS
SELECT ta.id, ta.patient_no, ta.original_therapist_id, ta.temporary_therapist_id,
       ta.date, ta.period, ta.expires_at,
       CASE WHEN ta.temporary_therapist_id IS NOT NULL THEN 'temp_claimed' ELSE 'temp_released' END AS state
FROM temporary_assignment ta
WHERE ta.status = 'open';

COMMIT;
