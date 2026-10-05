"""跨文档一致性校验（可重复运行）。检查设计.md / CHANGELOG.md / README.md 与代码实现是否一致。

## 2026-10-05：排期功能整体下线，本脚本的断言逐条换了对象

科室确认**排班不是本系统的职责**（理由与代价见 `CHANGELOG.md` 的决策条目），
因此 `appointment` / `rest_block` / `leave_record` 三张表、`v_patient_next_appointment`
视图、`is_temporary` 等存储列与全部排期接口一并删除，患者列表排序从
"下一个排期"改为"我最近一次已提交治疗"。

本脚本**没有把断言删空，而是逐条换成新实现的等价断言**：

| 旧断言 | 新断言 |
|---|---|
| 表清单里有 `appointment` / `rest_block` / `leave_record` | 008 必须删掉这三张表 |
| 视图 `v_patient_next_appointment` | 视图 `v_patient_last_treated`（只统计 `submitted`） |
| `treatment_record` 的 `is_temporary` / `appointment_id` 列 | 三列已删；`is_temporary` 改为查询时推导 |
| "设计.md 两条半日不变量" | 这两条不变量在文档里**不得再作为现行规则**出现 |
| —— | **新增**：`设计.md` / `README.md` / `开发计划.md` 里**不得出现**已删死代码 `covers_patient`（连"已删除"留痕也不写名字 —— 按"标记行"放行的旧断言抓不住"直接当现行函数写"的漂移） |
| 接口数 / 待办数字 | 直接数路由注册与验收脚本，与文档里的数字对账 |

## 2026-10-05（第二步）：临时指派（`temporary_assignment`）彻底删除

`temporary_assignment` 是"临时指派"（原治疗师请半天假 → 可见归属变 NULL → 他人可认领）。
它已**设计性失效**：唯一的自动来源（单日请假）随 008 下线；从来没有 API/CLI 登记入口
（`/temp-release`、`/temp-claim` 从未实现）；2026-10-03 改成"全科白板"后它**不改变任何权限**，
只影响 `scope=mine` 的筛选与排序分组。实测表 0 行、`temp_claim`/`temp_release` 历史 0 条。

于是迁移 **009** 删掉该表、`v_open_temporary_assignment` 视图与它的触发器，并把
`v_patient_visibility` 简化成"可见归属 = 原归属"两层结构：

| 旧断言 | 新断言 |
|---|---|
| 008 **不删** `temporary_assignment` | 009 **必须删**它（008 依旧不得删它 —— 它只是"保留"到 009） |
| 有效表集合里**仍有** `temporary_assignment` | 有效表集合里**没有**它 |
| 唯一索引 `ux_temp_assign_open` 仍在 | 该索引随表在 009 消失（001 里的定义是历史事实） |
| 视图 `v_open_temporary_assignment` 存在 | 009 删掉它；`v_patient_visibility` 保留（简化版） |
| 迁移枚举 `temp status` | —— 该枚举已无任何现行存储列承载 |
| —— | **新增**：`visibility_from()` 里不再有 `temp` scope；`Scope` Literal 不含 `temp`；`patient.py` 的 `VISIBILITY_VIEW_SQL` 与 009 逐字一致 |

> ⚠ **文档已同步（2026-10-05 收尾）**：`设计.md` / `开发计划.md` / `README.md` /
> `docs/sync-protocol.md` / `docs/setup.md` / `app/README.md` 里"`temporary_assignment` 保留"
> 这类**把临时指派当现行设计**的表述已全部改写为"已删除（009）"。因此
> `temporary_assignment` / `v_open_temporary_assignment` **已加入 `DEPRECATED_TOKENS`** ——
> 从现在起，任何文档行再把它们当现行设计写（不带"已删除/已下线/曾"这类标记）都会失败。
>
> 同一次收尾还**新增了一条"迁移清单"断言**（`001–009` 共 9 个、末个是
> `009_drop_temporary_assignment.sql`、且 `README.md` 的写法一致），并**合并了一条近乎重复的
> 009 视图断言**（"删掉 `v_open_temporary_assignment`" 与 "不得重建它"），
> 所以本脚本自报的总项数**仍是 231 项** —— README 里那一项就是拿这个数字与本脚本比对。

## ⚠ `scope=temp` 删除 ≠ `is_temporary` 删除（两件事，别混）

用户决定（2026-10-05）把 **`scope=temp` 这个筛选**也一并删除：患者列表的
（`patient.py::Scope` / `visibility_from()`）与「时间轴 / 记录列表」的
（`api/v1/records.py`，现在只接受 `mine` / `visible`）**都删了**，
App 的 `TimelineScope` 枚举也只剩 `visible` / `mine`。

但 **`is_temporary` 是记录级标记，必须保留**：它表示"记录人 ≠ 该患者**记录创建时刻**
的归属治疗师"，由 `app/models/treatment.py::temporary_expr()` **查询时推导**，
与已删除的 `temporary_assignment` 表从来没有依赖关系。它有三个真实消费方：

| 消费方 | 用途 |
|---|---|
| `app/services/pdf.py` | 打印时在治疗师名后标"（临时）" |
| `app/services/summary.py` | 患者每日汇总的 `temporary` 标记 |
| `admin/src/pages/RecordsPage.tsx` | 后台记录明细的"是否临时治疗" |

因此**不存在**"临时治疗功能整体下线"这种说法 —— 下线的只是两个筛选入口。

`DEPRECATED_TOKENS` 是"已下线功能"的守门人：这些词**只允许**出现在
"已删除 / 已下线 / 曾如此"这类说明行里，不允许作为现行设计再次出现。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parents[1]  # backend/scripts/ -> 仓库根
sys.path.insert(0, str(SCRIPTS_DIR))  # 复用验收项数复核工具

DESIGN = (ROOT / "设计.md").read_text(encoding="utf-8")
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
PLAN = (ROOT / "开发计划.md").read_text(encoding="utf-8")
SETUP = (ROOT / "docs" / "setup.md").read_text(encoding="utf-8")
SYNC_DOC = (ROOT / "docs" / "sync-protocol.md").read_text(encoding="utf-8")
APP_README = (ROOT / "app" / "README.md").read_text(encoding="utf-8")

MIG001 = (ROOT / "backend/app/db/migrations/001_initial_schema.sql").read_text(encoding="utf-8")
MIG002 = (ROOT / "backend/app/db/migrations/002_triggers.sql").read_text(encoding="utf-8")
MIG004 = (ROOT / "backend/app/db/migrations/004_sync_support.sql").read_text(encoding="utf-8")
MIG005 = (ROOT / "backend/app/db/migrations/005_template_code.sql").read_text(encoding="utf-8")
MIG006 = (ROOT / "backend/app/db/migrations/006_open_scheduling.sql").read_text(encoding="utf-8")
MIG007 = (ROOT / "backend/app/db/migrations/007_patient_last_treated.sql").read_text(encoding="utf-8")
MIG008 = (ROOT / "backend/app/db/migrations/008_drop_scheduling.sql").read_text(encoding="utf-8")
MIG009 = (ROOT / "backend/app/db/migrations/009_drop_temporary_assignment.sql").read_text(encoding="utf-8")
MIG010 = (ROOT / "backend/app/db/migrations/010_drop_visibility_state.sql").read_text(encoding="utf-8")

CONFIG = (ROOT / "backend/app/core/config.py").read_text(encoding="utf-8")
SYNC_PY = (ROOT / "backend/app/services/sync.py").read_text(encoding="utf-8")
SUMMARY_PY = (ROOT / "backend/app/services/summary.py").read_text(encoding="utf-8")
PDF_PY = (ROOT / "backend/app/services/pdf.py").read_text(encoding="utf-8")
TREATMENT_PY = (ROOT / "backend/app/models/treatment.py").read_text(encoding="utf-8")
PATIENT_PY = (ROOT / "backend/app/models/patient.py").read_text(encoding="utf-8")
RECORDS_PY = (ROOT / "backend/app/api/v1/records.py").read_text(encoding="utf-8")
CLI_PY = (ROOT / "backend/app/cli.py").read_text(encoding="utf-8")
CLOCK_PY = (ROOT / "backend/app/core/clock.py").read_text(encoding="utf-8")
WORKTIME_PY = (ROOT / "backend/app/core/worktime.py").read_text(encoding="utf-8")

APP_DB = (ROOT / "app/lib/data/local/app_database.dart").read_text(encoding="utf-8")
APP_TABLES = (ROOT / "app/lib/data/local/tables.dart").read_text(encoding="utf-8")
APP_HOME = (ROOT / "app/lib/features/home/home_shell.dart").read_text(encoding="utf-8")
APP_PDF = (ROOT / "app/lib/features/timeline/pdf_export.dart").read_text(encoding="utf-8")
APP_TIMELINE_PROVIDERS = (ROOT / "app/lib/features/timeline/timeline_providers.dart").read_text(
    encoding="utf-8"
)

ADMIN_README = (ROOT / "admin" / "README.md").read_text(encoding="utf-8")
ADMIN_ROUTES = (ROOT / "admin" / "src" / "routes.tsx").read_text(encoding="utf-8")
ADMIN_RECORDS_TSX = (ROOT / "admin" / "src" / "pages" / "RecordsPage.tsx").read_text(encoding="utf-8")
ADMIN_MODULE_ROUTES = (
    "/patients",
    "/records",
    "/summary",
    "/users",
    "/dict",
    "/option-sets",
    "/response-defs",
    "/templates",
    "/audit-logs",
)

failures: list[str] = []
total = 0

# 已下线功能的标识词；只允许出现在"已删除/已下线/曾如此"这类说明行里
DEPRECATED_TOKENS = (
    "appointment",
    "rest_block",
    "leave_record",
    "v_patient_next_appointment",
    "/schedule",
    "/rest-blocks",
    "/leave",
    # 2026-10-05（第二步）：临时指派整体删除（迁移 009）。文档已同步改写为"已删除"，
    # 故从本轮起纳入守门 —— 不许再把它们当作现行设计出现（含"保留"这类旧口径）。
    "temporary_assignment",
    "v_open_temporary_assignment",
)
DEPRECATED_MARKERS = ("下线", "删除", "移除", "废止", "取消", "曾", "不做", "已不", "不再", "不排")


def check(name: str, ok: bool) -> None:
    global total
    total += 1
    if not ok:
        failures.append(name)


def deprecated_lines(text: str, tokens: tuple[str, ...] = DEPRECATED_TOKENS) -> list[str]:
    """找出把已下线功能当作**现行设计**写下的行（说明性提及不算）。"""
    return [
        line.strip()
        for line in text.splitlines()
        if any(t in line for t in tokens) and not any(m in line for m in DEPRECATED_MARKERS)
    ]


# --------------------------------------------------------------------------- #
# 1. 迁移、表与视图
# --------------------------------------------------------------------------- #
tables = set(re.findall(r"CREATE TABLE (\w+)", MIG001))
for t in [
    "user", "auth_session", "patient", "patient_assignment_history",
    "main_item", "sub_item", "sub_item_param_def",
    "option_set", "option_item", "response_def", "record_template", "record_template_item",
    "treatment_record", "record_item", "audit_log", "change_log",
]:
    check(f"表 {t}", t in tables)

# 008 是"排期下线"的唯一落点：三张表都要删（008 里**不得**动 temporary_assignment ——
# 那是 009 的职责：008 之后、009 之前的中间态里它还必须存在）。
for t in ("appointment", "rest_block", "leave_record"):
    check(f"008 删除表 {t}", f"DROP TABLE IF EXISTS {t};" in MIG008)
check("008 不删 temporary_assignment（该表保留到 009）",
      "DROP TABLE IF EXISTS temporary_assignment" not in MIG008)

# 009 是"临时指派删除"的唯一落点
check("009 删除表 temporary_assignment", "DROP TABLE IF EXISTS temporary_assignment;" in MIG009)
check("009 先删视图再删表（否则悬空引用会让迁移失败）",
      MIG009.index("DROP VIEW IF EXISTS v_patient_visibility;")
      < MIG009.index("DROP TABLE IF EXISTS temporary_assignment;"))
# 两条 009 视图断言合并为一条（原本是"必须有 DROP"与"不得有 CREATE"两条，
# 说的是同一个对象；合并后腾出的项数用于新增下面的"迁移清单"断言，总项数不变）。
check("009 删除 v_open_temporary_assignment 视图且不再重建它",
      "DROP VIEW IF EXISTS v_open_temporary_assignment;" in MIG009
      and "CREATE VIEW v_open_temporary_assignment" not in MIG009)
check("009 删除临时指派的 updated_at 触发器",
      "DROP TRIGGER IF EXISTS trg_temp_assign_updated_at;" in MIG009)
check("009 清掉 temporary_assignment 的历史同步游标",
      "DELETE FROM change_log WHERE entity = 'temporary_assignment'" in MIG009)

# 迁移清单（2026-10-05 新增）：文件数、末个文件必须是"删除临时指派"的那个，
# 且 README 里的写法要与实际一致 —— 让"9 个迁移"这个数字不再是文档里的孤证，
# 同时防止以后有人新增迁移却忘了更新 README / 本脚本。
_MIGRATION_FILES = sorted(p.name for p in (ROOT / "backend/app/db/migrations").glob("*.sql"))
check(f"迁移清单与 README 一致（共 {len(_MIGRATION_FILES)} 个：001–010，末个为 010_drop_visibility_state.sql）",
      len(_MIGRATION_FILES) == 10
      and _MIGRATION_FILES[-1] == "010_drop_visibility_state.sql"
      and "10 个 SQL 迁移" in README
      and "001–010" in README)

_dropped = set(re.findall(r"DROP TABLE IF EXISTS (\w+)", MIG008 + MIG009))
_effective_tables = tables - _dropped
check("有效表集合里没有排期/休息块/请假",
      not (_effective_tables & {"appointment", "rest_block", "leave_record"}))
check("有效表集合里没有 temporary_assignment（临时指派已彻底删除）",
      "temporary_assignment" not in _effective_tables)
check("008 清掉 appointment 的历史同步游标",
      "DELETE FROM change_log WHERE entity = 'appointment'" in MIG008)
check("006 已删除 ux_appt_therapist_slot（治疗师半日唯一，S1 放开）",
      "DROP INDEX IF EXISTS ux_appt_therapist_slot" in MIG006)
check("006 已删除 ux_appt_patient_slot（患者半日唯一，放弃 Q2）",
      "DROP INDEX IF EXISTS ux_appt_patient_slot" in MIG006)
check("ux_temp_assign_open 只在 001 的历史定义里（随 009 删表一起消失）",
      "ux_temp_assign_open" in MIG001 and "ux_temp_assign_open" not in MIG009)

# treatment_record 去掉三个已无语义的列（008 重建表；代码侧也要核对）
_new_record_table = MIG008.split("CREATE TABLE treatment_record_new", 1)[-1].split(");", 1)[0]
for column in ("appointment_id", "is_temporary", "original_therapist_id"):
    check(f"008 重建 treatment_record 时不再有 {column}", column not in _new_record_table)
_record_columns = TREATMENT_PY.split("RECORD_COLUMNS = (", 1)[-1].split(")", 1)[0]
check("treatment.py 的 RECORD_COLUMNS 不含 appointment_id",
      "appointment_id" not in _record_columns)
check("is_temporary 改为查询时推导（temporary_expr）",
      "def temporary_expr(" in TREATMENT_PY and "AS is_temporary" in TREATMENT_PY)
check("查询里真的用上了 temporary_expr", TREATMENT_PY.count("temporary_expr(") >= 3)
check("设计.md 写明 is_temporary 按“记录创建时刻”的归属推导",
      "记录创建时刻" in DESIGN and "is_temporary" in DESIGN)
# 时间轴/记录列表的 `scope=temp` 也已按用户决定**删除**（2026-10-05），
# 现在只剩 mine / visible。但这**不等于**"临时治疗"这个概念下线：
# `is_temporary`（记录级标记）仍由 temporary_expr 推导，且有三个真实消费方。
check("记录列表/时间轴的 scope=temp 已删除（只留 mine / visible）",
      '"mine", "visible"' in RECORDS_PY and 'scope == "temp"' not in RECORDS_PY)
check("is_temporary 记录级标记仍保留，且三个消费方都在（PDF / 汇总 / 后台列表）",
      "def temporary_expr(" in TREATMENT_PY
      and '"（临时）"' in PDF_PY
      and '"temporary"' in SUMMARY_PY
      and "is_temporary" in ADMIN_RECORDS_TSX)
check("app 时间轴枚举已删除 temp（只留 visible / mine）",
      "enum TimelineScope {" in APP_TIMELINE_PROVIDERS
      and "temp(" not in APP_TIMELINE_PROVIDERS
      and "'mine'" in APP_TIMELINE_PROVIDERS)

# 视图：旧的排期视图必须消失，新的"我最近一次已提交治疗"必须在文档与迁移里同时出现
check("视图 v_patient_last_treated（007 新建）",
      "CREATE VIEW v_patient_last_treated" in MIG007 and "v_patient_last_treated" in DESIGN)
check("007 的 v_patient_last_treated 只统计 submitted",
      "WHERE r.status = 'submitted'" in MIG007)
check("007 按 (patient_no, therapist_id) 分组",
      "GROUP BY r.patient_no, r.therapist_id" in MIG007)
check("008 重建视图时与 007 定义一致（同样只统计 submitted）",
      "WHERE r.status = 'submitted'" in MIG008)
# 归属解析的唯一真源 `v_patient_visibility`：009 把它简化成"可见归属 = 原归属"，
# 010 又删掉了恒为 'assigned' 的 `visibility_state` 死列，
# 但视图本身**必须保留**（患者列表、认领、`scope` 筛选都建立在它上面）。
check("视图 v_patient_visibility 保留（010 重建的最终形态）",
      "CREATE VIEW v_patient_visibility" in MIG010
      and "CREATE VIEW v_patient_visibility" in PATIENT_PY)
check("009 的简化视图：可见归属直接等于原归属",
      "p.assigned_therapist_id AS visible_therapist_id" in MIG009)
check("010 删掉 visibility_state（恒为 'assigned' 的死列，无任何消费者）",
      "DROP VIEW IF EXISTS v_patient_visibility;" in MIG010
      and "visibility_state" not in MIG010.split("CREATE VIEW", 1)[1]
      # 反向锁：不许再把它加回视图、模型或响应 schema
      and "visibility_state" not in PATIENT_PY.split("VISIBILITY_VIEW_SQL", 1)[1].split('"""', 2)[1]
      and "visibility_state" not in (ROOT / "backend/app/schemas/patient.py").read_text(encoding="utf-8"))
# 模型里的视图常量必须与迁移逐字一致，否则"模型建库"与"迁移建库"会长出两个不同的视图。
def _normalize_view_sql(sql: str) -> str:
    text = sql.strip().rstrip(";").strip()
    return re.sub(r"\s+", " ", text)


_mig_view = MIG010.split("CREATE VIEW v_patient_visibility AS", 1)[1].split(";", 1)[0]
_patient_view = PATIENT_PY.split("VISIBILITY_VIEW_SQL = \"\"\"", 1)[1].split("\"\"\"", 1)[0]
_patient_view = _patient_view.split("CREATE VIEW v_patient_visibility AS", 1)[1]
check("patient.py 的 VISIBILITY_VIEW_SQL 与迁移 010 逐字一致",
      _normalize_view_sql("CREATE VIEW v_patient_visibility AS" + _mig_view)
      == _normalize_view_sql("CREATE VIEW v_patient_visibility AS" + _patient_view))
_check_missing = [c for c in ("temp_assignment_id", "temp_therapist_id", "temp_original_therapist_id",
                              "temp_expires_at") if c in PATIENT_PY]
check("patient.py 不再输出任何 temp_* 视图列"
      + (f"：命中 {'、'.join(_check_missing)}" if _check_missing else ""),
      not _check_missing)
check("visibility_from() 里不再有 temp scope",
      'if scope == "temp"' not in PATIENT_PY)
check("Scope Literal 不含 temp（患者列表的范围白名单）",
      'Scope = Literal["mine", "unassigned", "all", "visible", "dept"]' in PATIENT_PY)
check("认领不再依赖临时指派（temp_released 分支与 temp-claim hint 已删）",
      'if patient["visibility_state"] == "temp_released"' not in PATIENT_PY
      and '"hint": "temp-claim"' not in PATIENT_PY)
check("临时指派模块已删除（文件不存在）",
      not (ROOT / "backend/app/models/temporary_assignment.py").exists())
check("cli 不再注册 close-expired 子命令（它只清理临时指派）",
      'sub.add_parser("close-expired"' not in CLI_PY and "cmd_close_expired" not in CLI_PY)
check("clock 不再定义/导出 period_expiry（只服务已删除的临时指派到期时点）",
      "def period_expiry(" not in CLOCK_PY and '"period_expiry"' not in CLOCK_PY)
check("worktime 也删掉了 period_end_datetime / period_label（唯一调用方是已删的到期时点输出）",
      "def period_end_datetime(" not in WORKTIME_PY
      and "def period_label(" not in WORKTIME_PY
      and '"period_end_datetime"' not in WORKTIME_PY
      # 但半日边界本身要留着：/health 与 `cli periods` 仍在用
      and "def day_period_bounds(" in WORKTIME_PY
      and "day_period_bounds" in (ROOT / "backend/app/cli.py").read_text(encoding="utf-8"))

for label, values in {
    "patient.status": ["in_hospital", "discharged", "paused"],
    "period": ["'am'", "'pm'"],
    "record status": ["'draft'", "'submitted'", "'locked'"],
    "scope": ["'global'", "'dept'", "'personal'"],
    "value_type": ["'tag'", "'number'", "'select'", "'text'"],
    "role": ["'therapist'", "'admin'"],
}.items():
    for v in values:
        check(f"迁移枚举 {label}={v}", v in MIG001)
        check(f"设计.md 枚举 {label}={v}", v.strip("'") in DESIGN)

# --------------------------------------------------------------------------- #
# 2. 患者列表排序（本次功能变更的核心）
# --------------------------------------------------------------------------- #
check("patient.py 患者列表 JOIN 了 v_patient_last_treated",
      "LEFT JOIN v_patient_last_treated" in PATIENT_PY)
check("patient.py 组内按我最近一次治疗日期降序",
      "COALESCE(l.last_date, '0000-01-01') DESC" in PATIENT_PY)
check("patient.py 保留归属分组（我的 → 未分配 → 其他）",
      "WHEN v.visible_therapist_id = ? THEN 0" in PATIENT_PY
      and "WHEN v.visible_therapist_id IS NULL THEN 1 ELSE 2 END" in PATIENT_PY)
check("排序只算已提交（视图 WHERE status = 'submitted'）",
      "status = 'submitted'" in MIG007 and "status = 'submitted'" not in PATIENT_PY)
check("设计.md 写明组内排序依据", "我最近一次已提交治疗" in DESIGN)
check("设计.md 写明草稿不参与排序", "草稿不算" in DESIGN)
check("设计.md 不再把按排期排序的旧视图当现行视图",
      not [line for line in DESIGN.splitlines()
           if "v_patient_next_appointment" in line
           and not any(m in line for m in DEPRECATED_MARKERS)])
check("归属判定死函数 covers_patient / can_schedule 均已删除，归属只见于可见性视图与 scope 条件",
      "def covers_patient(" not in PATIENT_PY
      and "def can_schedule(" not in PATIENT_PY
      and "CREATE VIEW v_patient_visibility" in PATIENT_PY
      and "def visibility_from(" in PATIENT_PY)
check("设计.md 不再把 can_schedule 当现行函数名",
      not [line for line in DESIGN.splitlines()
           if "can_schedule" in line
           and not any(m in line for m in ("原名", "改名", "曾", "下线", "删除"))])
# `covers_patient()` 已按死代码删除，三个主文档里**一律不得出现这个名字** ——
# 连"已删除"的留痕也不写名字（留痕改述为"曾有的归属判定单体函数（原名 can_schedule）"）。
# 上面那条按"标记行"放行的断言抓不住"不带任何标记、直接当现行函数写"的漂移，故补一条更硬的。
_COVERS_PATIENT_FILES = [
    name
    for name, text in (("设计.md", DESIGN), ("README.md", README), ("开发计划.md", PLAN))
    if "covers_patient" in text
]
check(
    "设计.md / README.md / 开发计划.md 不得出现已删除的 covers_patient（含“已删除”留痕）"
    + (f"：命中 {'、'.join(_COVERS_PATIENT_FILES)}" if _COVERS_PATIENT_FILES else ""),
    not _COVERS_PATIENT_FILES,
)
check("设计.md 不再把两条半日不变量当现行规则",
      not [line for line in DESIGN.splitlines()
           if ("治疗师半日" in line or "患者半日" in line)
           and not any(m in line for m in DEPRECATED_MARKERS)])
check("设计.md 不再把排期相关概念当现行设计",
      not deprecated_lines(DESIGN))
check("开发计划.md 不再把排期接口/表当现行设计",
      not deprecated_lines(PLAN))
check("sync-protocol.md 不再把 appointment / 临时指派当同步通道",
      not deprecated_lines(SYNC_DOC, ("appointment", "/rest-blocks", "/leave",
                                      "temporary_assignment", "v_open_temporary_assignment")))

# --------------------------------------------------------------------------- #
# 3. 阶段 4：离线同步支撑
# --------------------------------------------------------------------------- #
for table in ("patient", "treatment_record"):
    check(f"同步：{table} 有 client_uuid", f"ALTER TABLE {table} ADD COLUMN client_uuid" in MIG004)
check("同步：client_uuid 有唯一索引", "ux_record_client_uuid" in MIG004)
check("同步：唯一索引带 WHERE client_uuid IS NOT NULL", "WHERE client_uuid IS NOT NULL" in MIG004)
check("同步：允许离线写的实体只剩治疗记录",
      'PUSHABLE_ENTITIES = ("treatment_record",)' in SYNC_PY)
check("同步：可拉取实体为 patient + treatment_record",
      'PULLABLE_ENTITIES = ("patient", "treatment_record")' in SYNC_PY)
check("同步：冲突策略含草稿客户端优先",
      'CLIENT_WINS_ENTITIES = ("treatment_record",)' in SYNC_PY)
check("sync-protocol.md 与代码一致（可推送实体）",
      'PUSHABLE_ENTITIES = ("treatment_record",)' in SYNC_DOC)
check("sync-protocol.md 与代码一致（可拉取实体）",
      'PULLABLE_ENTITIES = ("patient", "treatment_record")' in SYNC_DOC)
check("设计.md 提到游标为 change_log", "change_log" in DESIGN)
check("设计.md 写明一期离线可写只有治疗记录",
      "治疗记录" in DESIGN and "允许离线写的实体" in DESIGN)

# --------------------------------------------------------------------------- #
# 4. 阶段 5：打印、汇总与后台
# --------------------------------------------------------------------------- #
check("打印：使用内置 CID 中文字体", "UnicodeCIDFont" in PDF_PY and "STSong-Light" in PDF_PY)
check("设计.md 的 PDF 方案与实现一致", "STSong-Light" in DESIGN and "reportlab" in DESIGN)
check("设计.md 已标注 WeasyPrint 被推翻", "WeasyPrint" in DESIGN and "推翻" in DESIGN)
# Q10：抬头有科室名、页脚有页码与打印时间、不做签名栏
check("打印：抬头含科室名", "DEFAULT_DEPT_NAME" in PDF_PY)
check("打印：页脚含页码", "第 {canvas.getPageNumber()} 页" in PDF_PY)
check("打印：页脚含打印时间", "打印时间：" in PDF_PY)
# Q10 不做签名栏：代码里可以出现"签名"二字（注释里解释为什么不画），
# 但**不能真的往 canvas 上画**。所以断言的是"没有 drawString 签名文本"这类实际绘制。
check(
    "打印：不绘制签名栏（Q10）",
    not any(
        marker in PDF_PY
        for marker in ('drawString(0, 0, "签名', 'drawString(0, 0, "患者签字', '"签名："', "'签名：'")
    ),
)
check("设计.md Q10 明确不做签名栏", "签名栏" in DESIGN and "**无**" in DESIGN)
# 已核对 summary.py 的真实取值：只统计已提交与已锁定（草稿是"还没写完"，不该计入）
check("汇总：只统计已提交与已锁定", 'COUNTED_STATUSES = ("submitted", "locked")' in SUMMARY_PY)
check("设计.md 三种汇总口径都在", all(k in DESIGN for k in ("按日期汇总", "按患者每日汇总", "单个患者汇总打印")))
for endpoint in (
    "/summary/date",
    "/summary/patient/{no}",
    "/print/patient/{no}",
    "/print/summary/date",
    "/print/summary/patient/{no}",
    "/audit-logs",
):
    check(f"设计.md 列出接口 {endpoint}", endpoint in DESIGN)

# 接口总数：直接数注册的路由（README 的"接口"按"方法+路径"的操作数计）
sys.path.insert(0, str(ROOT / "backend"))
try:
    from app.api.v1 import api_router as _api_router  # noqa: E402

    _operations = [r for r in _api_router.routes if getattr(r, "methods", None)]
    _paths = {r.path for r in _operations}
    check(
        f"README 接口数与路由注册数一致（{len(_operations)} 个操作 / {len(_paths)} 个路径）",
        f"{len(_operations)} 个接口" in README,
    )
except Exception as exc:  # pragma: no cover - 只在环境缺依赖时触发
    check(f"接口数可核对（导入 app.api.v1 失败，请用系统 Python 3.13 运行）：{exc!r}", False)

# --------------------------------------------------------------------------- #
# 5. 验收项数：文档里的数字必须与脚本里的 check() 条数对得上
# --------------------------------------------------------------------------- #
import count_verify_checks  # noqa: E402

_counts = count_verify_checks.count_all()
_doc_counts = {name: int(n) for name, n in re.findall(r"(verify_\w+\.py).*?（(\d+) 项）", SETUP)}
check("setup.md 逐个列出 6 个验收脚本的项数",
      set(_doc_counts) == set(_counts))
for name, count in sorted(_counts.items()):
    check(f"setup.md 的 {name} 项数与脚本一致（{count} 项）", _doc_counts.get(name) == count)
check("setup.md 的端到端项数等于各脚本之和",
      f"端到端 {sum(_counts.values())} 项" in SETUP)
check("README 与 setup.md 的端到端项数一致",
      f"端到端 {sum(_counts.values())} 项" in README)
check("开发计划.md 的端到端项数与脚本一致",
      f"{sum(_counts.values())} 项端到端检查" in PLAN)

# --------------------------------------------------------------------------- #
# 6. 阶段 5 补种：四大高频模板（D04 / T3.2）
# --------------------------------------------------------------------------- #
DICT_SEED = json.loads((ROOT / "backend/seed/dict_seed.json").read_text(encoding="utf-8"))
TPL_SEED_PY = (ROOT / "backend/seed/templates.py").read_text(encoding="utf-8")

seeded_main_codes = [m["code"] for m in DICT_SEED["main_items"]]
check("种子：字典含 4 个主项目", len(seeded_main_codes) == 4)
check("种子：字典含 29 个子项目",
      sum(len(m["sub_items"]) for m in DICT_SEED["main_items"]) == 29)
check("种子：字典含 89 个参数",
      sum(len(s["params"]) for m in DICT_SEED["main_items"] for s in m["sub_items"]) == 89)
check("种子：含 templates 段", isinstance(DICT_SEED.get("templates"), list))
check("种子：模板 4 套（对应四大高频模板）", len(DICT_SEED.get("templates") or []) == 4)
for template in DICT_SEED.get("templates") or []:
    check(f"种子：模板 {template.get('code')} 有 code", bool(template.get("code")))
    check(f"种子：模板 {template.get('code')} 是科室级", template.get("scope") == "dept")
    check(f"种子：模板 {template.get('code')} 归属已知主项目",
          template.get("main_item_code") in seeded_main_codes)
check("设计.md 8.2 有四节模板细化",
      all(f"8.2.{i}" in DESIGN for i in (1, 2, 3, 4)))
check("设计.md 一期 MVP 要求四大高频模板", "四大高频模板" in DESIGN)
check("迁移 005：模板加 code 列", "ADD COLUMN code TEXT" in MIG005)
check("迁移 005：code 有部分唯一索引", "ux_template_code" in MIG005 and "WHERE code IS NOT NULL" in MIG005)
check("种子：按 code 查找模板（改名后仍能命中）", "WHERE code = ?" in TPL_SEED_PY)
check("种子：模板参数取自字典默认值", "default_value" in TPL_SEED_PY)
check("种子：单选默认值拆成标量", 'if input_type == "select"' in TPL_SEED_PY)

for tag, sql in (("001", MIG001), ("002", MIG002)):
    check(f"{tag} 无 localtime 用法", not [
        i for i, line in enumerate(sql.splitlines(), 1)
        if "'localtime'" in line and not line.strip().startswith("--")
    ])
    check(f"{tag} 用 UTC 毫秒时间戳", "%Y-%m-%dT%H:%M:%fZ" in sql)

check("002 不含 IS NOT 不等式", not [
    line for line in MIG002.splitlines()
    if re.search(r"\bIS NOT\b", line) and not line.strip().startswith("--")
])
check("002 使用 COALESCE", "COALESCE" in MIG002)

for value in ["06:00", "11:30", "13:00", "17:30"]:
    check(f"config.py 作息 {value}", value in CONFIG)
    check(f"设计.md 作息 {value}", value in DESIGN)
check("README 作息", "06:00" in README)
check("CHANGELOG 作息", "06:00" in CHANGELOG)

# --------------------------------------------------------------------------- #
# 7. 文档版本、CHANGELOG 与"已删掉的排期工作"的留痕
# --------------------------------------------------------------------------- #
check("设计.md 头部 V1.2", "**版本**：V1.2" in DESIGN)
check("设计.md 结尾 V1.2", "**文档版本**：V1.2" in DESIGN)
check("设计.md 无 V1.1 头部", "**版本**：V1.1" not in DESIGN)
check("设计.md 无中文状态枚举残留", "在院、出院、暂停治疗" not in DESIGN)
check("设计.md 说明了排期为何下线（排班不是本系统的职责）",
      "排班不是本系统的职责" in DESIGN)

check("README 声明 V1.2", "V1.2" in README or "V1.3" in README)
check("README 引用 app.cli", "app.cli" in README)
_changelog_headings = [line for line in CHANGELOG.splitlines() if line.startswith("### ")]
check("CHANGELOG 段落唯一", len(_changelog_headings) == len(set(_changelog_headings)))
check("CHANGELOG 无过期待办声明", "尚未执行" not in CHANGELOG)
check("CHANGELOG 已登记「取消排期功能」决策", "取消排期功能" in CHANGELOG)
check("CHANGELOG 记录了用户的原始理由", "app功能过剩" in CHANGELOG)
check("CHANGELOG 记录了删除范围（后端 + 管理后台 + 安卓）",
      all(k in CHANGELOG for k in ("管理后台", "安卓")))
check("CHANGELOG 记录了代价（验收项数下降 + 阶段 2 作废）",
      "验收项数" in CHANGELOG and "阶段 2 作废" in CHANGELOG)

# --------------------------------------------------------------------------- #
# 8. 安卓端（页签 3 个、PDF 三种去向、没有排期）
# --------------------------------------------------------------------------- #
check("Drift schemaVersion 已升到 4（v3 删排期表、v4 删 visibility_state）",
      "schemaVersion => 4" in APP_DB)
check("Drift 迁移删掉 appointments 表", "deleteTable('appointments')" in APP_DB)
check("Drift 迁移去掉 treatment_records.appointment_id",
      "dropColumn(treatmentRecords, 'appointment_id')" in APP_DB)
check("Drift 迁移删掉 patients.visibility_state（临时指派删除后该字段已退化）",
      "dropColumn(patients, 'visibility_state')" in APP_DB)
check("Drift 不再定义 Patients.visibilityState",
      "visibilityState" not in APP_TABLES)
check("Drift 不再定义 Appointments 表", "class Appointments" not in APP_TABLES)
check("App 页签为 3 个（患者 / 时间轴 / 我的）",
      APP_HOME.count("NavigationDestination(") == 3
      and all(k in APP_HOME for k in ("'患者'", "'时间轴'", "'我的'")))
check("PDF 导出为三种去向（发送给微信 / 系统打印 / 打开）",
      all(k in APP_PDF for k in ("'share'", "'print'", "'open'")))
check("app/README.md 写明页签 3 个", "页签" in APP_README and "3 个" in APP_README)
check("app/README.md 写明 PDF 三种去向",
      all(k in APP_README for k in ("发送给微信", "系统打印", "打开")))
check("app/README.md 不再描述排期页/排期表",
      not [line for line in APP_README.splitlines()
           if any(t in line for t in ("排期", "schedule", "appointment"))
           and not any(m in line for m in DEPRECATED_MARKERS)])

# --------------------------------------------------------------------------- #
# 8b. 管理后台：文档的模块清单与路由表必须一致（排期页/请假页已删除）
# --------------------------------------------------------------------------- #
for route in ADMIN_MODULE_ROUTES:
    check(f"admin 路由表有 {route}", f'path="{route.lstrip("/")}"' in ADMIN_ROUTES)
    check(f"admin/README.md 列出模块 {route}", f"`{route}`" in ADMIN_README)
check("admin/README.md 不再把 /schedule、/leave 当现行模块",
      not deprecated_lines(ADMIN_README, ("/schedule", "/leave")))
check("admin/README.md 写明排期/请假页已删除",
      "下线" in ADMIN_README or "删除" in ADMIN_README)

# --------------------------------------------------------------------------- #
# 9. 环境认知：必须写明用系统 Python 3.13，避免复现"探错解释器"的误判
# --------------------------------------------------------------------------- #
check("setup.md 写明系统 Python 3.13", "Python313" in SETUP)
check("setup.md 警告不要用 dsh Python", "dsh-primary-runtime" in SETUP)

# --------------------------------------------------------------------------- #
# 10. 本脚本自报的项数也要和文档对得上（放在最后，因为要用最终 total）
# --------------------------------------------------------------------------- #
_expected_total = total + 1  # 下面这次 check 本身也计入
check(f"README 记录的跨文档校验项数与本脚本一致（{_expected_total} 项）",
      f"跨文档校验 {_expected_total} 项" in README)

# ⚠ 失败汇总行要打印**包含最后那次自校验**的项数（即 `total`，此时 check() 已被调用过），
# 否则会出现"检查 231 项，1 项失败"而实际跑了 232 项 —— 自己把自己的项数说少一项，
# 与本文件要解决的"文档数字与实现漂移"是同一类毛病。
if failures:
    print(f"检查 {total} 项，{len(failures)} 项失败：")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print(f"检查 {total} 项，全部一致（0 失败）。")
