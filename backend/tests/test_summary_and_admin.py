"""阶段 5 测试：汇总、打印、模板与后台（`开发计划.md` 阶段 5）。

覆盖重点：
1. **汇总口径**：只统计已提交/已锁定，草稿不计入（否则"今天治疗了几人次"会被草稿污染）；
2. **汇总与 PDF 同源**：两者用同一段查询，避免出现两个不同的数字；
3. **中文 PDF**：用 pypdf 反向提取文本，确认中文真的印出来了（不是一页方框）；
4. **版式约定**（Q10）：抬头有科室名、页脚有页码与打印时间、**没有签名栏**；
5. **权限**：汇总与打印不能成为绕过数据级权限看别人患者的入口；
6. **模板自洽**：`dept` 无归属人、`personal` 必有归属人；套用只是预填不锁内容。
"""

from __future__ import annotations

import io
import unittest
import zlib

from app.models import template as template_model
from app.models import user as user_model
from app.services import pdf as pdf_service
from app.services import summary as summary_service
from seed.dictionary import seed_dictionary
from seed.options import seed_options
from seed.responses import seed_responses
from tests.api_base import DEFAULT_PASSWORD, ApiTestCase


def pdf_text(content: bytes) -> str:
    """用 pypdf 反向提取 PDF 文本，用于断言中文确实渲染出来了。

    这是本阶段最关键的验证手段：reportlab 若拿不到中文字体，
    会生成**满页方框**的 PDF —— 文件大小正常、页数正常、肉眼不看根本发现不了。
    只有把文本提取出来比对，才能确认字体真的生效。
    """
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def pdf_page_count(content: bytes) -> int:
    from pypdf import PdfReader

    return len(PdfReader(io.BytesIO(content)).pages)


class SummaryTestCase(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        # 三份种子都要导：少了 responses 就没法测患者反应摘要，
        # 少了 options 就测不到"选项解析回落到哪一层"。
        seed_dictionary(self.conn)
        seed_responses(self.conn)
        seed_options(self.conn)
        self.t1 = self.make_user("T001", "张三")
        self.t2 = self.make_user("T002", "李四")
        self.admin = self.make_admin("A001")

        from app.models import patient as patient_model

        self.p1 = patient_model.create_patient(
            self.conn, inpatient_no="ZY001", name="患者甲",
            diagnosis="脑卒中恢复期", admin_note="左侧偏瘫，注意防跌倒",
            assigned_therapist_id=int(self.t1["id"]),
        )
        self.p2 = patient_model.create_patient(
            self.conn, inpatient_no="ZY002", name="患者乙", assigned_therapist_id=int(self.t2["id"])
        )
        self.h1 = self.login_headers("T001")
        self.h2 = self.login_headers("T002")
        self.ha = self.login_headers("A001")

        self.motor_main = int(
            self.conn.execute("SELECT id FROM main_item WHERE code = 'motor_function'").fetchone()["id"]
        )
        self.motor_sub = int(
            self.conn.execute(
                "SELECT id FROM sub_item WHERE main_item_id = ? ORDER BY sort", (self.motor_main,)
            ).fetchone()["id"]
        )
        self.swallow_main = int(
            self.conn.execute("SELECT id FROM main_item WHERE code = 'swallow_function'").fetchone()["id"]
        )
        self.swallow_sub = int(
            self.conn.execute(
                "SELECT id FROM sub_item WHERE main_item_id = ? ORDER BY sort", (self.swallow_main,)
            ).fetchone()["id"]
        )

    def write_record(
        self,
        *,
        patient_no: str = "ZY001",
        day: str = "2027-03-01",
        period: str = "am",
        status: str = "submitted",
        duration: int = 30,
        note: str | None = None,
        main_item_id: int | None = None,
        sub_item_id: int | None = None,
        params: dict | None = None,
        patient_response: dict | None = None,
        headers: dict | None = None,
    ) -> dict:
        # 默认参数只对默认子项目（运动）有意义；换了子项目还塞 {"side": ...}
        # 会被"未知参数键"校验正确拦下，所以这里按子项目给默认值。
        if params is None:
            params = {"side": "左"} if (sub_item_id or self.motor_sub) == self.motor_sub else {}
        payload = {
            "patient_no": patient_no,
            "record_date": day,
            "session_period": period,
            "duration_min": duration,
            "status": status,
            "note": note,
            "patient_response": patient_response,
            "items": [
                {
                    "main_item_id": main_item_id or self.motor_main,
                    "sub_item_id": sub_item_id or self.motor_sub,
                    "params": params if params is not None else {"side": "左"},
                }
            ],
        }
        resp = self.client.post("/api/v1/records", json=payload, headers=headers or self.h1)
        assert resp.status_code == 201, resp.text
        return resp.json()


class TestDateSummary(SummaryTestCase):
    def test_empty_day(self) -> None:
        body = self.client.get(
            "/api/v1/summary/date", params={"date": "2027-03-01"}, headers=self.h1
        ).json()
        self.assertEqual(body["totals"]["record_count"], 0)
        self.assertEqual(body["groups"], [])

    def test_counts_submitted_records(self) -> None:
        self.write_record(day="2027-03-01", duration=30)
        self.write_record(day="2027-03-01", period="pm", duration=45)
        body = self.client.get(
            "/api/v1/summary/date", params={"date": "2027-03-01"}, headers=self.h1
        ).json()
        self.assertEqual(body["totals"]["record_count"], 2)
        self.assertEqual(body["totals"]["total_duration_min"], 75)
        self.assertEqual(body["totals"]["patient_count"], 1)

    def test_drafts_are_excluded(self) -> None:
        """草稿是没写完的东西，不该算进"今天治疗了多少人次"。"""
        self.write_record(day="2027-03-01", status="submitted")
        self.write_record(day="2027-03-01", period="pm", status="draft")
        body = self.client.get(
            "/api/v1/summary/date", params={"date": "2027-03-01"}, headers=self.h1
        ).json()
        self.assertEqual(body["totals"]["record_count"], 1, "草稿不应计入汇总")

    def test_locked_records_are_counted(self) -> None:
        record = self.write_record(day="2027-03-01")
        self.client.post(f"/api/v1/records/{record['id']}/lock", headers=self.ha)
        body = self.client.get(
            "/api/v1/summary/date", params={"date": "2027-03-01"}, headers=self.h1
        ).json()
        self.assertEqual(body["totals"]["record_count"], 1)

    def test_group_by_therapist(self) -> None:
        self.write_record(day="2027-03-01", headers=self.h1)
        self.write_record(patient_no="ZY002", day="2027-03-01", headers=self.h2)

        body = self.client.get(
            "/api/v1/summary/date", params={"date": "2027-03-01", "group_by": "therapist"},
            headers=self.ha,
        ).json()
        keys = {g["key"] for g in body["groups"]}
        self.assertEqual(keys, {"张三", "李四"})
        self.assertEqual(body["group_by"], "therapist")

    def test_group_by_patient(self) -> None:
        self.write_record(day="2027-03-01", headers=self.h1)
        body = self.client.get(
            "/api/v1/summary/date", params={"date": "2027-03-01", "group_by": "patient"},
            headers=self.ha,
        ).json()
        self.assertEqual([g["key"] for g in body["groups"]], ["患者甲"])

    def test_invalid_group_by_rejected(self) -> None:
        resp = self.client.get(
            "/api/v1/summary/date", params={"date": "2027-03-01", "group_by": "room"}, headers=self.h1
        )
        self.assert_error(resp, 422, "INVALID")

    def test_main_and_sub_item_frequencies(self) -> None:
        self.write_record(day="2027-03-01")
        self.write_record(
            day="2027-03-01", period="pm",
            main_item_id=self.swallow_main, sub_item_id=self.swallow_sub,
        )
        body = self.client.get(
            "/api/v1/summary/date", params={"date": "2027-03-01"}, headers=self.h1
        ).json()
        self.assertEqual(body["totals"]["main_item_counts"].get("运动功能障碍训练"), 1)
        self.assertEqual(body["totals"]["main_item_counts"].get("吞咽功能障碍训练"), 1)
        self.assertEqual(len(body["totals"]["sub_item_counts"]), 2)

    def test_params_digest_uses_snapshot_names(self) -> None:
        self.write_record(day="2027-03-01", params={"side": "左", "position": "坐位"})
        body = self.client.get(
            "/api/v1/summary/date", params={"date": "2027-03-01"}, headers=self.h1
        ).json()
        digest = body["groups"][0]["rows"][0]["params_digest"]
        self.assertIn("侧别：左", digest)
        self.assertIn("体位：坐位", digest)

    def test_response_digest(self) -> None:
        self.write_record(
            day="2027-03-01",
            patient_response={"tags": ["no_discomfort"], "items": [{"code": "pain", "value": 3}]},
        )
        body = self.client.get(
            "/api/v1/summary/date", params={"date": "2027-03-01"}, headers=self.h1
        ).json()
        digest = body["groups"][0]["rows"][0]["response_digest"]
        self.assertIn("无不适", digest)
        self.assertIn("疼痛 3分", digest)

    def test_summary_covers_whole_department(self) -> None:
        """白板：按日期汇总对全科在院患者可见（不再按归属过滤）。"""
        self.write_record(day="2027-03-01", headers=self.h1)
        self.write_record(patient_no="ZY002", day="2027-03-01", headers=self.h2)
        body = self.client.get(
            "/api/v1/summary/date", params={"date": "2027-03-01"}, headers=self.h1
        ).json()
        patients = {row["patient_no"] for group in body["groups"] for row in group["rows"]}
        self.assertEqual(patients, {"ZY001", "ZY002"})

    def test_summary_excludes_discharged_patients(self) -> None:
        """白板范围只含在院/暂停：已出院患者不进当日汇总（管理员不受限）。"""
        from app.models import patient as patient_model

        self.write_record(day="2027-03-01", headers=self.h1)
        self.write_record(patient_no="ZY002", day="2027-03-01", headers=self.h2)
        patient_model.update_patient(self.conn, "ZY002", status=patient_model.STATUS_DISCHARGED)
        body = self.client.get(
            "/api/v1/summary/date", params={"date": "2027-03-01"}, headers=self.h1
        ).json()
        patients = {row["patient_no"] for group in body["groups"] for row in group["rows"]}
        self.assertEqual(patients, {"ZY001"})

    def test_admin_sees_all(self) -> None:
        self.write_record(day="2027-03-01", headers=self.h1)
        self.write_record(patient_no="ZY002", day="2027-03-01", headers=self.h2)
        body = self.client.get(
            "/api/v1/summary/date", params={"date": "2027-03-01"}, headers=self.ha
        ).json()
        self.assertEqual(body["totals"]["record_count"], 2)


class TestPatientDailySummary(SummaryTestCase):
    def test_daily_rows_grouped_by_date(self) -> None:
        self.write_record(day="2027-03-01", duration=30)
        self.write_record(day="2027-03-03", period="pm", duration=45)
        body = self.client.get("/api/v1/summary/patient/ZY001", headers=self.h1).json()
        self.assertEqual([d["record_date"] for d in body["days"]], ["2027-03-03", "2027-03-01"])
        self.assertEqual(body["totals"]["record_count"], 2)
        self.assertEqual(body["totals"]["total_duration_min"], 75)

    def test_multiple_items_same_day_merge_into_one_row(self) -> None:
        """同一天两条记录（不同子项目）在"每日汇总"里应合并为一天。"""
        self.write_record(day="2027-03-01")
        self.write_record(
            day="2027-03-01", period="pm",
            main_item_id=self.swallow_main, sub_item_id=self.swallow_sub,
        )
        body = self.client.get("/api/v1/summary/patient/ZY001", headers=self.h1).json()
        self.assertEqual(len(body["days"]), 1, "同一天应合并为一行")
        day = body["days"][0]
        self.assertEqual(len(day["main_items"]), 2)
        self.assertEqual(day["duration_min"], 60)

    def test_date_range_filter(self) -> None:
        for day in ("2027-03-01", "2027-03-05", "2027-03-09"):
            self.write_record(day=day)
        body = self.client.get(
            "/api/v1/summary/patient/ZY001",
            params={"from": "2027-03-02", "to": "2027-03-07"},
            headers=self.h1,
        ).json()
        self.assertEqual([d["record_date"] for d in body["days"]], ["2027-03-05"])

    def test_patient_info_included(self) -> None:
        body = self.client.get("/api/v1/summary/patient/ZY001", headers=self.h1).json()
        self.assertEqual(body["patient"]["name"], "患者甲")
        self.assertEqual(body["patient"]["diagnosis"], "脑卒中恢复期")
        self.assertEqual(body["patient"]["admin_note"], "左侧偏瘫，注意防跌倒")

    def test_can_summarize_colleague_patient(self) -> None:
        """白板：在院患者对全科可见，因此也能看他的每日汇总。"""
        self.write_record(patient_no="ZY002", day="2027-03-01", headers=self.h2)
        resp = self.client.get("/api/v1/summary/patient/ZY002", headers=self.h1)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["patient"]["inpatient_no"], "ZY002")

    def test_cannot_summarize_discharged_patient(self) -> None:
        """已出院默认不在白板上 —— 这时才返回 403（管理员仍可看）。"""
        from app.models import patient as patient_model

        patient_model.update_patient(self.conn, "ZY002", status=patient_model.STATUS_DISCHARGED)
        resp = self.client.get("/api/v1/summary/patient/ZY002", headers=self.h1)
        self.assert_error(resp, 403, "PATIENT_NOT_VISIBLE")
        admin_resp = self.client.get("/api/v1/summary/patient/ZY002", headers=self.ha)
        self.assertEqual(admin_resp.status_code, 200, admin_resp.text)

    def test_unknown_patient_is_404(self) -> None:
        resp = self.client.get("/api/v1/summary/patient/NOPE", headers=self.ha)
        self.assert_error(resp, 404)


class TestPatientOverview(SummaryTestCase):
    def test_overview_has_patient_and_records(self) -> None:
        self.write_record(day="2027-03-01", note="首次")
        self.write_record(day="2027-03-03", note="第二次")
        body = self.client.get("/api/v1/summary/patient/ZY001/overview", headers=self.h1).json()
        self.assertEqual(body["patient"]["name"], "患者甲")
        self.assertEqual(body["patient"]["assigned_therapist_name"], "张三")
        self.assertEqual(len(body["records"]), 2)
        self.assertEqual([r["record_no"] for r in body["records"]], [1, 2])
        self.assertEqual(body["records"][0]["note"], "首次")

    def test_overview_excludes_drafts(self) -> None:
        self.write_record(day="2027-03-01", status="draft")
        body = self.client.get("/api/v1/summary/patient/ZY001/overview", headers=self.h1).json()
        self.assertEqual(body["records"], [])


class TestSummaryServiceConsistency(SummaryTestCase):
    """汇总与 PDF 同源：JSON 与 PDF 用的是同一段查询，数字必须一致。"""

    def test_json_and_pdf_totals_agree(self) -> None:
        self.write_record(day="2027-03-01", duration=30)
        self.write_record(day="2027-03-01", period="pm", duration=45)
        summary = summary_service.summarize_date(self.conn, day="2027-03-01")
        overview = summary_service.patient_overview(self.conn, patient_no="ZY001")
        self.assertEqual(summary["totals"]["record_count"], 2)
        self.assertEqual(overview["totals"]["record_count"], 2)
        self.assertEqual(
            summary["totals"]["total_duration_min"], overview["totals"]["total_duration_min"]
        )

    def test_draft_excluded_at_service_level(self) -> None:
        self.write_record(day="2027-03-01", status="draft")
        summary = summary_service.summarize_date(self.conn, day="2027-03-01")
        self.assertEqual(summary["totals"]["record_count"], 0)


class TestPdfRendering(SummaryTestCase):
    """PDF 的反向文本校验 —— 这是确认中文字体真的生效的唯一可靠手段。"""

    def test_font_registers(self) -> None:
        self.assertEqual(pdf_service.ensure_font(), pdf_service.FONT_NAME)

    def test_patient_summary_pdf_contains_chinese(self) -> None:
        self.write_record(day="2027-03-01", params={"side": "左", "position": "坐位"})
        overview = summary_service.patient_overview(self.conn, patient_no="ZY001")
        content = pdf_service.patient_summary_pdf(overview)
        self.assertTrue(content.startswith(b"%PDF"), "应是合法 PDF")
        text = pdf_text(content)
        for expected in ("康复医学科", "患者甲", "ZY001", "脑卒中恢复期", "张三", "坐位", "汇总统计"):
            self.assertIn(expected, text, f"PDF 里应能提取到「{expected}」（否则中文没渲染出来）")

    def test_patient_summary_no_signature_field(self) -> None:
        """Q10：不做签名栏（对齐 1.4 不采集患者签字）。"""
        self.write_record(day="2027-03-01")
        overview = summary_service.patient_overview(self.conn, patient_no="ZY001")
        text = pdf_text(pdf_service.patient_summary_pdf(overview))
        for forbidden in ("签名", "患者签字", "家属签字"):
            self.assertNotIn(forbidden, text, f"Q10 定了不做签名栏，不应出现「{forbidden}」")

    def test_pdf_footer_has_page_number_and_print_time(self) -> None:
        self.write_record(day="2027-03-01")
        overview = summary_service.patient_overview(self.conn, patient_no="ZY001")
        text = pdf_text(pdf_service.patient_summary_pdf(overview))
        self.assertIn("第 1 页", text)
        self.assertIn("打印时间：", text)

    def test_date_summary_pdf(self) -> None:
        self.write_record(day="2027-03-01")
        summary = summary_service.summarize_date(self.conn, day="2027-03-01")
        text = pdf_text(pdf_service.date_summary_pdf(summary))
        for expected in ("康复医学科", "2027-03-01", "患者甲", "张三", "当日总计"):
            self.assertIn(expected, text)

    def test_patient_daily_pdf(self) -> None:
        self.write_record(day="2027-03-01")
        self.write_record(day="2027-03-03", period="pm")
        daily = summary_service.summarize_patient_daily(self.conn, patient_no="ZY001")
        text = pdf_text(pdf_service.patient_daily_pdf(daily))
        for expected in ("康复医学科", "患者甲", "每日汇总", "2027-03-01", "2027-03-03"):
            self.assertIn(expected, text)

    def test_empty_pdf_does_not_crash(self) -> None:
        """没有记录时也要出一份可打印的 PDF（空表 + 说明文字），而不是报错。"""
        overview = summary_service.patient_overview(self.conn, patient_no="ZY001")
        text = pdf_text(pdf_service.patient_summary_pdf(overview))
        self.assertIn("治疗次数：0", text)
        self.assertIn("无", text, "空表应有说明文字")

    def test_multipage_pdf_numbers_every_page(self) -> None:
        for index in range(40):
            self.write_record(day=f"2027-04-{index % 28 + 1:02d}", period="am" if index % 2 else "pm")
        overview = summary_service.patient_overview(self.conn, patient_no="ZY001")
        content = pdf_service.patient_summary_pdf(overview)
        pages = pdf_page_count(content)
        self.assertGreater(pages, 1, "40 条记录应该超过一页")
        text = pdf_text(content)
        for page in range(1, pages + 1):
            self.assertIn(f"第 {page} 页", text, "每一页都要有页码")

    def test_pdf_is_not_blank(self) -> None:
        """防"生成成功但内容是空白"：压缩流不应把中文压没。"""
        self.write_record(day="2027-03-01")
        overview = summary_service.patient_overview(self.conn, patient_no="ZY001")
        content = pdf_service.patient_summary_pdf(overview)
        self.assertGreater(len(content), 1500, "PDF 过小，可能没渲染出内容")
        zlib.decompressobj()  # 确认 zlib 可用（PDF 流压缩依赖它）


class TestPrintEndpoints(SummaryTestCase):
    def test_print_patient_endpoint(self) -> None:
        self.write_record(day="2027-03-01")
        resp = self.client.get("/api/v1/print/patient/ZY001", headers=self.h1)
        self.assertEqual(resp.status_code, 200, resp.text[:200])
        self.assertEqual(resp.headers["content-type"], "application/pdf")
        self.assertIn("patient-ZY001.pdf", resp.headers["content-disposition"])
        self.assertIn("患者甲", pdf_text(resp.content))

    def test_print_date_summary_endpoint(self) -> None:
        self.write_record(day="2027-03-01")
        resp = self.client.get(
            "/api/v1/print/summary/date", params={"date": "2027-03-01"}, headers=self.h1
        )
        self.assertEqual(resp.status_code, 200, resp.text[:200])
        self.assertEqual(resp.headers["content-type"], "application/pdf")
        self.assertIn("2027-03-01", pdf_text(resp.content))

    def test_print_patient_daily_endpoint(self) -> None:
        self.write_record(day="2027-03-01")
        resp = self.client.get("/api/v1/print/summary/patient/ZY001", headers=self.h1)
        self.assertEqual(resp.status_code, 200, resp.text[:200])
        self.assertIn("每日汇总", pdf_text(resp.content))

    def test_print_covers_department_patients(self) -> None:
        """白板：可按日期打印全科范围内的记录。"""
        self.write_record(day="2027-03-01", headers=self.h1)
        self.write_record(patient_no="ZY002", day="2027-03-01", headers=self.h2)
        resp = self.client.get(
            "/api/v1/print/summary/date", params={"date": "2027-03-01"}, headers=self.h1
        )
        text = pdf_text(resp.content)
        self.assertIn("患者甲", text)
        self.assertIn("患者乙", text)

    def test_print_respects_discharged_visibility(self) -> None:
        """已出院默认不可见 —— 这时打印单患者汇总返回 403。"""
        from app.models import patient as patient_model

        patient_model.update_patient(self.conn, "ZY002", status=patient_model.STATUS_DISCHARGED)
        resp = self.client.get("/api/v1/print/patient/ZY002", headers=self.h1)
        self.assert_error(resp, 403, "PATIENT_NOT_VISIBLE")

    def test_print_requires_auth(self) -> None:
        resp = self.client.get("/api/v1/print/patient/ZY001")
        self.assert_error(resp, 401, "AUTH_REQUIRED")

    def test_print_date_excludes_discharged_patients(self) -> None:
        """已出院患者不进按日期打印（与白板范围一致）；管理员不受限。"""
        from app.models import patient as patient_model

        self.write_record(day="2027-03-01", headers=self.h1)
        self.write_record(patient_no="ZY002", day="2027-03-01", headers=self.h2)
        patient_model.update_patient(self.conn, "ZY002", status=patient_model.STATUS_DISCHARGED)
        text = pdf_text(
            self.client.get(
                "/api/v1/print/summary/date", params={"date": "2027-03-01"}, headers=self.h1
            ).content
        )
        self.assertIn("患者甲", text)
        self.assertNotIn("患者乙", text)


class TestTemplates(SummaryTestCase):
    def test_create_personal_template(self) -> None:
        resp = self.client.post(
            "/api/v1/templates",
            json={
                "name": "我的运动组合", "scope": "personal",
                "main_item_id": self.motor_main,
                "items": [{"sub_item_id": self.motor_sub, "params": {"side": "左", "position": "坐位"}}],
            },
            headers=self.h1,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual(body["scope"], "personal")
        self.assertEqual(body["owner_user_id"], int(self.t1["id"]))
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["params"]["position"], "坐位")

    def test_therapist_cannot_create_dept_template(self) -> None:
        resp = self.client.post(
            "/api/v1/templates",
            json={"name": "全科模板", "scope": "dept", "main_item_id": self.motor_main,
                 "items": [{"sub_item_id": self.motor_sub}]},
            headers=self.h1,
        )
        self.assert_error(resp, 403, "DEPT_TEMPLATE_ADMIN_ONLY")

    def test_admin_can_create_dept_template(self) -> None:
        resp = self.client.post(
            "/api/v1/templates",
            json={"name": "全科运动模板", "scope": "dept", "main_item_id": self.motor_main,
                 "items": [{"sub_item_id": self.motor_sub}]},
            headers=self.ha,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertIsNone(resp.json()["owner_user_id"], "科室模板不能有归属人")

    def test_personal_template_owner_is_forced_to_self(self) -> None:
        """个人模板自动归属当前用户，不能借请求体指定给别人。"""
        resp = self.client.post(
            "/api/v1/templates",
            json={"name": "借用", "scope": "personal", "main_item_id": self.motor_main,
                 "items": [{"sub_item_id": self.motor_sub}]},
            headers=self.h1,
        )
        self.assertEqual(resp.json()["owner_user_id"], int(self.t1["id"]))

    def test_list_shows_dept_and_own_only(self) -> None:
        self.client.post(
            "/api/v1/templates",
            json={"name": "甲的私人模板", "scope": "personal", "main_item_id": self.motor_main,
                 "items": [{"sub_item_id": self.motor_sub}]},
            headers=self.h1,
        )
        self.client.post(
            "/api/v1/templates",
            json={"name": "科室模板", "scope": "dept", "main_item_id": self.motor_main,
                 "items": [{"sub_item_id": self.motor_sub}]},
            headers=self.ha,
        )
        mine = self.client.get("/api/v1/templates", headers=self.h1).json()
        names = {t["name"] for t in mine}
        self.assertEqual(names, {"甲的私人模板", "科室模板"})

        other = self.client.get("/api/v1/templates", headers=self.h2).json()
        self.assertEqual({t["name"] for t in other}, {"科室模板"}, "不应看到别人的私人模板")

    def test_apply_template_returns_prefill_only(self) -> None:
        created = self.client.post(
            "/api/v1/templates",
            json={
                "name": "套用测试", "scope": "personal", "main_item_id": self.motor_main,
                "items": [{"sub_item_id": self.motor_sub, "params": {"side": "右"}}],
            },
            headers=self.h1,
        ).json()
        applied = self.client.post(
            f"/api/v1/templates/{created['id']}/apply", headers=self.h1
        ).json()
        self.assertEqual(len(applied["items"]), 1)
        self.assertEqual(applied["items"][0]["params"], {"side": "右"})
        self.assertEqual(applied["items"][0]["main_item_id"], self.motor_main)
        self.assertIn("仅为预填", applied["note"])
        # 套用不产生治疗记录
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM treatment_record").fetchone()[0], 0)

    def test_cannot_see_others_personal_template(self) -> None:
        created = self.client.post(
            "/api/v1/templates",
            json={"name": "私人的", "scope": "personal", "main_item_id": self.motor_main,
                 "items": [{"sub_item_id": self.motor_sub}]},
            headers=self.h1,
        ).json()
        resp = self.client.get(f"/api/v1/templates/{created['id']}", headers=self.h2)
        self.assert_error(resp, 403, "TEMPLATE_NOT_VISIBLE")

    def test_cannot_edit_others_personal_template(self) -> None:
        created = self.client.post(
            "/api/v1/templates",
            json={"name": "私人的", "scope": "personal", "main_item_id": self.motor_main,
                 "items": [{"sub_item_id": self.motor_sub}]},
            headers=self.h1,
        ).json()
        resp = self.client.put(
            f"/api/v1/templates/{created['id']}", json={"name": "改名"}, headers=self.h2
        )
        self.assert_error(resp, 403)

    def test_cannot_delete_dept_template_as_therapist(self) -> None:
        created = self.client.post(
            "/api/v1/templates",
            json={"name": "科室模板", "scope": "dept", "main_item_id": self.motor_main,
                 "items": [{"sub_item_id": self.motor_sub}]},
            headers=self.ha,
        ).json()
        resp = self.client.delete(f"/api/v1/templates/{created['id']}", headers=self.h1)
        self.assert_error(resp, 403)

    def test_update_template_items(self) -> None:
        second_sub = int(
            self.conn.execute(
                "SELECT id FROM sub_item WHERE main_item_id = ? AND id <> ? ORDER BY sort",
                (self.motor_main, self.motor_sub),
            ).fetchone()["id"]
        )
        created = self.client.post(
            "/api/v1/templates",
            json={"name": "t", "scope": "personal", "main_item_id": self.motor_main,
                  "items": [{"sub_item_id": self.motor_sub}]},
            headers=self.h1,
        ).json()
        updated = self.client.put(
            f"/api/v1/templates/{created['id']}",
            json={"name": "改过", "items": [{"sub_item_id": self.motor_sub}, {"sub_item_id": second_sub}]},
            headers=self.h1,
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["name"], "改过")
        self.assertEqual(len(updated.json()["items"]), 2)

    def test_template_main_item_mismatch_rejected(self) -> None:
        resp = self.client.post(
            "/api/v1/templates",
            json={
                "name": "错配", "scope": "personal", "main_item_id": self.motor_main,
                "items": [{"sub_item_id": self.swallow_sub}],
            },
            headers=self.h1,
        )
        self.assert_error(resp, 422, "INVALID")

    def test_duplicate_sub_item_in_template_rejected(self) -> None:
        resp = self.client.post(
            "/api/v1/templates",
            json={
                "name": "重复", "scope": "personal", "main_item_id": self.motor_main,
                "items": [{"sub_item_id": self.motor_sub}, {"sub_item_id": self.motor_sub}],
            },
            headers=self.h1,
        )
        self.assert_error(resp, 422, "INVALID")

    def test_unknown_sub_item_rejected(self) -> None:
        resp = self.client.post(
            "/api/v1/templates",
            json={"name": "x", "scope": "personal", "main_item_id": self.motor_main,
                 "items": [{"sub_item_id": 99999}]},
            headers=self.h1,
        )
        self.assert_error(resp, 404)

    def test_delete_own_template(self) -> None:
        created = self.client.post(
            "/api/v1/templates",
            json={"name": "待删", "scope": "personal", "main_item_id": self.motor_main,
                 "items": [{"sub_item_id": self.motor_sub}]},
            headers=self.h1,
        ).json()
        deleted = self.client.delete(f"/api/v1/templates/{created['id']}", headers=self.h1)
        self.assertEqual(deleted.status_code, 204, deleted.text)
        gone = self.client.get(f"/api/v1/templates/{created['id']}", headers=self.h1)
        self.assert_error(gone, 404)

    def test_model_scope_validation(self) -> None:
        from app.models.base import Invalid as DomainInvalid

        with self.assertRaises(DomainInvalid):
            template_model.create_template(
                self.conn, scope="global", name="x", owner_user_id=None,
                main_item_id=self.motor_main,
            )
        with self.assertRaises(DomainInvalid):
            template_model.create_template(
                self.conn, scope="personal", name="x", owner_user_id=None,
                main_item_id=self.motor_main,
            )
        with self.assertRaises(DomainInvalid):
            template_model.create_template(
                self.conn, scope="dept", name="x", owner_user_id=int(self.t1["id"]),
                main_item_id=self.motor_main,
            )

    def test_apply_skips_deactivated_sub_item(self) -> None:
        """字典把子项目停用后，模板仍应可用其余部分，而不是整份报错。

        注意用**停用**而不是物理删除：`record_template_item` 有外键指向 `sub_item`，
        物理删除会被数据库正确阻止（那才是对的 —— 不能让模板指向不存在的字典项）。
        现场实际发生的也是"字典调整/停用"。
        """
        second_sub = int(
            self.conn.execute(
                "SELECT id FROM sub_item WHERE main_item_id = ? AND id <> ? ORDER BY sort",
                (self.motor_main, self.motor_sub),
            ).fetchone()["id"]
        )
        created = self.client.post(
            "/api/v1/templates",
            json={
                "name": "含停用项", "scope": "personal", "main_item_id": self.motor_main,
                "items": [{"sub_item_id": self.motor_sub}, {"sub_item_id": second_sub}],
            },
            headers=self.h1,
        ).json()
        self.assertEqual(len(created["items"]), 2, created)

        self.conn.execute("UPDATE sub_item SET status = 'disabled' WHERE id = ?", (second_sub,))
        applied = self.client.post(
            f"/api/v1/templates/{created['id']}/apply", headers=self.h1
        ).json()
        self.assertEqual(len(applied["items"]), 1, "已停用子项目应被跳过，其余仍可套用")
        self.assertEqual(applied["items"][0]["sub_item_id"], self.motor_sub)

    def test_physical_delete_of_referenced_sub_item_is_blocked(self) -> None:
        """外键应阻止删掉仍被模板引用的子项目 —— 这保证模板不会指向不存在的字典项。"""
        import sqlite3

        self.client.post(
            "/api/v1/templates",
            json={"name": "引用中", "scope": "personal", "main_item_id": self.motor_main,
                  "items": [{"sub_item_id": self.motor_sub}]},
            headers=self.h1,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("DELETE FROM sub_item WHERE id = ?", (self.motor_sub,))


class TestAuditLogs(SummaryTestCase):
    def test_admin_can_query_audit_logs(self) -> None:
        self.write_record(day="2027-03-01")
        resp = self.client.get("/api/v1/audit-logs", headers=self.ha)
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertGreater(body["total"], 0)
        self.assertIn("items", body)

    def test_therapist_cannot_query_audit_logs(self) -> None:
        resp = self.client.get("/api/v1/audit-logs", headers=self.h1)
        self.assert_error(resp, 403)

    def test_filter_by_action(self) -> None:
        self.write_record(day="2027-03-01")
        body = self.client.get(
            "/api/v1/audit-logs", params={"action": "record_modified_after_submit"}, headers=self.ha
        ).json()
        for item in body["items"]:
            self.assertEqual(item["action"], "record_modified_after_submit")

    def test_filter_by_target_type(self) -> None:
        self.write_record(day="2027-03-01")
        body = self.client.get(
            "/api/v1/audit-logs", params={"target_type": "treatment_record"}, headers=self.ha
        ).json()
        self.assertGreater(body["total"], 0)
        for item in body["items"]:
            self.assertEqual(item["target_type"], "treatment_record")

    def test_log_includes_actor_name(self) -> None:
        self.write_record(day="2027-03-01")
        body = self.client.get(
            "/api/v1/audit-logs", params={"target_type": "treatment_record"}, headers=self.ha
        ).json()
        self.assertEqual(body["items"][0]["user_name"], "张三")

    def test_facets(self) -> None:
        self.write_record(day="2027-03-01")
        body = self.client.get("/api/v1/audit-logs/facets", headers=self.ha).json()
        self.assertIn("treatment_record", body["target_types"])
        self.assertIn("create", body["actions"])

    def test_audit_logs_are_read_only(self) -> None:
        """没有写入/删除接口 —— 能改的审计日志就不是审计日志。"""
        for method in ("post", "put", "delete"):
            resp = getattr(self.client, method)("/api/v1/audit-logs", headers=self.ha)
            self.assertIn(resp.status_code, {404, 405}, f"{method.upper()} 不应存在")


class TestAdminOptionSets(SummaryTestCase):
    def test_admin_creates_global_option_set(self) -> None:
        resp = self.client.put(
            "/api/v1/admin/option-sets",
            json={"code": "side", "name": "全科侧别", "values": ["左", "右", "双侧"],
                  "default_values": ["左"]},
            headers=self.ha,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["scope"], "global")
        self.assertEqual(len(body["items"]), 3)

    def test_admin_creates_dept_option_set_with_tag(self) -> None:
        body = self.client.put(
            "/api/v1/admin/option-sets",
            json={"code": "side", "name": "PT侧别", "values": ["左", "右"], "dept_tag": "PT"},
            headers=self.ha,
        ).json()
        self.assertEqual(body["scope"], "dept")
        self.assertEqual(body["dept_tag"], "PT")

    def test_therapist_cannot_edit_dept_option_set(self) -> None:
        resp = self.client.put(
            "/api/v1/admin/option-sets",
            json={"code": "side", "name": "x", "values": ["左"]},
            headers=self.h1,
        )
        self.assert_error(resp, 403)

    def test_admin_option_set_takes_effect_for_therapists(self) -> None:
        """这一层影响全科：管理员改了，治疗师立刻看到。"""
        self.client.put(
            "/api/v1/admin/option-sets",
            json={"code": "side", "name": "全科侧别", "values": ["左", "右"]},
            headers=self.ha,
        )
        resolved = self.client.get(
            "/api/v1/option-sets/resolve", params={"code": "side"}, headers=self.h1
        ).json()
        self.assertEqual(resolved["source"], "global")
        self.assertEqual([o["value"] for o in resolved["options"]], ["左", "右"])

    def test_overwrite_option_set_replaces_items(self) -> None:
        self.client.put(
            "/api/v1/admin/option-sets",
            json={"code": "side", "name": "v1", "values": ["左", "右", "双侧"]},
            headers=self.ha,
        )
        body = self.client.put(
            "/api/v1/admin/option-sets",
            json={"code": "side", "name": "v2", "values": ["左", "右"]},
            headers=self.ha,
        ).json()
        self.assertEqual([i["value"] for i in body["items"]], ["左", "右"], "覆盖后不应残留旧项")

    def test_duplicate_values_rejected(self) -> None:
        resp = self.client.put(
            "/api/v1/admin/option-sets",
            json={"code": "side", "name": "x", "values": ["左", "左"]},
            headers=self.ha,
        )
        self.assert_error(resp, 422, "INVALID")

    def test_default_must_be_in_values(self) -> None:
        resp = self.client.put(
            "/api/v1/admin/option-sets",
            json={"code": "side", "name": "x", "values": ["左"], "default_values": ["右"]},
            headers=self.ha,
        )
        self.assert_error(resp, 422, "INVALID")

    def test_list_all_option_sets(self) -> None:
        self.client.put(
            "/api/v1/admin/option-sets",
            json={"code": "side", "name": "全科侧别", "values": ["左", "右"]},
            headers=self.ha,
        )
        body = self.client.get("/api/v1/admin/option-sets", headers=self.ha).json()
        self.assertTrue(any(s["scope"] == "global" for s in body))
        only_global = self.client.get(
            "/api/v1/admin/option-sets", params={"scope": "global"}, headers=self.ha
        ).json()
        self.assertTrue(all(s["scope"] == "global" for s in only_global))

    def test_delete_option_set(self) -> None:
        created = self.client.put(
            "/api/v1/admin/option-sets",
            json={"code": "side", "name": "x", "values": ["左"]},
            headers=self.ha,
        ).json()
        deleted = self.client.delete(
            f"/api/v1/admin/option-sets/{created['id']}", headers=self.ha
        )
        self.assertEqual(deleted.status_code, 204, deleted.text)

    def test_cannot_delete_personal_option_set_via_admin(self) -> None:
        """个人快捷选项是治疗师的私人数据，管理员不该从这里删。"""
        self.client.put(
            "/api/v1/option-sets/personal",
            json={"code": "side", "name": "我的", "values": ["左"]},
            headers=self.h1,
        )
        row = self.conn.execute(
            "SELECT id FROM option_set WHERE scope = 'personal'"
        ).fetchone()
        resp = self.client.delete(f"/api/v1/admin/option-sets/{int(row['id'])}", headers=self.ha)
        self.assert_error(resp, 422, "INVALID")

    def test_admin_actions_are_audited(self) -> None:
        self.client.put(
            "/api/v1/admin/option-sets",
            json={"code": "side", "name": "x", "values": ["左"]},
            headers=self.ha,
        )
        body = self.client.get(
            "/api/v1/audit-logs", params={"target_type": "option_set"}, headers=self.ha
        ).json()
        self.assertGreater(body["total"], 0)
        self.assertEqual(body["items"][0]["action"], "upsert")


class TestUserAdminSurface(SummaryTestCase):
    """后台"用户管理"模块已有接口，这里确认它的管理员边界仍然成立。"""

    def test_therapist_cannot_list_users(self) -> None:
        resp = self.client.get("/api/v1/users", headers=self.h1)
        self.assert_error(resp, 403)

    def test_admin_can_list_users(self) -> None:
        body = self.client.get("/api/v1/users", headers=self.ha).json()
        self.assertGreaterEqual(body["total"], 3)

    def test_cannot_demote_last_admin(self) -> None:
        resp = self.client.put(
            f"/api/v1/users/{int(self.admin['id'])}", json={"role": "therapist"}, headers=self.ha
        )
        self.assertIn(resp.status_code, {409, 422}, f"必须保住最后一个管理员：{resp.text[:160]}")

    def test_deactivated_user_cannot_login(self) -> None:
        user_model.update_user(self.conn, int(self.t2["id"]), status="disabled")
        resp = self.client.post(
            "/api/v1/auth/login", json={"employee_no": "T002", "password": DEFAULT_PASSWORD}
        )
        self.assert_error(resp, 403)


if __name__ == "__main__":
    unittest.main(verbosity=2)
