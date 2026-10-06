"""给每位在院患者生成 31 天的治疗记录（含首评），供用户手工测试。

    cd backend
    python scripts/seed_demo_records.py            # 从今天往前 31 天
    python scripts/seed_demo_records.py --days 5   # 少几天
    python scripts/seed_demo_records.py --days 11 --initial-days-ago 31
                                                   # 短窗口也想看到复评：首评往前挪 31 天
    python scripts/seed_demo_records.py --wipe     # 先清掉这些患者的记录

## 生成规则（与真实业务一致，不是随便插数据）

- 每名患者选 2 个**大类**（不同治疗师常各管一类）；每天每类 2 条 → 一天 4 条
- **首评放在日期范围之前**（默认前一天，`--initial-days-ago` 可调；硬门禁要求），
  首评不占次数，当天仍记日常
- 日常记录**计入次数**；首评/复评不计次（用户 2026-10-05 纠正过的语义）
- 距上次评估满 **30 个自然日**后自动补一份**复评**，之后继续日常
  （2026-10-06 起复评按日期算，不再是"每 20 次日常"）
- 内容用**真实模板字段**（`templates/*.json`），所以打印出来的 SOAP 文本是真的
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.db import storage  # noqa: E402
from app.models import treatment as treatment_model  # noqa: E402
from app.models import user as user_model  # noqa: E402
from app.services import record_template as rt  # noqa: E402

# 每个大类挑几个"常用疗法"，让数据看起来像真的
THERAPY_PICKS = {
    "PT": ["偏瘫肢体综合训练", "平衡功能训练", "徒手肌力训练", "转移动作训练",
           "站立步行能力综合训练", "关节松动训练", "上下肢协调功能训练"],
    "OT": ["日常生活能力训练", "独立生活能力训练", "家务劳动训练", "社交技能训练"],
    "ST_SW": ["肌肉功能训练", "吞咽电刺激治疗", "吞咽球囊治疗", "儿童口部感觉运动功能训练"],
    "ST_SP": ["构音障碍治疗", "诵读训练", "失语症治疗", "实用语言交流能力治疗"],
}

# 每个大类配两名治疗师（用户说过"可能是不同的治疗师操作"）
THERAPISTS = ["T001", "T002"]


def _pick(rng: random.Random, options: list[str], n: int = 1) -> list[str]:
    n = min(n, len(options))
    return rng.sample(options, n)


def make_body(rng: random.Random, discipline: str, kind: str) -> dict:
    """按模板字段造一份"像真的"答案（只填模板里存在的 key）。"""
    tpl = rt.load(discipline, kind)
    keys = {f["key"]: f for f in tpl.all_fields()}
    body: dict = {}

    def put(key: str, value):
        if key in keys:
            body[key] = value

    def one(key: str, idx: int = 0):
        f = keys.get(key)
        if f and f.get("options"):
            put(key, f["options"][min(idx, len(f["options"]) - 1)])

    def many(key: str, n: int = 2):
        f = keys.get(key)
        if f and f.get("options"):
            if f.get("options_source") or key == "therapy_items":
                pool = THERAPY_PICKS.get(discipline, [])
            else:
                pool = f["options"]
            body[key] = _pick(rng, [o for o in pool if o in (f["options"] or pool)], n) \
                if not f.get("options_source") else _pick(rng, pool, n)

    # 本次训练项目：**必填**，用该大类的真实疗法清单
    put("therapy_items", _pick(rng, THERAPY_PICKS[discipline], rng.choice([1, 2, 2, 3])))

    if discipline == "PT":
        put("mental", ["良好", "良好", "一般"][rng.randrange(3)])
        many("complaint", 1)
        put("vas", rng.choice([0, 1, 2, 3]))
        one("dizziness", 0)
        put("compliance", ["良好", "良好", "一般"][rng.randrange(3)])
        one("consciousness", 0)
        one("affected_side", rng.randrange(2))
        put("mmt_upper", rng.choice([2, 3, 3, 4]))
        put("mmt_lower", rng.choice([3, 3, 4, 4]))
        one("ashworth", rng.randrange(3))
        one("rom", rng.randrange(3))
        one("sit_balance", rng.choice([1, 2, 2]))
        one("stand_balance", rng.choice([1, 2, 2]))
        one("transfer", rng.choice([1, 2, 2]))
        one("gait", rng.choice([1, 2]))
        one("fall_risk", rng.choice([0, 1, 1, 2]))
        one("vital_signs", 0)
        put("diagnosis", _pick(rng, ["偏瘫运动功能障碍", "平衡功能障碍", "跌倒高风险"], 1)
            if kind != "daily" else None)
        if not body.get("diagnosis"):
            body.pop("diagnosis", None)
        one("impairment", rng.choice([1, 2]))
        many("core_problem", 2)
        one("potential", 0)
        put("performance", ["较前改善", "较前改善", "维持稳定"][rng.randrange(3)])
        many("existing_problem", 1)
        one("plan_effect", 0)
        put("stand_sec", rng.choice([30, 45, 60, 90]))
        many("completed", 2)
        one("adverse", 0)
        one("next_step", 0)
        many("safety", 1)
    elif discipline == "OT":
        one("selfcare", rng.choice([1, 2, 3]))
        many("complaint", 1)
        put("compliance", ["良好", "一般"][rng.randrange(2)])
        many("expectation", 2)
        one("hand_function", rng.choice([1, 1, 2]))
        one("coordination", rng.choice([1, 2]))
        one("feeding", rng.choice([0, 1, 2]))
        one("dressing", rng.choice([0, 1, 2]))
        one("washing", rng.choice([0, 1, 2]))
        one("toileting", rng.choice([0, 1, 2]))
        put("fim", rng.choice([40, 55, 65, 78, 90]))
        put("diagnosis", ["上肢精细功能障碍", "日常生活活动能力下降"] if kind != "daily" else None)
        if not body.get("diagnosis"):
            body.pop("diagnosis", None)
        one("dependency", rng.choice([1, 2, 2]))
        many("core_problem", 1)
        one("potential", 0)
        put("performance", ["改善", "改善", "稳定"][rng.randrange(3)])
        many("existing_problem", 1)
        one("plan_effect", 0)
        one("next_step", 0)
    elif discipline == "ST_SW":
        many("symptom", 1)
        one("intake_route", rng.choice([1, 2, 3]))
        one("choke_freq", rng.choice([0, 1, 1, 2]))
        one("sputum", 1)
        many("expectation", 2)
        one("lip_closure", rng.choice([0, 1]))
        one("tongue", rng.choice([0, 1, 2]))
        one("soft_palate", rng.choice([0, 1]))
        one("swallow_reflex", rng.choice([0, 1]))
        # 洼田：先分级再判读。**判读必须由分级推出来**，不能各自随机 ——
        # 第一版就是两处独立随机，造出了「3级（中）」+「正常」这种自相矛盾的记录
        #（1级且5秒内完成才算正常；3–5级提示吞咽障碍）。
        kubota_grade = rng.choice(["1级（优）", "2级（良）", "3级（中）", "4级（可）"])
        put("kubota", kubota_grade)
        if kubota_grade.startswith("1级"):
            # 1 级还要看"5 秒内完成"，这里随机取一种（两种判读都可能，且都与 1 级相容）
            put("kubota_result", rng.choice([
                "正常（1级且5秒内完成）", "可疑（1级超5秒，或2级）"]))
        elif kubota_grade.startswith("2级"):
            put("kubota_result", "可疑（1级超5秒，或2级）")
        else:
            put("kubota_result", "异常（3–5级，提示吞咽障碍）")
        one("aspiration_risk", rng.choice([0, 1, 1, 2]))
        one("lung_auscultation", 0)
        put("diagnosis", ["口腔期吞咽障碍", "咽期吞咽障碍"] if kind != "daily" else None)
        if not body.get("diagnosis"):
            body.pop("diagnosis", None)
        one("safety", rng.choice([1, 2]))
        many("core_problem", 1)
        one("potential", 0)
        one("throat_discomfort", 0)
        one("spontaneous_choke", rng.choice([0, 1]))
        many("completed", 2)
        one("nausea", 0)
        one("choke_in_training", 0)
        one("larynx_lift", rng.choice([0, 1]))
        put("performance", ["较前改善", "维持稳定"][rng.randrange(2)])
        one("risk_change", 0)
        one("plan_effect", 0)
        one("next_step", 0)
    else:  # ST_SP
        many("symptom", 1)
        one("communication", rng.choice([1, 1, 2]))
        put("compliance", ["良好", "一般"][rng.randrange(2)])
        many("expectation", 2)
        one("spontaneous_speech", rng.choice([1, 1, 2]))
        one("comprehension", rng.choice([1, 1, 2]))
        one("repetition", rng.choice([0, 1, 1]))
        one("naming", rng.choice([0, 1, 1]))
        one("articulation_organ", rng.choice([0, 1]))
        put("diagnosis", ["构音障碍", "运动性失语"] if kind != "daily" else None)
        if not body.get("diagnosis"):
            body.pop("diagnosis", None)
        one("impairment", rng.choice([1, 2]))
        many("core_problem", 1)
        one("potential", 0)
        one("willingness", 0)
        one("effort_change", 0)
        many("completed", 2)
        put("clarity", rng.choice(["提升", "持平"]))
        one("instruction", 0)
        one("mood", 0)
        put("performance", ["改善", "改善", "稳定"][rng.randrange(3)])
        one("plan_effect", 0)
        many("existing_problem", 1)
        one("next_step", 0)

    # 去掉 None 与空值（渲染器会跳过，但别把 None 塞进 body_json）
    return {k: v for k, v in body.items() if v not in (None, [], "")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--days", type=int, default=31,
        help="天数（默认 31：复评周期是 **30 个自然日**，只有日期范围覆盖到 30 天以上，"
             "这批数据里才会出现一份**复评** —— 门槛是「距上次评估满 30 天后的下一次治疗」）",
    )
    ap.add_argument(
        "--initial-days-ago", type=int, default=1,
        help="首评放在日期范围开始前多少天（默认 1 = 只提前一天）。"
             "复评周期是 **30 个自然日**，想用较短的天数窗口就看到复评时把它调大"
             "（例如 `--days 11 --initial-days-ago 31`）。",
    )
    ap.add_argument("--wipe", action="store_true", help="先清掉这些患者的记录")
    ap.add_argument(
        "--open-today", action="store_true",
        help="今天只生成 1 条/大类，**留一条当日额度给人手动测试**。"
             "默认 2 条/大类会把「同一天同一大类至多 2 条」占满，"
             "于是今天记任何一条都会被服务端拒（现场看起来像又冲突了）。",
    )
    ap.add_argument("--seed", type=int, default=20261005)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    settings = get_settings()
    conn = storage.connect(settings)

    today = date.today()
    start = today - timedelta(days=args.days - 1)
    print(f"  目标库：{settings.db_path}")
    print(f"  日期范围：{start} ~ {today}（{args.days} 天）")

    try:
        # 治疗师账号：确保 T001/T002 存在（不存在就建）
        tids: dict[str, int] = {}
        for i, emp in enumerate(THERAPISTS, start=1):
            row = user_model.get_by_employee_no(conn, emp)
            if row is None:
                created = user_model.create_user(
                    conn, employee_no=emp, name=f"治疗师{i}",
                    role=user_model.ROLE_THERAPIST, password="Ther#2026pass",
                )
                tids[emp] = int(created["id"])
            else:
                tids[emp] = int(row["id"])

        patients = [
            dict(r) for r in conn.execute(
                "SELECT inpatient_no, name FROM patient"
                " WHERE status IN ('in_hospital', 'paused') ORDER BY inpatient_no"
            )
        ]
        if not patients:
            print("  !! 没有在院/暂停患者，无法生成", file=sys.stderr)
            return 2

        if args.wipe:
            for p in patients:
                conn.execute("DELETE FROM treatment_record WHERE patient_no = ?",
                             (p["inpatient_no"],))
            conn.execute("DELETE FROM change_log WHERE entity = 'treatment_record'")
            conn.commit()
            print(f"  已清空 {len(patients)} 位患者的旧记录")

        total = 0
        for pi, p in enumerate(patients):
            pno = p["inpatient_no"]
            # 每位患者固定 2 个大类（模拟"不同治疗师各管一类"）
            discs = (["PT", "OT"], ["PT", "ST_SW"], ["PT", "ST_SP"],
                     ["OT", "ST_SW"], ["ST_SW", "ST_SP"])[pi % 5]
            by_disc = {d: THERAPISTS[(pi + i) % len(THERAPISTS)] for i, d in enumerate(discs)}

            # 已有记录时接着编号，避免撞唯一索引
            existing = {
                d: conn.execute(
                    "SELECT COUNT(*), COALESCE(MAX(seq_no), 0) FROM treatment_record"
                    " WHERE patient_no = ? AND discipline = ? AND kind = 'daily'",
                    (pno, d)).fetchone()
                for d in discs
            }

            made = 0
            for d in discs:
                tid = tids[by_disc[d]]
                # 只取"已有日常条数"作为计数基数：`seq_no` 不参与，
                # 因为首评/复评的 seq_no 是 NULL（评估不占次数）。
                cnt = existing[d][0]

                # 还没有任何记录 → 先写首评（门禁要求；首评不占次数）
                #
                # ★ 首评放在日期范围**前一天**，不是第一天：同一天同一大类至多 2 条，
                # 把首评挤在第一天会占掉一个额度（每天就少一条日常）。
                # 挪到前一天也更贴近现实：入院当天评估、次日起每天治疗。
                #
                # ★★ 2026-10-06：复评改成「距首评 30 个自然日」之后，
                #   首评只提前一天就意味着**应做日在 30 天之后** ——
                #   想在这十来天的窗口里看到一次复评，首评必须放到更早。
                #   用 `--initial-days-ago` 控制（默认 1 = 只提前一天）。
                if cnt == 0:
                    treatment_model.create_record(
                        conn, patient_no=pno, therapist_id=tid,
                        record_date=str(start - timedelta(days=args.initial_days_ago)),
                        discipline=d,
                        kind="initial", body=make_body(rng, d, "initial"),
                        status="submitted",
                    )
                    made += 1

                for day_off in range(args.days):
                    day = str(start + timedelta(days=day_off))

                    # 今天要不要先补复评？——**直接问服务端用的那个门禁**
                    # （`treatment_model.pending_document`，它内部就是
                    #  「首评日 + 30 天 × k 的第一个未复评格子」那套判定）。
                    # 不要在脚本里把规则重算一遍：复评锚点从"上次评估日"改成"首评日"
                    # 时就吃过一次亏，重算的那份会悄悄漂。
                    #
                    # ⚠ 必须**在当天日常之前**创建：同一天同一大类至多 2 条，
                    # 先把日常写了，复评就没额度了 —— 这是脚本第一版踩到的坑
                    #（10 天跑完一条复评都没有）。
                    if treatment_model.pending_document(conn, pno, d, day) == "reassessment":
                        treatment_model.create_record(
                            conn, patient_no=pno, therapist_id=tid,
                            record_date=day, discipline=d, kind="reassessment",
                            body=make_body(rng, d, "reassessment"),
                            status="submitted",
                        )
                        made += 1

                    # 每类每天 2 条；今天可选**只给 1 条**，把当日额度留一条给人手动测试。
                    #
                    # 为什么需要这个开关：用户要的是"每天 2~4 条"，而"同一天同一大类
                    # 至多 2 条"意味着 2 条/大类正好占满。于是他在**今天**记任何一条
                    # 都会被服务端拒（409 同日超限），现场看起来像"又冲突了"，
                    # 白白浪费一次排查。留一条额度，测的才是"新建能不能成功"。
                    per_day = 1 if (args.open_today and day == str(today)) else 2
                    for k in range(per_day):
                        try:
                            treatment_model.create_record(
                                conn, patient_no=pno, therapist_id=tid,
                                record_date=day, discipline=d, kind="daily",
                                body=make_body(rng, d, "daily"), status="submitted",
                            )
                        except Exception as exc:            # noqa: BLE001
                            # 同日额度已被复评占掉一条时，第 2 条会超限 —— 属预期，静默跳过
                            if "至多" not in str(exc):
                                print(f"    ! {pno} {d} {day} 第{k + 1}条跳过：{exc}")
                            continue
                        cnt += 1
                        made += 1
                total += made

            print(f"  {pno:<10} {p['name']:<14} 大类 {'/'.join(discs):<12} 生成 {made} 条")

        conn.commit()
        print(f"\n  合计写入 {total} 条记录")
        rows = conn.execute(
            "SELECT discipline, kind, COUNT(*) FROM treatment_record GROUP BY discipline, kind"
            " ORDER BY discipline, kind").fetchall()
        print("  分布（大类 / 形态 / 条数）:")
        for r in rows:
            print(f"    {r[0]:<7} {r[1]:<14} {r[2]}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
