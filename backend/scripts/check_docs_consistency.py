"""跨文档一致性校验（可重复运行）。检查设计.md / CHANGELOG.md / README.md 与代码实现是否一致。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # backend/scripts/ -> 仓库根
DESIGN = (ROOT / "设计.md").read_text(encoding="utf-8")
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
MIG001 = (ROOT / "backend/app/db/migrations/001_initial_schema.sql").read_text(encoding="utf-8")
MIG002 = (ROOT / "backend/app/db/migrations/002_triggers.sql").read_text(encoding="utf-8")
MIG004 = (ROOT / "backend/app/db/migrations/004_sync_support.sql").read_text(encoding="utf-8")
CONFIG = (ROOT / "backend/app/core/config.py").read_text(encoding="utf-8")

failures: list[str] = []
total = 0


def check(name: str, ok: bool) -> None:
    global total
    total += 1
    if not ok:
        failures.append(name)


tables = set(re.findall(r"CREATE TABLE (\w+)", MIG001))
for t in [
    "user", "auth_session", "patient", "patient_assignment_history", "appointment", "rest_block",
    "leave_record", "temporary_assignment", "main_item", "sub_item", "sub_item_param_def",
    "option_set", "option_item", "response_def", "record_template", "record_template_item",
    "treatment_record", "record_item", "audit_log", "change_log",
]:
    check(f"表 {t}", t in tables)

for v in ["v_patient_next_appointment", "v_open_temporary_assignment"]:
    check(f"视图 {v}", v in MIG001 and v in DESIGN)

for label, values in {
    "patient.status": ["in_hospital", "discharged", "paused"],
    "period": ["'am'", "'pm'"],
    "leave_type": ["half_day_am", "half_day_pm", "full_day", "multi_day"],
    "source": ["therapist_self", "admin_entry"],
    "temp status": ["'open'", "'closed'", "'converted'"],
    "record status": ["'draft'", "'submitted'", "'locked'"],
    "scope": ["'global'", "'dept'", "'personal'"],
    "value_type": ["'tag'", "'number'", "'select'", "'text'"],
    "role": ["'therapist'", "'admin'"],
}.items():
    for v in values:
        check(f"迁移枚举 {label}={v}", v in MIG001)
        check(f"设计.md 枚举 {label}={v}", v.strip("'") in DESIGN)

for name in ("ux_appt_therapist_slot", "ux_appt_patient_slot"):
    check(f"唯一索引 {name}", name in MIG001)
check("设计.md 两条不变量", "治疗师半日" in DESIGN and "患者半日" in DESIGN)

# 阶段 4：离线同步支撑
for table in ("patient", "appointment", "treatment_record"):
    check(f"同步：{table} 有 client_uuid", f"ALTER TABLE {table} ADD COLUMN client_uuid" in MIG004)
check("同步：client_uuid 有唯一索引", "ux_record_client_uuid" in MIG004)
check("同步：唯一索引带 WHERE client_uuid IS NOT NULL", "WHERE client_uuid IS NOT NULL" in MIG004)
SYNC_PY = (ROOT / "backend/app/services/sync.py").read_text(encoding="utf-8")
check("同步：允许离线写的实体与设计一致", 'PUSHABLE_ENTITIES = ("treatment_record", "appointment")' in SYNC_PY)
check("同步：冲突策略含草稿客户端优先", 'CLIENT_WINS_ENTITIES = ("treatment_record",)' in SYNC_PY)
check("设计.md 提到游标为 change_log", "change_log" in DESIGN)

# 阶段 5：打印、汇总与后台
PDF_PY = (ROOT / "backend/app/services/pdf.py").read_text(encoding="utf-8")
SUMMARY_PY = (ROOT / "backend/app/services/summary.py").read_text(encoding="utf-8")
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

# 阶段 5 补种：四大高频模板（D04 / T3.2）
import json as _json  # noqa: E402

DICT_SEED = _json.loads((ROOT / "backend/seed/dict_seed.json").read_text(encoding="utf-8"))
MIG005 = (ROOT / "backend/app/db/migrations/005_template_code.sql").read_text(encoding="utf-8")
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

check("设计.md 头部 V1.2", "**版本**：V1.2" in DESIGN)
check("设计.md 结尾 V1.2", "**文档版本**：V1.2" in DESIGN)
check("设计.md 无 V1.1 头部", "**版本**：V1.1" not in DESIGN)
check("设计.md 无中文状态枚举残留", "在院、出院、暂停治疗" not in DESIGN)
# "拖拽改时间" 只允许出现在"我们不做"与"V1.1 曾如此"两类说明里，
# 不允许作为 3.4 的功能项被承诺。
_drag_ok = [
    line for line in DESIGN.splitlines()
    if "拖拽改时间" in line and ("不做" in line or "V1.1" in line)
]
_drag_all = [line for line in DESIGN.splitlines() if "拖拽改时间" in line]
check("设计.md 拖拽改时间仅作否定/历史说明", len(_drag_ok) == len(_drag_all) and bool(_drag_all))
check("设计.md 3.4.4 为半日格子视图", "半日格子视图" in DESIGN)

check("README 声明 V1.2", "V1.2" in README or "V1.3" in README)
check("README 引用 app.cli", "app.cli" in README)
_changelog_headings = [line for line in CHANGELOG.splitlines() if line.startswith("### ")]
check("CHANGELOG 段落唯一", len(_changelog_headings) == len(set(_changelog_headings)))
check("CHANGELOG 无过期待办声明", "尚未执行" not in CHANGELOG)

# PDF 方案必须已改写为 reportlab（V1.3 修订），不得再以 WeasyPrint 为落地方案
check("D03 已定为 reportlab", "reportlab" in DESIGN and "STSong-Light" in DESIGN)
check("开发计划 D03 已修订", "STSong-Light" in (ROOT / "开发计划.md").read_text(encoding="utf-8"))
_wp_lines = [
    line for line in DESIGN.splitlines()
    if "WeasyPrint" in line and ("定" in line or "选" in line or "必须" in line)
    and "推翻" not in line and "不必" not in line
]
check("设计.md 不再把 WeasyPrint 定为方案", not _wp_lines)

# 环境认知：必须写明用系统 Python 3.13，避免复现"探错解释器"的误判
SETUP = (ROOT / "docs" / "setup.md").read_text(encoding="utf-8")
check("setup.md 写明系统 Python 3.13", "Python313" in SETUP)
check("setup.md 警告不要用 dsh Python", "dsh-primary-runtime" in SETUP)

if failures:
    print(f"检查 {total} 项，{len(failures)} 项失败：")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print(f"检查 {total} 项，全部一致（0 失败）。")
