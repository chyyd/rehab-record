"""A 步验收：校验模板 + 实际渲染 SOAP 文本。

    cd backend
    python scripts/preview_record_templates.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import record_template as rt  # noqa: E402

OK = "  OK  "
BAD = "  FAIL"


def main() -> int:
    failures: list[str] = []

    print("=" * 78)
    print("一、模板校验")
    print("=" * 78)

    disciplines = rt.load_disciplines()
    print(f"  大类 {len(disciplines)} 个：" + "、".join(
        f"{d['name']}({d['key']}, {len(d['therapy_options'])} 项疗法)" for d in disciplines))

    all_t = rt.load_all()
    pending: list[str] = []
    for d in disciplines:
        key = d["key"]
        have = sorted(all_t.get(key, {}).keys())
        missing = [k for k in rt.KINDS if k not in have]
        line = f"  {d['name']:<6} 已有形态 {have}"
        if missing:
            # 缺形态**不算失败**：A 步的策略是先把「运动」一类做完整给你验收，
            # 确认字段设计与输出样子之后再复制到其余三类。
            line += f"   ← 待写 {missing}"
            pending.append(d["name"])
        print(line)
        # 真正要拦的是「写了一半」（部分形态存在、部分缺失）
        if have and missing:
            failures.append(f"{key} 只写了一半：有 {have}，缺 {missing}")

    # 逐份模板做结构校验
    for key, kinds in all_t.items():
        for kind, t in kinds.items():
            # s/o/a/p 各一次
            secs = [s["key"] for s in t.soap]
            if sorted(secs) != ["a", "o", "p", "s"]:
                failures.append(f"{key}/{kind} 的 SOAP 段不是 s/o/a/p 各一次：{secs}")
            # 字段 key 唯一
            keys = [f["key"] for f in t.all_fields()]
            dup = {k for k in keys if keys.count(k) > 1}
            if dup:
                failures.append(f"{key}/{kind} 字段 key 重复：{sorted(dup)}")
            # 选项非空
            for f in t.all_fields():
                if f["type"] in ("single", "multi") and not f.get("options") and not f.get("allow_other"):
                    failures.append(f"{key}/{kind}.{f['key']} 无选项")

    print()
    print("=" * 78)
    print("二、首评与复评的客观字段是否共用同一套 key（出院小结自动汇总的前提）")
    print("=" * 78)
    for d in disciplines:
        key = d["key"]
        kinds = all_t.get(key, {})
        if "initial" not in kinds or "reassessment" not in kinds:
            print(f"  {d['name']:<6} 暂缺模板，跳过")
            continue
        def okeys(t):
            for s in t.soap:
                if s["key"] == "o":
                    return {f["key"] for f in s["fields"]}
            return set()
        a, b = okeys(kinds["initial"]), okeys(kinds["reassessment"])
        both = sorted(a & b)
        print(f"  {d['name']:<6} 首评 O 段 {len(a)} 项 / 复评 O 段 {len(b)} 项 / 共用 {len(both)} 项")
        if len(both) < 3:
            failures.append(f"{key} 首评与复评的 O 段共用 key 太少（{len(both)}）—— 出院小结无法汇总")
        else:
            print(f"         共用：{'、'.join(both)}")

    print()
    print("=" * 78)
    print("三、触发规则")
    print("=" * 78)
    print("  ★ 只有日常记录计入次数：「评定并不占用日常训练的次数，第一次首评后，")
    print("    当天还是要有一个日常记录用来记录当天的训练。复评和出院小结也是。」")
    print()
    for kind in rt.KINDS:
        mark = "计入次数" if rt.counts_as_session(kind) else "不计次（独立文书）"
        print(f"  {kind:<13} {rt.KIND_LABELS[kind]:<8} {mark}")
    print()
    print("  复评周期：**30 个自然日**（用户 2026-10-06「也就是 1 个月评一次」）。")
    print("  锚点是**首评日**（唯一不动的时间原点），应做日 = 首评日 + 30 × k；")
    print("  补做晚了周期也不漂 —— 已复评过的格子跳过，下一个应做日仍是原来的格子。")
    print("  计量单位是「天」，不是「第几次日常」—— 次数只回答『这是第几次治疗』。")
    print()
    # 复评判定：锚点是**首评日**，应做日 = 首评日 + 30 天（再按 30 天逐格推进）
    base = "2026-11-01"
    due = rt.next_reassessment_due(base)
    mark = OK if str(due) == "2026-12-01" else BAD
    if str(due) != "2026-12-01":
        failures.append(f"next_reassessment_due({base}) = {due}，期望 2026-12-01")
    print(f"{mark} 首评 {base} → 复评应做日 {due}（+{rt.REASSESS_INTERVAL_DAYS} 天）")
    print()
    print("  距应做日    该填哪种形态")
    _date_cases = [
        ("2026-11-01", "daily", 30),
        ("2026-11-20", "daily", 11),
        ("2026-11-30", "daily", 1),
        ("2026-12-01", "reassessment", 0),
        ("2026-12-15", "reassessment", -14),
    ]
    for on, want, want_days in _date_cases:
        got = rt.reassessment_document_for(
            has_initial=True, initial_date=base, on_date=on
        )
        got_kind = rt.kind_for_date(
            has_initial=True, initial_date=base, on_date=on
        )
        days = rt.days_until_reassessment(base, on)
        mark = OK if got_kind == want and days == want_days else BAD
        if got_kind != want or days != want_days:
            failures.append(
                f"{on}: kind={got_kind}（期望 {want}）days={days}（期望 {want_days}）")
        label = "需补复评" if got else "只需日常记录"
        print(f"{mark} {on}  距应做日 {days:>4} 天 → {label}")

    # 周期不漂移：拖到应做日之后才补做，下一次应做日仍落在「首评日 + 30 × k」的格子上。
    # ★ 锚点是**首评日**（唯一不动的时间原点），不是"最近一次评估日" ——
    #   后者会越拖越漂（拖到第 35 天补做，下一次就变第 65 天）。
    #   已经做过复评的格子由 `done_dates` 标出，跳过它取下一格。
    _drift = rt.next_reassessment_due(
        "2026-01-01", done_dates=["2026-02-05"], on_date="2026-02-05"
    )
    mark = OK if str(_drift) == "2026-03-02" else BAD
    if str(_drift) != "2026-03-02":
        failures.append(
            f"晚 5 天补做后下一次应做日 = {_drift}，期望 2026-03-02（不能漂成 03-07）")
    print(f"{mark} 拖 5 天补做 → 下一次应做日 {_drift}（周期不漂移）")
    # 补过的那一格要**跳过**：01-31 这格已被 02-05 的复评覆盖，所以下一个是 03-02，不是 01-31
    _skip = rt.next_reassessment_due(
        "2026-01-01", done_dates=["2026-01-31"], on_date="2026-02-05"
    )
    mark = OK if str(_skip) == "2026-03-02" else BAD
    if str(_skip) != "2026-03-02":
        failures.append(
            f"补过 01-31 这格后下一个应做日 = {_skip}，期望 2026-03-02（已复评的格子要跳过）")
    print(f"{mark} 01-31 那格已补过 → 下一个应做日 {_skip}（已复评的格子跳过）")

    # 评估文书不得显示序号 —— 否则「出院小结 第 21 次」会被误读成第 21 次治疗记录
    print()
    _probe = rt.render(all_t["PT"]["discharge"], rt.blank_answers(all_t["PT"]["discharge"]),
                       record_date="2026-11-30", seq_no=21, total_sessions=21)
    if "第 21 次" in _probe:
        failures.append("出院小结不该显示「第 N 次」（评估文书不计次）")
    else:
        print(f"{OK} 出院小结不显示序号，只显示「共治疗 N 次」")
    _probe2 = rt.render(all_t["PT"]["initial"], rt.blank_answers(all_t["PT"]["initial"]),
                        record_date="2026-10-05", seq_no=1)
    if "第 1 次" in _probe2:
        failures.append("首评不该显示「第 N 次」（评估文书不计次）")
    else:
        print(f"{OK} 首评不显示序号")

    print()
    print("=" * 78)
    print("三点五、硬阻断门禁（用户 2026-10-05：「1A。2不能。3不能。」）")
    print("=" * 78)
    print("  点大类后先弹评估文书，填完才进当天的日常记录；三份文书都不能跳过。")
    print()
    print("  场景                                        还缺哪份文书")
    _gate_cases = [
        # (有无首评, 首评日, 本次记录日, 期望)
        (False, None, "2026-11-01", "initial"),
        (True, "2026-11-01", "2026-11-02", None),
        (True, "2026-11-01", "2026-11-30", None),
        (True, "2026-11-01", "2026-12-01", "reassessment"),
        (True, "2026-11-01", "2026-11-15", None),
        # 顺延：应做日那天没治疗，拖到 12-20 来记，仍然要求复评
        (True, "2026-11-01", "2026-12-20", "reassessment"),
    ]
    for has_initial, initial, on, want in _gate_cases:
        got = rt.reassessment_document_for(
            has_initial=has_initial, initial_date=initial, on_date=on
        )
        mark = OK if got == want else BAD
        if got != want:
            failures.append(
                f"reassessment_document_for(initial={has_initial}, 首评日={initial}, on={on})"
                f" = {got}，期望 {want}")
        desc = f"首评={has_initial} 首评日={initial or '—'} 本次={on}"
        print(f"{mark} {desc:<44} {got or '（可记）'}")

    # 已复评过的格子要跳过：12-01 这格补过之后，12-20 就不再要求复评（下一个是 12-31）
    _next_cell = rt.reassessment_document_for(
        has_initial=True, initial_date="2026-11-01",
        done_dates=["2026-12-01"], on_date="2026-12-20",
    )
    mark = OK if _next_cell is None else BAD
    if _next_cell is not None:
        failures.append(
            f"补过 12-01 这格后 12-20 仍要求 {_next_cell}，期望不要求（该格已复评）")
    print(f"{mark} {'补过 12-01 这格 → 12-20 不再要求复评':<44} {_next_cell or '（可记）'}")

    print()
    print("=" * 78)
    print("四、实际渲染（这才是『输出也用类似格式』的样子）")
    print("=" * 78)

    pt_initial = all_t["PT"]["initial"]
    pt_daily = all_t["PT"]["daily"]
    pt_reassess = all_t["PT"]["reassessment"]
    pt_discharge = all_t["PT"]["discharge"]

    # ---- 首评 ----
    a = rt.blank_answers(pt_initial)
    a.update({
        "complaint": ["肢体无力", "活动费力"],
        "vas": 3,
        "premorbid": "基本自理",
        "compliance": "配合良好",
        "expectation": ["恢复室内步行", "降低跌倒风险"],
        "consciousness": "清楚",
        "affected_side": "左侧",
        "mmt_upper": 2, "mmt_lower": 3,
        "ashworth": "1+级", "rom": "轻度受限",
        "sit_balance": "Ⅱ级", "stand_balance": "Ⅰ级",
        "transfer": "部分辅助", "gait": "辅助步行",
        "fall_risk": "高风险", "vital_signs": "平稳",
        "diagnosis": ["偏瘫运动功能障碍", "平衡功能障碍"],
        "impairment": "中度受损",
        "core_problem": ["肌力不足", "患侧负重不足"],
        "potential": "良好",
        "goal_long": "出院可独立室内短距离步行，自主完成床椅转移，跌倒风险降至低风险",
        "goal_short": "坐位平衡达Ⅲ级，辅助站立平衡维持≥60s，可部分辅助完成床椅转移",
        "therapy_items": ["偏瘫肢体综合训练", "徒手肌力训练", "平衡功能训练"],
        "plan_items": ["偏瘫肢体综合训练", "坐位立位平衡训练", "重心转移训练"],
        "frequency": "每日1次，每次30min，每周5次",
        "safety": ["训练全程监护", "循序渐进负重", "防跌倒"],
        "education": ["良肢位摆放", "居家观察肢体痉挛变化"],
        "next_review": "每20次治疗后复评",
    })
    print()
    print("---------- 首评（第 1 次，强制）----------")
    print(rt.render(pt_initial, a, record_date="2026-10-05"))
    print()
    print(f"  [必填校验] 空答案时缺：{rt.validate_answers(pt_initial, rt.blank_answers(pt_initial))}")

    # ---- 日常（只预填训练项目）----
    d = rt.blank_answers(pt_daily)
    d = rt.apply_prefill(pt_daily, d, last_daily={"therapy_items": ["偏瘫肢体综合训练", "平衡功能训练"]})
    print()
    print("---------- 日常记录：刚打开时（只预填了『本次训练项目』）----------")
    print(rt.render(pt_daily, d, record_date="2026-10-05", seq_no=1))
    d.update({
        "mental": "良好", "complaint": ["乏力"], "vas": 2, "dizziness": "无", "compliance": "良好",
        "vital_signs": "平稳", "completed": ["坐位重心转移", "辅助站立负重训练"],
        "stand_sec": 45, "adverse": "无",
        "performance": "较前改善", "existing_problem": ["患侧负重不足"], "plan_effect": "有效",
        "next_step": "继续维持原方案", "safety": ["继续落实防跌倒宣教"],
    })
    print()
    print("---------- 日常记录：填完之后 ----------")
    print(rt.render(pt_daily, d, record_date="2026-10-05", seq_no=1))

    # ---- 复评（预填上一次评估）----
    r = rt.blank_answers(pt_reassess)
    r = rt.apply_prefill(pt_reassess, r, last_assessment=a,
                         last_daily={"therapy_items": ["偏瘫肢体综合训练", "平衡功能训练"]})
    r.update({
        "subjective_change": ["患肢力量较前明显改善", "站立稳定性变好"],
        "fatigue": "轻度", "vas": 1, "dizziness": "无",
        "mmt_upper": 3, "mmt_lower": 4,          # ← 只改了这两项
        "sit_balance": "Ⅲ级", "stand_balance": "Ⅱ级",
        "transfer": "监护独立", "fall_risk": "中风险",
        "prev_goal": "基本完成", "impairment": "轻度",
        "core_problem": ["下肢负重耐力不足"],
        "potential": "持续良好",
        "goal_long": "出院可监护下室内独立步行，自主完成转移，居家安全活动",
        "goal_short": "监护下独立站立，可辅助短距离步行",
        "adjustment": "保留肌力平衡训练，新增踏步/步态预备训练",
        "frequency": "每日1次，30min，每周5次",
        "safety": ["步行训练全程陪护", "严防跌倒"],
        "education": ["纠正站立姿势", "家属训练时做好防护"],
        "next_review": "再20次治疗后",
    })
    print()
    print("---------- 复评（第 21 次，自动触发；进来时已带出上次评估值）----------")
    print(rt.render(pt_reassess, r, record_date="2026-11-10"))

    # ---- 出院（自动汇总 + 治疗师补几段）----
    x = rt.blank_answers(pt_discharge)
    x.update({
        # ★ 汇总句尾**不带句号** —— 渲染器还要拼 `；` 接下一个字段，
        #   带句号会输出「…中风险。；出院时…」这种双标点。
        #   （渲染器对 auto 字段已做 rstrip 兜底，但示例里也别写。）
        "summary": "住院期间共治疗 21 次。较首评：上肢肌力 2级→3级，下肢肌力 3级→4级；"
                   "坐位平衡 Ⅱ级→Ⅲ级，站立平衡 Ⅰ级→Ⅱ级。",
        "subjective_change": ["肢体力量明显恢复", "站立行走稳定性改善"],
        "vas": 1, "home_activity": "可在家属监护下室内活动",
        "mmt_upper": 3, "mmt_lower": 4,
        "sit_balance": "Ⅲ级", "stand_balance": "Ⅱ级",
        "transfer": "监护独立", "gait": "监护下独立室内步行", "fall_risk": "中风险",
        "goal_achieved": "基本达成",
        "improvement": ["运动能力显著改善", "平衡能力显著改善", "转移能力显著改善"],
        "residual": ["步行耐力不足，长时间活动易疲劳"],
        "discharge_goal": "维持现有运动功能，逐步提升步行耐力，安全进行居家活动",
        "home_training": ["肌力训练", "平衡训练", "步态训练"],
        "home_frequency": "每日2次，每次20min",
        "safety_note": ["起身、转身动作缓慢", "避免劳累", "避免快速变换体位"],
        "home_management": ["坚持良肢位摆放", "监测肢体痉挛情况"],
        "follow_up": "康复科门诊定期复诊评估功能",
    })
    print()
    print("---------- 出院小结（点『出院』；S 段汇总是自动生成的）----------")
    print(rt.render(pt_discharge, x, record_date="2026-11-30", seq_no=21, total_sessions=21))
    print()

    print("=" * 78)
    print("五、多日记录：按时间顺序往下排（不分页、不一天一张）")
    print("=" * 78)
    print("  用户 2026-10-05：『多日的情况下，是按时间顺序往下排就行，不用一天一张』")
    print()

    def one_day(day: str, seq: int, extra: dict) -> str:
        ans = rt.apply_prefill(
            pt_daily, rt.blank_answers(pt_daily),
            last_daily={"therapy_items": ["偏瘫肢体综合训练", "平衡功能训练"]})
        ans.update({
            "mental": "良好", "complaint": ["乏力"], "vas": 2, "dizziness": "无",
            "compliance": "良好", "vital_signs": "平稳",
            "completed": ["坐位重心转移"], "stand_sec": 40, "adverse": "无",
            "performance": "较前改善", "existing_problem": ["患侧负重不足"],
            "plan_effect": "有效", "next_step": "继续维持原方案",
            "safety": ["继续落实防跌倒宣教"],
            "extra_note": "训练后无不适，家属在场",
        })
        ans.update(extra)
        return rt.render(pt_daily, ans, record_date=day, seq_no=seq)

    print("\n\n".join([
        one_day("2026-10-05", 1, {}),
        one_day("2026-10-06", 2, {"stand_sec": 45, "vas": 1}),
        one_day("2026-10-07", 3, {"stand_sec": 50, "vas": 1, "performance": "维持稳定"}),
    ]))
    print()

    print("=" * 78)
    print("结论")
    print("=" * 78)
    if failures:
        print(f"  {len(failures)} 项失败：")
        for f in failures:
            print(f"    - {f}")
        return 1
    print("  模板结构与渲染全部通过。")
    if pending:
        print(f"  待写形态的大类：{'、'.join(pending)}（A 步策略：先验收【运动】一类，再复制过去）")
    print("  四类 × 四形态 = 16 份，本轮完成【运动】4 份。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
