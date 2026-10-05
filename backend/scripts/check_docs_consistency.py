"""跨文档一致性校验（可重复运行）。检查设计.md / CHANGELOG.md / README.md 与代码实现是否一致。

## 2026-10-05：排期功能整体下线，本脚本的断言逐条换了对象

科室确认**排班不是本系统的职责**（理由与代价见 `CHANGELOG.md` 的决策条目），
因此 `appointment` / `rest_block` / `leave_record` 三张表、`v_patient_next_appointment`
视图、`is_temporary` 等存储列与全部排期接口一并删除，患者列表排序从
"下一个排期"改为"我最近一次已提交治疗"。

本脚本**没有把断言删空，而是逐条换成新实现的等价断言**：

| 旧断言 | 新断言 |
|---|---|
| 表清单里有 `appointment` / `rest_block` / `leave_record` | 008 必须删掉这三张表，且**不删** `temporary_assignment` |
| 视图 `v_patient_next_appointment` | 视图 `v_patient_last_treated`（只统计 `submitted`） |
| `treatment_record` 的 `is_temporary` / `appointment_id` 列 | 三列已删；`is_temporary` 改为查询时推导 |
| "设计.md 两条半日不变量" | 这两条不变量在文档里**不得再作为现行规则**出现 |
| —— | **新增**：`设计.md` / `README.md` / `开发计划.md` 里**不得出现**已删死代码 `covers_patient`（连"已删除"留痕也不写名字 —— 按"标记行"放行的旧断言抓不住"直接当现行函数写"的漂移） |
| 接口数 / 待办数字 | 直接数路由注册与验收脚本，与文档里的数字对账 |

`DEPRECATED_TOKENS` 是"已下线功能"的守门人：这些词**只允许**出现在
"已删除 / 已下线 / 曾如此"这类说明行里，不允许作为现行设计再次出现。
`temporary_assignment` **不在**这些词里 —— 它是归属解析的一部分，没有被删。
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

CONFIG = (ROOT / "backend/app/core/config.py").read_text(encoding="utf-8")
SYNC_PY = (ROOT / "backend/app/services/sync.py").read_text(encoding="utf-8")
SUMMARY_PY = (ROOT / "backend/app/services/summary.py").read_text(encoding="utf-8")
PDF_PY = (ROOT / "backend/app/services/pdf.py").read_text(encoding="utf-8")
TREATMENT_PY = (ROOT / "backend/app/models/treatment.py").read_text(encoding="utf-8")
PATIENT_PY = (ROOT / "backend/app/models/patient.py").read_text(encoding="utf-8")

APP_DB = (ROOT / "app/lib/data/local/app_database.dart").read_text(encoding="utf-8")
APP_TABLES = (ROOT / "app/lib/data/local/tables.dart").read_text(encoding="utf-8")
APP_HOME = (ROOT / "app/lib/features/home/home_shell.dart").read_text(encoding="utf-8")
APP_PDF = (ROOT / "app/lib/features/timeline/pdf_export.dart").read_text(encoding="utf-8")

ADMIN_README = (ROOT / "admin" / "README.md").read_text(encoding="utf-8")
ADMIN_ROUTES = (ROOT / "admin" / "src" / "routes.tsx").read_text(encoding="utf-8")
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
    "temporary_assignment", "main_item", "sub_item", "sub_item_param_def",
    "option_set", "option_item", "response_def", "record_template", "record_template_item",
    "treatment_record", "record_item", "audit_log", "change_log",
]:
    check(f"表 {t}", t in tables)

# 008 是"排期下线"的唯一落点：三张表都要删，temporary_assignment 必须留下
for t in ("appointment", "rest_block", "leave_record"):
    check(f"008 删除表 {t}", f"DROP TABLE IF EXISTS {t};" in MIG008)
check("008 不删 temporary_assignment（归属解析，与请假无关）",
      "DROP TABLE IF EXISTS temporary_assignment" not in MIG008)
_dropped = set(re.findall(r"DROP TABLE IF EXISTS (\w+)", MIG008))
_effective_tables = tables - _dropped
check("有效表集合里没有排期/休息块/请假",
      not (_effective_tables & {"appointment", "rest_block", "leave_record"}))
check("有效表集合里仍有 temporary_assignment", "temporary_assignment" in _effective_tables)
check("008 清掉 appointment 的历史同步游标",
      "DELETE FROM change_log WHERE entity = 'appointment'" in MIG008)
check("006 已删除 ux_appt_therapist_slot（治疗师半日唯一，S1 放开）",
      "DROP INDEX IF EXISTS ux_appt_therapist_slot" in MIG006)
check("006 已删除 ux_appt_patient_slot（患者半日唯一，放弃 Q2）",
      "DROP INDEX IF EXISTS ux_appt_patient_slot" in MIG006)
check("唯一索引 ux_temp_assign_open 仍在（临时指派与排期无关）",
      "ux_temp_assign_open" in MIG001)

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

# 视图：旧的排期视图必须消失，新的"我最近一次已提交治疗"必须在文档与迁移里同时出现
check("视图 v_patient_last_treated（007 新建）",
      "CREATE VIEW v_patient_last_treated" in MIG007 and "v_patient_last_treated" in DESIGN)
check("007 的 v_patient_last_treated 只统计 submitted",
      "WHERE r.status = 'submitted'" in MIG007)
check("007 按 (patient_no, therapist_id) 分组",
      "GROUP BY r.patient_no, r.therapist_id" in MIG007)
check("008 重建视图时与 007 定义一致（同样只统计 submitted）",
      "WHERE r.status = 'submitted'" in MIG008)
check("视图 v_open_temporary_assignment",
      "CREATE VIEW v_open_temporary_assignment" in MIG001
      and "v_open_temporary_assignment" in DESIGN)

for label, values in {
    "patient.status": ["in_hospital", "discharged", "paused"],
    "period": ["'am'", "'pm'"],
    "temp status": ["'open'", "'closed'", "'converted'"],
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
check("sync-protocol.md 不再把 appointment 当同步通道",
      not deprecated_lines(SYNC_DOC, ("appointment", "/rest-blocks", "/leave")))

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
check("Drift schemaVersion 已升到 3", "schemaVersion => 3" in APP_DB)
check("Drift 迁移删掉 appointments 表", "deleteTable('appointments')" in APP_DB)
check("Drift 迁移去掉 treatment_records.appointment_id",
      "dropColumn(treatmentRecords, 'appointment_id')" in APP_DB)
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

if failures:
    print(f"检查 {total} 项，{len(failures)} 项失败：")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print(f"检查 {total} 项，全部一致（0 失败）。")
