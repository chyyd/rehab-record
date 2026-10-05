"""治疗记录接口测试（SOAP 模板驱动，迁移 011 之后的新模型）。

覆盖重点（★ 为用户明确要求、必须有回归的行为）：

1. ★ **首评不占次数**：首评 + 当天日常 → 日常是第 1 次；
2. ★ **评估文书硬阻断**：第 1 次日常缺首评 → 409；第 21 次缺复评 → 409；
3. ★ **同一天同一大类至多 2 条**；
4. ★ **待出院患者不能记新记录**；
5. ★ **`rendered_text` 冻结**：改了模板 JSON 后旧记录的文本不变；
6. ★ **必填校验**：缺「功能诊断」「本次训练项目」→ 422；
7. 表单接口（`GET /records/form`）：该填哪份文书、预填、`existing`；
8. 状态机（草稿 → 已提交 → 已锁定）与权限边界、删除草稿写 `change_log`。
"""

from __future__ import annotations

import unittest

from app.models import patient as patient_model
from app.models import treatment as treatment_model
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


class RecordTestCase(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.t1 = self.make_user("T001", "张三")
        self.t2 = self.make_user("T002", "李四")
        self.admin = self.make_admin("A001")
        patient_model.create_patient(
            self.conn,
            inpatient_no="ZY001",
            name="患者甲",
            diagnosis="脑卒中恢复期",
            assigned_therapist_id=int(self.t1["id"]),
        )
        patient_model.create_patient(
            self.conn, inpatient_no="ZY002", name="患者乙", assigned_therapist_id=int(self.t2["id"])
        )
        self.h1 = self.login_headers("T001")
        self.h2 = self.login_headers("T002")
        self.ha = self.login_headers("A001")

    # -- 便捷方法 ---------------------------------------------------------- #
    def create(
        self,
        *,
        kind: str = "daily",
        record_date: str = "2027-03-01",
        body: dict | None = None,
        status: str = "submitted",
        headers: dict | None = None,
        patient_no: str = "ZY001",
        discipline: str = DISCIPLINE,
    ):
        return self.client.post(
            "/api/v1/records",
            json={
                "patient_no": patient_no,
                "record_date": record_date,
                "discipline": discipline,
                "kind": kind,
                "body": body if body is not None else daily_body(),
                "status": status,
            },
            headers=headers or self.h1,
        )

    def create_ok(self, **kwargs) -> dict:
        resp = self.create(**kwargs)
        self.assertEqual(resp.status_code, 201, resp.text)
        return resp.json()

    def seed_daily(self, count: int, *, headers: dict | None = None) -> None:
        """直接落库造 N 条日常记录（跳过门禁，用于构造第 21 次这类场景）。"""
        for index in range(1, count + 1):
            self.conn.execute(
                "INSERT INTO treatment_record"
                " (patient_no, therapist_id, record_date, discipline, kind, seq_no, body_json,"
                "  rendered_text, status)"
                " VALUES ('ZY001', ?, ?, ?, 'daily', ?, '{}', '', 'submitted')",
                (int(self.t1["id"]), f"2027-01-{index:02d}" if index <= 28 else "2027-02-01", DISCIPLINE, index),
            )


class TestAssessmentDoesNotCount(RecordTestCase):
    """★ 用户 2026-10-05：「评定并不占用日常训练的次数」。"""

    def test_initial_then_daily_is_first_session(self) -> None:
        initial = self.create_ok(kind="initial", body=initial_body())
        self.assertIsNone(initial["seq_no"], "首评不占次数")
        self.assertEqual(initial["span_seq"], 1, "首评挂靠第 1 次日常")
        self.assertEqual(initial["rendered_text"].startswith("康复初始评定"), True)

        daily = self.create_ok(kind="daily", body=daily_body())
        self.assertEqual(daily["seq_no"], 1, "首评之后当天的日常记录仍是第 1 次")
        self.assertIsNone(daily["span_seq"])

    def test_reassessment_does_not_consume_a_session(self) -> None:
        self.seed_daily(20)
        self.conn.execute(
            "INSERT INTO treatment_record"
            " (patient_no, therapist_id, record_date, discipline, kind, span_seq, body_json,"
            "  rendered_text, status)"
            " VALUES ('ZY001', ?, '2027-01-01', 'PT', 'initial', 1, '{}', '', 'submitted')",
            (int(self.t1["id"]),),
        )
        reassessment = self.create_ok(
            kind="reassessment", record_date="2027-03-01", body=reassessment_body()
        )
        self.assertIsNone(reassessment["seq_no"])
        self.assertEqual(reassessment["span_seq"], 21)

        daily = self.create_ok(kind="daily", record_date="2027-03-01", body=daily_body())
        self.assertEqual(daily["seq_no"], 21, "第 21 次日常与复评并存")

    def test_seq_no_is_per_discipline(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        self.create_ok(kind="daily", body=daily_body())
        # 换一个大类：重新从"缺首评"开始，所以这里先给该大类首评
        self.create_ok(
            kind="initial",
            discipline="OT",
            body={"diagnosis": ["日常生活活动能力障碍"], "therapy_items": ["日常生活能力训练"]},
        )
        ot_daily = self.create_ok(
            kind="daily",
            discipline="OT",
            body={"therapy_items": ["日常生活能力训练"]},
        )
        self.assertEqual(ot_daily["seq_no"], 1, "四大类分开计数")


class TestAssessmentGate(RecordTestCase):
    """★ 三份评估文书都是**硬阻断**，不能跳过（用户：「1A。2不能。3不能。」）。"""

    def test_first_daily_without_initial_is_blocked(self) -> None:
        resp = self.create(kind="daily")
        self.assert_error(resp, 409, "MISSING_ASSESSMENT")
        self.assertEqual(resp.json()["details"]["missing_document"], "initial")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM treatment_record").fetchone()[0], 0,
            "被拦下的请求不得留下任何记录",
        )

    def test_21st_daily_without_reassessment_is_blocked(self) -> None:
        self.seed_daily(20)
        self.conn.execute(
            "INSERT INTO treatment_record"
            " (patient_no, therapist_id, record_date, discipline, kind, span_seq, body_json,"
            "  rendered_text, status)"
            " VALUES ('ZY001', ?, '2027-01-01', 'PT', 'initial', 1, '{}', '', 'submitted')",
            (int(self.t1["id"]),),
        )
        resp = self.create(kind="daily", record_date="2027-03-01")
        self.assert_error(resp, 409, "MISSING_ASSESSMENT")
        self.assertEqual(resp.json()["details"]["missing_document"], "reassessment")
        self.assertEqual(resp.json()["details"]["next_seq"], 21)

        # 补上复评之后就能记了
        self.create_ok(kind="reassessment", record_date="2027-03-01", body=reassessment_body())
        daily = self.create_ok(kind="daily", record_date="2027-03-01")
        self.assertEqual(daily["seq_no"], 21)

    def test_second_initial_for_same_span_is_rejected(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        resp = self.create(kind="initial", record_date="2027-03-02", body=initial_body())
        self.assert_error(resp, 409, "ASSESSMENT_ALREADY_EXISTS")

    def test_gate_allows_plain_daily_sessions(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        for day in ("2027-03-01", "2027-03-02", "2027-03-03"):
            record = self.create_ok(kind="daily", record_date=day)
            self.assertIsNotNone(record["seq_no"])


class TestSameDayLimit(RecordTestCase):
    """★ 用户：「同一天同一大类只允许至多 2 条」。"""

    def test_two_records_on_same_day_are_allowed(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        self.create_ok(kind="daily", body=daily_body())
        kinds = [
            row["kind"]
            for row in self.conn.execute(
                "SELECT kind FROM treatment_record ORDER BY id"
            ).fetchall()
        ]
        self.assertEqual(kinds, ["initial", "daily"], "首评 + 日常 = 当天 2 条")

    def test_third_record_on_same_day_is_rejected(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        self.create_ok(kind="daily", body=daily_body())
        resp = self.create(kind="daily", body=daily_body(vas=3))
        self.assert_error(resp, 409)
        details = resp.json()["details"]
        self.assertEqual(details["limit"], 2)
        self.assertEqual(details["date"], "2027-03-01")
        self.assertEqual(details["discipline"], "PT")

    def test_next_day_is_not_limited(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        self.create_ok(kind="daily", body=daily_body())
        self.create_ok(kind="daily", record_date="2027-03-02", body=daily_body())


class TestPendingDischargeBlock(RecordTestCase):
    """★ 待出院患者不能记新记录（用户：「填完小结即待出院」）。"""

    def test_pending_discharge_patient_cannot_get_new_record(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        self.create_ok(kind="daily", body=daily_body())
        patient_model.update_patient(
            self.conn, "ZY001", status=patient_model.STATUS_PENDING_DISCHARGE
        )
        resp = self.create(kind="daily", record_date="2027-03-05", body=daily_body())
        self.assert_error(resp, 409, "PATIENT_PENDING_DISCHARGE")

    def test_pending_discharge_patient_disappears_from_board(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        patient_model.update_patient(
            self.conn, "ZY001", status=patient_model.STATUS_PENDING_DISCHARGE
        )
        listed = self.client.get("/api/v1/patients", headers=self.h1).json()
        self.assertNotIn("ZY001", {item["inpatient_no"] for item in listed["items"]})


class TestRequiredFields(RecordTestCase):
    """★ 必填校验：缺「功能诊断」「本次训练项目」→ 422。"""

    def test_missing_diagnosis_is_rejected(self) -> None:
        body = initial_body()
        body.pop("diagnosis")
        resp = self.create(kind="initial", body=body)
        self.assert_error(resp, 422, "INVALID")
        self.assertIn("功能诊断", resp.json()["details"]["missing"])

    def test_missing_therapy_items_is_rejected(self) -> None:
        body = initial_body()
        body.pop("therapy_items")
        resp = self.create(kind="initial", body=body)
        self.assert_error(resp, 422, "INVALID")
        self.assertIn("本次训练项目", resp.json()["details"]["missing"])

    def test_empty_multi_select_counts_as_missing(self) -> None:
        resp = self.create(kind="initial", body=initial_body(therapy_items=[]))
        self.assert_error(resp, 422, "INVALID")
        self.assertIn("本次训练项目", resp.json()["details"]["missing"])

    def test_valid_body_passes(self) -> None:
        self.create_ok(kind="initial", body=initial_body())

    def test_daily_body_also_requires_therapy_items(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        body = daily_body()
        body.pop("therapy_items")
        resp = self.create(kind="daily", body=body)
        self.assert_error(resp, 422, "INVALID")
        self.assertIn("本次训练项目", resp.json()["details"]["missing"])


class TestRenderedTextFrozen(RecordTestCase):
    """★ `rendered_text` 冻结：改了模板 JSON 之后，旧记录的文本**不变**。"""

    def test_old_record_text_survives_template_edit(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        record = self.create_ok(kind="daily", body=daily_body())
        original_text = record["rendered_text"]
        self.assertIn("本次训练项目：偏瘫肢体综合训练", original_text)

        # 手改模板：日常记录的标题与字段标签都换掉（用户会这么做）
        template_file = record_template.template_path(DISCIPLINE, "daily")
        original_json = template_file.read_text(encoding="utf-8")
        try:
            edited = original_json.replace("康复治疗记录（PT运动）", "康复治疗记录（改过的标题）")
            edited = edited.replace('"label": "疼痛VAS"', '"label": "疼痛评分VAS"')
            template_file.write_text(edited, encoding="utf-8")
            record_template.clear_cache()

            reread = self.client.get(f"/api/v1/records/{record['id']}", headers=self.h1).json()
            self.assertEqual(reread["rendered_text"], original_text, "已落库的文本必须原样返回")
            self.assertNotIn("改过的标题", reread["rendered_text"])
        finally:
            template_file.write_text(original_json, encoding="utf-8")
            record_template.clear_cache()

    def test_new_record_after_edit_uses_new_template(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        first = self.create_ok(kind="daily", body=daily_body())
        template_file = record_template.template_path(DISCIPLINE, "daily")
        original_json = template_file.read_text(encoding="utf-8")
        try:
            template_file.write_text(
                original_json.replace("康复治疗记录（PT运动）", "康复治疗记录（新标题）"),
                encoding="utf-8",
            )
            record_template.clear_cache()
            second = self.create_ok(kind="daily", record_date="2027-03-02", body=daily_body())
            self.assertIn("新标题", second["rendered_text"])
            self.assertNotEqual(second["rendered_text"], first["rendered_text"])
        finally:
            template_file.write_text(original_json, encoding="utf-8")
            record_template.clear_cache()

    def test_rendered_text_is_regenerated_when_body_changes(self) -> None:
        """冻结的是"生成那一刻"，不是"永不更新"：当前这条记录改内容要跟着重渲染。"""
        self.create_ok(kind="initial", body=initial_body())
        record = self.create_ok(kind="daily", body=daily_body(), status="draft")
        self.assertNotIn("疼痛VAS：9分", record["rendered_text"])
        updated = self.client.put(
            f"/api/v1/records/{record['id']}",
            json={"body": daily_body(vas=9)},
            headers=self.h1,
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertIn("疼痛VAS：9分", updated.json()["rendered_text"])


class TestRecordLifecycle(RecordTestCase):
    def test_create_draft_keeps_seq_no(self) -> None:
        """库层 CHECK 要求日常记录一落库就带序号（否则唯一索引无法约束重复编号）。"""
        self.create_ok(kind="initial", body=initial_body())
        draft = self.create_ok(kind="daily", status="draft")
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(draft["seq_no"], 1, "草稿也占号 —— CHECK 与唯一索引都建立在它上面")

    def test_submit_and_lock(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        record = self.create_ok(kind="daily", status="draft")
        submitted = self.client.post(f"/api/v1/records/{record['id']}/submit", headers=self.h1)
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.assertEqual(submitted.json()["status"], "submitted")
        self.assertIsNotNone(submitted.json()["submitted_at"])

        locked = self.client.post(f"/api/v1/records/{record['id']}/lock", headers=self.ha)
        self.assertEqual(locked.status_code, 200, locked.text)
        self.assertEqual(locked.json()["status"], "locked")

    def test_double_submit_rejected(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        record = self.create_ok(kind="daily")
        resp = self.client.post(f"/api/v1/records/{record['id']}/submit", headers=self.h1)
        self.assert_error(resp, 409)

    def test_draft_cannot_be_locked_directly(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        record = self.create_ok(kind="daily", status="draft")
        resp = self.client.post(f"/api/v1/records/{record['id']}/lock", headers=self.ha)
        self.assert_error(resp, 409)

    def test_locked_record_cannot_be_edited_by_therapist(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        record = self.create_ok(kind="daily")
        self.client.post(f"/api/v1/records/{record['id']}/lock", headers=self.ha)
        resp = self.client.put(
            f"/api/v1/records/{record['id']}", json={"body": daily_body(vas=5)}, headers=self.h1
        )
        self.assert_error(resp, 403, "RECORD_LOCKED")

    def test_admin_can_edit_locked_record(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        record = self.create_ok(kind="daily")
        self.client.post(f"/api/v1/records/{record['id']}/lock", headers=self.ha)
        resp = self.client.put(
            f"/api/v1/records/{record['id']}", json={"body": daily_body(vas=5)}, headers=self.ha
        )
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_submitted_edit_is_audited_and_counted(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        record = self.create_ok(kind="daily")
        updated = self.client.put(
            f"/api/v1/records/{record['id']}", json={"body": daily_body(vas=4)}, headers=self.h1
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["edit_count"], 1, "库层触发器应累加 edit_count")

    def test_invalid_status_rejected(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        record = self.create_ok(kind="daily", status="draft")
        resp = self.client.put(
            f"/api/v1/records/{record['id']}", json={"status": "whatever"}, headers=self.h1
        )
        self.assert_error(resp, 422, "INVALID")

    def test_update_unknown_record_is_404(self) -> None:
        resp = self.client.put("/api/v1/records/99999", json={"status": "draft"}, headers=self.h1)
        self.assert_error(resp, 404, "NOT_FOUND")

    def test_status_cannot_jump_backwards(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        record = self.create_ok(kind="daily")
        self.client.post(f"/api/v1/records/{record['id']}/lock", headers=self.ha)
        resp = self.client.put(
            f"/api/v1/records/{record['id']}", json={"status": "draft"}, headers=self.ha
        )
        self.assert_error(resp, 409)

    def test_delete_draft_writes_change_log(self) -> None:
        """★ 删除草稿必须写 `change_log(op='delete')`，否则离线端会留下幻影记录。"""
        self.create_ok(kind="initial", body=initial_body())
        draft = self.create_ok(kind="daily", status="draft")
        resp = self.client.delete(f"/api/v1/records/{draft['id']}", headers=self.h1)
        self.assertEqual(resp.status_code, 204, resp.text)

        row = self.conn.execute(
            "SELECT op, entity, entity_id FROM change_log WHERE entity = 'treatment_record'"
            "   AND op = 'delete'"
        ).fetchone()
        self.assertIsNotNone(row, "删除草稿必须进 change_log")
        self.assertEqual(row["entity_id"], str(draft["id"]))

    def test_only_draft_can_be_deleted(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        submitted = self.create_ok(kind="daily")
        resp = self.client.delete(f"/api/v1/records/{submitted['id']}", headers=self.h1)
        self.assert_error(resp, 409)

    def test_cannot_delete_others_draft(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        draft = self.create_ok(kind="daily", status="draft")
        resp = self.client.delete(f"/api/v1/records/{draft['id']}", headers=self.h2)
        self.assert_error(resp, 403)

    def test_detail_returns_body_and_rendered_text(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        record = self.create_ok(kind="daily")
        detail = self.client.get(f"/api/v1/records/{record['id']}", headers=self.h1).json()
        self.assertEqual(detail["body"]["therapy_items"], ["偏瘫肢体综合训练"])
        self.assertIn("主观资料：", detail["rendered_text"])
        self.assertEqual(detail["kind"], "daily")
        self.assertEqual(detail["discipline"], "PT")

    def test_unknown_kind_or_discipline_is_422(self) -> None:
        bad_kind = self.create(kind="weekly")
        self.assert_error(bad_kind, 422, "INVALID")
        bad_discipline = self.create(discipline="XZ")
        self.assert_error(bad_discipline, 422, "INVALID")


class TestRecordListAndTimeline(RecordTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.create_ok(kind="initial", body=initial_body())
        self.create_ok(kind="daily", record_date="2027-03-01", body=daily_body())
        self.create_ok(kind="daily", record_date="2027-03-03", body=daily_body())

    def test_list_is_ordered_by_date_desc(self) -> None:
        body = self.client.get("/api/v1/records", headers=self.h1).json()
        self.assertEqual([i["record_date"] for i in body["items"]], ["2027-03-03", "2027-03-01", "2027-03-01"])
        self.assertEqual(body["total"], 3)

    def test_list_filters_by_kind_and_discipline(self) -> None:
        daily = self.client.get("/api/v1/records", params={"kind": "daily"}, headers=self.h1).json()
        self.assertEqual(daily["total"], 2)
        initial = self.client.get("/api/v1/records", params={"kind": "initial"}, headers=self.h1).json()
        self.assertEqual(initial["total"], 1)
        other = self.client.get("/api/v1/records", params={"discipline": "OT"}, headers=self.h1).json()
        self.assertEqual(other["total"], 0)

    def test_list_items_carry_soap_text(self) -> None:
        body = self.client.get("/api/v1/records", params={"kind": "daily"}, headers=self.h1).json()
        item = body["items"][0]
        self.assertEqual(item["discipline"], "PT")
        self.assertEqual(item["kind"], "daily")
        self.assertIn("主观资料：", item["rendered_text"])
        self.assertIn("主观资料：", item["rendered_excerpt"])

    def test_list_scope_mine(self) -> None:
        mine = self.client.get("/api/v1/records", params={"scope": "mine"}, headers=self.h2).json()
        self.assertEqual(mine["total"], 0)
        mine1 = self.client.get("/api/v1/records", params={"scope": "mine"}, headers=self.h1).json()
        self.assertEqual(mine1["total"], 3)

    def test_invalid_scope_rejected(self) -> None:
        resp = self.client.get("/api/v1/records", params={"scope": "temp"}, headers=self.h1)
        self.assert_error(resp, 404, "INVALID_SCOPE")

    def test_timeline_is_ordered_desc(self) -> None:
        body = self.client.get("/api/v1/timeline", headers=self.h1).json()
        dates = [i["record_date"] for i in body["items"]]
        self.assertEqual(dates[:2], ["2027-03-03", "2027-03-01"])
        self.assertEqual(body["items"][0]["kind"], "daily")

    def test_timeline_filters(self) -> None:
        body = self.client.get(
            "/api/v1/timeline",
            params={"from": "2027-03-02", "to": "2027-03-05", "kind": "daily"},
            headers=self.h1,
        ).json()
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["record_date"], "2027-03-03")

    def test_discharged_patient_records_hidden(self) -> None:
        patient_model.update_patient(self.conn, "ZY001", status=patient_model.STATUS_DISCHARGED)
        listed = self.client.get("/api/v1/records", headers=self.h1).json()
        self.assertEqual(listed["total"], 0)
        admin_listed = self.client.get("/api/v1/records", headers=self.ha).json()
        self.assertEqual(admin_listed["total"], 3, "管理员不受在院状态限制")

    def test_can_write_for_colleague_patient(self) -> None:
        """全科白板：可以给"别人负责的患者"写记录（记录人必须是自己）。"""
        record = self.create_ok(
            patient_no="ZY002", kind="initial", body=initial_body(), headers=self.h1
        )
        self.assertEqual(record["therapist_id"], int(self.t1["id"]))

    def test_enums_include_disciplines(self) -> None:
        body = self.client.get("/api/v1/records/enums", headers=self.h1).json()
        self.assertEqual(body["statuses"], ["draft", "submitted", "locked"])
        self.assertEqual(body["kinds"], ["initial", "daily", "reassessment", "discharge"])
        self.assertEqual([d["key"] for d in body["disciplines"]], ["PT", "OT", "ST_SW", "ST_SP"])


class TestTemporaryTreatmentFlag(RecordTestCase):
    """`is_temporary` = "记录人 ≠ 该患者在**记录创建时刻**的归属治疗师"（查询时推导）。"""

    def test_owner_recording_is_not_temporary(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        record = self.create_ok(kind="daily")
        self.assertEqual(record["is_temporary"], 0)

    def test_other_therapist_recording_is_temporary(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        record = self.create_ok(kind="daily", headers=self.h2)
        self.assertEqual(record["is_temporary"], 1, "非归属人做的治疗应标为临时")
        patient = patient_model.get_patient_or_raise(self.conn, "ZY001")
        self.assertEqual(patient["assigned_therapist_id"], int(self.t1["id"]), "原归属不变")

    def test_no_assignment_history_is_not_temporary(self) -> None:
        patient_model.create_patient(self.conn, inpatient_no="ZY003", name="未分配患者")
        self.create_ok(patient_no="ZY003", kind="initial", body=initial_body(), headers=self.h2)
        record = self.create_ok(patient_no="ZY003", kind="daily", headers=self.h2)
        self.assertEqual(record["is_temporary"], 0)

    def test_transfer_after_recording_does_not_retroactively_flag(self) -> None:
        import time

        self.create_ok(kind="initial", body=initial_body())
        record = self.create_ok(kind="daily")
        self.assertEqual(record["is_temporary"], 0)

        time.sleep(0.02)
        self.conn.execute(
            "UPDATE patient SET assigned_therapist_id = ? WHERE inpatient_no = 'ZY001'",
            (int(self.t2["id"]),),
        )
        self.conn.execute(
            "INSERT INTO patient_assignment_history"
            " (patient_no, from_therapist_id, to_therapist_id, change_type)"
            " VALUES ('ZY001', ?, ?, 'admin_assign')",
            (int(self.t1["id"]), int(self.t2["id"])),
        )
        refreshed = self.client.get(f"/api/v1/records/{record['id']}", headers=self.ha).json()
        self.assertEqual(refreshed["is_temporary"], 0, "归属变更不得追溯改写历史记录的性质")

    def test_temporary_flag_is_derived_not_stored(self) -> None:
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(treatment_record)")}
        for gone in ("is_temporary", "appointment_id", "original_therapist_id", "session_period"):
            self.assertNotIn(gone, columns, f"{gone} 已删除，不应重新出现")


class TestRecordForm(RecordTestCase):
    """`GET /records/form`：该填哪份文书 + 预填 + 已存在的那条。"""

    def form(self, **params) -> dict:
        defaults = {"patient_no": "ZY001", "discipline": DISCIPLINE}
        defaults.update(params)
        resp = self.client.get("/api/v1/records/form", params=defaults, headers=self.h1)
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()

    def test_first_visit_asks_for_initial(self) -> None:
        body = self.form()
        self.assertEqual(body["pending_document"], "initial")
        self.assertEqual(body["kind"], "initial", "缺评估文书时先弹它")
        self.assertEqual(body["kind_label"], "首评")
        self.assertEqual(body["next_seq"], 1)
        self.assertEqual(body["total_daily"], 0)
        self.assertEqual(body["discipline_name"], "运动")
        self.assertEqual(body["title"], "康复初始评定（PT运动）")
        self.assertEqual([s["key"] for s in body["soap"]], ["s", "o", "a", "p"])
        self.assertEqual(body["footer"], ["治疗师签名：__________"])
        self.assertIsNone(body["existing"])

    def test_after_initial_asks_for_daily(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        body = self.form()
        self.assertIsNone(body["pending_document"])
        self.assertEqual(body["kind"], "daily")
        self.assertEqual(body["kind_label"], "日常治疗记录")
        self.assertEqual(body["next_seq"], 1, "首评不占次数")
        self.assertEqual(body["total_daily"], 0)

    def test_daily_prefill_only_carries_therapy_items(self) -> None:
        """日常记录**只**预填「本次训练项目」（其余项每天都要重新判断）。"""
        self.create_ok(kind="initial", body=initial_body())
        self.create_ok(kind="daily", body=daily_body(vas=7, mental="差"))
        body = self.form()
        self.assertEqual(body["prefill"], {"therapy_items": ["偏瘫肢体综合训练"]})
        self.assertEqual(body["prefill_source"], {"therapy_items": "last_daily"})

    def test_second_record_same_day_prefills_first(self) -> None:
        self.create_ok(kind="initial", body=initial_body())
        self.create_ok(kind="daily", body=daily_body(vas=6, mental="一般"))
        body = self.form(date="2027-03-01")
        self.assertIsNone(body["existing"], "已提交的那条不拦着当天第 2 条新建")
        self.assertEqual(body["prefill"]["mental"], "一般")
        self.assertEqual(body["prefill"]["vas"], 6)
        self.assertEqual(body["prefill_source"]["mental"], "same_day_first")

    def test_draft_daily_is_returned_as_existing(self) -> None:
        """草稿才是"继续编辑"的对象；已提交的日常只是预填来源。"""
        self.create_ok(kind="initial", body=initial_body())
        draft = self.create_ok(kind="daily", body=daily_body(), status="draft")
        body = self.form(date="2027-03-01")
        self.assertIsNotNone(body["existing"])
        self.assertEqual(body["existing"]["id"], draft["id"])
        self.assertEqual(body["existing"]["status"], "draft")

    def test_form_for_other_date_has_no_existing(self) -> None:
        """`existing` 是按**该日期**找的：换一天就是新的一条。"""
        self.create_ok(kind="initial", body=initial_body())
        self.create_ok(kind="daily", body=daily_body())
        body = self.form(date="2027-03-02")
        self.assertIsNone(body["existing"])

    def test_assessment_prefill_uses_last_assessment(self) -> None:
        self.create_ok(kind="initial", body=initial_body(mmt_lower=2))
        self.seed_daily(20)
        body = self.form(record_date="2027-03-01")
        self.assertEqual(body["pending_document"], "reassessment")
        self.assertEqual(body["kind"], "reassessment")
        self.assertEqual(body["prefill"]["mmt_lower"], 2, "复评带出上次评估的客观值")
        self.assertIn(body["prefill_source"]["mmt_lower"], {"last_assessment", "same_day_first"})

    def test_existing_initial_is_returned_for_editing(self) -> None:
        """显式要首评表单时，`existing` 给出已有那份（App 继续编辑而不是重复新建）。"""
        record = self.create_ok(kind="initial", body=initial_body())
        body = self.form(kind="initial")
        self.assertEqual(body["kind"], "initial")
        self.assertIsNotNone(body["existing"])
        self.assertEqual(body["existing"]["id"], record["id"])
        self.assertEqual(body["existing"]["body"]["diagnosis"], ["偏瘫运动功能障碍"])

    def test_discharge_form_has_auto_summary_against_initial(self) -> None:
        """出院小结的「治疗过程汇总」由服务端自动生成（模板里 `auto: latest_vs_initial`）。"""
        self.create_ok(kind="initial", body=initial_body(mmt_lower=2))
        self.seed_daily(20)
        self.create_ok(kind="reassessment", record_date="2027-03-01", body=reassessment_body(mmt_lower=3))
        body = self.form(kind="discharge", record_date="2027-03-02")
        self.assertEqual(body["kind"], "discharge")
        self.assertEqual(body["kind_label"], "出院小结")
        summary = body["prefill"]["summary"]
        self.assertIn("住院期间共治疗", summary)
        self.assertIn("患肢肌力MMT 下肢 2级→3级", summary, summary)
        self.assertEqual(body["prefill_source"]["summary"], "auto")
        self.assertIsNone(body["existing"])

    def test_form_requires_patient_visibility(self) -> None:
        patient_model.create_patient(self.conn, inpatient_no="ZY-D", name="已出院患者")
        patient_model.update_patient(self.conn, "ZY-D", status=patient_model.STATUS_DISCHARGED)
        resp = self.client.get(
            "/api/v1/records/form",
            params={"patient_no": "ZY-D", "discipline": DISCIPLINE},
            headers=self.h1,
        )
        self.assert_error(resp, 403, "PATIENT_NOT_VISIBLE")

    def test_form_unknown_discipline_is_422(self) -> None:
        resp = self.client.get(
            "/api/v1/records/form",
            params={"patient_no": "ZY001", "discipline": "XZ"},
            headers=self.h1,
        )
        self.assert_error(resp, 422, "INVALID")


class TestModelLevelRules(RecordTestCase):
    def test_model_rejects_pending_discharge_patient(self) -> None:
        from app.models.base import Conflict

        patient_model.update_patient(
            self.conn, "ZY001", status=patient_model.STATUS_PENDING_DISCHARGE
        )
        with self.assertRaises(Conflict):
            treatment_model.create_record(
                self.conn,
                patient_no="ZY001",
                therapist_id=int(self.t1["id"]),
                record_date="2027-03-01",
                discipline="PT",
                kind="daily",
                body=daily_body(),
            )

    def test_model_unknown_status(self) -> None:
        from app.models.base import Invalid

        with self.assertRaises(Invalid):
            treatment_model.create_record(
                self.conn,
                patient_no="ZY001",
                therapist_id=int(self.t1["id"]),
                record_date="2027-03-01",
                discipline="PT",
                kind="daily",
                body=daily_body(),
                status="whatever",
            )

    def test_record_columns_include_body_and_rendered(self) -> None:
        columns = treatment_model.record_columns("r")
        self.assertIn("r.body_json", columns)
        self.assertIn("r.rendered_text", columns)


if __name__ == "__main__":
    unittest.main(verbosity=2)
