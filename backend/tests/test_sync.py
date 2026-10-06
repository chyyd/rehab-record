"""阶段 4 测试：离线与同步（`开发计划.md` M06、`设计.md` 5.4）。

覆盖重点：

1. **幂等**：同一条变更带同一个 `client_uuid` 重复推送不产生重复数据（弱网重试是常态）；
2. **游标**：`change_log.id` 即游标；增量拉取不漏不重；无新变更时游标不前移；
3. **冲突分层**：记录仍是草稿 → 客户端优先；已提交/已锁定 → 服务端优先并回报冲突；
4. **范围限制**：一期只允许**治疗记录**离线写；字典类只读（那几张表已删除）；
5. **批量边界**：单次推送/拉取有上限，超限明确报错而不是静默截断。

> 2026-10-05：记录改 SOAP 模板驱动后，离线 payload 变成
> `{patient_no, record_date, discipline, kind, body, status}`。
> **门禁不是后门**：离线推一条"第 1 次日常"却缺首评，同样会被 409 拦下 ——
> 所以本文件里的日常记录都要先推首评（`ensure_initial`）。
"""

from __future__ import annotations

import unittest

from app.models import patient as patient_model
from app.models import treatment as treatment_model
from app.services import sync as sync_service
from tests.api_base import ApiTestCase


def daily_body(**overrides) -> dict:
    body = {"therapy_items": ["偏瘫肢体综合训练"], "mental": "良好"}
    body.update(overrides)
    return body


def initial_body(**overrides) -> dict:
    body = {"diagnosis": ["偏瘫运动功能障碍"], "therapy_items": ["偏瘫肢体综合训练"]}
    body.update(overrides)
    return body


class SyncTestCase(ApiTestCase):
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

    def record_payload(self, **overrides) -> dict:
        payload = {
            "patient_no": "ZY001",
            "record_date": "2027-03-01",
            "discipline": "PT",
            "kind": "daily",
            "body": daily_body(),
            "status": "draft",
        }
        payload.update(overrides)
        return payload

    def push(self, changes: list[dict], headers: dict | None = None):
        return self.client.post("/api/v1/sync/push", json={"changes": changes}, headers=headers or self.h1)

    def pull(self, cursor: int = 0, **params):
        return self.client.get(
            "/api/v1/sync/pull", params={"cursor": cursor, **params}, headers=self.h1
        )

    def push_initial(self, uuid: str = "uuid-init-0001", patient_no: str = "ZY001") -> dict:
        """离线场景下第一条必须是首评（门禁要求），所以测试也照这个顺序推。"""
        resp = self.push(
            [
                {
                    "entity": "treatment_record",
                    "client_uuid": uuid,
                    "op": "insert",
                    "payload": self.record_payload(
                        patient_no=patient_no, kind="initial", body=initial_body()
                    ),
                }
            ]
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["applied"]) == 1, body
        return body

    def push_daily(self, uuid: str, record_date: str = "2027-03-01") -> dict:
        """首评之后再推日常记录（每天至多 2 条，见模型层的同日限制）。"""
        resp = self.push(
            [
                {
                    "entity": "treatment_record",
                    "client_uuid": uuid,
                    "op": "insert",
                    "payload": self.record_payload(record_date=record_date),
                }
            ]
        )
        assert resp.status_code == 200, resp.text
        return resp.json()


class TestSyncInfo(SyncTestCase):
    def test_info_describes_contract(self) -> None:
        body = self.client.get("/api/v1/sync/info", headers=self.h1).json()
        self.assertEqual(body["pushable_entities"], ["treatment_record"])
        self.assertEqual(body["pullable_entities"], ["patient", "treatment_record"])
        self.assertEqual(body["max_push_batch"], 200)
        self.assertIn("treatment_record:draft", body["conflict_policy"])
        self.assertEqual(body["conflict_policy"]["treatment_record:draft"], "client_wins")
        self.assertEqual(body["conflict_policy"]["treatment_record:submitted"], "server_wins")
        self.assertEqual(body["conflict_policy"]["treatment_record:locked"], "server_wins")
        self.assertIn("change_log.id", body["note"])


class TestChangeLogWritten(SyncTestCase):
    """服务端写操作必须留下变更日志，否则客户端永远拉不到。"""

    def test_pull_is_empty_initially(self) -> None:
        resp = self.pull()
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["changes"], [])
        self.assertEqual(body["cursor"], 0)

    def test_creating_a_record_writes_change_log(self) -> None:
        created = self.client.post(
            "/api/v1/records",
            json={
                "patient_no": "ZY001",
                "record_date": "2027-03-01",
                "discipline": "PT",
                "kind": "initial",
                "body": initial_body(),
                "status": "draft",
            },
            headers=self.h1,
        )
        self.assertEqual(created.status_code, 201, created.text)
        body = self.pull().json()
        self.assertEqual(len(body["changes"]), 1)
        change = body["changes"][0]
        self.assertEqual(change["entity"], "treatment_record")
        self.assertEqual(change["op"], "insert")
        self.assertEqual(change["entity_id"], str(created.json()["id"]))
        # 快照要能让客户端在本地完整重建（SOAP 模型：body + rendered_text）
        self.assertIn("body", change["payload"])
        self.assertIn("rendered_text", change["payload"])
        self.assertGreater(body["cursor"], 0)

    def test_submit_and_lock_are_logged(self) -> None:
        record = self.client.post(
            "/api/v1/records",
            json={
                "patient_no": "ZY001",
                "record_date": "2027-03-01",
                "discipline": "PT",
                "kind": "initial",
                "body": initial_body(),
                "status": "draft",
            },
            headers=self.h1,
        ).json()
        self.client.post(f"/api/v1/records/{record['id']}/submit", headers=self.h1)
        self.client.post(f"/api/v1/records/{record['id']}/lock", headers=self.ha)

        ops = [c["op"] for c in self.pull().json()["changes"]]
        self.assertEqual(ops, ["insert", "update", "update"], "创建/提交/锁定都应进日志")

    def test_delete_draft_writes_delete_op(self) -> None:
        """草稿删除必须写 `op=delete`：否则离线端会永久保留一条幻影记录。"""
        record = self.client.post(
            "/api/v1/records",
            json={
                "patient_no": "ZY001",
                "record_date": "2027-03-01",
                "discipline": "PT",
                "kind": "initial",
                "body": initial_body(),
                "status": "draft",
            },
            headers=self.h1,
        ).json()
        resp = self.client.delete(f"/api/v1/records/{record['id']}", headers=self.h1)
        self.assertEqual(resp.status_code, 204, resp.text)

        changes = self.pull().json()["changes"]
        self.assertEqual([c["op"] for c in changes], ["insert", "delete"])
        self.assertEqual(changes[-1]["entity_id"], str(record["id"]))
        row = self.conn.execute(
            "SELECT action FROM audit_log WHERE action = 'delete_draft' AND target_id = ?",
            (str(record["id"]),),
        ).fetchone()
        self.assertIsNotNone(row, "删除草稿应留审计")

    def test_record_update_is_logged_with_snapshot(self) -> None:
        created = self.client.post(
            "/api/v1/records",
            json={
                "patient_no": "ZY001",
                "record_date": "2027-03-01",
                "discipline": "PT",
                "kind": "initial",
                "body": initial_body(),
                "status": "draft",
            },
            headers=self.h1,
        ).json()
        self.client.put(
            f"/api/v1/records/{created['id']}",
            json={"body": initial_body(diagnosis=["平衡功能障碍"])},
            headers=self.h1,
        )
        changes = self.pull().json()["changes"]
        self.assertEqual([c["op"] for c in changes], ["insert", "update"])
        self.assertEqual(changes[-1]["payload"]["body"]["diagnosis"], ["平衡功能障碍"])


class TestCursorSemantics(SyncTestCase):
    def test_cursor_advances_and_is_monotonic(self) -> None:
        self.push_initial(uuid="uuid-cur-init")
        for index, day in enumerate(("2027-03-01", "2027-03-02", "2027-03-03"), start=1):
            self.push_daily(uuid=f"uuid-cur-{index}", record_date=day)
        first = self.pull().json()
        ids = [c["id"] for c in first["changes"]]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(first["cursor"], ids[-1])

        second = self.pull(cursor=first["cursor"]).json()
        self.assertEqual(second["changes"], [])
        self.assertEqual(second["cursor"], first["cursor"], "无新变更时游标不应前移")
        self.assertFalse(second["has_more"])

    def test_incremental_pull_does_not_skip(self) -> None:
        self.push_initial(uuid="uuid-inc-0001")
        first = self.pull().json()
        self.push_daily(uuid="uuid-inc-0002", record_date="2027-03-02")
        second = self.pull(cursor=first["cursor"]).json()
        self.assertEqual(len(second["changes"]), 1)
        self.assertGreater(second["cursor"], first["cursor"])

    def test_has_more_when_batch_is_truncated(self) -> None:
        self.push_initial(uuid="uuid-more-init")
        for index, day in enumerate(("2027-03-01", "2027-03-02"), start=1):
            self.push_daily(uuid=f"uuid-more-{index:04d}", record_date=day)
        body = self.pull(limit=1).json()
        self.assertEqual(len(body["changes"]), 1)
        self.assertTrue(body["has_more"], "还有未拉取的变更时应提示 has_more")

    def test_entity_filter_is_for_initial_full_sync_only(self) -> None:
        sync_service.record_change(
            self.conn, entity="patient", entity_id="ZY001", op="update",
            revision=2, actor_user_id=int(self.admin["id"]), payload={"name": "患者甲"},
        )
        self.push_initial(uuid="uuid-filter-0001")

        only_records = self.pull(entities=["treatment_record"]).json()
        self.assertEqual(len(only_records["changes"]), 1)
        self.assertEqual(only_records["changes"][0]["entity"], "treatment_record")
        self.assertEqual(only_records["cursor"], only_records["latest_cursor"])
        self.assertFalse(only_records["has_more"])

        unfiltered = self.pull().json()
        self.assertEqual(
            [c["entity"] for c in unfiltered["changes"]], ["patient", "treatment_record"]
        )

    def test_latest_cursor_reported(self) -> None:
        self.push_initial(uuid="uuid-latest-0001")
        body = self.pull().json()
        self.assertEqual(body["latest_cursor"], body["cursor"], "拉完全部后两者应一致")

    def test_unknown_entity_filter_rejected(self) -> None:
        resp = self.pull(entities=["dictionary"])
        self.assert_error(resp, 422, "INVALID")

    def test_negative_cursor_rejected(self) -> None:
        resp = self.client.get("/api/v1/sync/pull", params={"cursor": -1}, headers=self.h1)
        self.assert_error(resp, 422)

    def test_limit_above_max_rejected(self) -> None:
        resp = self.client.get(
            "/api/v1/sync/pull", params={"cursor": 0, "limit": 99999}, headers=self.h1
        )
        self.assert_error(resp, 422)


class TestIdempotentPush(SyncTestCase):
    def change(self, uuid: str, **payload_overrides) -> dict:
        return {
            "entity": "treatment_record",
            "client_uuid": uuid,
            "op": "insert",
            "payload": self.record_payload(**payload_overrides),
        }

    def test_push_creates_record(self) -> None:
        resp = self.push([self.change("uuid-aaaa-0001", kind="initial", body=initial_body())])
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(len(body["applied"]), 1)
        self.assertEqual(body["applied"][0]["outcome"], "applied")
        self.assertEqual(body["conflicts"], [])
        count = self.conn.execute("SELECT COUNT(*) FROM treatment_record").fetchone()[0]
        self.assertEqual(count, 1)
        # client_uuid 在创建时就写进去了（离线幂等的唯一依据）
        row = self.conn.execute("SELECT client_uuid, seq_no FROM treatment_record").fetchone()
        self.assertEqual(row["client_uuid"], "uuid-aaaa-0001")
        self.assertIsNone(row["seq_no"], "首评不占次数")

    def test_push_daily_without_initial_is_reported_per_item(self) -> None:
        """★ 离线推送不是后门：第 1 次日常缺首评同样被拦下。

        **★ 2026-10-05 修：拦截方式从"整批 409"改为"逐条 conflict"。**

        原来 `apply_push` 里 `create_record()` 抛的 `Conflict` 直接穿透，
        整个 `/sync/push` 返回 409 —— 离线队列里攒了几十条时，客户端**连哪一条
        出的问题都不知道**，只能整批重推。现在这一条进 `conflicts` 并带
        `reason`/`details`，其余条目照常应用，HTTP 仍是 200。
        """
        resp = self.push([self.change("uuid-aaaa-0009")])
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["applied"], [])
        self.assertEqual(len(body["conflicts"]), 1, str(body)[:250])
        item = body["conflicts"][0]
        self.assertEqual(item["client_uuid"], "uuid-aaaa-0009")
        self.assertEqual(item["reason"], "MISSING_ASSESSMENT")
        self.assertEqual(item["details"]["missing_document"], "initial")
        # 服务端根本没写：拦下的条目不能留下半条数据
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM treatment_record").fetchone()[0], 0
        )

    def test_one_blocked_item_does_not_stop_the_rest_of_the_batch(self) -> None:
        """★ 一条被门禁拦下，同批其它条目照常应用 —— 这是本次修复的全部意义。

        构造是**确定性**的：先备好首评 + 当天 1 条日常（该日已占 1 条），
        再在同一批里推「同一天的第 3 条」（必然撞同日上限 → conflict）
        与「另一天的第 1 条」（必然应用）。断言两条各自的归属。
        """
        self.push_initial(uuid="uuid-init-batch")
        self.push_daily("uuid-day1-first", record_date="2027-03-01")
        self.push_daily("uuid-day1-second", record_date="2027-03-01")  # 该日已 2 条 → 满

        blocked = {
            "entity": "treatment_record",
            "client_uuid": "uuid-day1-third",
            "op": "insert",
            "payload": self.record_payload(record_date="2027-03-01"),   # 第 3 条 → 拦
        }
        ok = {
            "entity": "treatment_record",
            "client_uuid": "uuid-day2-first",
            "op": "insert",
            "payload": self.record_payload(record_date="2027-03-02"),   # 另一天 → 放行
        }
        resp = self.push([blocked, ok])
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(
            [c["client_uuid"] for c in body["conflicts"]], ["uuid-day1-third"],
            f"只该拦下同日第 3 条；body={str(body)[:250]}",
        )
        self.assertEqual(
            [a["client_uuid"] for a in body["applied"]], ["uuid-day2-first"],
            f"同批里合法的那条必须照常应用；body={str(body)[:250]}",
        )

    def test_same_client_uuid_twice_is_idempotent(self) -> None:
        """弱网重试：同一条变更推两次只能产生一条数据。

        第二次应被识别为"同一条"并正常更新（草稿客户端优先），
        而不能被当成冲突 —— 客户端重推自己创建的那条时通常没带 base_revision。
        """
        change = self.change("uuid-aaaa-0002", kind="initial", body=initial_body())
        first = self.push([change]).json()
        self.assertEqual(len(first["applied"]), 1)

        second = self.push([change]).json()
        count = self.conn.execute("SELECT COUNT(*) FROM treatment_record").fetchone()[0]
        self.assertEqual(count, 1, "重复推送不得产生重复数据")
        self.assertEqual(second["conflicts"], [], "重试自己创建的草稿不应被判为冲突")
        self.assertEqual(len(second["applied"]), 1)
        self.assertEqual(second["applied"][0]["op"], "update")

    def test_duplicate_uuid_within_one_batch_skipped(self) -> None:
        change = self.change("uuid-aaaa-0003", kind="initial", body=initial_body())
        body = self.push([change, dict(change)]).json()
        self.assertEqual(len(body["applied"]), 1)
        self.assertEqual(len(body["skipped"]), 1)
        self.assertEqual(body["skipped"][0]["reason"], "duplicate_in_batch")

    def test_push_updates_existing_draft_when_revision_matches(self) -> None:
        pushed = self.push([self.change("uuid-aaaa-0004", kind="initial", body=initial_body())]).json()
        record_id = pushed["applied"][0]["entity_id"]
        revision = pushed["applied"][0]["revision"]

        updated = self.push(
            [
                {
                    "entity": "treatment_record",
                    "client_uuid": "uuid-aaaa-0004",
                    "op": "update",
                    "base_revision": revision,
                    "payload": self.record_payload(
                        kind="initial", body=initial_body(diagnosis=["平衡功能障碍"])
                    ),
                }
            ]
        ).json()
        self.assertEqual(len(updated["applied"]), 1)
        self.assertEqual(updated["applied"][0]["outcome"], "applied")
        body_json = self.conn.execute(
            "SELECT body_json FROM treatment_record WHERE id = ?", (record_id,)
        ).fetchone()["body_json"]
        self.assertIn("平衡功能障碍", body_json)

    def test_push_rejects_unknown_entity(self) -> None:
        """`appointment`（已下线的排期实体）必须明确报错而不是静默丢弃。"""
        resp = self.push(
            [
                {
                    "entity": "appointment",
                    "client_uuid": "uuid-bbbb-0001",
                    "op": "insert",
                    "payload": {"patient_no": "ZY001", "date": "2027-03-01", "period": "am"},
                }
            ]
        )
        self.assert_error(resp, 422, "INVALID")
        self.assertIn("treatment_record", resp.json()["details"]["allowed"])


class TestConflictPolicy(SyncTestCase):
    """冲突分层：草稿客户端优先；已提交/已锁定服务端优先。"""

    def _push_initial_draft(self, uuid: str = "uuid-c000-0001") -> dict:
        return self.push(
            [
                {
                    "entity": "treatment_record",
                    "client_uuid": uuid,
                    "op": "insert",
                    "payload": self.record_payload(kind="initial", body=initial_body()),
                }
            ]
        ).json()

    def test_client_wins_while_server_is_draft(self) -> None:
        pushed = self._push_initial_draft()
        revision = pushed["applied"][0]["revision"]

        self.conn.execute("UPDATE treatment_record SET revision = revision + 1")
        stale = self.push(
            [
                {
                    "entity": "treatment_record",
                    "client_uuid": "uuid-c000-0001",
                    "op": "update",
                    "base_revision": revision,
                    "payload": self.record_payload(
                        kind="initial", body=initial_body(diagnosis=["重心转移障碍"])
                    ),
                }
            ]
        ).json()
        self.assertEqual(len(stale["applied"]), 1, f"草稿应客户端优先：{stale}")
        self.assertEqual(stale["conflicts"], [])
        body_json = self.conn.execute("SELECT body_json FROM treatment_record").fetchone()["body_json"]
        self.assertIn("重心转移障碍", body_json)

    def test_server_wins_when_submitted(self) -> None:
        pushed = self._push_initial_draft(uuid="uuid-c000-0002")
        revision = pushed["applied"][0]["revision"]
        record_id = pushed["applied"][0]["entity_id"]
        treatment_model.submit_record(self.conn, int(record_id), user_id=int(self.t1["id"]))

        stale = self.push(
            [
                {
                    "entity": "treatment_record",
                    "client_uuid": "uuid-c000-0002",
                    "op": "update",
                    "base_revision": revision,
                    "payload": self.record_payload(
                        kind="initial", body=initial_body(diagnosis=["试图覆盖已提交"])
                    ),
                }
            ]
        ).json()
        self.assertEqual(len(stale["conflicts"]), 1, f"已提交应服务端优先：{stale}")
        conflict = stale["conflicts"][0]
        self.assertEqual(conflict["outcome"], "conflict")
        self.assertEqual(conflict["server_status"], "submitted")
        self.assertGreater(conflict["server_revision"], revision)
        body_json = self.conn.execute("SELECT body_json FROM treatment_record").fetchone()["body_json"]
        self.assertNotIn("试图覆盖已提交", body_json)

    def test_server_wins_when_locked(self) -> None:
        pushed = self._push_initial_draft(uuid="uuid-c000-0003")
        revision = pushed["applied"][0]["revision"]
        record_id = int(pushed["applied"][0]["entity_id"])
        treatment_model.submit_record(self.conn, record_id, user_id=int(self.t1["id"]))
        treatment_model.lock_record(self.conn, record_id)

        stale = self.push(
            [
                {
                    "entity": "treatment_record",
                    "client_uuid": "uuid-c000-0003",
                    "op": "update",
                    "base_revision": revision,
                    "payload": self.record_payload(kind="initial", body=initial_body()),
                }
            ]
        ).json()
        self.assertEqual(len(stale["conflicts"]), 1)
        self.assertEqual(stale["conflicts"][0]["server_status"], "locked")

    def test_missing_base_revision_is_server_wins(self) -> None:
        """客户端没给基线版本、且服务端已不是草稿时，服务端优先（无法安全合并）。"""
        pushed = self._push_initial_draft(uuid="uuid-c000-0004")
        record_id = pushed["applied"][0]["entity_id"]
        treatment_model.submit_record(self.conn, int(record_id), user_id=int(self.t1["id"]))

        body = self.push(
            [
                {
                    "entity": "treatment_record",
                    "client_uuid": "uuid-c000-0004",
                    "op": "update",
                    "payload": self.record_payload(kind="initial", body=initial_body()),
                }
            ]
        ).json()
        self.assertEqual(len(body["conflicts"]), 1, f"应服务端优先：{body}")
        self.assertEqual(body["conflicts"][0]["reason"], "missing_base_revision")

    def test_same_revision_applies_without_conflict(self) -> None:
        pushed = self._push_initial_draft(uuid="uuid-c000-0005")
        revision = pushed["applied"][0]["revision"]
        body = self.push(
            [
                {
                    "entity": "treatment_record",
                    "client_uuid": "uuid-c000-0005",
                    "op": "update",
                    "base_revision": revision,
                    "payload": self.record_payload(kind="initial", body=initial_body()),
                }
            ]
        ).json()
        self.assertEqual(body["conflicts"], [])
        self.assertEqual(len(body["applied"]), 1)

    def test_one_conflict_does_not_fail_whole_batch(self) -> None:
        """离线队列常攒几十条；一条冲突不应让整批退回。"""
        pushed = self._push_initial_draft(uuid="uuid-c000-0006")
        treatment_model.submit_record(
            self.conn, int(pushed["applied"][0]["entity_id"]), user_id=int(self.t1["id"])
        )
        body = self.push(
            [
                {
                    "entity": "treatment_record",
                    "client_uuid": "uuid-c000-0006",
                    "op": "update",
                    "base_revision": pushed["applied"][0]["revision"],
                    "payload": self.record_payload(kind="initial", body=initial_body()),
                },
                {
                    "entity": "treatment_record",
                    "client_uuid": "uuid-c000-0007",
                    "op": "insert",
                    "payload": self.record_payload(record_date="2027-03-02"),
                },
            ]
        ).json()
        self.assertEqual(len(body["conflicts"]), 1)
        self.assertEqual(len(body["applied"]), 1, "另一条应正常应用")
        self.assertEqual(body["applied"][0]["client_uuid"], "uuid-c000-0007")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM treatment_record").fetchone()[0],
            2,
            "冲突条不得被写入，正常条必须落库",
        )

    def test_resolve_conflict_helper_directly(self) -> None:
        self.assertIsNone(
            sync_service.resolve_conflict(
                self.conn, entity="treatment_record", entity_id=99999, base_revision=1
            ),
            "服务端没有该记录时不算冲突",
        )

    def test_revision_bumps_on_every_mutation(self) -> None:
        """离线客户端靠 revision 判断副本是否过期；任何会改数据的操作都必须推进它。"""
        record = self.client.post(
            "/api/v1/records",
            json={
                "patient_no": "ZY001",
                "record_date": "2027-03-01",
                "discipline": "PT",
                "kind": "initial",
                "body": initial_body(),
                "status": "draft",
            },
            headers=self.h1,
        ).json()
        self.assertEqual(record["revision"], 1, "新建应为 1")

        updated = treatment_model.update_record(
            self.conn, int(record["id"]), user_id=int(self.t1["id"]),
            body=initial_body(diagnosis=["平衡功能障碍"]),
        )
        self.assertEqual(updated["revision"], 2, "修改应推进 revision")

        submitted = treatment_model.submit_record(
            self.conn, int(record["id"]), user_id=int(self.t1["id"])
        )
        self.assertEqual(submitted["revision"], 3, "提交应推进 revision")

        locked = treatment_model.lock_record(self.conn, int(record["id"]))
        self.assertEqual(locked["revision"], 4, "锁定应推进 revision")

    def test_retry_after_submit_is_reported_but_never_duplicates(self) -> None:
        """重试自己**已提交**的记录：不得产生重复数据，且必须回报冲突。"""
        change = {
            "entity": "treatment_record",
            "client_uuid": "uuid-j000-0001",
            "op": "insert",
            "payload": self.record_payload(kind="initial", body=initial_body()),
        }
        first = self.push([change]).json()
        treatment_model.submit_record(
            self.conn, int(first["applied"][0]["entity_id"]), user_id=int(self.t1["id"])
        )

        second = self.push([change]).json()
        self.assertEqual(len(second["conflicts"]), 1, f"已提交应服务端优先：{second}")
        self.assertEqual(second["conflicts"][0]["reason"], "missing_base_revision")
        self.assertEqual(second["conflicts"][0]["server_status"], "submitted")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM treatment_record").fetchone()[0],
            1,
            "重试不得产生重复数据",
        )


class TestPushValidation(SyncTestCase):
    def test_cannot_push_patient(self) -> None:
        """一期只允许治疗记录离线写；患者主数据由管理员在线维护。"""
        resp = self.push(
            [
                {
                    "entity": "patient",
                    "client_uuid": "uuid-d000-0001",
                    "op": "insert",
                    "payload": {"inpatient_no": "ZY999", "name": "不该离线建"},
                }
            ]
        )
        self.assert_error(resp, 422, "INVALID")
        self.assertIn("allowed", resp.json()["details"])

    def test_missing_client_uuid_rejected(self) -> None:
        resp = self.push([{"entity": "treatment_record", "op": "insert", "payload": {}}])
        self.assert_error(resp, 422)

    def test_empty_changes_rejected(self) -> None:
        resp = self.client.post("/api/v1/sync/push", json={"changes": []}, headers=self.h1)
        self.assert_error(resp, 422)

    def test_batch_too_large_rejected(self) -> None:
        too_many = [
            {
                "entity": "treatment_record",
                "client_uuid": f"uuid-e000-{i:04d}",
                "op": "insert",
                "payload": self.record_payload(kind="initial", body=initial_body()),
            }
            for i in range(sync_service.MAX_PUSH_BATCH + 1)
        ]
        resp = self.push(too_many)
        self.assert_error(resp, 422, "VALIDATION_ERROR")
        self.assertIn("changes", resp.json()["details"]["fields"])

    def test_push_requires_auth(self) -> None:
        resp = self.client.post(
            "/api/v1/sync/push",
            json={
                "changes": [
                    {
                        "entity": "treatment_record",
                        "client_uuid": "uuid-f000-0001",
                        "op": "insert",
                        "payload": self.record_payload(kind="initial", body=initial_body()),
                    }
                ]
            },
        )
        self.assert_error(resp, 401, "AUTH_REQUIRED")

    def test_invalid_op_rejected(self) -> None:
        """op 必须是 insert / update / delete —— 服务端显式校验，而不是默默当作 update。"""
        resp = self.push(
            [
                {
                    "entity": "treatment_record",
                    "client_uuid": "uuid-g000-0001",
                    "op": "merge",
                    "payload": self.record_payload(kind="initial", body=initial_body()),
                }
            ]
        )
        self.assert_error(resp, 422, "INVALID")
        self.assertEqual(resp.json()["details"]["op"], "merge")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM treatment_record").fetchone()[0],
            0,
            "非法 op 不应产生任何写入",
        )

    def test_missing_required_field_rejected(self) -> None:
        """不在客户端兜底：缺必填同样在服务端被 422 拦下。"""
        resp = self.push(
            [
                {
                    "entity": "treatment_record",
                    "client_uuid": "uuid-g000-0002",
                    "op": "insert",
                    "payload": self.record_payload(kind="initial", body={"therapy_items": []}),
                }
            ]
        )
        self.assert_error(resp, 422, "INVALID")
        self.assertIn("功能诊断", resp.json()["details"]["missing"])


class TestOfflineThenOnlineScenario(SyncTestCase):
    """完整离线场景：断网期攒变更 → 恢复后一次推送 → 另一端拉取到全部。"""

    def test_offline_batch_then_pull(self) -> None:
        changes = [
            {
                "entity": "treatment_record",
                "client_uuid": "uuid-h000-0000",
                "op": "insert",
                "payload": self.record_payload(
                    record_date="2027-03-01", kind="initial", body=initial_body()
                ),
            }
        ]
        for index in range(1, 5):
            changes.append(
                {
                    "entity": "treatment_record",
                    "client_uuid": f"uuid-h000-{index:04d}",
                    "op": "insert",
                    "payload": self.record_payload(record_date=f"2027-03-0{index + 1}"),
                }
            )
        body = self.push(changes).json()
        self.assertEqual(len(body["applied"]), 5, f"应全部应用：{body}")
        self.assertEqual(body["conflicts"], [])

        pulled = self.pull().json()
        self.assertEqual(len(pulled["changes"]), 5)
        self.assertEqual(pulled["cursor"], body["cursor"], "推送返回的游标应与拉取一致")

    def test_retry_whole_batch_after_network_failure(self) -> None:
        """模拟"服务端已写入但响应丢失"，客户端整批重试。"""
        changes = [
            {
                "entity": "treatment_record",
                "client_uuid": "uuid-i000-0000",
                "op": "insert",
                "payload": self.record_payload(
                    record_date="2027-03-01", kind="initial", body=initial_body()
                ),
            }
        ]
        for index in range(1, 3):
            changes.append(
                {
                    "entity": "treatment_record",
                    "client_uuid": f"uuid-i000-{index:04d}",
                    "op": "insert",
                    "payload": self.record_payload(record_date=f"2027-03-0{index + 1}"),
                }
            )
        self.push(changes)
        before = self.conn.execute("SELECT COUNT(*) FROM treatment_record").fetchone()[0]

        self.push(changes)
        after = self.conn.execute("SELECT COUNT(*) FROM treatment_record").fetchone()[0]
        self.assertEqual(before, after, "整批重试不得产生重复数据")


if __name__ == "__main__":
    unittest.main(verbosity=2)
