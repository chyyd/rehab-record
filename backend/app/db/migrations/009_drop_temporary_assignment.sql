-- 009_drop_temporary_assignment.sql
-- 临时指派（temporary_assignment）彻底删除（业务决策变更，2026-10-05）。
--
-- 背景：`temporary_assignment` 表达的是"某患者在某半日暂时不归原治疗师管，
-- 可见归属变 NULL、他人可临时认领"。它已经**设计性失效**：
--
--   1. 唯一自动产生来源是"单日请假"，而请假（leave_record）已随排期功能整体下线
--      （迁移 008），自动来源消失；
--   2. 它**从来没有** API 或 CLI 登记入口 —— `/temp-release`、`/temp-claim`
--      两个接口从未实现过（设计里有，代码里没有）；
--   3. 2026-10-03 改成"**全科白板**"后，任何治疗师都能查看/记录任何在院患者，
--      所以"临时把患者从甲转给乙"**不改变任何权限**，只影响 `scope=mine` 的
--      筛选与排序分组 —— 那是可以用 `assigned_therapist_id` 直接表达的；
--   4. 生产数据实测：表 0 行、temp_claim/temp_release 历史 0 条、
--      16 位患者全部 `assigned`，可见归属恒等于原归属；而 `scope=temp`
--      （App 时间轴里的一个可见页签）永远返回 0 条。
--
-- 所以本次把归属**简化为两层**（这才是系统真正在用的）：
--
--   visible_therapist_id 直接 = patient.assigned_therapist_id
--   scope=mine        → 归属是我
--   scope=unassigned  → 归属为 NULL
--
-- 注意**两件事不要混淆**（用户决定，2026-10-05）：
--
--   * `scope=temp` —— **数据范围筛选**，已**全部删除**：患者列表的
--     （`app/models/patient.py` 的 `Scope` / `visibility_from()`）与
--     「时间轴 / 记录列表」的（`app/api/v1/records.py`）都删了。
--   * `is_temporary` —— **记录级标记**（"记录人 ≠ 该患者当时的归属人"），
--     **仍然保留**，由 `app/models/treatment.py::temporary_expr()` **查询时推导**，
--     与本次删除的表**从来没有依赖关系**。它有三个真实消费方：打印 PDF 标"（临时）"、
--     患者每日汇总置 `temporary`、后台记录列表显示该列。
--     所以这不是"临时治疗功能整体下线"。
--
-- 已应用的迁移不得修改（校验和不匹配会让服务拒绝启动），故新开本文件。

-- ---------------------------------------------------------------------------
-- 0) 外键检查必须在事务之外关闭
--    SQLite 的 `PRAGMA foreign_keys` 在事务内是 no-op，所以放在 BEGIN 之前。
--    executescript 会隐式提交先前事务，因此这里的位置是安全的。
-- ---------------------------------------------------------------------------
PRAGMA foreign_keys = OFF;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1) 先删视图 —— 否则下面 DROP TABLE 会留下悬空引用
--    v_patient_visibility 依赖 temporary_assignment 算 visible_therapist_id，
--    v_open_temporary_assignment 直接读该表。
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS v_patient_visibility;
DROP VIEW IF EXISTS v_open_temporary_assignment;

-- ---------------------------------------------------------------------------
-- 2) 删触发器与表（表上的索引随表一起消失，无需单独 DROP）
--    `trg_temp_assign_updated_at` 会随表自动消失，这里显式删除是为了让
--    迁移在"表已手工删掉、触发器残留"的库上同样幂等。
-- ---------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_temp_assign_updated_at;
DROP TABLE IF EXISTS temporary_assignment;

-- ---------------------------------------------------------------------------
-- 3) 重建**简化后**的 v_patient_visibility
--
--    与迁移 003 的旧版相比：不再 JOIN 临时指派，可见归属直接等于原归属。
--    `visibility_state` 列**保留但恒为 'assigned'**：
--      * 它是 `schemas/patient.py::PatientOut` 的响应字段，也是安卓端 Drift
--        本地库缓存过的列，直接删列会让旧客户端拿不到预期字段；
--      * 它的取值集合原本是 assigned / temp_released / temp_claimed，
--        现在后两者已不可能出现，所以这一列**已经退化**。
--    将来确认没有客户端再读它时，可以再开一个迁移把它一起删掉。
--
--    定义必须与 `app/models/patient.py::VISIBILITY_VIEW_SQL` 完全一致
--    （`scripts/check_docs_consistency.py` 会逐字比对两者）。
-- ---------------------------------------------------------------------------
CREATE VIEW v_patient_visibility AS
SELECT p.inpatient_no,
       p.assigned_therapist_id,
       p.assigned_therapist_id AS visible_therapist_id,
       'assigned' AS visibility_state
FROM patient p;

-- ---------------------------------------------------------------------------
-- 4) 清掉 change_log 里临时指派的历史游标
--    这些行的 entity='temporary_assignment' 已经没有对应表了，留着会让客户端
--    在增量拉取时收到"找不到实体"的变更。游标本身是单调 id，删行不影响连续性。
-- ---------------------------------------------------------------------------
DELETE FROM change_log WHERE entity = 'temporary_assignment';

COMMIT;

PRAGMA foreign_keys = ON;
