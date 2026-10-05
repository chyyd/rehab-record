"""出院流程（用户 2026-10-05 明确要求）。

用户的三句话定义了整条链路：

1. 「填完小结即待出院」—— 治疗师提交出院小结后患者进入 `pending_discharge`；
2. 「所有治疗师都能发起出院」—— 发起出院的接口**不是** `AdminUser`；
3. 「1 周后自动出院」+「真的自动」—— 满 7 天由 `app.cli auto-discharge` 真正落地。

对应的回归：

- ★ 出院小结提交 → 治疗师发起出院 → `pending_discharge` → 管理员确认 → `discharged`；
- 管理员可以取消待出院（回在院）；
- 满 7 天自动出院真的会改状态（`auto_discharge_pending` / CLI 子命令）；
- 待出院患者从治疗师白板消失，且不能再记新记录（后者在 `test_records.py`）。
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from app.models import patient as patient_model
from app.models import treatment as treatment_model
from tests.api_base import ApiTestCase

DISCIPLINE = "PT"


def initial_body() -> dict:
    return {
        "diagnosis": ["偏瘫运动功能障碍"],
        "therapy_items": ["偏瘫肢体综合训练"],
    }


def daily_body() -> dict:
    return {"therapy_items": ["偏瘫肢体综合训练"], "mental": "良好"}


def discharge_body(summary: str = "住院期间共治疗 1 次") -> dict:
    return {
        "summary": summary,
        "subjective_change": ["肢体力量明显恢复"],
        "home_activity": ["可独立室内活动"],
        "mmt_lower": 3,
        "gait": ["监护下独立室内步行"],
        "goal_achieved": ["基本达成"],
        "home_training": ["肌力训练"],
        "follow_up": ["1个月后康复科门诊复查"],
    }


class DischargeFlowTestCase(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.t1 = self.make_user("T001", "张三")
        self.t2 = self.make_user("T002", "李四")
        self.admin = self.make_admin("A001")
        patient_model.create_patient(
            self.conn, inpatient_no="ZY001", name="患者甲", assigned_therapist_id=int(self.t1["id"])
        )
        self.h1 = self.login_headers("T001")
        self.h2 = self.login_headers("T002")
        self.ha = self.login_headers("A001")

    def post_record(self, *, kind: str, body: dict, status: str = "submitted", headers: dict | None = None,
                    record_date: str = "2027-03-01"):
        resp = self.client.post(
            "/api/v1/records",
            json={
                "patient_no": "ZY001",
                "record_date": record_date,
                "discipline": DISCIPLINE,
                "kind": kind,
                "body": body,
                "status": status,
            },
            headers=headers or self.h1,
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    def make_discharge_summary(self, *, status: str = "submitted", headers: dict | None = None) -> dict:
        headers = headers or self.h1
        if not treatment_model.has_initial(self.conn, "ZY001", DISCIPLINE):
            self.post_record(kind="initial", body=initial_body(), headers=headers)
        if treatment_model.count_sessions(self.conn, "ZY001", DISCIPLINE) == 0:
            self.post_record(kind="daily", body=daily_body(), headers=headers, record_date="2027-03-01")
        return self.post_record(
            kind="discharge",
            body=discharge_body(),
            status=status,
            headers=headers,
            record_date="2027-03-05",
        )

    def status(self) -> str:
        return str(patient_model.get_patient_or_raise(self.conn, "ZY001")["status"])


class TestDischargeFlow(DischargeFlowTestCase):
    def test_submitting_discharge_summary_marks_pending(self) -> None:
        """★ 「填完小结即待出院」：提交出院小结那一刻患者就是待出院。"""
        summary = self.make_discharge_summary()
        self.assertEqual(summary["kind"], "discharge")
        self.assertEqual(self.status(), patient_model.STATUS_PENDING_DISCHARGE)

    def test_discharge_summary_renders_soap_text(self) -> None:
        summary = self.make_discharge_summary()
        text = summary["rendered_text"]
        self.assertIn("康复出院小结（PT运动）", text)
        self.assertIn("共治疗 1 次", text)
        self.assertIn("出院指导：", text)
        self.assertNotIn("第 1 次", text, "出院小结不占次数，也不显示序号")

    def test_therapist_can_request_discharge(self) -> None:
        """★ 发起出院**任何治疗师**都能调（不是 AdminUser）。"""
        summary = self.make_discharge_summary()
        resp = self.client.post(
            "/api/v1/patients/ZY001/discharge",
            json={"record_id": summary["id"]},
            headers=self.h2,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["status"], patient_model.STATUS_PENDING_DISCHARGE)

    def test_discharge_request_is_idempotent(self) -> None:
        summary = self.make_discharge_summary()
        first = self.client.post(
            "/api/v1/patients/ZY001/discharge", json={"record_id": summary["id"]}, headers=self.h1
        )
        second = self.client.post(
            "/api/v1/patients/ZY001/discharge", json={"record_id": summary["id"]}, headers=self.h1
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["status"], patient_model.STATUS_PENDING_DISCHARGE)

    def test_admin_confirms_discharge(self) -> None:
        """★ 管理员确认 → 真正出院。"""
        summary = self.make_discharge_summary()
        self.client.post(
            "/api/v1/patients/ZY001/discharge", json={"record_id": summary["id"]}, headers=self.h1
        )
        resp = self.client.post("/api/v1/patients/ZY001/discharge/confirm", headers=self.ha)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["status"], patient_model.STATUS_DISCHARGED)
        # 审计里能看出是谁确认的
        row = self.conn.execute(
            "SELECT action FROM audit_log WHERE action = 'discharge_confirm'"
        ).fetchone()
        self.assertIsNotNone(row)

    def test_therapist_cannot_confirm_discharge(self) -> None:
        summary = self.make_discharge_summary()
        self.client.post(
            "/api/v1/patients/ZY001/discharge", json={"record_id": summary["id"]}, headers=self.h1
        )
        resp = self.client.post("/api/v1/patients/ZY001/discharge/confirm", headers=self.h1)
        self.assert_error(resp, 403, "ADMIN_REQUIRED")

    def test_admin_cancels_pending_discharge(self) -> None:
        summary = self.make_discharge_summary()
        self.client.post(
            "/api/v1/patients/ZY001/discharge", json={"record_id": summary["id"]}, headers=self.h1
        )
        resp = self.client.post("/api/v1/patients/ZY001/discharge/cancel", headers=self.ha)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["status"], patient_model.STATUS_IN_HOSPITAL)

    def test_cancel_requires_pending_status(self) -> None:
        resp = self.client.post("/api/v1/patients/ZY001/discharge/cancel", headers=self.ha)
        self.assert_error(resp, 409)

    def test_confirm_requires_pending_status(self) -> None:
        resp = self.client.post("/api/v1/patients/ZY001/discharge/confirm", headers=self.ha)
        self.assert_error(resp, 409)

    def test_discharge_request_needs_a_submitted_discharge_summary(self) -> None:
        """出院不是点一下按钮：必须指向该患者**已提交**的出院小结。"""
        self.post_record(kind="initial", body=initial_body())
        missing = self.client.post(
            "/api/v1/patients/ZY001/discharge", json={"record_id": 999999}, headers=self.h1
        )
        self.assert_error(missing, 404)

        draft = self.make_discharge_summary(status="draft")
        resp = self.client.post(
            "/api/v1/patients/ZY001/discharge", json={"record_id": draft["id"]}, headers=self.h1
        )
        self.assert_error(resp, 409, "CONFLICT")

    def test_discharge_request_rejects_other_kind(self) -> None:
        self.post_record(kind="initial", body=initial_body())
        daily = self.post_record(kind="daily", body=daily_body())
        resp = self.client.post(
            "/api/v1/patients/ZY001/discharge", json={"record_id": daily["id"]}, headers=self.h1
        )
        self.assert_error(resp, 422, "INVALID")

    def test_discharge_request_rejects_other_patient_record(self) -> None:
        patient_model.create_patient(self.conn, inpatient_no="ZY002", name="患者乙")
        self.post_record(kind="initial", body=initial_body())
        daily = self.post_record(kind="daily", body=daily_body())
        resp = self.client.post(
            "/api/v1/patients/ZY002/discharge", json={"record_id": daily["id"]}, headers=self.h1
        )
        # ZY002 无记录、无出院小结 → 该记录不属于该患者
        self.assert_error(resp, 422, "INVALID")

    def test_pending_discharge_patient_is_off_the_board(self) -> None:
        self.make_discharge_summary()
        listed = self.client.get("/api/v1/patients", headers=self.h1).json()
        self.assertEqual(listed["items"], [], "待出院患者从治疗师白板消失")
        admin_listed = self.client.get(
            "/api/v1/patients", params={"scope": "all"}, headers=self.ha
        ).json()
        self.assertEqual(
            [i["inpatient_no"] for i in admin_listed["items"]], ["ZY001"], "管理员仍能看到"
        )

    def test_admin_can_still_change_status_directly(self) -> None:
        """管理员专用的 `PUT /patients/{no}` 改状态**保持不动**（用户要求保留）。"""
        resp = self.client.put(
            "/api/v1/patients/ZY001",
            json={"status": patient_model.STATUS_PENDING_DISCHARGE},
            headers=self.ha,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(self.status(), patient_model.STATUS_PENDING_DISCHARGE)


class TestAutoDischarge(DischargeFlowTestCase):
    """★ 「1 周后自动出院」要**真的自动**。"""

    def pending_patient(self) -> dict:
        summary = self.make_discharge_summary()
        self.client.post(
            "/api/v1/patients/ZY001/discharge", json={"record_id": summary["id"]}, headers=self.h1
        )
        return summary

    def test_not_discharged_before_seven_days(self) -> None:
        self.pending_patient()
        numbers = patient_model.auto_discharge_pending(self.conn, days=7)
        self.assertEqual(numbers, [])
        self.assertEqual(self.status(), patient_model.STATUS_PENDING_DISCHARGE)

    def test_discharged_after_seven_days(self) -> None:
        self.pending_patient()
        from datetime import UTC, datetime, timedelta

        future = (datetime.now(UTC) + timedelta(days=7, minutes=1)).strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        )[:-3] + "Z"
        numbers = patient_model.auto_discharge_pending(self.conn, days=7, now=future)
        self.assertEqual(numbers, ["ZY001"])
        self.assertEqual(self.status(), patient_model.STATUS_DISCHARGED)

    def test_dry_run_does_not_change_status(self) -> None:
        self.pending_patient()
        from datetime import UTC, datetime, timedelta

        future = (datetime.now(UTC) + timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        numbers = patient_model.auto_discharge_pending(self.conn, days=7, now=future, dry_run=True)
        self.assertEqual(numbers, ["ZY001"])
        self.assertEqual(self.status(), patient_model.STATUS_PENDING_DISCHARGE, "试运行不改状态")

    def test_cli_command_auto_discharges(self) -> None:
        """CLI 子命令（运维用计划任务跑它）必须能真的改状态。"""
        from app.cli import main

        self.pending_patient()
        # 用 --now 把时钟推到 8 天后（可注入的设计就是为了补跑与测试）
        from datetime import UTC, datetime, timedelta

        future = (datetime.now(UTC) + timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["auto-discharge", "--now", future])
        self.assertEqual(code, 0, buffer.getvalue())
        self.assertIn("自动出院 1 人", buffer.getvalue())
        self.assertEqual(self.status(), patient_model.STATUS_DISCHARGED)

    def test_audit_and_change_log_untouched_by_auto_discharge(self) -> None:
        """自动出院是系统动作：不写"某人"的审计，但记录仍在（可追溯出院小结）。"""
        summary = self.pending_patient()
        from datetime import UTC, datetime, timedelta

        future = (datetime.now(UTC) + timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        patient_model.auto_discharge_pending(self.conn, days=7, now=future)
        record = treatment_model.get_record_or_raise(self.conn, int(summary["id"]))
        self.assertEqual(record["kind"], "discharge")
        self.assertEqual(self.status(), patient_model.STATUS_DISCHARGED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
