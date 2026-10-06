"""阶段 5 测试：汇总、打印与后台（`设计.md` 3.8 / 3.9 / 6.2）。

覆盖重点（2026-10-05 记录改 SOAP 模板驱动后）：

1. **计数口径**：只算 `kind='daily'` 且已提交/已锁定 —— 草稿不计，
   **首评/复评/出院小结也一个都不计**（它们是独立文书，不占治疗次数）；
2. **内容口径**：汇总与 PDF 一律输出冻结的 `rendered_text`（SOAP 纯文本），
   不再有"主项目 / 子项目 / 参数 / 患者反应"这些表格字段；
3. **中文 PDF**：用 pypdf 反向提取文本，确认中文真的印出来了（不是一页方框）；
4. **版式**（Q10）：抬头有科室名、页脚有页码与打印时间、**多日记录按时间升序往下排**；
5. **权限**：汇总与打印不能成为绕过数据级权限看别人患者的入口。
"""

from __future__ import annotations

import io
import unittest
import zlib

from app.models import patient as patient_model
from app.services import pdf as pdf_service
from app.services import summary as summary_service
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
        "mmt_lower": 2,
        "diagnosis": ["偏瘫运动功能障碍"],
        "therapy_items": ["偏瘫肢体综合训练"],
    }
    body.update(overrides)
    return body


class SummaryTestCase(ApiTestCase):
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
            admin_note="左侧偏瘫，注意防跌倒",
            assigned_therapist_id=int(self.t1["id"]),
        )
        patient_model.create_patient(
            self.conn, inpatient_no="ZY002", name="患者乙", assigned_therapist_id=int(self.t2["id"])
        )
        self.h1 = self.login_headers("T001")
        self.h2 = self.login_headers("T002")
        self.ha = self.login_headers("A001")

    # -- 便捷：造记录 ------------------------------------------------------ #
    def ensure_initial(
        self, *, patient_no: str = "ZY001", day: str = "2027-03-01", headers: dict | None = None
    ) -> None:
        """保证该患者该大类已有首评 —— 门禁要求"第 1 次日常前必须先有首评"。

        刻意建成**草稿**：草稿不进汇总与打印，所以它不会污染本文件里
        "当天有几条记录 / PDF 里印了什么"那些断言，同时又能满足门禁。
        """
        from app.models import treatment as treatment_model

        if treatment_model.has_initial(self.conn, patient_no, "PT"):
            return
        resp = self.client.post(
            "/api/v1/records",
            json={
                "patient_no": patient_no,
                "record_date": day,
                "discipline": "PT",
                "kind": "initial",
                "body": initial_body(),
                "status": "draft",
            },
            headers=headers or self.h1,
        )
        assert resp.status_code == 201, resp.text

    def write_record(
        self,
        *,
        patient_no: str = "ZY001",
        day: str = "2027-03-01",
        kind: str = "daily",
        status: str = "submitted",
        body: dict | None = None,
        headers: dict | None = None,
    ) -> dict:
        if kind == "initial":
            payload_body = body if body is not None else initial_body()
        else:
            if kind == "daily":
                self.ensure_initial(patient_no=patient_no, day=day, headers=headers)
            payload_body = body if body is not None else daily_body()
        resp = self.client.post(
            "/api/v1/records",
            json={
                "patient_no": patient_no,
                "record_date": day,
                "discipline": "PT",
                "kind": kind,
                "body": payload_body,
                "status": status,
            },
            headers=headers or self.h1,
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    def seed_daily(self, count: int, *, patient_no: str = "ZY001", day: str = "2027-01-01") -> None:
        """直接落库造 N 条日常记录（越过门禁，用来构造"已经做过很多次"的既有状态）。"""
        for index in range(1, count + 1):
            self.conn.execute(
                "INSERT INTO treatment_record"
                " (patient_no, therapist_id, record_date, discipline, kind, seq_no, body_json,"
                "  rendered_text, status)"
                " VALUES (?, ?, ?, 'PT', 'daily', ?, '{}', ?, 'submitted')",
                (
                    patient_no,
                    int(self.t1["id"]),
                    day,
                    index,
                    f"康复治疗记录（PT运动）\n治疗日期：{day}   第 {index} 次\n\n主观资料：精神状态：良好",
                ),
            )


class TestDateSummary(SummaryTestCase):
    def test_empty_day(self) -> None:
        body = self.client.get(
            "/api/v1/summary/date", params={"date": "2027-03-01"}, headers=self.h1
        ).json()
        self.assertEqual(body["totals"]["record_count"], 0)
        self.assertEqual(body["groups"], [])

    def test_counts_submitted_daily_records(self) -> None:
        self.write_record(kind="initial")
        self.write_record(day="2027-03-01")
        self.write_record(day="2027-03-02")
        body = self.client.get(
            "/api/v1/summary/date", params={"date": "2027-03-01"}, headers=self.h1
        ).json()
        self.assertEqual(body["totals"]["record_count"], 1, "首评不算治疗次数")
        self.assertEqual(body["totals"]["patient_count"], 1)
        self.assertEqual(body["totals"]["discipline_counts"], {"运动": 1})

    def test_drafts_are_excluded(self) -> None:
        self.write_record(day="2027-03-01", status="draft")
        body = self.client.get(
            "/api/v1/summary/date", params={"date": "2027-03-01"}, headers=self.h1
        ).json()
        self.assertEqual(body["totals"]["record_count"], 0, "草稿不应计入汇总")

    def test_locked_records_are_counted(self) -> None:
        record = self.write_record(day="2027-03-01")
        self.client.post(f"/api/v1/records/{record['id']}/lock", headers=self.ha)
        body = self.client.get(
            "/api/v1/summary/date", params={"date": "2027-03-01"}, headers=self.h1
        ).json()
        self.assertEqual(body["totals"]["record_count"], 1)

    def test_reassessment_is_not_counted(self) -> None:
        self.seed_daily(20)
        self.conn.execute(
            "INSERT INTO treatment_record"
            " (patient_no, therapist_id, record_date, discipline, kind, body_json,"
            "  rendered_text, status)"
            " VALUES ('ZY001', ?, '2027-03-01', 'PT', 'initial', '{}', '', 'submitted')",
            (int(self.t1["id"]),),
        )
        self.write_record(day="2027-03-02", kind="reassessment", body={"diagnosis": ["偏瘫运动功能障碍"],
                                                                     "therapy_items": ["平衡生物反馈训练"]})
        body = self.client.get(
            "/api/v1/summary/date", params={"date": "2027-03-02"}, headers=self.h1
        ).json()
        self.assertEqual(body["totals"]["record_count"], 0, "复评不占治疗次数")

    def test_group_by_therapist_and_patient(self) -> None:
        self.write_record(day="2027-03-01", headers=self.h1)
        self.write_record(patient_no="ZY002", day="2027-03-01", headers=self.h2)
        by_therapist = self.client.get(
            "/api/v1/summary/date",
            params={"date": "2027-03-01", "group_by": "therapist"},
            headers=self.ha,
        ).json()
        self.assertEqual({g["key"] for g in by_therapist["groups"]}, {"张三", "李四"})
        by_patient = self.client.get(
            "/api/v1/summary/date",
            params={"date": "2027-03-01", "group_by": "patient"},
            headers=self.ha,
        ).json()
        self.assertEqual({g["key"] for g in by_patient["groups"]}, {"患者甲", "患者乙"})

    def test_invalid_group_by_rejected(self) -> None:
        resp = self.client.get(
            "/api/v1/summary/date", params={"date": "2027-03-01", "group_by": "room"}, headers=self.h1
        )
        self.assert_error(resp, 422, "INVALID")

    def test_rows_carry_soap_text(self) -> None:
        self.write_record(day="2027-03-01")
        body = self.client.get(
            "/api/v1/summary/date", params={"date": "2027-03-01"}, headers=self.h1
        ).json()
        row = body["groups"][0]["rows"][0]
        self.assertEqual(row["kind"], "daily")
        self.assertEqual(row["discipline_name"], "运动")
        self.assertIn("主观资料：精神状态：良好", row["rendered_text"])
        self.assertIn("客观资料：本次训练项目：偏瘫肢体综合训练", row["rendered_text"])
        self.assertNotIn("main_item_name", row, "旧的表格字段不应再出现")

    def test_summary_covers_whole_department(self) -> None:
        self.write_record(day="2027-03-01", headers=self.h1)
        self.write_record(patient_no="ZY002", day="2027-03-01", headers=self.h2)
        body = self.client.get(
            "/api/v1/summary/date", params={"date": "2027-03-01"}, headers=self.h1
        ).json()
        patients = {row["patient_no"] for group in body["groups"] for row in group["rows"]}
        self.assertEqual(patients, {"ZY001", "ZY002"})

    def test_summary_excludes_discharged_patients(self) -> None:
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
    def test_daily_rows_grouped_by_date_with_texts(self) -> None:
        self.write_record(day="2027-03-01")
        self.write_record(day="2027-03-03")
        body = self.client.get("/api/v1/summary/patient/ZY001", headers=self.h1).json()
        self.assertEqual([d["record_date"] for d in body["days"]], ["2027-03-03", "2027-03-01"])
        self.assertEqual(body["totals"]["record_count"], 2)
        self.assertEqual(len(body["days"][0]["texts"]), 1)
        self.assertIn("康复治疗记录（PT运动）", body["days"][0]["texts"][0])

    def test_same_day_assessment_and_daily_are_both_kept(self) -> None:
        """同一天的首评 + 日常：打印时两份文书都要在，但只算 1 次治疗。"""
        self.write_record(kind="initial", day="2027-03-01")
        self.write_record(kind="daily", day="2027-03-01")
        body = self.client.get("/api/v1/summary/patient/ZY001", headers=self.h1).json()
        self.assertEqual(len(body["days"]), 1)
        day = body["days"][0]
        self.assertEqual(len(day["texts"]), 2, "两份文书都要保留（首评不占次数但仍是文书）")
        self.assertEqual(day["record_count"], 1, "只把日常记录算作一次治疗")
        self.assertIn("康复初始评定", day["texts"][0])
        self.assertIn("康复治疗记录", day["texts"][1])

    def test_date_range_filter(self) -> None:
        self.write_record(day="2027-03-01")
        self.write_record(day="2027-03-05")
        self.write_record(day="2027-03-09")
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
        self.write_record(patient_no="ZY002", day="2027-03-01", headers=self.h2)
        resp = self.client.get("/api/v1/summary/patient/ZY002", headers=self.h1)
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_cannot_summarize_discharged_patient(self) -> None:
        patient_model.update_patient(self.conn, "ZY002", status=patient_model.STATUS_DISCHARGED)
        resp = self.client.get("/api/v1/summary/patient/ZY002", headers=self.h1)
        self.assert_error(resp, 403, "PATIENT_NOT_VISIBLE")
        admin_resp = self.client.get("/api/v1/summary/patient/ZY002", headers=self.ha)
        self.assertEqual(admin_resp.status_code, 200, admin_resp.text)

    def test_unknown_patient_is_404(self) -> None:
        resp = self.client.get("/api/v1/summary/patient/NOPE", headers=self.ha)
        self.assert_error(resp, 404)


class TestPatientOverview(SummaryTestCase):
    def test_overview_records_are_chronological(self) -> None:
        self.write_record(kind="initial", day="2027-03-01")
        self.write_record(kind="daily", day="2027-03-03")
        body = self.client.get("/api/v1/summary/patient/ZY001/overview", headers=self.h1).json()
        self.assertEqual(body["patient"]["name"], "患者甲")
        self.assertEqual(body["patient"]["assigned_therapist_name"], "张三")
        self.assertEqual([r["record_no"] for r in body["records"]], [1, 2])
        self.assertEqual([r["record_date"] for r in body["records"]], ["2027-03-01", "2027-03-03"])
        self.assertEqual(body["records"][0]["kind"], "initial")
        self.assertIn("康复初始评定", body["records"][0]["rendered_text"])
        self.assertEqual(body["totals"]["record_count"], 1, "只有日常记录算次数")

    def test_overview_excludes_drafts(self) -> None:
        self.write_record(day="2027-03-01", status="draft")
        body = self.client.get("/api/v1/summary/patient/ZY001/overview", headers=self.h1).json()
        self.assertEqual(body["records"], [])


class TestSummaryServiceConsistency(SummaryTestCase):
    """汇总与 PDF 同源：JSON 与 PDF 用的是同一段查询，数字必须一致。"""

    def test_json_and_pdf_totals_agree(self) -> None:
        self.write_record(day="2027-03-01")
        self.write_record(day="2027-03-02")
        summary = summary_service.summarize_date(self.conn, day="2027-03-01")
        overview = summary_service.patient_overview(self.conn, patient_no="ZY001")
        self.assertEqual(summary["totals"]["record_count"], 1)
        self.assertEqual(overview["totals"]["record_count"], 2)

    def test_draft_excluded_at_service_level(self) -> None:
        self.write_record(day="2027-03-01", status="draft")
        summary = summary_service.summarize_date(self.conn, day="2027-03-01")
        self.assertEqual(summary["totals"]["record_count"], 0)


class TestPdfRendering(SummaryTestCase):
    """PDF 的反向文本校验 —— 这是确认中文字体真的生效的唯一可靠手段。"""

    def test_font_registers(self) -> None:
        self.assertEqual(pdf_service.ensure_font(), pdf_service.FONT_NAME)

    def test_patient_summary_pdf_prints_soap_text(self) -> None:
        self.write_record(kind="initial", day="2027-03-01")
        self.write_record(kind="daily", day="2027-03-03")
        overview = summary_service.patient_overview(self.conn, patient_no="ZY001")
        content = pdf_service.patient_summary_pdf(overview)
        self.assertTrue(content.startswith(b"%PDF"), "应是合法 PDF")
        text = pdf_text(content)
        for expected in ("康复医学科", "患者甲", "ZY001", "脑卒中恢复期", "张三", "治疗次数"):
            self.assertIn(expected, text, f"PDF 里应能提取到「{expected}」（否则中文没渲染出来）")
        # SOAP 正文（不是表格）
        for expected in ("康复初始评定", "主观资料", "客观资料", "偏瘫肢体综合训练", "功能诊断"):
            self.assertIn(expected, text, f"PDF 正文里应能提取到「{expected}」")

    def test_patient_summary_is_chronological(self) -> None:
        """★ 用户：「多日的情况下，是按时间顺序往下排就行，不用一天一张」。"""
        self.write_record(kind="initial", day="2027-03-01")
        self.write_record(kind="daily", day="2027-03-03")
        self.write_record(kind="daily", day="2027-03-05")
        overview = summary_service.patient_overview(self.conn, patient_no="ZY001")
        text = pdf_text(pdf_service.patient_summary_pdf(overview))
        positions = [text.index(day) for day in ("2027-03-01", "2027-03-03", "2027-03-05")]
        self.assertEqual(positions, sorted(positions), "日期必须由早到晚排列")

    def test_patient_summary_has_no_patient_signature_line(self) -> None:
        """Q10：不采集患者签字（正文里的「治疗师签名」是模板 footer，见模板 README）。"""
        self.write_record(day="2027-03-01")
        overview = summary_service.patient_overview(self.conn, patient_no="ZY001")
        text = pdf_text(pdf_service.patient_summary_pdf(overview))
        for forbidden in ("患者签字", "家属签字"):
            self.assertNotIn(forbidden, text, f"Q10 定了不做患者签字栏，不应出现「{forbidden}」")

    def test_pdf_footer_has_page_number_and_print_time(self) -> None:
        self.write_record(day="2027-03-01")
        overview = summary_service.patient_overview(self.conn, patient_no="ZY001")
        text = pdf_text(pdf_service.patient_summary_pdf(overview))
        self.assertIn("第 1 页", text)
        self.assertIn("打印时间：", text)

    def test_date_summary_pdf(self) -> None:
        self.write_record(kind="initial", day="2027-03-01")
        self.write_record(kind="daily", day="2027-03-01")
        summary = summary_service.summarize_date(self.conn, day="2027-03-01")
        text = pdf_text(pdf_service.date_summary_pdf(summary))
        for expected in ("康复医学科", "2027-03-01", "患者甲", "张三", "当日总计", "主观资料"):
            self.assertIn(expected, text)
        self.assertNotIn("康复初始评定", text, "按日期汇总只印日常记录（评估文书不占次数）")

    def test_patient_daily_pdf(self) -> None:
        self.write_record(day="2027-03-01")
        self.write_record(day="2027-03-03")
        daily = summary_service.summarize_patient_daily(self.conn, patient_no="ZY001")
        text = pdf_text(pdf_service.patient_daily_pdf(daily))
        for expected in ("康复医学科", "患者甲", "每日汇总", "2027-03-01", "2027-03-03", "主观资料"):
            self.assertIn(expected, text)
        positions = [text.index(day) for day in ("2027-03-01", "2027-03-03")]
        self.assertEqual(positions, sorted(positions), "多日记录按时间升序往下排")

    def test_empty_pdf_does_not_crash(self) -> None:
        overview = summary_service.patient_overview(self.conn, patient_no="ZY001")
        text = pdf_text(pdf_service.patient_summary_pdf(overview))
        self.assertIn("治疗次数：0", text)
        self.assertIn("无", text, "空表应有说明文字")

    def test_multipage_pdf_numbers_every_page(self) -> None:
        for index in range(1, 41):
            self.conn.execute(
                "INSERT INTO treatment_record"
                " (patient_no, therapist_id, record_date, discipline, kind, seq_no, body_json,"
                "  rendered_text, status, submitted_at)"
                " VALUES ('ZY001', ?, ?, 'PT', 'daily', ?, '{}', ?, 'submitted', '2027-04-01T00:00:00.000Z')",
                (
                    int(self.t1["id"]),
                    f"2027-04-{index % 28 + 1:02d}",
                    index,
                    "康复治疗记录（PT运动）\n治疗日期：2027-04-01   第 1 次\n\n"
                    "主观资料：精神状态：良好；主诉：乏力；疼痛VAS：2分\n\n"
                    "客观资料：本次训练项目：偏瘫肢体综合训练",
                ),
            )
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
        self.assertIn("2027-03-01", pdf_text(resp.content))

    def test_print_patient_daily_endpoint(self) -> None:
        self.write_record(day="2027-03-01")
        resp = self.client.get("/api/v1/print/summary/patient/ZY001", headers=self.h1)
        self.assertEqual(resp.status_code, 200, resp.text[:200])
        self.assertIn("每日汇总", pdf_text(resp.content))

    def test_print_covers_department_patients(self) -> None:
        self.write_record(day="2027-03-01", headers=self.h1)
        self.write_record(patient_no="ZY002", day="2027-03-01", headers=self.h2)
        resp = self.client.get(
            "/api/v1/print/summary/date", params={"date": "2027-03-01"}, headers=self.h1
        )
        text = pdf_text(resp.content)
        self.assertIn("患者甲", text)
        self.assertIn("患者乙", text)

    def test_print_respects_discharged_visibility(self) -> None:
        patient_model.update_patient(self.conn, "ZY002", status=patient_model.STATUS_DISCHARGED)
        resp = self.client.get("/api/v1/print/patient/ZY002", headers=self.h1)
        self.assert_error(resp, 403, "PATIENT_NOT_VISIBLE")

    def test_print_requires_auth(self) -> None:
        resp = self.client.get("/api/v1/print/patient/ZY001")
        self.assert_error(resp, 401, "AUTH_REQUIRED")


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

    def test_filter_by_action_and_target_type(self) -> None:
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


class TestRemovedLegacySurfaces(SummaryTestCase):
    """旧模型的接口必须真的消失（表都删了，接口留着只会 500）。"""

    def test_dictionary_endpoints_are_gone(self) -> None:
        for path in (
            "/api/v1/dict/tree",
            "/api/v1/dict/main-items",
            "/api/v1/dict/sub-items/1/params",
            "/api/v1/response-defs",
            "/api/v1/option-sets/resolve",
            "/api/v1/admin/option-sets",
        ):
            resp = self.client.get(path, headers=self.ha)
            self.assertEqual(resp.status_code, 404, f"{path} 应已删除：{resp.status_code}")

    def test_template_endpoints_are_gone(self) -> None:
        """科室模板表已随迁移 011 删除；模板改由 templates/*.json 承载。"""
        resp = self.client.get("/api/v1/templates", headers=self.ha)
        self.assertEqual(resp.status_code, 404)


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
        from app.models import user as user_model

        user_model.update_user(self.conn, int(self.t2["id"]), status="disabled")
        resp = self.client.post(
            "/api/v1/auth/login", json={"employee_no": "T002", "password": DEFAULT_PASSWORD}
        )
        self.assert_error(resp, 403)


if __name__ == "__main__":
    unittest.main(verbosity=2)
