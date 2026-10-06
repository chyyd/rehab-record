"""★ 复评周期 = 「距首评或上一次复评 **30 个自然日**」（用户 2026-10-06 改）。

## 为什么单独一个文件

原规则是"每 20 次日常治疗后复评"，判据是**次数**（挂在 `treatment_record.span_seq`
上，随迁移 014 删除）；现规则是**自然日**。新契约的边界几乎都落在"日期前后一天"
和"应做日当天没治疗"上 —— 这些散在别处看不全，聚在一处才能一眼看清周期语义。

覆盖：

1. 满 30 天**前**一天仍是普通日常；满 30 天**当天**必须先补复评（409）；
2. **顺延**：「应做日那天没有治疗」→ 下一次来治疗时照样要求复评
   （用户原话：「如果当日没有治疗，顺延到下一次治疗时评估」）；
3. **周期不漂移**：复评补做晚了，下一次应做日仍按 30 天步进（直接对
   `record_template` 做单元测试）；
4. 表单响应报的是 `days_until_reassessment` / `reassessment_due`，
   **不再**有 `sessions_until_reassessment`（次数不再是复评的判据）；
5. 复评按月重复产生：30/60/90 天各一份都要成功。

首评唯一（每个大类一份）在 `test_records.py::TestAssessmentGate` 里，
因为那条约束的落点是库层索引，不属于"复评周期"。
"""

from __future__ import annotations

import unittest
from datetime import date

from app.models import patient as patient_model
from app.services import record_template
from tests.api_base import ApiTestCase

DISCIPLINE = "PT"


def daily_body(**overrides) -> dict:
    body = {
        "mental": "良好",
        "complaint": ["乏力"],
        "vas": 2,
        "therapy_items": ["偏瘫肢体综合训练"],
        "performance": "较前改善",
        "next_step": "继续维持原方案",
    }
    body.update(overrides)
    return body


def initial_body(**overrides) -> dict:
    body = {
        "complaint": ["肢体无力"],
        "consciousness": "清楚",
        "affected_side": "左侧",
        "mmt_lower": 2,
        "diagnosis": ["偏瘫运动功能障碍"],
        "therapy_items": ["偏瘫肢体综合训练"],
    }
    body.update(overrides)
    return body


def reassessment_body(**overrides) -> dict:
    body = {
        "diagnosis": ["偏瘫运动功能障碍"],
        "therapy_items": ["平衡生物反馈训练"],
    }
    body.update(overrides)
    return body


class TestReassessmentIntervalMath(unittest.TestCase):
    """纯日期计算（不碰数据库）—— 规则的唯一实现在 `record_template`。"""

    def test_interval_is_30_natural_days(self) -> None:
        self.assertEqual(record_template.REASSESS_INTERVAL_DAYS, 30)

    def test_due_is_anchor_plus_30_days(self) -> None:
        self.assertEqual(record_template.next_reassessment_due("2027-01-01"), date(2027, 1, 31))
        self.assertIsNone(
            record_template.next_reassessment_due(None), "该大类还没有评估 → 无从计算"
        )

    def test_late_reassessment_does_not_drift_the_cycle(self) -> None:
        """★ 应做日从**计划节奏**起算，不因补做晚而漂移。

        首评 01-01 → 应做 01-31；治疗师拖到 02-05 才补做。
        下一次应做日是 **03-02**（首评 + 60），而不是 03-07（02-05 + 30）——
        按实际完成日算会让"1 个月评一次"越拖越长（拖 5 天就变 35 天一次）。

        这是**生产路径**的语义，不是一条没人用的函数契约：
        锚点是首评日（`models/treatment.py::initial_date`），
        `_resolve_placement` 与 `services/records.py::build_form` 都这么传。
        """
        due = record_template.next_reassessment_due(
            "2027-01-01", done_dates=["2027-02-05"], on_date="2027-02-05"
        )
        self.assertEqual(due, date(2027, 3, 2), "周期从计划节奏（首评 + 30k）起算")
        self.assertNotEqual(due, date(2027, 3, 7), "★ 拿实际完成日 + 30 就会漂移")

    def test_late_by_more_than_one_period_keeps_stepping(self) -> None:
        """★ 拖过一个周期也不"跳过"没做的那一格：逾期的格子继续报它自己。

        首评 01-01 → 第 1 格应做 01-31。治疗师一直没做，直到 04-10 才补了一份复评。
        问"下一个应做日"时，**01-31 那一格仍然是逾期未做** —— 只补一份复评
        覆盖不了它（`[01-31, 03-02)` 区间内没有复评）。

        这正是"每格都要做"的语义：**不能靠一次性补做把欠的账抹平**。
        把 01-31 那格也补上之后，才轮到 03-02。
        """
        self.assertEqual(
            record_template.next_reassessment_due(
                "2027-01-01", done_dates=["2027-04-10"], on_date="2027-04-10"
            ),
            date(2027, 1, 31),
            "01-31 那格没做 → 仍然是它（不能被后面的复评顶掉）",
        )
        # 把 01-31 那格补上 → 前进到下一格（03-02），而不是 04-10 + 30
        self.assertEqual(
            record_template.next_reassessment_due(
                "2027-01-01",
                done_dates=["2027-01-31", "2027-04-10"],
                on_date="2027-04-10",
            ),
            date(2027, 3, 2),
            "01-31 做过、03-02 没做 → 报 03-02（首评 + 60，不是 04-10 + 30 的 05-10）",
        )

    def test_days_until_reassessment_counts_down_to_zero(self) -> None:
        self.assertEqual(record_template.days_until_reassessment("2027-01-01", "2027-01-30"), 1)
        self.assertEqual(
            record_template.days_until_reassessment("2027-01-01", "2027-01-31"), 0, "0 = 正是应做日"
        )
        self.assertEqual(
            record_template.days_until_reassessment("2027-01-01", "2027-02-14"), -14, "负数 = 已逾期"
        )
        self.assertIsNone(
            record_template.days_until_reassessment(None, "2027-01-01"), "没有评估基准 → None"
        )

    def test_document_switches_exactly_on_the_due_date(self) -> None:
        """满 29 天不要求、满 30 天（应做日）要求 —— 边界是闭区间 `on_date >= due`。"""
        self.assertIsNone(
            record_template.reassessment_document_for(
                has_initial=True, initial_date="2027-01-01", on_date="2027-01-30"
            )
        )
        self.assertEqual(
            record_template.reassessment_document_for(
                has_initial=True, initial_date="2027-01-01", on_date="2027-01-31"
            ),
            "reassessment",
        )
        # 顺延：应做日过了很久，来治疗时依然要求复评
        self.assertEqual(
            record_template.reassessment_document_for(
                has_initial=True, initial_date="2027-01-01", on_date="2027-02-14"
            ),
            "reassessment",
        )
        # 没有首评时永远是首评优先（顺延与否都不放行）
        self.assertEqual(
            record_template.reassessment_document_for(
                has_initial=False, initial_date=None, on_date="2027-02-14"
            ),
            "initial",
        )


class ReassessmentIntervalTestCase(ApiTestCase):
    """30 天周期的接口级行为（门禁 + 表单）。"""

    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.t1 = self.make_user("T001", "张三")
        patient_model.create_patient(
            self.conn,
            inpatient_no="ZY001",
            name="患者甲",
            assigned_therapist_id=int(self.t1["id"]),
        )
        self.h1 = self.login_headers("T001")

    # -- 便捷方法 ---------------------------------------------------------- #
    def initial(self, record_date: str) -> dict:
        return self.create_ok(kind="initial", record_date=record_date, body=initial_body())

    def create(
        self,
        *,
        kind: str = "daily",
        record_date: str = "2027-01-31",
        body: dict | None = None,
    ):
        return self.client.post(
            "/api/v1/records",
            json={
                "patient_no": "ZY001",
                "record_date": record_date,
                "discipline": DISCIPLINE,
                "kind": kind,
                "body": body if body is not None else daily_body(),
                "status": "submitted",
            },
            headers=self.h1,
        )

    def create_ok(self, *, kind: str = "daily", record_date: str = "2027-01-31", body=None) -> dict:
        resp = self.create(kind=kind, record_date=record_date, body=body)
        self.assertEqual(resp.status_code, 201, resp.text)
        return resp.json()

    def form(self, *, date: str) -> dict:
        """`GET /records/form`；⚠ 日期参数名是 `date`（路由 query alias）。"""
        resp = self.client.get(
            "/api/v1/records/form",
            params={"patient_no": "ZY001", "discipline": DISCIPLINE, "date": date},
            headers=self.h1,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()


class TestThirtyDayBoundary(ReassessmentIntervalTestCase):
    """★ 满 30 天前后各一天的行为。"""

    def test_day_29_is_daily_but_day_30_requires_reassessment(self) -> None:
        self.initial("2027-01-01")

        # 第 29 天（2027-01-30）：还没到应做日，普通日常
        before = self.create_ok(kind="daily", record_date="2027-01-30")
        self.assertEqual(before["seq_no"], 1)
        self.assertEqual(before["kind"], "daily")

        # 第 30 天（2027-01-31）= 应做日：必须先补复评
        resp = self.create(kind="daily", record_date="2027-01-31")
        self.assert_error(resp, 409, "MISSING_ASSESSMENT")
        details = resp.json()["details"]
        self.assertEqual(details["missing_document"], "reassessment")
        self.assertEqual(details["reassessment_due"], "2027-01-31", "应做日 = 首评日 + 30 天")
        self.assertEqual(details["next_seq"], 2, "★ 被拦下的是第 2 次日常（新规则不看次数）")

        # 补复评后同一日期就能记（当天两条正好到上限）
        self.create_ok(kind="reassessment", record_date="2027-01-31", body=reassessment_body())
        daily = self.create_ok(kind="daily", record_date="2027-01-31")
        self.assertEqual(daily["seq_no"], 2)

    def test_missed_due_date_defers_to_the_next_visit(self) -> None:
        """★ 用户原话：「如果当日没有治疗，顺延到下一次治疗时评估」。

        2027-01-31 那天没有任何记录（没来治疗），两周后 2027-02-14 来记日常，
        照样先被拦下要求复评 —— 判定拿**本次记录日期**去比应做日，
        不需要"补记"也不需要定时任务。
        """
        self.initial("2027-01-01")

        resp = self.create(kind="daily", record_date="2027-02-14")
        self.assert_error(resp, 409, "MISSING_ASSESSMENT")
        details = resp.json()["details"]
        self.assertEqual(details["missing_document"], "reassessment")
        self.assertEqual(
            details["reassessment_due"], "2027-01-31", "应做日仍是原来那天（不是「今天加 30 天」）"
        )

        self.create_ok(kind="reassessment", record_date="2027-02-14", body=reassessment_body())
        daily = self.create_ok(kind="daily", record_date="2027-02-14")
        self.assertEqual(daily["seq_no"], 1)

        # 复评已补做（在 02-14，落在 `[01-31, 03-02)` 这一格里）→ 该格完成，
        # 应做日前进到**下一格 03-02**（首评 + 60），而不是 02-14 + 30 = 03-16。
        #
        # ★ 这条就是"周期不漂移"在**生产路径**上的证据：
        #   `_resolve_placement` 与 `build_form` 都拿首评日当锚、传 `done_dates`。
        body = self.form(date="2027-02-14")
        self.assertIsNone(body["pending_document"], "刚评过，当天不再要求复评")
        self.assertEqual(
            body["reassessment_due"],
            "2027-03-02",
            "★ 从计划节奏（首评 + 30k）起算；不是实际完成日 + 30 的 03-16",
        )

    def test_gate_does_not_apply_to_assessment_documents_themselves(self) -> None:
        """复评文书本身不受"必须先复评"的阻断 —— 否则就死锁了。"""
        self.initial("2027-01-01")
        self.create_ok(kind="reassessment", record_date="2027-01-31", body=reassessment_body())
        self.create_ok(kind="reassessment", record_date="2027-03-02", body=reassessment_body())


class TestMonthlyReassessmentCadence(ReassessmentIntervalTestCase):
    """★ 复评按月重复产生：30/60/90 天各一份，每份都要能建、且都能放行当天日常。"""

    def test_reassessment_repeats_every_30_days(self) -> None:
        self.initial("2027-01-01")
        expected_seq = 1
        for day in ("2027-01-31", "2027-03-02", "2027-04-01"):
            # 到点那天先记日常 → 被拦（要求复评）
            resp = self.create(kind="daily", record_date=day)
            self.assert_error(resp, 409, "MISSING_ASSESSMENT")
            self.assertEqual(resp.json()["details"]["missing_document"], "reassessment")

            reassessment = self.create_ok(
                kind="reassessment", record_date=day, body=reassessment_body()
            )
            self.assertIsNone(reassessment["seq_no"], "复评不占次数")

            daily = self.create_ok(kind="daily", record_date=day)
            self.assertEqual(daily["seq_no"], expected_seq)
            expected_seq += 1

        count = self.conn.execute(
            "SELECT COUNT(*) FROM treatment_record WHERE kind = 'reassessment'"
        ).fetchone()[0]
        self.assertEqual(count, 3, "★ 复评不是一次性文书：同一大类按月可以有多份")


class TestFormReassessmentFields(ReassessmentIntervalTestCase):
    """★ 表单响应：报"还差几天 / 应做日是哪天"，不再报"还差几次"。"""

    def test_form_reports_days_and_due_date(self) -> None:
        self.initial("2027-01-01")
        body = self.form(date="2027-01-20")
        self.assertEqual(body["reassessment_interval_days"], 30)
        self.assertEqual(body["reassessment_due"], "2027-01-31")
        self.assertEqual(body["days_until_reassessment"], 11)
        self.assertNotIn(
            "sessions_until_reassessment", body, "★ 次数不再是复评判据，字段已删除"
        )

    def test_form_reports_zero_and_negative_when_overdue(self) -> None:
        self.initial("2027-01-01")
        on_due = self.form(date="2027-01-31")
        self.assertEqual(on_due["days_until_reassessment"], 0, "0 = 正是应做日")
        self.assertEqual(on_due["pending_document"], "reassessment")

        overdue = self.form(date="2027-02-14")
        self.assertEqual(overdue["days_until_reassessment"], -14, "负数 = 已逾期 14 天")
        self.assertEqual(overdue["kind"], "reassessment", "缺复评时表单直接折成复评")

    def test_form_has_no_dates_before_the_first_assessment(self) -> None:
        """还没有评估 → 两个字段都是 None（而不是 0 或今天 + 30）。"""
        body = self.form(date="2027-01-20")
        self.assertIsNone(body["days_until_reassessment"])
        self.assertIsNone(body["reassessment_due"])
        self.assertEqual(body["pending_document"], "initial")


if __name__ == "__main__":
    unittest.main(verbosity=2)
