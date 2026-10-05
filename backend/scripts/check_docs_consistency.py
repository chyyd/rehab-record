"""跨文档一致性校验（可重复运行）。检查设计.md / 开发计划.md / README.md / CHANGELOG.md /
docs/*.md / admin/README.md / app/README.md 与代码实现是否一致。

## 2026-10-05（第三步）：治疗记录改为 SOAP 模板驱动，本脚本的断言逐条换了对象

用户决定把治疗记录从**参数表格**改成 **SOAP 模板驱动**：

> 「当前app端功能过剩…太过于繁琐，需要点多次，不容易使用」
> 「改成类似模板这样，输出时也用类似格式，避免现有的表格方式」
> 「使用json格式保存模板，不进数据库，以便以后我手动修改」

于是字典 / 选项集 / 患者反应定义 / 科室模板那套（4 主项目 / 29 子项目 / 89 参数、
两层快照、`session_period` 半日）**整体下线**：迁移 011 重建 `treatment_record`（19 列）、
012 删掉六张字典表，013 给 `patient.status` 加 `pending_discharge`。

本脚本**没有把断言删空，而是逐条换成新实现的等价断言**：

| 旧断言 | 新断言 |
|---|---|
| 迁移清单 001–010 共 10 个 | 迁移清单 **001–013 共 13 个**，末个 `013_patient_pending_discharge.sql` |
| 表清单里有字典 / 选项集 / 反应定义 / 记录明细 / 模板表 | 这些表**必须被 011/012 删掉**；有效表恰好 **8 张** |
| `treatment_record` 的 `appointment_id` / `is_temporary` 等列 | **19 列**固定清单 + `body_json` / `rendered_text` |
| `session_period`（半日）与两层参数快照 | 三者**已删除**，且不得在文档里作为现行设计出现 |
| 字典种子 4/29/89、选项集 47/208、反应 27、模板 4 套 | `templates/` 下 **16 份 JSON 模板** + 疗法 **58/5/4/13** |
| 患者反应定义 / 参数选项校验 | 模板 `required` 校验（缺 → 422）+ 三条门禁（缺评估文书 / 待出院 → 409） |
| PDF 表格版式 | PDF 正文是**冻结的 `rendered_text`（SOAP 纯文本）** |
| 字典 / 选项集 / 反应定义 / 模板四组接口 | 四组接口**都不在册**；新增 `GET /records/form` 与三个出院接口 |
| 接口数 / 待办数字 | 直接数路由注册与验收脚本，与文档里的数字对账 |

## 三类守门人

1. **结构断言**：迁移清单、有效表 / 视图、`treatment_record` 的 19 列与枚举 CHECK、
   索引与触发器、模板文件数量与疗法条数、`record_template.py` 的关键 API。
2. **`DEPRECATED_TOKENS`**：已删概念**只允许**出现在「已删除 / 已下线 / 已废弃 / 待删除 /
   待适配 / 曾如此」这类说明行里，不允许作为现行设计再次出现。
3. **数字对账**：接口数直接数 `api_router.routes`；端到端项数直接问
   `count_verify_checks.py`；本脚本自报的项数也要与 README 里的数字一致。

## ⚠ 本脚本**不**用 `DEPRECATED_TOKENS` 去扫 CHANGELOG.md

`CHANGELOG.md` 是留痕文件：它必须逐字保留「当时删了什么、为什么」，
里面出现 `appointment` / `option_set` / `session_period` 是**正确的**。
所以对它只做**正向断言**（决策条目写了、代价数字对得上、移除清单完整）。

## 迁移 001–013 一律不得修改

已应用的迁移改了校验和会导致 `storage.migrate()` 拒绝启动。新 DDL 一律新建 014+。
本脚本只**读**迁移文件与路由注册，从不修改它们。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parents[1]  # backend/scripts/ -> 仓库根
sys.path.insert(0, str(SCRIPTS_DIR))  # 复用验收项数复核工具


def _read(*parts: str) -> str:
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


DESIGN = _read("设计.md")
CHANGELOG = _read("CHANGELOG.md")
README = _read("README.md")
PLAN = _read("开发计划.md")
SETUP = _read("docs", "setup.md")
SYNC_DOC = _read("docs", "sync-protocol.md")
APP_README = _read("app", "README.md")
ADMIN_README = _read("admin", "README.md")

MIGRATIONS_DIR = ROOT / "backend" / "app" / "db" / "migrations"
_MIGRATION_PATHS = sorted(MIGRATIONS_DIR.glob("*.sql"))
MIG = {path.name[:3]: path.read_text(encoding="utf-8") for path in _MIGRATION_PATHS}
MIG001 = MIG.get("001", "")
MIG002 = MIG.get("002", "")
MIG004 = MIG.get("004", "")
MIG008 = MIG.get("008", "")
MIG009 = MIG.get("009", "")
MIG010 = MIG.get("010", "")
MIG011 = MIG.get("011", "")
MIG012 = MIG.get("012", "")
MIG013 = MIG.get("013", "")

CONFIG = _read("backend", "app", "core", "config.py")
CLOCK_PY = _read("backend", "app", "core", "clock.py")
WORKTIME_PY = _read("backend", "app", "core", "worktime.py")
STORAGE_PY = _read("backend", "app", "db", "storage.py")
CLI_PY = _read("backend", "app", "cli.py")
TREATMENT_PY = _read("backend", "app", "models", "treatment.py")
PATIENT_PY = _read("backend", "app", "models", "patient.py")
PATIENTS_PY = _read("backend", "app", "api", "v1", "patients.py")
RECORDS_PY = _read("backend", "app", "api", "v1", "records.py")
RECORDS_SCHEMA_PY = _read("backend", "app", "schemas", "records.py")
SYNC_PY = _read("backend", "app", "services", "sync.py")
SUMMARY_PY = _read("backend", "app", "services", "summary.py")
PDF_PY = _read("backend", "app", "services", "pdf.py")
RECORDS_SERVICE_PY = _read("backend", "app", "services", "records.py")
RECORD_TEMPLATE_PY = _read("backend", "app", "services", "record_template.py")

TEMPLATES_DIR = ROOT / "templates"
TEMPLATES_README = (TEMPLATES_DIR / "README.md").read_text(encoding="utf-8")
DISCIPLINES_JSON = json.loads((TEMPLATES_DIR / "disciplines.json").read_text(encoding="utf-8"))

APP_DB = _read("app", "lib", "data", "local", "app_database.dart")
APP_TABLES = _read("app", "lib", "data", "local", "tables.dart")
APP_HOME = _read("app", "lib", "features", "home", "home_shell.dart")
APP_PDF = _read("app", "lib", "features", "timeline", "pdf_export.dart")
APP_TIMELINE_PROVIDERS = _read("app", "lib", "features", "timeline", "timeline_providers.dart")

ADMIN_ROUTES = _read("admin", "src", "routes.tsx")
ADMIN_RECORDS_TSX = _read("admin", "src", "pages", "RecordsPage.tsx")
ADMIN_MODULE_ROUTES = ("/patients", "/records", "/summary", "/users", "/audit-logs")

# 有效表：001 建的表 - 008/009/011/012 删掉的表 + storage.py 自己建的 schema_migrations
EXPECTED_TABLES = {
    "audit_log",
    "auth_session",
    "change_log",
    "patient",
    "patient_assignment_history",
    "schema_migrations",
    "treatment_record",
    "user",
}
EXPECTED_VIEWS = {"v_patient_visibility", "v_patient_last_treated"}

# `treatment_record` 的 19 列（顺序即 DDL 顺序，`models/treatment.py::COLUMN_NAMES` 必须与之一致）
EXPECTED_RECORD_COLUMNS = (
    "id", "patient_no", "therapist_id", "record_date", "discipline", "kind", "seq_no",
    "span_seq", "body_json", "rendered_text", "note", "status", "edit_count", "locked_at",
    "created_at", "submitted_at", "updated_at", "revision", "client_uuid",
)
RECORD_INDEXES = (
    "ix_record_patient_date", "ix_record_therapist_date", "ix_record_status",
    "ix_record_discipline", "ux_record_client_uuid", "ux_record_daily_seq",
    "ux_record_assessment_span",
)

DISCIPLINES = ("PT", "OT", "ST_SW", "ST_SP")
KINDS = ("initial", "daily", "reassessment", "discharge")
# 疗法清单条数（用户 2026-10-05 给的清单：运动 / 生活技能 / 吞咽 / 言语）
THERAPY_COUNTS = {"PT": 58, "OT": 5, "ST_SW": 4, "ST_SP": 13}
# 011/012 删掉的旧模型表（九张）
DROPPED_OLD_TABLES = (
    "record_item", "record_template", "record_template_item",
    "main_item", "sub_item", "sub_item_param_def",
    "option_set", "option_item", "response_def",
)

failures: list[str] = []
total = 0

# 已下线功能的标识词；只允许出现在"已删除 / 已下线 / 已废弃 / 待删除 / 待适配 / 曾如此"这类说明行里
DEPRECATED_TOKENS = (
    # 2026-10-05：排期整体下线（迁移 008）
    "appointment",
    "rest_block",
    "leave_record",
    "v_patient_next_appointment",
    "/schedule",
    "/rest-blocks",
    # 2026-10-05（第二步）：临时指派整体删除（迁移 009）
    "temporary_assignment",
    "v_open_temporary_assignment",
    # 2026-10-05（第三步）：参数表格模型 + 字典/选项集/反应定义/科室模板整体删除（迁移 011/012）
    "record_item",
    "main_item",
    "sub_item",
    "sub_item_param_def",
    "option_set",
    "option_item",
    "response_def",
    "session_period",
    "patient_response_json",
    "params_json",
    "params_snapshot_json",
    "/option-sets",
    "/response-defs",
    "last_period_rank",
    "icon",
)
DEPRECATED_MARKERS = (
    "下线", "删除", "删掉", "移除", "废止", "取消", "曾", "不做", "已不", "不再", "不排",
    "废弃", "待删除", "待适配", "退回", "推翻", "替换", "改为", "旧模型", "历史",
)


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


def _no_deprecated(label: str, text: str, tokens: tuple[str, ...] = DEPRECATED_TOKENS) -> None:
    hits = deprecated_lines(text, tokens)
    check(
        f"{label}不再把已删概念当现行设计"
        + (f"：命中 {len(hits)} 行（首行：{hits[0][:60]}）" if hits else ""),
        not hits,
    )


# --------------------------------------------------------------------------- #
# 1. 迁移清单
# --------------------------------------------------------------------------- #
_MIGRATION_FILES = sorted(path.name for path in _MIGRATION_PATHS)
check(
    f"迁移清单与 README 一致（共 {len(_MIGRATION_FILES)} 个：001–013，"
    "末个为 013_patient_pending_discharge.sql）",
    len(_MIGRATION_FILES) == 13
    and _MIGRATION_FILES[-1] == "013_patient_pending_discharge.sql"
    and "13 个 SQL 迁移" in README
    and "001–013" in README,
)

# --------------------------------------------------------------------------- #
# 2. 有效表（8 张）与视图（2 个）
# --------------------------------------------------------------------------- #
# 有效表：按"最后一次 CREATE / DROP 谁在后"算出**当前存在**的表集合
# （`ALTER TABLE x RENAME TO y` 视为 x 消失、y 出现；同一迁移里"先 DROP 后 CREATE"
#  视为仍然存在 —— 迁移 011 重建 treatment_record 就是这种写法）
_all_migrations = [MIG[key] for key in sorted(MIG)]
_created_at: dict[str, int] = {}
_dropped_at: dict[str, int] = {}
for _index, _sql in enumerate(_all_migrations):
    for _table in re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?([a-z_][a-z0-9_]*)", _sql):
        _created_at[_table] = _index
    for _table in re.findall(r"DROP TABLE (?:IF EXISTS )?([a-z_][a-z0-9_]*)", _sql):
        _dropped_at[_table] = _index
    for _src, _dst in re.findall(
        r"ALTER TABLE ([a-z_][a-z0-9_]*) RENAME TO ([a-z_][a-z0-9_]*)", _sql
    ):
        _created_at[_dst] = _index
        _created_at.pop(_src, None)
        _dropped_at.pop(_src, None)
_effective = {
    _table for _table, _at in _created_at.items() if _at >= _dropped_at.get(_table, -1)
}
check("storage.py 自己建 schema_migrations（迁移账本，不属于业务表，也不在任何迁移里）",
      "CREATE TABLE IF NOT EXISTS schema_migrations" in STORAGE_PY
      and "schema_migrations" not in _effective)
_effective |= {"schema_migrations"}
check(f"有效表恰好 8 张（实际 {len(_effective)} 张：{'、'.join(sorted(_effective))}）",
      _effective == EXPECTED_TABLES)
for _table in sorted(EXPECTED_TABLES):
    check(f"有效表集合里有 {_table}", _table in _effective)
for _table in (*DROPPED_OLD_TABLES, "appointment", "rest_block", "leave_record",
               "temporary_assignment"):
    check(f"已删表 {_table} 不在有效表集合里", _table not in _effective)
check("已删表集合里的旧模型表都不在有效表集合里（逐张由上面的循环锁定）",
      not (_effective & set(DROPPED_OLD_TABLES)))

# 每个被删表都必须有一个明确的删除落点（否则"删了"只是文档里的说法）
for _tag, _names in (
    ("008", ("appointment", "rest_block", "leave_record")),
    ("009", ("temporary_assignment",)),
    ("011", ("record_item", "record_template", "record_template_item")),
    ("012", ("main_item", "sub_item", "sub_item_param_def", "option_set", "option_item",
             "response_def")),
):
    for _name in _names:
        check(f"{_tag} 删除表 {_name}", f"DROP TABLE IF EXISTS {_name};" in MIG[_tag])
check("008 不删 temporary_assignment（该表保留到 009）",
      "DROP TABLE IF EXISTS temporary_assignment" not in MIG008)
check("009 先删视图再删表（否则悬空引用会让迁移失败）",
      MIG009.index("DROP VIEW IF EXISTS v_patient_visibility;")
      < MIG009.index("DROP TABLE IF EXISTS temporary_assignment;"))
check("011 删掉只服务旧模型的模板表与明细表（模板改由 JSON 文件承载）",
      "DROP TABLE IF EXISTS record_template_item;" in MIG011
      and "DROP TABLE IF EXISTS record_template;" in MIG011
      and "DROP TABLE IF EXISTS record_item;" in MIG011)
check("011 清掉旧记录与旧同步游标（用户确认「清掉重来」）",
      "DELETE FROM record_item;" in MIG011
      and "DELETE FROM treatment_record;" in MIG011
      and "DELETE FROM change_log WHERE entity = 'treatment_record';" in MIG011)
check("012 在事务外关掉 foreign_keys（事务内 PRAGMA 是 no-op）",
      MIG012.index("PRAGMA foreign_keys = OFF;") < MIG012.index("BEGIN;"))
check("012 清掉六张表的同步游标", "DELETE FROM change_log WHERE entity IN" in MIG012)

# 视图：同样的"最后一次 CREATE / DROP 谁在后"口径（用**另一份**字典，别和表名混在一起）
_view_created_at: dict[str, int] = {}
_view_dropped_at: dict[str, int] = {}
for _index, _sql in enumerate(_all_migrations):
    # ⚠ 必须限定 ASCII 标识符：010 的注释里写着「本段 CREATE VIEW 必须与 …逐字一致」，
    #   用 `\w+` 会把「必须与」当成一个视图名（中文也是 \w），凭空多出一个"视图"。
    for _view in re.findall(r"CREATE VIEW ([a-z_][a-z0-9_]*)", _sql):
        _view_created_at[_view] = _index
    for _view in re.findall(r"DROP VIEW IF EXISTS ([a-z_][a-z0-9_]*)", _sql):
        _view_dropped_at[_view] = _index
_final_views = {v for v, at in _view_created_at.items()
                if at >= _view_dropped_at.get(v, -1)}
check(f"最终只有 2 个视图（实际 {len(_final_views)} 个：{'、'.join(sorted(_final_views))}）",
      _final_views == EXPECTED_VIEWS)
check("已删视图 v_open_temporary_assignment 不再存在",
      "v_open_temporary_assignment" not in _final_views)
check("已删视图 v_patient_next_appointment 不再存在",
      "v_patient_next_appointment" not in _final_views)
check("007 的 v_patient_last_treated 只统计 submitted",
      "WHERE r.status = 'submitted'" in MIG["007"]
      and "GROUP BY r.patient_no, r.therapist_id" in MIG["007"])
check("011/013 重建排序视图时加了「只算日常」的条件",
      "AND r.kind = 'daily'" in MIG011 and "AND r.kind = 'daily'" in MIG013)
_last_period_doc_lines = [
    line for line in (*DESIGN.splitlines(), *PLAN.splitlines()) if "last_period_rank" in line
]
check("011/013 重建的 v_patient_last_treated 已无 last_period_rank 列"
      "（DDL 里没有、patient.py 只剩注释、文档只允许出现在「已删除」行里）",
      "last_period_rank" not in MIG011
      and "last_period_rank" not in MIG013
      and not [line for line in PATIENT_PY.splitlines()
               if "last_period_rank" in line and not line.lstrip().startswith("#")]
      and not [line for line in _last_period_doc_lines
               if not any(m in line for m in DEPRECATED_MARKERS)])
check("视图 v_patient_visibility 保留（010 简化、013 原样建回）",
      "CREATE VIEW v_patient_visibility" in MIG010
      and "CREATE VIEW v_patient_visibility" in MIG013
      and "CREATE VIEW v_patient_visibility" in PATIENT_PY
      and "p.assigned_therapist_id AS visible_therapist_id" in MIG010)
check("010 删掉 visibility_state（恒为 'assigned' 的死列，无任何消费者）",
      "DROP VIEW IF EXISTS v_patient_visibility;" in MIG010
      and "visibility_state" not in MIG010.split("CREATE VIEW", 1)[1]
      and "visibility_state" not in PATIENT_PY.split("VISIBILITY_VIEW_SQL", 1)[1].split('"""', 2)[1]
      and "visibility_state" not in _read("backend", "app", "schemas", "patient.py"))


def _normalize_view_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.strip().rstrip(";").strip())


_mig_view = MIG010.split("CREATE VIEW v_patient_visibility AS", 1)[1].split(";", 1)[0]
_patient_view = PATIENT_PY.split('VISIBILITY_VIEW_SQL = """', 1)[1].split('"""', 1)[0]
_patient_view = _patient_view.split("CREATE VIEW v_patient_visibility AS", 1)[1]
check("patient.py 的 VISIBILITY_VIEW_SQL 与迁移 010 逐字一致",
      _normalize_view_sql("CREATE VIEW v_patient_visibility AS" + _mig_view)
      == _normalize_view_sql("CREATE VIEW v_patient_visibility AS" + _patient_view))
check("patient.py 不再输出任何 temp_* 视图列",
      not [c for c in ("temp_assignment_id", "temp_therapist_id", "temp_original_therapist_id",
                       "temp_expires_at") if c in PATIENT_PY])
check("visibility_from() 里不再有 temp scope", 'if scope == "temp"' not in PATIENT_PY)
check("认领不再依赖临时指派（temp_released 分支与 temp-claim hint 已删）",
      'if patient["visibility_state"] == "temp_released"' not in PATIENT_PY
      and '"hint": "temp-claim"' not in PATIENT_PY)
check("临时指派模块已删除（文件不存在）",
      not (ROOT / "backend/app/models/temporary_assignment.py").exists())
check("cli 不再注册 close-expired 子命令（它只清理临时指派）",
      'sub.add_parser("close-expired"' not in CLI_PY and "cmd_close_expired" not in CLI_PY)
check("clock 不再定义/导出 period_expiry", "def period_expiry(" not in CLOCK_PY)
check("worktime 也删掉了 period_end_datetime / period_label",
      "def period_end_datetime(" not in WORKTIME_PY
      and "def period_label(" not in WORKTIME_PY
      # 但半日边界本身要留着：/health 与 `cli periods` 仍在用
      and "def day_period_bounds(" in WORKTIME_PY
      and "day_period_bounds" in CLI_PY)

# --------------------------------------------------------------------------- #
# 3. treatment_record 的 19 列、枚举 CHECK、索引与触发器（迁移 011 = 唯一落点）
# --------------------------------------------------------------------------- #
_record_block = MIG011.split("CREATE TABLE treatment_record (", 1)[1].split("\n);", 1)[0]
_record_columns = tuple(re.findall(r"^\s{4}([a-z_]+)\s+(?:INTEGER|TEXT)", _record_block, re.M))
check(f"treatment_record 恰好 19 列（实际 {len(_record_columns)} 列）", len(_record_columns) == 19)
check("treatment_record 的 19 列与约定逐字一致", _record_columns == EXPECTED_RECORD_COLUMNS)
for _column in EXPECTED_RECORD_COLUMNS:
    check(f"treatment_record 有列 {_column}", _column in _record_columns)

_py_columns = tuple(
    re.findall(r'"([a-z_]+)"', TREATMENT_PY.split("COLUMN_NAMES = (", 1)[1].split(")", 1)[0])
)
check("models/treatment.py 的 COLUMN_NAMES 与迁移 011 一致（同样 19 列）",
      _py_columns == EXPECTED_RECORD_COLUMNS)
check("treatment.py 用 ASSESSMENT_KINDS 区分日常与评估文书",
      "ASSESSMENT_KINDS" in TREATMENT_PY and "KINDS = record_template.KINDS" in TREATMENT_PY)
check("treatment.py 的 daily_count 支持按状态过滤（真正治疗了几次只算已提交/已锁定）",
      "def count_sessions(" in TREATMENT_PY
      and "statuses=(STATUS_SUBMITTED, STATUS_LOCKED)" in TREATMENT_PY)
check("treatment.py 的 daily_count 只数 kind='daily'",
      "kind = 'daily'" in TREATMENT_PY)

check("011 的 discipline CHECK 只允许四大类",
      "CHECK (discipline IN ('PT', 'OT', 'ST_SW', 'ST_SP'))" in MIG011)
check("011 的 kind CHECK 只允许四种形态",
      "CHECK (kind IN ('initial', 'daily', 'reassessment', 'discharge'))" in MIG011)
check("011 的 seq_no CHECK：只有 daily 有次数（(kind='daily')=(seq_no IS NOT NULL)）",
      "CHECK ((kind = 'daily') = (seq_no IS NOT NULL))" in MIG011)
check("011 的 status CHECK 仍是 draft/submitted/locked",
      "CHECK (status IN ('draft', 'submitted', 'locked'))" in MIG011)
check("011 用 json_valid 兜底 body_json", "CHECK (json_valid(body_json))" in MIG011)
check("011 已删掉 duration_min（时长随记录表格一起下线）", "duration_min" not in _record_block)
check("011 不再有 session_period / patient_response_json / params 列",
      not [c for c in ("session_period", "patient_response_json", "params_json",
                       "params_snapshot_json") if c in _record_block])

for _index in RECORD_INDEXES:
    check(f"011 建索引 {_index}",
          f"CREATE INDEX {_index}" in MIG011 or f"CREATE UNIQUE INDEX {_index}" in MIG011)
check("ux_record_daily_seq 只在 seq_no 非空时生效（评估文书不占号）",
      "WHERE seq_no IS NOT NULL" in MIG011)
check("ux_record_assessment_span 保证每个区间同形态唯一",
      "WHERE span_seq IS NOT NULL" in MIG011)
check("ux_record_client_uuid 带 WHERE client_uuid IS NOT NULL",
      "WHERE client_uuid IS NOT NULL" in MIG011)
for _trigger in ("trg_treatment_record_updated_at", "trg_record_edit_trace"):
    check(f"011 建触发器 {_trigger}", f"CREATE TRIGGER {_trigger}" in MIG011)
check("edit_trace 只在已提交的实质改动上累加（草稿不留痕）",
      "NEW.status = 'submitted' AND OLD.status = 'submitted'" in MIG011
      and "NEW.body_json <> OLD.body_json OR NEW.rendered_text <> OLD.rendered_text" in MIG011)
check("011 已删掉旧的 trg_record_edit_count（与 edit_trace 合并）",
      "DROP TRIGGER IF EXISTS trg_record_edit_count;" in MIG011)

# 013：patient.status 新增 pending_discharge（重建表，因为 001 的 CHECK 不能改）
check("013 重建 patient 表并在 CHECK 里加 pending_discharge",
      "CREATE TABLE patient_new" in MIG013
      and "pending_discharge" in MIG013
      and "CHECK (status IN ('in_hospital', 'discharged', 'paused'," in MIG013)
check("013 重建前先删两个视图（否则悬空引用会让迁移失败）",
      MIG013.index("DROP VIEW IF EXISTS v_patient_visibility;")
      < MIG013.index("CREATE TABLE patient_new"))
check("013 把受影响的外键表与索引/触发器按原定义建回",
      "CREATE INDEX ix_patient_assigned" in MIG013
      and "CREATE INDEX ix_patient_status" in MIG013
      and "CREATE UNIQUE INDEX ux_patient_client_uuid" in MIG013
      and "CREATE TRIGGER trg_patient_updated_at" in MIG013)
check("patient 模型里 pending_discharge 与 ACTIVE_STATUSES 有明确语义",
      "STATUS_PENDING_DISCHARGE" in PATIENT_PY and "ACTIVE_STATUSES" in PATIENT_PY)
check("设计.md 写明 pending_discharge（待出院对治疗师白板不可见）",
      "pending_discharge" in DESIGN)
check("设计.md 写明满 7 天自动出院用 app.cli auto-discharge",
      "auto-discharge" in DESIGN and "7 天" in DESIGN)
check("cli 注册了 auto-discharge 子命令", 'add_parser("auto-discharge"' in CLI_PY)
check("setup.md 也列出 auto-discharge", "auto-discharge" in SETUP)
check("README/开发计划.md 也列出 auto-discharge",
      "auto-discharge" in README or "auto-discharge" in PLAN)

# --------------------------------------------------------------------------- #
# 4. 模板是 JSON 文件（16 份）与疗法清单（58/5/4/13）
# --------------------------------------------------------------------------- #
_template_files = sorted(
    path.relative_to(TEMPLATES_DIR).as_posix()
    for path in TEMPLATES_DIR.rglob("*.json")
    if path.name not in ("schema.json", "disciplines.json")
)
check(f"templates/ 下 16 份模板齐备（实际 {len(_template_files)} 份）", len(_template_files) == 16)
for _discipline in DISCIPLINES:
    for _kind in KINDS:
        check(f"模板 {_discipline}/{_kind}.json 存在",
              (TEMPLATES_DIR / _discipline / f"{_kind}.json").exists())
for _extra in ("schema.json", "disciplines.json", "README.md"):
    check(f"templates/ 下有 {_extra}", (TEMPLATES_DIR / _extra).exists())
check("templates/README.md 写明模板不进数据库", "不进数据库" in TEMPLATES_README)
check("templates/ 下只有 JSON 与 Markdown（模板不进数据库，没有 SQL/DB 文件）",
      not [str(path) for path in TEMPLATES_DIR.rglob("*")
           if path.is_file() and path.suffix not in (".json", ".md")])

_disciplines = DISCIPLINES_JSON["disciplines"]
check("disciplines.json 恰好四个大类", [d["key"] for d in _disciplines] == list(DISCIPLINES))
check("四大类的中文名是运动 / 生活技能 / 吞咽 / 言语",
      [d["name"] for d in _disciplines] == ["运动", "生活技能", "吞咽", "言语"])
_counts = {d["key"]: len(d["therapy_options"]) for d in _disciplines}
check(f"疗法清单条数为运动 58 / 生活技能 5 / 吞咽 4 / 言语 13（实际 {_counts}）",
      _counts == THERAPY_COUNTS)
check("设计.md 写明疗法清单条数（运动 58 / 生活技能 5 / 吞咽 4 / 言语 13）",
      all(k in DESIGN for k in ("运动 58", "生活技能 5", "吞咽 4", "言语 13")))
check("README 写明疗法清单条数",
      all(k in README for k in ("运动 58", "生活技能 5", "吞咽 4", "言语 13")))
check("设计.md 写明模板共 16 份", "16 份" in DESIGN)
check("README 把 templates/ 写进仓库结构（含 16 份）", "templates/" in README and "16 份" in README)
check("开发计划.md 把 templates/ 写进仓库结构（含 16 份）",
      "templates/" in PLAN and "16 份" in PLAN)

# 模板内容：四段固定、评估文书 mandatory、日常记录必填 therapy_items
for _discipline in DISCIPLINES:
    _raw = {
        _kind: json.loads(
            (TEMPLATES_DIR / _discipline / f"{_kind}.json").read_text(encoding="utf-8")
        )
        for _kind in KINDS
    }
    check(f"{_discipline} 的四份模板都声明正确的 discipline/kind",
          all(_raw[_kind]["discipline"] == _discipline and _raw[_kind]["kind"] == _kind
              for _kind in KINDS))
    check(f"{_discipline} 的三份评估文书 trigger.mandatory = true（不能跳过）",
          all(_raw[_kind].get("trigger", {}).get("mandatory") is True
              for _kind in ("initial", "reassessment", "discharge")))
    check(f"{_discipline} 的每份模板都有 S/O/A/P 四段",
          all([s["key"] for s in _raw[_kind]["soap"]] == ["s", "o", "a", "p"] for _kind in KINDS))
    check(f"{_discipline} 的前三段段名固定为 主观资料 / 客观资料 / 评估分析",
          all([s["heading"] for s in _raw[_kind]["soap"]][:3]
              == ["主观资料", "客观资料", "评估分析"] for _kind in KINDS))
    check(f"{_discipline} 的 P 段段名：非出院小结为「康复计划」、出院小结为「出院指导」",
          all(_raw[_kind]["soap"][3]["heading"]
              == ("出院指导" if _kind == "discharge" else "康复计划") for _kind in KINDS))
    check(f"{_discipline} 的日常记录必填「本次训练项目」（therapy_items.required）",
          any(f["key"] == "therapy_items" and f.get("required")
              for s in _raw["daily"]["soap"] for f in s["fields"]))
    check(f"{_discipline} 的模板都带「备注」（extra_note）且选填",
          all(any(f["key"] == "extra_note" and not f.get("required")
                  for s in _raw[_kind]["soap"] for f in s["fields"])
              for _kind in KINDS))

# ★ 首评与复评的 O 段共用 key —— 出院小结「治疗过程汇总」自动对比 `latest_vs_initial` 的前提
def _o_keys(discipline: str, kind: str) -> set[str]:
    raw = json.loads((TEMPLATES_DIR / discipline / f"{kind}.json").read_text(encoding="utf-8"))
    return {f["key"] for s in raw["soap"] if s["key"] == "o" for f in s["fields"]}


for _discipline in DISCIPLINES:
    _shared = _o_keys(_discipline, "initial") & _o_keys(_discipline, "reassessment")
    check(f"{_discipline} 首评与复评的 O 段共用 key（≥5 项，实际 {len(_shared)}）", len(_shared) >= 5)
check("PT 的首评/复评共用肌力与平衡等关键项（mmt_upper / mmt_lower / sit_balance）",
      {"mmt_upper", "mmt_lower", "sit_balance"}
      <= (_o_keys("PT", "initial") & _o_keys("PT", "reassessment")))
check("出院小结里声明了自动汇总字段（auto: latest_vs_initial）",
      any(f.get("auto") == "latest_vs_initial"
          for _discipline in DISCIPLINES
          for s in json.loads(
              (TEMPLATES_DIR / _discipline / "discharge.json").read_text(encoding="utf-8")
          )["soap"] for f in s["fields"]))
check("出院小结的自动汇总确实按 O 段共用 key 做「首评 → 本次」对比",
      'field.get("auto") != "latest_vs_initial"' in RECORDS_SERVICE_PY
      and 's.get("key") == "o"' in RECORDS_SERVICE_PY)
check("设计.md 写明首评与复评的 O 段共用 key 是出院小结自动汇总的前提",
      "共用" in DESIGN and "latest_vs_initial" in DESIGN)

# --------------------------------------------------------------------------- #
# 5. record_template.py 的关键 API 与业务规则
# --------------------------------------------------------------------------- #
for _api in ("counts_as_session", "kind_for_seq", "next_session_gate", "assessment_span_seq",
             "render", "apply_prefill", "validate_answers", "sessions_until_reassessment",
             "blank_answers", "load", "load_disciplines"):
    check(f"record_template.py 提供 {_api}()", f"def {_api}(" in RECORD_TEMPLATE_PY)
check("只有 daily 计入治疗次数（counts_as_session 的语义）",
      'return kind == "daily"' in RECORD_TEMPLATE_PY)
check("复评周期写死为 20（REASSESS_EVERY = 20）", "REASSESS_EVERY = 20" in RECORD_TEMPLATE_PY)
check("kind_for_seq 的语义：第 1 次→首评、第 21/41/61…→复评、其余→日常",
      "(seq_no - 1) % REASSESS_EVERY == 0" in RECORD_TEMPLATE_PY)
check("首评挂 1、复评挂 21/41/61…（assessment_span_seq）",
      "((seq_no - 1) // REASSESS_EVERY) * REASSESS_EVERY + 1" in RECORD_TEMPLATE_PY)
check("next_session_gate 是硬阻断的唯一实现（缺评估文书 → 返回该形态）",
      "return None if has_initial else \"initial\"" in RECORD_TEMPLATE_PY
      and "assessment_span_seq(next_seq) in spans" in RECORD_TEMPLATE_PY)
check("渲染器是「段名 + 冒号 + ；连接」而不是表格",
      'lines.append(section["heading"] + "：" + SEP_INLINE.join' in RECORD_TEMPLATE_PY)
check("多选值用 / 连接、字段用 ；连接",
      'SEP_INLINE = "；"' in RECORD_TEMPLATE_PY and 'SEP_MULTI = "/"' in RECORD_TEMPLATE_PY)
check("没填的字段整条不出现（render_value 返回 None 就被跳过）",
      "def render_value(" in RECORD_TEMPLATE_PY and "if text:" in RECORD_TEMPLATE_PY)
check("整段都没填就整段不出现", "if not rendered:" in RECORD_TEMPLATE_PY)
check("评估文书不显示序号（否则「出院小结 第 21 次」会误导）",
      "counts_as_session(template.kind)" in RECORD_TEMPLATE_PY)
check("模板只从 JSON 文件加载，不查数据库",
      "_load_json(template_path(" in RECORD_TEMPLATE_PY
      and "import sqlite3" not in RECORD_TEMPLATE_PY)

# 模型层的三条硬阻断 + 同日至多 2 条 + 必填 422
check("缺评估文书 → 409 MISSING_ASSESSMENT",
      'code="MISSING_ASSESSMENT"' in TREATMENT_PY and '"missing_document"' in TREATMENT_PY)
check("待出院患者不能再记新记录 → 409 PATIENT_PENDING_DISCHARGE",
      'code="PATIENT_PENDING_DISCHARGE"' in TREATMENT_PY)
check("同一天同一大类至多 2 条（MAX_SAME_DAY_RECORDS = 2）",
      "MAX_SAME_DAY_RECORDS = 2" in TREATMENT_PY)
check("必填缺失 → 422（Invalid「必填项缺失」）",
      "必填项缺失" in TREATMENT_PY and "validate_answers" in TREATMENT_PY)
check("设计.md 写明三条硬阻断都不能跳过（含用户原话）",
      "不能跳过" in DESIGN and "1A。2不能。3不能。" in DESIGN)
check("设计.md 写明评估文书不占用日常训练次数",
      "不占用日常训练的次数" in DESIGN)
check("设计.md 写明每 20 次日常后复评", "每 20 次" in DESIGN)
check("设计.md 写明四大类分开记录及其理由",
      "四大类" in DESIGN and "不同的治疗师" in DESIGN)
check("设计.md 写明 rendered_text 冻结保存",
      "rendered_text" in DESIGN and "冻结" in DESIGN)
check("设计.md 写明输出不要表格、多日按时间顺序往下排",
      "不要表格" in DESIGN and "按时间顺序" in DESIGN)
check("设计.md 写明 SOAP 排版规则（；连接、/ 连接、没填的字段不出现）",
      "没填的字段" in DESIGN and "用 `；` 连接" in DESIGN)

# --------------------------------------------------------------------------- #
# 6. 接口：直接数注册的路由，与文档对账
# --------------------------------------------------------------------------- #
sys.path.insert(0, str(ROOT / "backend"))
try:
    from app.api.v1 import api_router as _api_router  # noqa: E402

    _operations = [r for r in _api_router.routes if getattr(r, "methods", None)]
    _paths = {r.path for r in _operations}
    check(f"README 接口数与路由注册数一致（{len(_operations)} 个操作 / {len(_paths)} 个路径）",
          f"{len(_operations)} 个接口" in README)
    check(f"设计.md 也写了接口总数（{len(_operations)} 个操作 / {len(_paths)} 个路径）",
          f"{len(_operations)} 个操作" in DESIGN and f"{len(_paths)} 个路径" in DESIGN)
    check(f"开发计划.md 也写了接口总数（{len(_operations)} 个操作 / {len(_paths)} 个路径）",
          f"{len(_operations)} 个操作" in PLAN and f"{len(_paths)} 个路径" in PLAN)
    check("记录页的唯一数据源 GET /records/form 在册",
          any(r.path == "/records/form" for r in _operations))
    check("三个出院接口都在册",
          {"/patients/{inpatient_no}/discharge", "/patients/{inpatient_no}/discharge/confirm",
           "/patients/{inpatient_no}/discharge/cancel"} <= _paths)
    _leftover = [p for p in _paths
                 if "/dict" in p or "option-sets" in p or "response-defs" in p or "templates" in p]
    check("已删的四组接口都不在册（/dict、/option-sets、/response-defs、/templates）", not _leftover)
except Exception as exc:  # pragma: no cover - 只在环境缺依赖时触发
    check(f"接口数可核对（导入 app.api.v1 失败，请用系统 Python 3.13 运行）：{exc!r}", False)

_create_request = RECORDS_SCHEMA_PY.split("class RecordCreateRequest", 1)[1].split("class ", 1)[0]
check("POST /records 的请求体用 body（{field_key: value}）而不是 items",
      "body: dict[str, Any]" in _create_request and "items" not in _create_request)
check("RecordCreateRequest 带 discipline 与 kind",
      "discipline: str = Field(" in _create_request and "kind: str = Field(" in _create_request)
check("记录列表/时间轴的 scope=temp 已删除（只留 mine / visible）",
      '"mine", "visible"' in RECORDS_PY and 'scope == "temp"' not in RECORDS_PY
      and "mine / visible" in RECORDS_PY)
check("patient.py 的 Scope 仍不含 temp",
      'Scope = Literal["mine", "unassigned", "all", "visible", "dept"]' in PATIENT_PY)
check("出院接口用 CurrentUser（任何治疗师可发起），确认/取消用 AdminUser",
      "def request_discharge(" in PATIENTS_PY and "user: CurrentUser" in PATIENTS_PY
      and "admin: AdminUser" in PATIENTS_PY)
check("设计.md 写明权限口径变更（治疗师可发起出院）",
      "治疗师可发起" in DESIGN)
check("设计.md 写明出院流程（管理员确认或满 7 天自动出院）",
      "管理员确认" in DESIGN and "自动出院" in DESIGN)

# --------------------------------------------------------------------------- #
# 7. 阶段 4：离线同步支撑
# --------------------------------------------------------------------------- #
for _table in ("patient", "treatment_record"):
    check(f"同步：{_table} 有 client_uuid",
          f"ALTER TABLE {_table} ADD COLUMN client_uuid" in MIG004)
check("同步：唯一索引带 WHERE client_uuid IS NOT NULL", "WHERE client_uuid IS NOT NULL" in MIG004)
check("同步：允许离线写的实体只剩治疗记录",
      'PUSHABLE_ENTITIES = ("treatment_record",)' in SYNC_PY)
check("同步：可拉取实体为 patient + treatment_record",
      'PULLABLE_ENTITIES = ("patient", "treatment_record")' in SYNC_PY)
check("同步：冲突策略含草稿客户端优先",
      'CLIENT_WINS_ENTITIES = ("treatment_record",)' in SYNC_PY)
check("同步：推送入口直接调用模型层 create_record（离线不是后门）",
      "treatment_model.create_record(" in SYNC_PY and "def _push_treatment_record(" in SYNC_PY)
check("sync-protocol.md 与代码一致（可推送实体）",
      'PUSHABLE_ENTITIES = ("treatment_record",)' in SYNC_DOC)
check("sync-protocol.md 与代码一致（可拉取实体）",
      'PULLABLE_ENTITIES = ("patient", "treatment_record")' in SYNC_DOC)
check("sync-protocol.md 写明离线 payload 用 body", "`body`" in SYNC_DOC)
check("sync-protocol.md 写明硬阻断在离线推送时同样生效（服务端会拒）",
      "硬阻断" in SYNC_DOC and "MISSING_ASSESSMENT" in SYNC_DOC)
check("设计.md 提到游标为 change_log", "change_log" in DESIGN)
check("设计.md 写明一期离线可写只有治疗记录",
      "治疗记录" in DESIGN and "允许离线写的实体" in DESIGN)

# --------------------------------------------------------------------------- #
# 8. 阶段 5：打印、汇总与后台（SOAP 纯文本口径）
# --------------------------------------------------------------------------- #
check("打印：使用内置 CID 中文字体", "UnicodeCIDFont" in PDF_PY and "STSong-Light" in PDF_PY)
check("设计.md 的 PDF 方案与实现一致", "STSong-Light" in DESIGN and "reportlab" in DESIGN)
check("设计.md 已标注 WeasyPrint 被推翻", "WeasyPrint" in DESIGN and "推翻" in DESIGN)
check("打印：抬头含科室名", "DEFAULT_DEPT_NAME" in PDF_PY)
check("打印：页脚含页码", "第 {canvas.getPageNumber()} 页" in PDF_PY)
check("打印：页脚含打印时间", "打印时间：" in PDF_PY)
check("打印：不绘制签名栏（Q10）",
      not any(marker in PDF_PY for marker in (
          'drawString(0, 0, "签名', 'drawString(0, 0, "患者签字', '"签名："', "'签名：'")))
check("设计.md Q10 明确不做签名栏", "签名栏" in DESIGN and "**无**" in DESIGN)
check("打印：正文用冻结的 rendered_text（不是表格）",
      "rendered_text" in PDF_PY and "_soap_paragraph" in PDF_PY)
check("打印：多日按时间顺序连排、不分页、不一天一张",
      'sorted(daily["days"], key=lambda d: str(d["record_date"]))' in PDF_PY
      and "KeepTogether" in PDF_PY)
check("设计.md 写明 SOAP 纯文本输出与多日连排",
      "SOAP 纯文本" in DESIGN and "时间顺序" in DESIGN)
check("汇总：只统计已提交与已锁定", 'COUNTED_STATUSES = ("submitted", "locked")' in SUMMARY_PY)
check("汇总：计入次数的形态只有日常记录", 'COUNTED_KINDS = ("daily",)' in SUMMARY_PY)
check("汇总：内容一律用冻结的 rendered_text",
      '"rendered_text": str(row.get("rendered_text") or "")' in SUMMARY_PY)
check("设计.md 三种汇总口径都在",
      all(k in DESIGN for k in ("按日期汇总", "按患者每日汇总", "单个患者汇总打印")))
for _endpoint in ("/summary/date", "/summary/patient/{inpatient_no}",
                  "/print/patient/{inpatient_no}", "/print/summary/date",
                  "/print/summary/patient/{inpatient_no}", "/audit-logs"):
    check(f"设计.md 列出接口 {_endpoint}", _endpoint in DESIGN)

check("is_temporary 改为查询时推导（temporary_expr）",
      "def temporary_expr(" in TREATMENT_PY and "AS is_temporary" in TREATMENT_PY)
check("查询里真的用上了 temporary_expr", TREATMENT_PY.count("temporary_expr(") >= 3)
check("is_temporary 记录级标记仍保留，三个消费方都在（PDF / 汇总 / 后台列表）",
      "def temporary_expr(" in TREATMENT_PY
      and '"（临时）"' in PDF_PY
      and '"temporary"' in SUMMARY_PY
      and "is_temporary" in ADMIN_RECORDS_TSX)
check("设计.md 写明 is_temporary 按记录创建时刻的归属推导",
      "记录创建时刻" in DESIGN and "is_temporary" in DESIGN)
check("app 时间轴枚举已删除 temp（只留 visible / mine）",
      "enum TimelineScope {" in APP_TIMELINE_PROVIDERS
      and "temp(" not in APP_TIMELINE_PROVIDERS
      and "'mine'" in APP_TIMELINE_PROVIDERS)

# --------------------------------------------------------------------------- #
# 9. 患者列表排序（只算 kind='daily' 的已提交记录）
# --------------------------------------------------------------------------- #
check("patient.py 患者列表 JOIN 了 v_patient_last_treated",
      "LEFT JOIN v_patient_last_treated" in PATIENT_PY)
check("patient.py 组内按我最近一次治疗日期降序",
      "COALESCE(l.last_date, '0000-01-01') DESC" in PATIENT_PY)
check("patient.py 保留归属分组（我的 → 未分配 → 其他）",
      "WHEN v.visible_therapist_id = ? THEN 0" in PATIENT_PY
      and "WHEN v.visible_therapist_id IS NULL THEN 1 ELSE 2 END" in PATIENT_PY)
check("排序只算已提交（视图 WHERE status = 'submitted'）",
      "status = 'submitted'" in MIG011 and "status = 'submitted'" not in PATIENT_PY)
check("设计.md 写明组内排序依据（我最近一次已提交治疗）",
      "我最近一次已提交治疗" in DESIGN)
check("设计.md 写明草稿不参与排序", "草稿不算" in DESIGN)
check("设计.md 写明评估文书不参与排序（只算日常记录）",
      "只算日常" in DESIGN or "kind='daily'" in DESIGN)
check("归属判定死函数 covers_patient / can_schedule 均已删除",
      "def covers_patient(" not in PATIENT_PY
      and "def can_schedule(" not in PATIENT_PY
      and "CREATE VIEW v_patient_visibility" in PATIENT_PY
      and "def visibility_from(" in PATIENT_PY)
_COVERS_PATIENT_FILES = [
    name
    for name, text in (("设计.md", DESIGN), ("README.md", README), ("开发计划.md", PLAN))
    if "covers_patient" in text
]
check("设计.md / README.md / 开发计划.md 不得出现已删除的 covers_patient"
      + (f"：命中 {'、'.join(_COVERS_PATIENT_FILES)}" if _COVERS_PATIENT_FILES else ""),
      not _COVERS_PATIENT_FILES)
check("设计.md 不再把两条半日不变量当现行规则",
      not [line for line in DESIGN.splitlines()
           if ("治疗师半日" in line or "患者半日" in line)
           and not any(m in line for m in DEPRECATED_MARKERS)])

# --------------------------------------------------------------------------- #
# 10. DEPRECATED_TOKENS：已删概念不得作为现行设计出现
# --------------------------------------------------------------------------- #
_no_deprecated("设计.md", DESIGN)
_no_deprecated("开发计划.md", PLAN)
_no_deprecated("README.md", README)
_no_deprecated("docs/setup.md", SETUP)
_no_deprecated("app/README.md", APP_README)
_no_deprecated("admin/README.md", ADMIN_README)
_no_deprecated("docs/sync-protocol.md", SYNC_DOC)
check("sync-protocol.md 不再把排期 / 临时指派当现行同步通道",
      not deprecated_lines(SYNC_DOC, ("appointment", "/rest-blocks", "/leave",
                                      "temporary_assignment", "v_open_temporary_assignment")))
check("admin/README.md 不再把排期页 / 请假页当现行模块",
      not deprecated_lines(ADMIN_README, ("/schedule", "/leave")))

# --------------------------------------------------------------------------- #
# 11. 环境认知与时间约定
# --------------------------------------------------------------------------- #
for _tag, _sql in (("001", MIG001), ("002", MIG002)):
    check(f"{_tag} 无 localtime 用法", not [
        line for line in _sql.splitlines()
        if "'localtime'" in line and not line.strip().startswith("--")
    ])
    check(f"{_tag} 用 UTC 毫秒时间戳", "%Y-%m-%dT%H:%M:%fZ" in _sql)
check("002 不含 IS NOT 不等式", not [
    line for line in MIG002.splitlines()
    if re.search(r"\bIS NOT\b", line) and not line.strip().startswith("--")
])
check("002 使用 COALESCE", "COALESCE" in MIG002)
for _value in ("06:00", "11:30", "13:00", "17:30"):
    check(f"config.py 作息 {_value}", _value in CONFIG)
    check(f"设计.md 作息 {_value}", _value in DESIGN)
check("README 作息", "06:00" in README)
check("CHANGELOG 作息", "06:00" in CHANGELOG)
check("setup.md 写明系统 Python 3.13", "Python313" in SETUP)
check("setup.md 警告不要用 dsh Python", "dsh-primary-runtime" in SETUP)
check("setup.md 写明 app.cli seed 已废弃", "app.cli seed" in SETUP and "废弃" in SETUP)
check("README 写明 app.cli seed 已废弃", "app.cli seed" in README and "废弃" in README)

# --------------------------------------------------------------------------- #
# 12. 文档版本、CHANGELOG 与本次 SOAP 改造的留痕
# --------------------------------------------------------------------------- #
check("设计.md 头部 V1.4", "**版本**：V1.4" in DESIGN)
check("设计.md 结尾 V1.4", "**文档版本**：V1.4" in DESIGN)
check("设计.md 无 V1.2 头部", "**版本**：V1.2" not in DESIGN)
check("设计.md 有 3.6 记录模板（JSON）与 SOAP 输出一节",
      "### 3.6 记录模板（JSON）与 SOAP 输出" in DESIGN)
check("设计.md 无中文状态枚举残留", "在院、出院、暂停治疗" not in DESIGN)
check("设计.md 说明了排期为何下线（排班不是本系统的职责）",
      "排班不是本系统的职责" in DESIGN)
check("开发计划.md 升到 V0.8", "V0.8" in PLAN)
check("README 声明 V1.4", "V1.4" in README)
check("README 引用 app.cli", "app.cli" in README)

_changelog_headings = [line for line in CHANGELOG.splitlines() if line.startswith("### ")]
check("CHANGELOG 段落唯一", len(_changelog_headings) == len(set(_changelog_headings)))
check("CHANGELOG 无过期待办声明", "尚未执行" not in CHANGELOG)
check("CHANGELOG 已登记「取消排期功能」决策", "取消排期功能" in CHANGELOG)
check("CHANGELOG 已登记「治疗记录改为 SOAP 模板驱动」决策", "SOAP 模板驱动" in CHANGELOG)
check("CHANGELOG 记录了用户的原始理由（太过于繁琐 / 不进数据库）",
      "太过于繁琐" in CHANGELOG and "不进数据库" in CHANGELOG)
check("CHANGELOG 记录了「避免现有的表格方式」", "避免现有的表格方式" in CHANGELOG)
check("CHANGELOG 记录了四大类分开记录的理由（不同的治疗师操作）",
      "不同的治疗师操作" in CHANGELOG)
check("CHANGELOG 记录了评估不占次数的纠正（用户原话）",
      "评定并不占用日常训练的次数" in CHANGELOG)
check("CHANGELOG 记录了硬阻断的用户原话（1A。2不能。3不能。）",
      "1A。2不能。3不能。" in CHANGELOG)
check("CHANGELOG 记录了出院流程与权限口径变更",
      "pending_discharge" in CHANGELOG and "权限口径" in CHANGELOG
      and "防止患者突然取消出院意愿" in CHANGELOG)
check("CHANGELOG 记录了代价：后端测试 454 → 334",
      "454" in CHANGELOG and "334" in CHANGELOG)
check("CHANGELOG 记录了代价：迁移变成 13 个、末个 013_patient_pending_discharge.sql",
      "013_patient_pending_discharge.sql" in CHANGELOG and "13" in CHANGELOG)
check("CHANGELOG 记录了代价：有效表 17 → 8 张",
      "8 张" in CHANGELOG and ("17 → 8" in CHANGELOG or "17→8" in CHANGELOG))
check("CHANGELOG 记录了代价：安卓端需重写 / 待适配",
      "安卓" in CHANGELOG and ("重写" in CHANGELOG or "待适配" in CHANGELOG))
check("CHANGELOG 记录了删除范围（后端 + 管理后台 + 安卓）",
      all(k in CHANGELOG for k in ("管理后台", "安卓")))
check("CHANGELOG 记录了上次的代价（验收项数下降 + 阶段 2 作废）",
      "验收项数" in CHANGELOG and "阶段 2 作废" in CHANGELOG)
check("CHANGELOG 的移除清单含九张旧模型的表",
      all(t in CHANGELOG for t in DROPPED_OLD_TABLES))

# --------------------------------------------------------------------------- #
# 13. 安卓端与管理后台（页签 3 个、Drift 版本、模块清单）
# --------------------------------------------------------------------------- #
check("Drift schemaVersion 已升到 5（v5 治疗记录改 SOAP 模板驱动）",
      "schemaVersion => 5" in APP_DB)
# v5：本地记录表重建（旧行是「主项目+子项目+参数」，新模型是「大类+形态+body」，
# 两者没有可计算的映射 → 直接丢弃；服务端已清空重建，用户已确认「清掉重来」）。
check("Drift v5 重建 treatment_records 并删掉 record_items 表",
      "deleteTable('treatment_records')" in APP_DB
      and "createTable(treatmentRecords)" in APP_DB
      and "deleteTable('record_items')" in APP_DB)
check("Drift 不再定义 RecordItems 表", "class RecordItems" not in APP_TABLES)
check("Drift 迁移删掉 appointments 表", "deleteTable('appointments')" in APP_DB)
check("Drift 迁移去掉 treatment_records.appointment_id",
      "dropColumn(treatmentRecords, 'appointment_id')" in APP_DB)
check("Drift 迁移删掉 patients.visibility_state",
      "dropColumn(patients, 'visibility_state')" in APP_DB)
check("Drift 不再定义 Patients.visibilityState", "visibilityState" not in APP_TABLES)
check("Drift 不再定义 Appointments 表", "class Appointments" not in APP_TABLES)
check("App 页签为 3 个（患者 / 时间轴 / 我的）",
      APP_HOME.count("NavigationDestination(") == 3
      and all(k in APP_HOME for k in ("'患者'", "'时间轴'", "'我的'")))
check("PDF 导出为三种去向（发送给微信 / 系统打印 / 打开）",
      all(k in APP_PDF for k in ("'share'", "'print'", "'open'")))
check("app/README.md 写明页签 3 个", "页签" in APP_README and "3 个" in APP_README)
check("app/README.md 写明 PDF 三种去向",
      all(k in APP_README for k in ("发送给微信", "系统打印", "打开")))
check("app/README.md 写明记录页取 /records/form（SOAP 模板驱动）",
      "/records/form" in APP_README and "`body`" in APP_README)
check("app/README.md 写明安卓端**已适配** SOAP 记录页（不能再写『待适配』）",
      "已适配" in APP_README and "待适配" not in APP_README)
check("app/README.md 不再描述排期页/排期表",
      not [line for line in APP_README.splitlines()
           if any(t in line for t in ("排期", "schedule", "appointment"))
           and not any(m in line for m in DEPRECATED_MARKERS)])

for _route in ADMIN_MODULE_ROUTES:
    check(f"admin 路由表有 {_route}", f'path="{_route.lstrip("/")}"' in ADMIN_ROUTES)
    check(f"admin/README.md 列出模块 {_route}", f"`{_route}`" in ADMIN_README)
check("admin/README.md 写明排期/请假页已删除",
      "下线" in ADMIN_README or "删除" in ADMIN_README)
check("admin/README.md 写明记录页展示 SOAP 文本",
      "rendered_text" in ADMIN_README or "SOAP" in ADMIN_README)

# --------------------------------------------------------------------------- #
# 14. 验收项数：文档里的数字必须与脚本里的 check() 条数对得上
# --------------------------------------------------------------------------- #
import count_verify_checks  # noqa: E402

_counts = count_verify_checks.count_all()
_doc_counts = {name: int(n) for name, n in re.findall(r"(verify_\w+\.py).*?（(\d+) 项）", SETUP)}
check("setup.md 逐个列出 6 个验收脚本的项数", set(_doc_counts) == set(_counts))
for name, count in sorted(_counts.items()):
    check(f"setup.md 的 {name} 项数与脚本一致（{count} 项）", _doc_counts.get(name) == count)
check("setup.md 的端到端项数等于各脚本之和",
      f"端到端 {sum(_counts.values())} 项" in SETUP)
check("README 与 setup.md 的端到端项数一致", f"端到端 {sum(_counts.values())} 项" in README)
check("开发计划.md 的端到端项数与脚本一致",
      f"{sum(_counts.values())} 项端到端检查" in PLAN)

# --------------------------------------------------------------------------- #
# 15. 本脚本自报的项数也要和文档对得上（放在最后，因为要用最终 total）
# --------------------------------------------------------------------------- #
_expected_total = total + 1  # 下面这次 check 本身也计入
check(f"README 记录的跨文档校验项数与本脚本一致（{_expected_total} 项）",
      f"跨文档校验 {_expected_total} 项" in README)

# ⚠ 失败汇总行要打印**包含最后那次自校验**的项数（此时 `check()` 已被调用过），
# 否则会出现"检查 231 项，1 项失败"而实际跑了 232 项 —— 自己把自己的项数说少一项，
# 与本文件要解决的"文档数字与实现漂移"是同一类毛病。
if failures:
    print(f"检查 {total} 项，{len(failures)} 项失败：")
    for failure in failures:
        print(f"  - {failure}")
    sys.exit(1)
print(f"检查 {total} 项，全部一致（0 失败）。")
