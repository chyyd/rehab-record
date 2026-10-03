"""阶段 2 测试：排期、休息与请假（`开发计划.md` 阶段 2）。

重点覆盖三件事：
1. **半日制的两条不变量**（治疗师半日 = 一台；患者半日 = 一名治疗师）；
2. **三条冲突规则**与可排性查询给出的原因；
3. **请假的副作用**：单日假临时释放（不改原归属）、多日假正式排空（不自动恢复）、撤销回滚。
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from app.core.clock import period_expiry
from app.core.config import WorkTimeConfig
from app.models import appointment as appointment_model
from app.models import leave as leave_model
from app.models import patient as patient_model
from app.models import rest_block as rest_block_model
from app.models.base import Conflict, Invalid
from tests.api_base import ApiTestCase

# 固定用未来的日期，避免"今天/昨天"这类相对时间把用例变脆
D1 = "2027-03-01"  # 周一
D2 = "2027-03-02"  # 周二
D3 = "2027-03-03"  # 周三
D4 = "2027-03-04"  # 周四


class ScheduleTestCase(ApiTestCase):
    """准备：一个管理员、两名治疗师、三名患者（归属不同）。"""

    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.t1 = self.make_user("T001", "张三")
        self.t2 = self.make_user("T002", "李四")
        self.admin = self.make_admin("A001")
        self.p1 = patient_model.create_patient(
            self.conn, inpatient_no="ZY001", name="患者甲", assigned_therapist_id=int(self.t1["id"])
        )
        self.p2 = patient_model.create_patient(
            self.conn, inpatient_no="ZY002", name="患者乙", assigned_therapist_id=int(self.t2["id"])
        )
        self.free = patient_model.create_patient(self.conn, inpatient_no="ZY003", name="患者丙")
        self.h1 = self.login_headers("T001")
        self.h2 = self.login_headers("T002")
        self.ha = self.login_headers("A001")


class TestSchedulingInvariants(ScheduleTestCase):
    """半日制的两条不变量（S1 / Q2）。"""

    def test_create_appointment_and_list(self) -> None:
        resp = self.client.post(
            "/api/v1/schedule",
            json={"patient_no": "ZY001", "date": D1, "period": "am"},
            headers=self.h1,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual(body["period"], "am")
        self.assertEqual(body["status"], "planned")
        self.assertEqual(body["patient_name"], "患者甲")
        self.assertEqual(body["therapist_name"], "张三")

        listed = self.client.get(
            "/api/v1/schedule", params={"from": D1, "to": D1}, headers=self.h1
        ).json()
        self.assertEqual(len(listed), 1)

    def test_therapist_half_day_is_single_slot(self) -> None:
        first = self.client.post(
            "/api/v1/schedule", json={"patient_no": "ZY001", "date": D1, "period": "am"}, headers=self.h1
        )
        self.assertEqual(first.status_code, 201)
        second = self.client.post(
            "/api/v1/schedule", json={"patient_no": "ZY003", "date": D1, "period": "am"}, headers=self.h1
        )
        self.assert_error(second, 409, "CONFLICT")
        rules = [c["rule"] for c in second.json()["details"]["conflicts"]]
        self.assertIn("therapist_slot_taken", rules)

    def test_same_therapist_other_period_is_allowed(self) -> None:
        """上午与下午是两个独立格子。"""
        self.client.post("/api/v1/schedule", json={"patient_no": "ZY001", "date": D1, "period": "am"}, headers=self.h1)
        resp = self.client.post(
            "/api/v1/schedule", json={"patient_no": "ZY003", "date": D1, "period": "pm"}, headers=self.h1
        )
        self.assertEqual(resp.status_code, 201, resp.text)

    def test_patient_half_day_is_single_therapist(self) -> None:
        """Q2：同一患者同一半日不能被两名治疗师排期。"""
        self.client.post("/api/v1/schedule", json={"patient_no": "ZY003", "date": D1, "period": "am"}, headers=self.h1)
        # 乙患者未分配，李四也可以排；但同一半日第二个治疗师应被拒
        resp = self.client.post(
            "/api/v1/schedule", json={"patient_no": "ZY003", "date": D1, "period": "am"}, headers=self.h2
        )
        self.assert_error(resp, 409, "CONFLICT")
        rules = [c["rule"] for c in resp.json()["details"]["conflicts"]]
        self.assertIn("patient_slot_taken", rules)

    def test_cancelled_appointment_frees_the_slot(self) -> None:
        created = self.client.post(
            "/api/v1/schedule", json={"patient_no": "ZY001", "date": D1, "period": "am"}, headers=self.h1
        ).json()
        cancelled = self.client.delete(f"/api/v1/schedule/{created['id']}", headers=self.h1)
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["status"], "cancelled")

        again = self.client.post(
            "/api/v1/schedule", json={"patient_no": "ZY003", "date": D1, "period": "am"}, headers=self.h1
        )
        self.assertEqual(again.status_code, 201, again.text)

    def test_cancelled_not_listed_by_default(self) -> None:
        created = self.client.post(
            "/api/v1/schedule", json={"patient_no": "ZY001", "date": D1, "period": "am"}, headers=self.h1
        ).json()
        self.client.delete(f"/api/v1/schedule/{created['id']}", headers=self.h1)
        active = self.client.get("/api/v1/schedule", params={"from": D1, "to": D1}, headers=self.h1).json()
        self.assertEqual(active, [])
        all_items = self.client.get(
            "/api/v1/schedule", params={"from": D1, "to": D1, "include_inactive": True}, headers=self.h1
        ).json()
        self.assertEqual(len(all_items), 1)

    def test_full_period_rejected_for_appointment(self) -> None:
        """full 是请假专用，不能用于排期。"""
        resp = self.client.post(
            "/api/v1/schedule", json={"patient_no": "ZY001", "date": D1, "period": "full"}, headers=self.h1
        )
        self.assert_error(resp, 422)

    def test_planned_times_must_be_within_period(self) -> None:
        """可选计划时间必须落在所属半日作息区间内。"""
        ok = self.client.post(
            "/api/v1/schedule",
            json={"patient_no": "ZY001", "date": D1, "period": "am", "start_time": "08:00", "end_time": "08:40"},
            headers=self.h1,
        )
        self.assertEqual(ok.status_code, 201, ok.text)

        bad = self.client.post(
            "/api/v1/schedule",
            json={"patient_no": "ZY003", "date": D1, "period": "am", "start_time": "14:00"},
            headers=self.h1,
        )
        self.assert_error(bad, 422, "INVALID")

    def test_planned_time_reversed_rejected(self) -> None:
        resp = self.client.post(
            "/api/v1/schedule",
            json={"patient_no": "ZY001", "date": D1, "period": "am", "start_time": "10:00", "end_time": "08:00"},
            headers=self.h1,
        )
        self.assert_error(resp, 422, "INVALID")

    def test_therapist_cannot_schedule_others_patient(self) -> None:
        """Q3：只能给自己可见范围内的患者排期。"""
        resp = self.client.post(
            "/api/v1/schedule", json={"patient_no": "ZY002", "date": D1, "period": "am"}, headers=self.h1
        )
        self.assert_error(resp, 403, "PATIENT_NOT_SCHEDULABLE")

    def test_therapist_cannot_schedule_for_another_therapist(self) -> None:
        resp = self.client.post(
            "/api/v1/schedule",
            json={"patient_no": "ZY001", "date": D1, "period": "am", "therapist_id": int(self.t2["id"])},
            headers=self.h1,
        )
        self.assert_error(resp, 403, "SCHEDULE_OTHER_THERAPIST")

    def test_admin_can_schedule_for_anyone(self) -> None:
        resp = self.client.post(
            "/api/v1/schedule",
            json={"patient_no": "ZY002", "date": D1, "period": "am", "therapist_id": int(self.t2["id"])},
            headers=self.ha,
        )
        self.assertEqual(resp.status_code, 201, resp.text)

    def test_update_moves_appointment(self) -> None:
        created = self.client.post(
            "/api/v1/schedule", json={"patient_no": "ZY001", "date": D1, "period": "am"}, headers=self.h1
        ).json()
        moved = self.client.put(
            f"/api/v1/schedule/{created['id']}", json={"date": D2, "period": "pm"}, headers=self.h1
        )
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertEqual((moved.json()["date"], moved.json()["period"]), (D2, "pm"))

    def test_therapist_cannot_update_others_appointment(self) -> None:
        created = self.client.post(
            "/api/v1/schedule", json={"patient_no": "ZY001", "date": D1, "period": "am"}, headers=self.h1
        ).json()
        resp = self.client.put(
            f"/api/v1/schedule/{created['id']}", json={"period": "pm"}, headers=self.h2
        )
        self.assert_error(resp, 403, "SCHEDULE_OTHER_THERAPIST")


class TestAvailability(ScheduleTestCase):
    def test_availability_marks_taken_and_open(self) -> None:
        self.client.post("/api/v1/schedule", json={"patient_no": "ZY001", "date": D1, "period": "am"}, headers=self.h1)
        slots = self.client.get(
            "/api/v1/schedule/availability", params={"from": D1, "to": D1, "therapist_id": int(self.t1["id"])},
            headers=self.h1,
        ).json()
        self.assertEqual(len(slots), 2, "一天两个半日")
        am = next(s for s in slots if s["period"] == "am")
        pm = next(s for s in slots if s["period"] == "pm")
        self.assertFalse(am["available"])
        self.assertIn("therapist_slot_taken", am["reasons"])
        self.assertEqual(am["patient_name"], "患者甲")
        self.assertTrue(pm["available"])
        self.assertEqual(pm["reasons"], [])

    def test_availability_reflects_patient_conflict(self) -> None:
        """传入 patient_no 后，同一患者在其他治疗师那里的占用也要算进来。"""
        self.client.post("/api/v1/schedule", json={"patient_no": "ZY003", "date": D1, "period": "am"}, headers=self.h1)
        slots = self.client.get(
            "/api/v1/schedule/availability",
            params={"from": D1, "to": D1, "therapist_id": int(self.t2["id"]), "patient_no": "ZY003"},
            headers=self.h2,
        ).json()
        am = next(s for s in slots if s["period"] == "am")
        self.assertFalse(am["available"])
        self.assertIn("patient_slot_taken", am["reasons"])

    def test_availability_reflects_rest_block(self) -> None:
        rest_block_model.create_rest_block(
            self.conn, therapist_id=int(self.t1["id"]), scope="date", specific_date=D1, period="pm"
        )
        slots = self.client.get(
            "/api/v1/schedule/availability", params={"from": D1, "to": D1}, headers=self.h1
        ).json()
        pm = next(s for s in slots if s["period"] == "pm")
        self.assertFalse(pm["available"])
        self.assertIn("rest_block", pm["reasons"])

    def test_availability_reflects_leave(self) -> None:
        leave_model.create_leave(
            self.conn, therapist_id=int(self.t1["id"]), leave_type="half_day_am",
            start_date=D1, end_date=D1, operator_user_id=int(self.t1["id"]),
        )
        slots = self.client.get(
            "/api/v1/schedule/availability", params={"from": D1, "to": D1}, headers=self.h1
        ).json()
        am = next(s for s in slots if s["period"] == "am")
        self.assertFalse(am["available"])
        self.assertIn("on_leave", am["reasons"])

    def test_availability_over_multiple_days(self) -> None:
        slots = self.client.get(
            "/api/v1/schedule/availability", params={"from": D1, "to": D3}, headers=self.h1
        ).json()
        self.assertEqual(len(slots), 6, "3 天 × 2 个半日")

    def test_invalid_date_range_rejected(self) -> None:
        resp = self.client.get(
            "/api/v1/schedule/availability", params={"from": D3, "to": D1}, headers=self.h1
        )
        self.assert_error(resp, 422, "INVALID")

    def test_periods_endpoint_exposes_q11_worktime(self) -> None:
        body = self.client.get("/api/v1/schedule/periods", headers=self.h1).json()
        self.assertEqual(body["periods"]["am"]["start"], "06:00")
        self.assertEqual(body["periods"]["am"]["end"], "11:30")
        self.assertEqual(body["periods"]["pm"]["start"], "13:00")
        self.assertEqual(body["periods"]["pm"]["end"], "17:30")
        self.assertEqual(body["labels"], {"am": "上午", "pm": "下午"})


class TestRestBlocks(ScheduleTestCase):
    def test_create_weekly_rest_block(self) -> None:
        resp = self.client.post(
            "/api/v1/rest-blocks",
            json={"scope": "weekly", "weekday": 2, "period": "pm", "note": "业务学习"},
            headers=self.h1,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual((body["scope"], body["weekday"], body["period"]), ("weekly", 2, "pm"))

    def test_create_date_rest_block(self) -> None:
        resp = self.client.post(
            "/api/v1/rest-blocks",
            json={"scope": "date", "specific_date": D1, "period": "am"},
            headers=self.h1,
        )
        self.assertEqual(resp.status_code, 201, resp.text)

    def test_weekly_requires_weekday(self) -> None:
        resp = self.client.post(
            "/api/v1/rest-blocks", json={"scope": "weekly", "period": "pm"}, headers=self.h1
        )
        self.assert_error(resp, 422, "INVALID")

    def test_date_requires_specific_date(self) -> None:
        resp = self.client.post(
            "/api/v1/rest-blocks", json={"scope": "date", "period": "pm"}, headers=self.h1
        )
        self.assert_error(resp, 422, "INVALID")

    def test_weekly_rejects_date(self) -> None:
        """scope 与字段必须自洽。"""
        resp = self.client.post(
            "/api/v1/rest-blocks",
            json={"scope": "weekly", "weekday": 1, "specific_date": D1, "period": "pm"},
            headers=self.h1,
        )
        self.assert_error(resp, 422, "INVALID")

    def test_full_period_rejected(self) -> None:
        resp = self.client.post(
            "/api/v1/rest-blocks", json={"scope": "weekly", "weekday": 1, "period": "full"}, headers=self.h1
        )
        self.assert_error(resp, 422, "INVALID")

    def test_duplicate_rest_block_rejected(self) -> None:
        payload = {"scope": "weekly", "weekday": 2, "period": "pm"}
        self.assertEqual(self.client.post("/api/v1/rest-blocks", json=payload, headers=self.h1).status_code, 201)
        again = self.client.post("/api/v1/rest-blocks", json=payload, headers=self.h1)
        self.assert_error(again, 409)

    def test_rest_block_blocks_scheduling(self) -> None:
        self.client.post(
            "/api/v1/rest-blocks", json={"scope": "date", "specific_date": D1, "period": "am"}, headers=self.h1
        )
        resp = self.client.post(
            "/api/v1/schedule", json={"patient_no": "ZY001", "date": D1, "period": "am"}, headers=self.h1
        )
        self.assert_error(resp, 409)
        rules = [c["rule"] for c in resp.json()["details"]["conflicts"]]
        self.assertIn("rest_block", rules)

    def test_weekly_rest_block_blocks_matching_weekday(self) -> None:
        # D1 是 2027-03-01 → 周一 → weekday 0
        self.client.post(
            "/api/v1/rest-blocks", json={"scope": "weekly", "weekday": 0, "period": "am"}, headers=self.h1
        )
        resp = self.client.post(
            "/api/v1/schedule", json={"patient_no": "ZY001", "date": D1, "period": "am"}, headers=self.h1
        )
        self.assert_error(resp, 409)

    def test_therapist_sees_own_blocks_only_by_default(self) -> None:
        rest_block_model.create_rest_block(
            self.conn, therapist_id=int(self.t2["id"]), scope="date", specific_date=D1, period="am"
        )
        mine = self.client.get("/api/v1/rest-blocks", headers=self.h1).json()
        self.assertEqual(mine, [], "治疗师默认只看自己的休息块")
        as_admin = self.client.get(
            "/api/v1/rest-blocks", params={"therapist_id": int(self.t2["id"])}, headers=self.ha
        ).json()
        self.assertEqual(len(as_admin), 1)

    def test_therapist_cannot_create_for_others(self) -> None:
        resp = self.client.post(
            "/api/v1/rest-blocks",
            json={"scope": "date", "specific_date": D1, "period": "am", "therapist_id": int(self.t2["id"])},
            headers=self.h1,
        )
        self.assert_error(resp, 403, "REST_BLOCK_OTHER_THERAPIST")

    def test_update_and_delete(self) -> None:
        created = self.client.post(
            "/api/v1/rest-blocks", json={"scope": "date", "specific_date": D1, "period": "am"}, headers=self.h1
        ).json()
        updated = self.client.put(
            f"/api/v1/rest-blocks/{created['id']}", json={"period": "pm"}, headers=self.h1
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["period"], "pm")

        deleted = self.client.delete(f"/api/v1/rest-blocks/{created['id']}", headers=self.h1)
        self.assertEqual(deleted.status_code, 204, deleted.text)
        self.assertEqual(self.client.get("/api/v1/rest-blocks", headers=self.h1).json(), [])


class TestLeaveSingleDay(ScheduleTestCase):
    """单日假：临时释放，**不改原归属**。"""

    def test_half_day_leave_releases_patients_without_changing_owner(self) -> None:
        resp = self.client.post(
            "/api/v1/leave",
            json={"leave_type": "half_day_am", "start_date": D1, "reason": "门诊"},
            headers=self.h1,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "active", "登记即生效，没有待审批状态")
        self.assertEqual(body["source"], "therapist_self")
        self.assertEqual(body["period"], "am")

        # 原归属不变
        patient = patient_model.get_patient_or_raise(self.conn, "ZY001")
        self.assertEqual(patient["assigned_therapist_id"], int(self.t1["id"]), "单日假不得修改原归属")
        # 该半日可见归属为 NULL（临时释放）
        temp = self.conn.execute(
            "SELECT * FROM temporary_assignment WHERE patient_no = 'ZY001' AND status = 'open'"
        ).fetchone()
        self.assertIsNotNone(temp)
        self.assertIsNone(temp["temporary_therapist_id"])

    def test_released_patient_visible_in_unassigned_scope(self) -> None:
        self.client.post(
            "/api/v1/leave", json={"leave_type": "half_day_am", "start_date": D1}, headers=self.h1
        )
        # 用数据库时间比较：expires_at 是未来时间点的 UTC 串，视图会判定为"仍有效"
        row = self.conn.execute(
            "SELECT expires_at FROM temporary_assignment WHERE patient_no = 'ZY001'"
        ).fetchone()
        self.assertIsNotNone(row["expires_at"])
        self.assertTrue(row["expires_at"].endswith("Z"), "到期时间必须是 UTC + Z 格式")

    def test_leave_blocks_scheduling_for_that_therapist(self) -> None:
        self.client.post(
            "/api/v1/leave", json={"leave_type": "half_day_am", "start_date": D1}, headers=self.h1
        )
        # 临时释放后该患者变为"未分配"，但治疗师本人正在请假（该半日），仍不能排
        resp = self.client.post(
            "/api/v1/schedule", json={"patient_no": "ZY001", "date": D1, "period": "am"}, headers=self.h1
        )
        self.assert_error(resp, 409)
        rules = [c["rule"] for c in resp.json()["details"]["conflicts"]]
        self.assertIn("on_leave", rules)

    def test_other_therapist_can_schedule_released_patient(self) -> None:
        """单日假的价值：患者不被锁死在不在岗的人名下。"""
        self.client.post(
            "/api/v1/leave", json={"leave_type": "half_day_am", "start_date": D1}, headers=self.h1
        )
        resp = self.client.post(
            "/api/v1/schedule", json={"patient_no": "ZY001", "date": D1, "period": "am"}, headers=self.h2
        )
        self.assertEqual(resp.status_code, 201, resp.text)

    def test_duplicate_overlapping_leave_rejected(self) -> None:
        self.assertEqual(
            self.client.post(
                "/api/v1/leave", json={"leave_type": "half_day_am", "start_date": D1}, headers=self.h1
            ).status_code,
            201,
        )
        again = self.client.post(
            "/api/v1/leave", json={"leave_type": "half_day_pm", "start_date": D1}, headers=self.h1
        )
        self.assert_error(again, 409)

    def test_single_day_type_cannot_span_days(self) -> None:
        resp = self.client.post(
            "/api/v1/leave",
            json={"leave_type": "full_day", "start_date": D1, "end_date": D2},
            headers=self.h1,
        )
        self.assert_error(resp, 422, "INVALID")

    def test_full_day_leave_period_is_full(self) -> None:
        body = self.client.post(
            "/api/v1/leave", json={"leave_type": "full_day", "start_date": D1}, headers=self.h1
        ).json()
        self.assertEqual(body["period"], "full")

    def test_effective_endpoint(self) -> None:
        self.client.post(
            "/api/v1/leave", json={"leave_type": "half_day_am", "start_date": D1}, headers=self.h1
        )
        am = self.client.get(
            "/api/v1/leave/effective", params={"date": D1, "period": "am"}, headers=self.h1
        ).json()
        self.assertTrue(am["on_leave"])
        pm = self.client.get(
            "/api/v1/leave/effective", params={"date": D1, "period": "pm"}, headers=self.h1
        ).json()
        self.assertFalse(pm["on_leave"])


class TestLeaveMultiDay(ScheduleTestCase):
    """多日假：正式排空，不自动恢复。"""

    def test_multi_day_clears_assignment(self) -> None:
        resp = self.client.post(
            "/api/v1/leave",
            json={"leave_type": "multi_day", "start_date": D1, "end_date": D4, "reason": "进修"},
            headers=self.h1,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        patient = patient_model.get_patient_or_raise(self.conn, "ZY001")
        self.assertIsNone(patient["assigned_therapist_id"], "多日假应正式排空归属")
        self.assertIsNone(patient["visible_therapist_id"])

    def test_multi_day_requires_at_least_two_days(self) -> None:
        resp = self.client.post(
            "/api/v1/leave",
            json={"leave_type": "multi_day", "start_date": D1, "end_date": D1},
            headers=self.h1,
        )
        self.assert_error(resp, 422, "INVALID")

    def test_others_can_claim_after_release(self) -> None:
        self.client.post(
            "/api/v1/leave", json={"leave_type": "multi_day", "start_date": D1, "end_date": D4}, headers=self.h1
        )
        claimed = self.client.post(
            "/api/v1/patients/claim", params={"inpatient_no": "ZY001"}, headers=self.h2
        )
        self.assertEqual(claimed.status_code, 200, claimed.text)
        patient = patient_model.get_patient_or_raise(self.conn, "ZY001")
        self.assertEqual(patient["assigned_therapist_id"], int(self.t2["id"]), "认领后归属正式转移")

    def test_cancel_restores_only_unclaimed(self) -> None:
        """撤销多日假：只回收未被认领的患者。"""
        leave = self.client.post(
            "/api/v1/leave", json={"leave_type": "multi_day", "start_date": D1, "end_date": D4}, headers=self.h1
        ).json()
        # 让李四认领 ZY001（模拟"已被他人认领"）
        self.client.post("/api/v1/patients/claim", params={"inpatient_no": "ZY001"}, headers=self.h2)

        result = self.client.post(
            f"/api/v1/leave/{leave['id']}/cancel", json={"cancel_reason": "计划变更"}, headers=self.h1
        )
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        self.assertEqual(body["status"], "cancelled")
        self.assertIn("ZY001", body["not_restored"], "已被认领的不应被强行收回")
        # 归属仍属于李四
        patient = patient_model.get_patient_or_raise(self.conn, "ZY001")
        self.assertEqual(patient["assigned_therapist_id"], int(self.t2["id"]))

    def test_cancel_restores_unclaimed_patients(self) -> None:
        leave = self.client.post(
            "/api/v1/leave", json={"leave_type": "multi_day", "start_date": D1, "end_date": D4}, headers=self.h1
        ).json()
        result = self.client.post(f"/api/v1/leave/{leave['id']}/cancel", json={}, headers=self.h1).json()
        self.assertIn("ZY001", result["restored"])
        patient = patient_model.get_patient_or_raise(self.conn, "ZY001")
        self.assertEqual(patient["assigned_therapist_id"], int(self.t1["id"]))

    def test_cancel_twice_rejected(self) -> None:
        leave = self.client.post(
            "/api/v1/leave", json={"leave_type": "multi_day", "start_date": D1, "end_date": D4}, headers=self.h1
        ).json()
        first = self.client.post(f"/api/v1/leave/{leave['id']}/cancel", json={}, headers=self.h1)
        self.assertEqual(first.status_code, 200)
        again = self.client.post(f"/api/v1/leave/{leave['id']}/cancel", json={}, headers=self.h1)
        self.assert_error(again, 409)


class TestLeavePermissionsAndAdmin(ScheduleTestCase):
    def test_therapist_can_only_see_own_leaves(self) -> None:
        self.client.post("/api/v1/leave", json={"leave_type": "half_day_am", "start_date": D1}, headers=self.h1)
        mine = self.client.get("/api/v1/leave", headers=self.h2).json()
        self.assertEqual(mine, [], "李四不应看到张三的请假")
        as_admin = self.client.get("/api/v1/leave", headers=self.ha).json()
        self.assertEqual(len(as_admin), 1, "管理员可查全部")

    def test_therapist_cannot_record_leave_for_others(self) -> None:
        resp = self.client.post(
            "/api/v1/leave",
            json={"leave_type": "half_day_am", "start_date": D1, "therapist_id": int(self.t2["id"])},
            headers=self.h1,
        )
        self.assert_error(resp, 403, "LEAVE_OTHER_THERAPIST")

    def test_admin_entry_records_source(self) -> None:
        resp = self.client.post(
            "/api/v1/leave/admin",
            json={"leave_type": "half_day_am", "start_date": D1, "therapist_id": int(self.t1["id"])},
            headers=self.ha,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual(body["source"], "admin_entry")
        self.assertEqual(body["created_by_name"], "管理员")

    def test_admin_entry_requires_therapist_id(self) -> None:
        resp = self.client.post(
            "/api/v1/leave/admin", json={"leave_type": "half_day_am", "start_date": D1}, headers=self.ha
        )
        self.assert_error(resp, 404, "THERAPIST_REQUIRED")

    def test_therapist_cannot_cancel_others_leave(self) -> None:
        leave = self.client.post(
            "/api/v1/leave", json={"leave_type": "half_day_am", "start_date": D1}, headers=self.h1
        ).json()
        resp = self.client.post(f"/api/v1/leave/{leave['id']}/cancel", json={}, headers=self.h2)
        self.assert_error(resp, 403, "LEAVE_OTHER_THERAPIST")

    def test_leave_enums_endpoint(self) -> None:
        body = self.client.get("/api/v1/leave/enums", headers=self.h1).json()
        self.assertEqual(body["leave_types"], ["half_day_am", "half_day_pm", "full_day", "multi_day"])
        self.assertEqual(body["leave_sources"], ["therapist_self", "admin_entry"])


class TestLeaveSideEffectsAtModelLevel(ScheduleTestCase):
    """直接验证模型层的到期清理与撤销回滚，不经过 HTTP。"""

    def test_close_expired_temporary_assignments(self) -> None:
        leave_model.create_leave(
            self.conn, therapist_id=int(self.t1["id"]), leave_type="half_day_am",
            start_date=D1, end_date=D1, operator_user_id=int(self.t1["id"]),
        )
        self.assertEqual(leave_model.close_expired_temporary_assignments(self.conn), 0, "未来的假不该被清理")

        # 手动把到期时间改成过去，模拟时间流逝
        self.conn.execute(
            "UPDATE temporary_assignment SET expires_at = '2020-01-01T00:00:00.000Z' WHERE status = 'open'"
        )
        self.assertEqual(leave_model.close_expired_temporary_assignments(self.conn), 1)
        row = self.conn.execute("SELECT status, closed_reason FROM temporary_assignment").fetchone()
        self.assertEqual((row["status"], row["closed_reason"]), ("closed", "expired"))

    def test_expired_temp_no_longer_affects_visibility(self) -> None:
        """过期后可见归属自动回到原归属——不依赖定时任务是否跑过（R8）。"""
        leave_model.create_leave(
            self.conn, therapist_id=int(self.t1["id"]), leave_type="half_day_am",
            start_date=D1, end_date=D1, operator_user_id=int(self.t1["id"]),
        )
        # 到期前：临时释放
        self.conn.execute(
            "UPDATE temporary_assignment SET expires_at = '2099-01-01T00:00:00.000Z'"
        )
        self.assertIsNone(patient_model.get_patient_or_raise(self.conn, "ZY001")["visible_therapist_id"])

        # 到期后（即使没跑清理任务）：回落到原归属。
        # 注意用明确的过去时间，不要用 utc_timestamp_now()：视图的条件是严格大于，
        # 而 leave 的 start_date 是未来日期，用"现在"会让临时指派落在请假区间之前而不生效。
        self.conn.execute("UPDATE temporary_assignment SET expires_at = '2020-01-01T00:00:00.000Z'")
        patient = patient_model.get_patient_or_raise(self.conn, "ZY001")
        self.assertEqual(patient["visible_therapist_id"], int(self.t1["id"]))
        self.assertEqual(patient["visibility_state"], "assigned")

    def test_period_expiry_uses_q11_boundaries(self) -> None:
        """到期的 UTC 时间戳要对应 Q11 的本地墙钟 11:30 / 17:30 / 次日 00:00。"""
        from datetime import datetime

        am = period_expiry(date(2027, 3, 1), "am", WorkTimeConfig())
        pm = period_expiry(date(2027, 3, 1), "pm", WorkTimeConfig())
        full = period_expiry(date(2027, 3, 1), "full", WorkTimeConfig())

        for value in (am, pm, full):
            self.assertTrue(value.endswith("Z"), f"{value} 必须是 UTC Z 格式")

        # 本机时区 +08:00：本地 11:30 → UTC 03:30；本地 17:30 → UTC 09:30。
        # offset_hours 是本地相对 UTC 的偏移（+08:00 → 8），UTC = 本地 - 偏移。
        offset_hours = int(datetime.now().astimezone().utcoffset().total_seconds() // 3600)  # type: ignore[union-attr]

        def utc_hm(value: str) -> tuple[int, int]:
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
            return parsed.hour, parsed.minute

        self.assertEqual(utc_hm(am), ((11 - offset_hours) % 24, 30))
        self.assertEqual(utc_hm(pm), ((17 - offset_hours) % 24, 30))
        # 全天假 → 次日 00:00 本地
        self.assertEqual(utc_hm(full), ((0 - offset_hours) % 24, 0))

    def test_cancel_closes_temp_assignment(self) -> None:
        leave = leave_model.create_leave(
            self.conn, therapist_id=int(self.t1["id"]), leave_type="half_day_am",
            start_date=D1, end_date=D1, operator_user_id=int(self.t1["id"]),
        )
        result = leave_model.cancel_leave(self.conn, int(leave["id"]), operator_user_id=int(self.t1["id"]))
        self.assertEqual(result["status"], "cancelled")
        row = self.conn.execute("SELECT status, closed_reason FROM temporary_assignment").fetchone()
        self.assertEqual(row["status"], "closed")
        self.assertEqual(row["closed_reason"], "leave_cancelled")


class TestCopySchedule(ScheduleTestCase):
    def test_copy_yesterday(self) -> None:
        target = date(2027, 3, 2)
        source = target - timedelta(days=1)
        appointment_model.create_appointment(
            self.conn, patient_no="ZY001", therapist_id=int(self.t1["id"]),
            day=source.isoformat(), period="am",
        )
        resp = self.client.post(
            "/api/v1/schedule/copy",
            json={"mode": "yesterday", "target_date": target.isoformat()},
            headers=self.h1,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(len(body["created"]), 1)
        self.assertEqual(body["source_date"], source.isoformat())
        self.assertEqual(body["target_date"], target.isoformat())

    def test_copy_skips_conflicting_slots(self) -> None:
        """冲突格子跳过并回报，不整体失败。"""
        target = date(2027, 3, 2)
        source = target - timedelta(days=1)
        appointment_model.create_appointment(
            self.conn, patient_no="ZY001", therapist_id=int(self.t1["id"]),
            day=source.isoformat(), period="am",
        )
        # 目标日同一半日先占掉
        appointment_model.create_appointment(
            self.conn, patient_no="ZY003", therapist_id=int(self.t1["id"]),
            day=target.isoformat(), period="am",
        )
        resp = self.client.post(
            "/api/v1/schedule/copy",
            json={"mode": "yesterday", "target_date": target.isoformat()},
            headers=self.h1,
        )
        body = resp.json()
        self.assertEqual(len(body["created"]), 0)
        self.assertEqual(len(body["skipped"]), 1)
        self.assertEqual(body["skipped"][0]["reason"], "CONFLICT")

    def test_copy_last_week(self) -> None:
        target = date(2027, 3, 8)
        source = target - timedelta(days=7)
        appointment_model.create_appointment(
            self.conn, patient_no="ZY001", therapist_id=int(self.t1["id"]),
            day=source.isoformat(), period="pm",
        )
        body = self.client.post(
            "/api/v1/schedule/copy",
            json={"mode": "last_week", "target_date": target.isoformat()},
            headers=self.h1,
        ).json()
        self.assertEqual(len(body["created"]), 1)
        self.assertEqual(body["created"][0]["period"], "pm")

    def test_invalid_mode_rejected(self) -> None:
        resp = self.client.post("/api/v1/schedule/copy", json={"mode": "tomorrow"}, headers=self.h1)
        self.assert_error(resp, 404, "INVALID_MODE")


class TestAppointmentModelGuards(ScheduleTestCase):
    """模型层的直接校验（不经过 HTTP），确保非法输入被拦在写库之前。"""

    def test_unknown_status_rejected(self) -> None:
        with self.assertRaises(Invalid):
            appointment_model.create_appointment(
                self.conn, patient_no="ZY001", therapist_id=int(self.t1["id"]),
                day=D1, period="am", status="whatever",
            )

    def test_unknown_patient_raises_not_found(self) -> None:
        from app.models.base import NotFound

        with self.assertRaises(NotFound):
            appointment_model.create_appointment(
                self.conn, patient_no="NOPE", therapist_id=int(self.t1["id"]), day=D1, period="am"
            )

    def test_conflict_raised_when_slot_taken(self) -> None:
        appointment_model.create_appointment(
            self.conn, patient_no="ZY001", therapist_id=int(self.t1["id"]), day=D1, period="am"
        )
        with self.assertRaises(Conflict):
            appointment_model.create_appointment(
                self.conn, patient_no="ZY003", therapist_id=int(self.t1["id"]), day=D1, period="am"
            )

    def test_leave_validation_covers_types_and_spans(self) -> None:
        with self.assertRaises(Invalid):
            leave_model.create_leave(
                self.conn, therapist_id=int(self.t1["id"]), leave_type="vacation",
                start_date=D1, end_date=D2, operator_user_id=int(self.t1["id"]),
            )
        with self.assertRaises(Invalid):
            leave_model.create_leave(
                self.conn, therapist_id=int(self.t1["id"]), leave_type="multi_day",
                start_date=D2, end_date=D1, operator_user_id=int(self.t1["id"]),
            )

    def test_rest_block_weekday_out_of_range(self) -> None:
        with self.assertRaises(Invalid):
            rest_block_model.create_rest_block(
                self.conn, therapist_id=int(self.t1["id"]), scope="weekly", weekday=9, period="am"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
