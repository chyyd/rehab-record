"""阶段 4 测试：离线与同步（`开发计划.md` M06、`设计.md` 5.4）。

覆盖重点：
1. **幂等**：同一条变更带同一个 `client_uuid` 重复推送不产生重复数据（弱网重试是常态）；
2. **游标**：`change_log.id` 即游标；增量拉取不漏不重；无新变更时游标不前移；
3. **冲突分层**：记录仍是草稿 → 客户端优先；已提交/已锁定 → 服务端优先并回报冲突；
4. **范围限制**：一期只允许治疗记录与排期离线写，字典类只读；
5. **批量边界**：单次推送/拉取有上限，超限明确报错而不是静默截断。
"""

from __future__ import annotations

import unittest

from app.models import patient as patient_model
from app.models import treatment as treatment_model
from app.services import sync as sync_service
from seed.dictionary import seed_dictionary
from tests.api_base import ApiTestCase


class SyncTestCase(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        seed_dictionary(self.conn)
        self.t1 = self.make_user("T001", "张三")
        self.t2 = self.make_user("T002", "李四")
        self.admin = self.make_admin("A001")
        self.p1 = patient_model.create_patient(
            self.conn, inpatient_no="ZY001", name="患者甲", assigned_therapist_id=int(self.t1["id"])
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

    def record_payload(self, **overrides) -> dict:
        payload = {
            "patient_no": "ZY001",
            "record_date": "2027-03-01",
            "session_period": "am",
            "note": "离线记录",
            "status": "draft",
            "items": [
                {
                    "main_item_id": self.motor_main,
                    "sub_item_id": self.motor_sub,
                    "params": {"side": "左"},
                }
            ],
        }
        payload.update(overrides)
        return payload

    def push(self, changes: list[dict], headers: dict | None = None):
        return self.client.post("/api/v1/sync/push", json={"changes": changes}, headers=headers or self.h1)

    def pull(self, cursor: int = 0, **params):
        return self.client.get(
            "/api/v1/sync/pull", params={"cursor": cursor, **params}, headers=self.h1
        )


class TestSyncInfo(SyncTestCase):
    def test_info_describes_contract(self) -> None:
        body = self.client.get("/api/v1/sync/info", headers=self.h1).json()
        self.assertEqual(body["pushable_entities"], ["treatment_record", "appointment"])
        self.assertEqual(body["pullable_entities"], ["patient", "appointment", "treatment_record"])
        self.assertEqual(body["max_push_batch"], 200)
        self.assertIn("treatment_record:draft", body["conflict_policy"])
        self.assertEqual(body["conflict_policy"]["treatment_record:draft"], "client_wins")
        self.assertEqual(body["conflict_policy"]["treatment_record:submitted"], "server_wins")
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
            "/api/v1/records", json=self.record_payload(), headers=self.h1
        )
        self.assertEqual(created.status_code, 201, created.text)
        body = self.pull().json()
        self.assertEqual(len(body["changes"]), 1)
        change = body["changes"][0]
        self.assertEqual(change["entity"], "treatment_record")
        self.assertEqual(change["op"], "insert")
        self.assertEqual(change["entity_id"], str(created.json()["id"]))
        self.assertGreater(body["cursor"], 0)

    def test_submit_and_lock_are_logged(self) -> None:
        record = self.client.post("/api/v1/records", json=self.record_payload(), headers=self.h1).json()
        self.client.post(f"/api/v1/records/{record['id']}/submit", headers=self.h1)
        self.client.post(f"/api/v1/records/{record['id']}/lock", headers=self.ha)

        ops = [c["op"] for c in self.pull().json()["changes"]]
        self.assertEqual(ops, ["insert", "update", "update"], "创建/提交/锁定都应进日志")

    def test_appointment_changes_are_logged(self) -> None:
        self.client.post(
            "/api/v1/schedule",
            json={"patient_no": "ZY001", "date": "2027-03-01", "period": "am"},
            headers=self.h1,
        )
        entities = [c["entity"] for c in self.pull().json()["changes"]]
        self.assertEqual(entities, ["appointment"])

    def test_cancel_appointment_is_logged(self) -> None:
        appt = self.client.post(
            "/api/v1/schedule",
            json={"patient_no": "ZY001", "date": "2027-03-01", "period": "am"},
            headers=self.h1,
        ).json()
        self.client.delete(f"/api/v1/schedule/{appt['id']}", headers=self.h1)
        changes = self.pull().json()["changes"]
        self.assertEqual([c["op"] for c in changes], ["insert", "update"])
        self.assertEqual(changes[-1]["payload"]["status"], "cancelled")


class TestCursorSemantics(SyncTestCase):
    def test_cursor_advances_and_is_monotonic(self) -> None:
        ids = []
        for day in ("2027-03-01", "2027-03-02", "2027-03-03"):
            self.client.post(
                "/api/v1/records", json=self.record_payload(record_date=day), headers=self.h1
            )
        first = self.pull().json()
        ids = [c["id"] for c in first["changes"]]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(first["cursor"], ids[-1])

        # 用返回的游标再拉，应该是空的且游标不前移
        second = self.pull(cursor=first["cursor"]).json()
        self.assertEqual(second["changes"], [])
        self.assertEqual(second["cursor"], first["cursor"], "无新变更时游标不应前移")
        self.assertFalse(second["has_more"])

    def test_incremental_pull_does_not_skip(self) -> None:
        self.client.post("/api/v1/records", json=self.record_payload(), headers=self.h1)
        first = self.pull().json()
        self.client.post(
            "/api/v1/records", json=self.record_payload(record_date="2027-03-02"), headers=self.h1
        )
        second = self.pull(cursor=first["cursor"]).json()
        self.assertEqual(len(second["changes"]), 1)
        self.assertGreater(second["cursor"], first["cursor"])

    def test_has_more_when_batch_is_truncated(self) -> None:
        for index in range(3):
            self.client.post(
                "/api/v1/records", json=self.record_payload(record_date=f"2027-03-0{index + 1}"),
                headers=self.h1,
            )
        body = self.pull(limit=1).json()
        self.assertEqual(len(body["changes"]), 1)
        self.assertTrue(body["has_more"], "还有未拉取的变更时应提示 has_more")

    def test_entity_filter_is_for_initial_full_sync_only(self) -> None:
        """按实体过滤只适合首次全量同步；此时用 latest_cursor 作为终点。

        被过滤掉的变更不会返回，游标会前进到"最后一条返回记录"的位置 ——
        这一点是本接口的**已知语义**（docstring 与 /sync/info 都写明了），
        所以测试也按这个契约来断言，而不是假设它会保留其它实体的位置。
        """
        self.client.post(
            "/api/v1/schedule",
            json={"patient_no": "ZY001", "date": "2027-03-01", "period": "am"},
            headers=self.h1,
        )
        record = self.client.post("/api/v1/records", json=self.record_payload(), headers=self.h1).json()

        only_records = self.pull(entities=["treatment_record"]).json()
        self.assertEqual(len(only_records["changes"]), 1)
        self.assertEqual(only_records["changes"][0]["entity"], "treatment_record")
        self.assertEqual(only_records["changes"][0]["entity_id"], str(record["id"]))
        # 过滤模式下 latest_cursor 才是全量同步的终点
        self.assertGreaterEqual(only_records["latest_cursor"], only_records["cursor"])
        # 本次过滤拉取已经走到服务端最新，因此 has_more 为 false；
        # 这正是"过滤只适合全量同步"的原因：被跳过的实体不会再被这条游标覆盖到。
        self.assertEqual(only_records["cursor"], only_records["latest_cursor"])

        # 与之对比：不带过滤时两条变更都能拿到
        unfiltered = self.pull().json()
        self.assertEqual(len(unfiltered["changes"]), 2)
        self.assertEqual(
            [c["entity"] for c in unfiltered["changes"]], ["appointment", "treatment_record"]
        )

    def test_latest_cursor_reported(self) -> None:
        self.client.post("/api/v1/records", json=self.record_payload(), headers=self.h1)
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
    def test_push_creates_record(self) -> None:
        resp = self.push(
            [{"entity": "treatment_record", "client_uuid": "uuid-aaaa-0001", "op": "insert",
              "payload": self.record_payload()}]
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(len(body["applied"]), 1)
        self.assertEqual(body["applied"][0]["outcome"], "applied")
        self.assertEqual(body["conflicts"], [])
        count = self.conn.execute("SELECT COUNT(*) FROM treatment_record").fetchone()[0]
        self.assertEqual(count, 1)

    def test_same_client_uuid_twice_is_idempotent(self) -> None:
        """弱网重试：同一条变更推两次只能产生一条数据。

        第二次应被识别为"同一条"并正常更新（草稿客户端优先），
        而不能被当成冲突 —— 客户端重推自己创建的那条时通常没带 base_revision。
        """
        change = {
            "entity": "treatment_record",
            "client_uuid": "uuid-aaaa-0002",
            "op": "insert",
            "payload": self.record_payload(),
        }
        first = self.push([change]).json()
        self.assertEqual(len(first["applied"]), 1)

        second = self.push([change]).json()
        count = self.conn.execute("SELECT COUNT(*) FROM treatment_record").fetchone()[0]
        self.assertEqual(count, 1, "重复推送不得产生重复数据")
        self.assertEqual(second["conflicts"], [], "重试自己创建的草稿不应被判为冲突")
        self.assertEqual(len(second["applied"]), 1)
        self.assertEqual(second["applied"][0]["op"], "update")

    def test_duplicate_uuid_within_one_batch_skipped(self) -> None:
        change = {
            "entity": "treatment_record",
            "client_uuid": "uuid-aaaa-0003",
            "op": "insert",
            "payload": self.record_payload(),
        }
        body = self.push([change, dict(change)]).json()
        self.assertEqual(len(body["applied"]), 1)
        self.assertEqual(len(body["skipped"]), 1)
        self.assertEqual(body["skipped"][0]["reason"], "duplicate_in_batch")

    def test_push_updates_existing_draft_when_revision_matches(self) -> None:
        pushed = self.push(
            [{"entity": "treatment_record", "client_uuid": "uuid-aaaa-0004", "op": "insert",
              "payload": self.record_payload()}]
        ).json()
        record_id = pushed["applied"][0]["entity_id"]
        revision = pushed["applied"][0]["revision"]

        updated = self.push(
            [{"entity": "treatment_record", "client_uuid": "uuid-aaaa-0004", "op": "update",
              "base_revision": revision, "payload": self.record_payload(note="离线改过")}]
        ).json()
        self.assertEqual(len(updated["applied"]), 1)
        self.assertEqual(updated["applied"][0]["outcome"], "applied")
        note = self.conn.execute(
            "SELECT note FROM treatment_record WHERE id = ?", (record_id,)
        ).fetchone()["note"]
        self.assertEqual(note, "离线改过")

    def test_appointment_push(self) -> None:
        body = self.push(
            [{"entity": "appointment", "client_uuid": "uuid-bbbb-0001", "op": "insert",
              "payload": {"patient_no": "ZY001", "date": "2027-03-01", "period": "am",
                          "therapist_id": int(self.t1["id"])}}]
        ).json()
        self.assertEqual(len(body["applied"]), 1)
        self.assertEqual(body["applied"][0]["entity"], "appointment")


class TestConflictPolicy(SyncTestCase):
    """冲突分层：草稿客户端优先；已提交/已锁定服务端优先。"""

    def _push_draft(self, uuid: str = "uuid-c000-0001"):
        return self.push(
            [{"entity": "treatment_record", "client_uuid": uuid, "op": "insert",
              "payload": self.record_payload()}]
        ).json()

    def test_client_wins_while_server_is_draft(self) -> None:
        pushed = self._push_draft()
        revision = pushed["applied"][0]["revision"]

        # 模拟服务端记录被改过（版本前进），但仍是草稿
        self.conn.execute(
            "UPDATE treatment_record SET revision = revision + 1, note = '服务端草稿改动'"
        )
        stale = self.push(
            [{"entity": "treatment_record", "client_uuid": "uuid-c000-0001", "op": "update",
              "base_revision": revision, "payload": self.record_payload(note="客户端较新")}]
        ).json()
        self.assertEqual(len(stale["applied"]), 1, f"草稿应客户端优先：{stale}")
        self.assertEqual(stale["conflicts"], [])
        note = self.conn.execute("SELECT note FROM treatment_record").fetchone()["note"]
        self.assertEqual(note, "客户端较新")

    def test_server_wins_when_submitted(self) -> None:
        pushed = self._push_draft(uuid="uuid-c000-0002")
        revision = pushed["applied"][0]["revision"]
        record_id = pushed["applied"][0]["entity_id"]
        # 提交（服务端版本前进）
        treatment_model.submit_record(self.conn, int(record_id), user_id=int(self.t1["id"]))

        stale = self.push(
            [{"entity": "treatment_record", "client_uuid": "uuid-c000-0002", "op": "update",
              "base_revision": revision, "payload": self.record_payload(note="试图覆盖已提交")}]
        ).json()
        self.assertEqual(len(stale["conflicts"]), 1, f"已提交应服务端优先：{stale}")
        conflict = stale["conflicts"][0]
        self.assertEqual(conflict["outcome"], "conflict")
        self.assertEqual(conflict["server_status"], "submitted")
        self.assertGreater(conflict["server_revision"], revision)
        # 服务端内容未被覆盖
        note = self.conn.execute("SELECT note FROM treatment_record").fetchone()["note"]
        self.assertNotEqual(note, "试图覆盖已提交")

    def test_server_wins_when_locked(self) -> None:
        pushed = self._push_draft(uuid="uuid-c000-0003")
        revision = pushed["applied"][0]["revision"]
        record_id = int(pushed["applied"][0]["entity_id"])
        treatment_model.submit_record(self.conn, record_id, user_id=int(self.t1["id"]))
        treatment_model.lock_record(self.conn, record_id)

        stale = self.push(
            [{"entity": "treatment_record", "client_uuid": "uuid-c000-0003", "op": "update",
              "base_revision": revision, "payload": self.record_payload(note="试图覆盖已锁定")}]
        ).json()
        self.assertEqual(len(stale["conflicts"]), 1)
        self.assertEqual(stale["conflicts"][0]["server_status"], "locked")

    def test_missing_base_revision_is_server_wins(self) -> None:
        """客户端没给基线版本、且服务端已不是草稿时，服务端优先（无法安全合并）。"""
        pushed = self._push_draft(uuid="uuid-c000-0004")
        record_id = pushed["applied"][0]["entity_id"]
        # 提交后 revision 会推进，服务端也不再是草稿
        treatment_model.submit_record(self.conn, int(record_id), user_id=int(self.t1["id"]))

        body = self.push(
            [{"entity": "treatment_record", "client_uuid": "uuid-c000-0004", "op": "update",
              "payload": self.record_payload(note="没给基线版本")}]
        ).json()
        self.assertEqual(len(body["conflicts"]), 1, f"应服务端优先：{body}")
        self.assertEqual(body["conflicts"][0]["reason"], "missing_base_revision")

    def test_same_revision_applies_without_conflict(self) -> None:
        pushed = self._push_draft(uuid="uuid-c000-0005")
        revision = pushed["applied"][0]["revision"]
        body = self.push(
            [{"entity": "treatment_record", "client_uuid": "uuid-c000-0005", "op": "update",
              "base_revision": revision, "payload": self.record_payload(note="版本一致")}]
        ).json()
        self.assertEqual(body["conflicts"], [])
        self.assertEqual(len(body["applied"]), 1)

    def test_one_conflict_does_not_fail_whole_batch(self) -> None:
        """离线队列常攒几十条；一条冲突不应让整批退回。"""
        pushed = self._push_draft(uuid="uuid-c000-0006")
        treatment_model.submit_record(
            self.conn, int(pushed["applied"][0]["entity_id"]), user_id=int(self.t1["id"])
        )
        body = self.push(
            [
                {"entity": "treatment_record", "client_uuid": "uuid-c000-0006", "op": "update",
                 "base_revision": pushed["applied"][0]["revision"],
                 "payload": self.record_payload(note="冲突条")},
                {"entity": "appointment", "client_uuid": "uuid-c000-0007", "op": "insert",
                 "payload": {"patient_no": "ZY001", "date": "2027-03-09", "period": "am",
                             "therapist_id": int(self.t1["id"])}},
            ]
        ).json()
        self.assertEqual(len(body["conflicts"]), 1)
        self.assertEqual(len(body["applied"]), 1, "另一条应正常应用")
        self.assertEqual(body["applied"][0]["entity"], "appointment")

    def test_resolve_conflict_helper_directly(self) -> None:
        self.assertIsNone(
            sync_service.resolve_conflict(
                self.conn, entity="treatment_record", entity_id=99999, base_revision=1
            ),
            "服务端没有该记录时不算冲突",
        )

    def test_revision_bumps_on_every_mutation(self) -> None:
        """离线客户端靠 revision 判断副本是否过期；任何会改数据的操作都必须推进它。

        这里直接断言模型层：早先 `update_record` 与 `submit_record` 都没推进 revision，
        导致客户端永远以为自己的草稿版是最新的。
        """
        record = self.client.post(
            "/api/v1/records", json=self.record_payload(), headers=self.h1
        ).json()
        self.assertEqual(record["revision"], 1, "新建应为 1")

        updated = treatment_model.update_record(
            self.conn, int(record["id"]), user_id=int(self.t1["id"]), is_admin=False, note="改一下"
        )
        self.assertEqual(updated["revision"], 2, "修改应推进 revision")

        submitted = treatment_model.submit_record(
            self.conn, int(record["id"]), user_id=int(self.t1["id"])
        )
        self.assertEqual(submitted["revision"], 3, "提交应推进 revision")

        locked = treatment_model.lock_record(self.conn, int(record["id"]))
        self.assertEqual(locked["revision"], 4, "锁定应推进 revision")

    def test_appointment_retry_without_base_revision_is_idempotent(self) -> None:
        """排期不是"客户端优先"实体，但重试同一 client_uuid 仍须幂等。"""
        change = {
            "entity": "appointment",
            "client_uuid": "uuid-j000-0001",
            "op": "insert",
            "payload": {"patient_no": "ZY001", "date": "2027-03-01", "period": "am",
                        "therapist_id": int(self.t1["id"])},
        }
        self.push([change])
        second = self.push([change]).json()
        self.assertEqual(second["conflicts"], [], f"排期重试不应冲突：{second}")
        self.assertEqual(len(second["applied"]), 1)
        count = self.conn.execute("SELECT COUNT(*) FROM appointment").fetchone()[0]
        self.assertEqual(count, 1)


class TestPushValidation(SyncTestCase):
    def test_cannot_push_patient(self) -> None:
        """一期只允许治疗记录与排期离线写；患者主数据由管理员在线维护。"""
        resp = self.push(
            [{"entity": "patient", "client_uuid": "uuid-d000-0001", "op": "insert",
              "payload": {"inpatient_no": "ZY999", "name": "不该离线建"}}]
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
            {"entity": "appointment", "client_uuid": f"uuid-e000-{i:04d}", "op": "insert",
             "payload": {"patient_no": "ZY001", "date": "2027-03-01", "period": "am"}}
            for i in range(sync_service.MAX_PUSH_BATCH + 1)
        ]
        resp = self.push(too_many)
        # 明确报错而不是静默截断：pydantic 的 max_length 校验先命中
        self.assert_error(resp, 422, "VALIDATION_ERROR")
        self.assertIn("changes", resp.json()["details"]["fields"])

    def test_push_requires_auth(self) -> None:
        resp = self.client.post(
            "/api/v1/sync/push",
            json={"changes": [{"entity": "appointment", "client_uuid": "uuid-f000-0001", "op": "insert",
                               "payload": {"patient_no": "ZY001", "date": "2027-03-01", "period": "am"}}]},
        )
        self.assert_error(resp, 401, "AUTH_REQUIRED")

    def test_invalid_op_rejected(self) -> None:
        """op 必须是 insert / update / delete —— 服务端显式校验，而不是默默当作 update。"""
        resp = self.push(
            [{"entity": "treatment_record", "client_uuid": "uuid-g000-0001", "op": "merge",
              "payload": self.record_payload()}]
        )
        self.assert_error(resp, 422, "INVALID")
        self.assertEqual(resp.json()["details"]["op"], "merge")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM treatment_record").fetchone()[0],
            0,
            "非法 op 不应产生任何写入",
        )


class TestOfflineThenOnlineScenario(SyncTestCase):
    """完整离线场景：断网期攒变更 → 恢复后一次推送 → 另一端拉取到全部。"""

    def test_offline_batch_then_pull(self) -> None:
        changes = []
        for index in range(5):
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
                "client_uuid": f"uuid-i000-{index:04d}",
                "op": "insert",
                "payload": self.record_payload(record_date=f"2027-03-0{index + 1}"),
            }
            for index in range(3)
        ]
        self.push(changes)
        before = self.conn.execute("SELECT COUNT(*) FROM treatment_record").fetchone()[0]

        # 整批再推一次
        self.push(changes)
        after = self.conn.execute("SELECT COUNT(*) FROM treatment_record").fetchone()[0]
        self.assertEqual(before, after, "整批重试不得产生重复数据")


if __name__ == "__main__":
    unittest.main(verbosity=2)
