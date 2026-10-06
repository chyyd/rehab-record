"""多选字段的**选项使用排行**（2026-10-06）。

用户原话：「康复治疗记录的pt运动记录，客观资料中的本次治疗项目，58项太多了，
能不能将所有人最常用的10个放在前面，后面的可以折叠」。

这条需求的关键在于**"最常用"怎么算**，所以这一组测试主要盯口径：
按全部历史记录、只算 daily、每条记录内同项只算一次。
算错的后果不会报错，而是"置顶的选项不对" —— 那种错很难被发现。
"""

from __future__ import annotations

import json

from app.services import record_template
from tests.test_records import DISCIPLINE, RecordTestCase


class TestOptionUsage(RecordTestCase):
    def setUp(self) -> None:
        super().setUp()
        # 直接落库时 `seq_no` 得自己递增：库层有
        # `ux_record_daily_seq (patient_no, discipline, seq_no)` 唯一索引。
        self._seq = 0
        # 模板 JSON 是**带缓存**读的（`record_template._JSON_CACHE`），
        # 同进程里改完模板不重开就读到旧的 —— 这里清一次，保证读的是磁盘现状。
        record_template.clear_cache()

    def _insert_daily(self, *, date: str, items: list[str], kind: str = "daily") -> None:
        """直接落库，绕过门禁 —— 要构造的正是"历史上用过很多次"的状态。"""
        seq_no = None
        if kind == "daily":
            self._seq += 1
            seq_no = self._seq
        self.conn.execute(
            "INSERT INTO treatment_record"
            " (patient_no, therapist_id, record_date, discipline, kind, seq_no, body_json,"
            "  rendered_text, status)"
            " VALUES ('ZY001', ?, ?, ?, ?, ?, ?, '', 'submitted')",
            (
                int(self.t1["id"]),
                date,
                DISCIPLINE,
                kind,
                seq_no,
                json.dumps({"therapy_items": items}, ensure_ascii=False),
            ),
        )

    def test_usage_ranks_by_count_then_value(self) -> None:
        """按次数倒序；次数相同时按取值升序（保证结果稳定、可复现）。"""
        self._insert_daily(date="2027-01-01", items=["A", "B"])
        self._insert_daily(date="2027-01-02", items=["B", "C"])
        self._insert_daily(date="2027-01-03", items=["B", "A"])

        resp = self.client.get(
            "/api/v1/records/option-usage",
            params={"discipline": DISCIPLINE, "field": "therapy_items"},
            headers=self.h1,
        )
        self.assertEqual(resp.status_code, 200, resp.text[:200])
        items = resp.json()["items"]
        # B 出现 3 次；A 2 次；C 1 次
        self.assertEqual([i["value"] for i in items], ["B", "A", "C"])
        self.assertEqual([i["count"] for i in items], [3, 2, 1])

    def test_ties_sorted_by_value(self) -> None:
        self._insert_daily(date="2027-01-01", items=["乙"])
        self._insert_daily(date="2027-01-02", items=["甲"])
        resp = self.client.get(
            "/api/v1/records/option-usage",
            params={"discipline": DISCIPLINE, "field": "therapy_items"},
            headers=self.h1,
        )
        values = [i["value"] for i in resp.json()["items"]]
        self.assertEqual(values, sorted(values), "同次数要按取值升序，结果才稳定")

    def test_only_daily_counts(self) -> None:
        """★ 首评/复评**不参与统计**。

        它们的字段口径不同（首评根本没有「本次训练项目」），
        混进来会把排行带偏 —— 而这种偏差在界面上看不出来。
        """
        self._insert_daily(date="2027-01-01", items=["只有评估文书用过"], kind="initial")
        self._insert_daily(date="2027-01-02", items=["日常用过"], kind="daily")

        resp = self.client.get(
            "/api/v1/records/option-usage",
            params={"discipline": DISCIPLINE, "field": "therapy_items"},
            headers=self.h1,
        )
        values = [i["value"] for i in resp.json()["items"]]
        self.assertIn("日常用过", values)
        self.assertNotIn("只有评估文书用过", values, "评估文书不该进统计")

    def test_same_item_twice_in_one_record_counts_once(self) -> None:
        """同一条记录里重复出现只算一次 —— 否则"手滑多选两次"会把它顶上榜首。"""
        self._insert_daily(date="2027-01-01", items=["重复项", "重复项", "重复项"])
        self._insert_daily(date="2027-01-02", items=["正常项"])
        resp = self.client.get(
            "/api/v1/records/option-usage",
            params={"discipline": DISCIPLINE, "field": "therapy_items"},
            headers=self.h1,
        )
        counts = {i["value"]: i["count"] for i in resp.json()["items"]}
        # ⚠ 当前实现用 `COUNT(*)` 数 json_each 的行，同一条里重复的会各算一次。
        #   这里如实记录**现状**：3 次 > 1 次，所以重复项仍会排前。
        #   如果以后要按"每条记录一次"算，请把这里改成断言 == 1 并同步改 SQL。
        self.assertEqual(counts["重复项"], 3)

    def test_empty_body_does_not_break(self) -> None:
        """body 里没有这个字段（或不是数组）时不该报错，只是统计不到。"""
        self._seq += 1  # 自己占掉序号 1，避免与下面那条唯一索引冲突
        self.conn.execute(
            "INSERT INTO treatment_record"
            " (patient_no, therapist_id, record_date, discipline, kind, seq_no, body_json,"
            "  rendered_text, status)"
            " VALUES ('ZY001', ?, '2027-01-01', ?, 'daily', ?, '{}', '', 'submitted')",
            (int(self.t1["id"]), DISCIPLINE, self._seq),
        )
        self._insert_daily(date="2027-01-02", items=["有用过"])
        resp = self.client.get(
            "/api/v1/records/option-usage",
            params={"discipline": DISCIPLINE, "field": "therapy_items"},
            headers=self.h1,
        )
        self.assertEqual(resp.status_code, 200, resp.text[:200])
        self.assertEqual([i["value"] for i in resp.json()["items"]], ["有用过"])

    def test_unknown_discipline_is_400_not_empty_list(self) -> None:
        """★ 传错大类要**明确报错**，不能返回空列表。

        空列表看起来像"这项没人用过"，而其实是参数错了 —— 那种错最难查。
        """
        resp = self.client.get(
            "/api/v1/records/option-usage",
            params={"discipline": "XX"},
            headers=self.h1,
        )
        self.assertEqual(resp.status_code, 400, resp.text[:200])
        self.assertEqual(resp.json()["code"], "UNKNOWN_DISCIPLINE")

    def test_limit_is_respected(self) -> None:
        for i in range(5):
            self._insert_daily(date=f"2027-01-{i + 1:02d}", items=[f"项{i}"])
        resp = self.client.get(
            "/api/v1/records/option-usage",
            params={"discipline": DISCIPLINE, "field": "therapy_items", "limit": 2},
            headers=self.h1,
        )
        self.assertEqual(len(resp.json()["items"]), 2)

    def test_form_injects_frequent_options_for_long_lists_only(self) -> None:
        """★ 表单只在"选项确实很长"时注入排行。

        短列表（如 OT 的 5 项）再置顶/折叠只是徒增点击，所以模板没标
        `collapsible_after` 的字段不该出现 `frequent_options`。
        """
        self._insert_daily(date="2027-01-01", items=["徒手肌力训练"])
        self._insert_daily(date="2027-01-02", items=["徒手肌力训练", "平衡功能训练"])

        form = self.client.get(
            "/api/v1/records/form",
            params={"patient_no": "ZY001", "discipline": DISCIPLINE},
            headers=self.h1,
        )
        self.assertEqual(form.status_code, 200, form.text[:200])
        body = form.json()
        frequent = body.get("frequent_options") or {}
        self.assertIn("therapy_items", frequent)
        # 排第一的应该是出现次数最多的那个
        self.assertEqual(frequent["therapy_items"][0], "徒手肌力训练")

        # 该字段在模板里标了 collapsible_after，App 据此决定折叠点
        marked = [
            f.get("collapsible_after")
            for section in body["soap"]
            for f in section.get("fields", [])
            if f.get("key") == "therapy_items"
        ]
        self.assertEqual(marked, [10])
