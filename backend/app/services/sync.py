"""同步支撑：变更日志、幂等推送、增量拉取与冲突策略（阶段 4 / `设计.md` 5.4、`开发计划.md` M06）。

## 协议要点

1. **幂等推送**：每次变更带客户端生成的 `client_uuid`，服务端据此 upsert，
   重复推送不产生重复数据（弱网重试是常态，不是异常）。
2. **游标拉取**：`change_log.id` 就是游标。服务端每次写操作都追加一条，
   客户端记住上次的 id 即可增量拉取，不需要时间戳——时间戳会因时钟偏移而漏数据。
3. **乐观锁**：推送时带 `base_revision`；与服务端当前 `revision` 不一致即视为冲突。
4. **冲突策略分层**（`设计.md` 5.4 表）：

   | 场景 | 策略 | 理由 |
   |---|---|---|
   | 草稿（`draft`） | **客户端优先** | 治疗师正在写的内容不该被覆盖；草稿也还没进入医疗文书 |
   | 已提交 / 已锁定 | **服务端优先** | 医疗文书以服务端为准，客户端收到冲突后留痕重提 |
   | 字典 / 选项集 / 模板 | **服务端优先** | 只读缓存，客户端不推送 |

一期允许离线写的实体只有**治疗记录**一类（`设计.md` 5.4 末尾；排期已随排期功能
整体下线于 2026-10-05 从可推实体中移除），患者主数据仍以管理员在线维护为主，
因此 `patient` 只支持"服务端优先"的服务端变更推送（客户端不推患者），
拉取侧两类都支持。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.core import jsonutil
from app.models.base import Invalid

# 允许客户端推送的实体（一期范围）
# 2026-10-05：排期（appointment）随功能下线一并移除；现在只剩治疗记录可离线写。
PUSHABLE_ENTITIES = ("treatment_record",)
# 允许拉取的实体
PULLABLE_ENTITIES = ("patient", "treatment_record")

# 冲突策略：客户端优先 / 服务端优先
CLIENT_WINS_ENTITIES = ("treatment_record",)  # 仅当服务端仍是 draft 时客户端优先
MAX_PUSH_BATCH = 200
MAX_PULL_LIMIT = 500


# --------------------------------------------------------------------------- #
# 变更日志
# --------------------------------------------------------------------------- #
def record_change(
    conn: sqlite3.Connection,
    *,
    entity: str,
    entity_id: Any,
    op: str,
    revision: int,
    actor_user_id: int | None = None,
    payload: Any = None,
) -> int:
    """追加一条变更日志，返回其 id（即新游标）。

    **必须在与业务写入同一个事务里调用**，否则会出现"业务改了但客户端拉不到"
    或"客户端拉到了但业务没改"的不一致。
    """
    if op not in ("insert", "update", "delete"):
        raise Invalid(f"变更操作非法：{op}", details={"op": op})
    cur = conn.execute(
        "INSERT INTO change_log (entity, entity_id, op, revision, actor_user_id, payload_json)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (entity, str(entity_id), op, int(revision), actor_user_id, jsonutil.dumps(payload)),
    )
    return int(cur.lastrowid)


def current_cursor(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM change_log").fetchone()
    return int(row[0])


def pull_changes(
    conn: sqlite3.Connection,
    *,
    cursor: int = 0,
    limit: int = MAX_PULL_LIMIT,
    entities: list[str] | None = None,
) -> dict[str, Any]:
    """按游标增量拉取。

    返回 ``{"cursor", "latest_cursor", "changes", "has_more"}``。

    - ``cursor``：本次返回的最后一条的 id（没有新变更时与请求游标相同）。客户端下次带它回来。
    - ``latest_cursor``：服务端当前已写入的最大 id。

    **特别注意（`entities` 过滤的语义）**：按实体过滤时，被过滤掉的变更不会返回，
    但游标仍会前进到"最后一条返回记录"的位置。因此**按实体过滤只适合首次全量同步**
    （客户端从空库开始，不关心其它实体的历史），之后应**不带过滤地**用游标增量拉取，
    再在客户端侧筛选实体 —— 否则会永久跳过被过滤实体的中间变更。
    过滤模式下建议直接用 ``latest_cursor`` 作为全量同步的终点。
    """
    if cursor < 0:
        raise Invalid("cursor 不能为负", details={"cursor": cursor})
    limit = max(1, min(int(limit), MAX_PULL_LIMIT))

    where = ["id > ?"]
    params: list[Any] = [cursor]
    if entities:
        unknown = set(entities) - set(PULLABLE_ENTITIES)
        if unknown:
            raise Invalid("存在不可拉取的实体", details={"entities": sorted(unknown)})
        where.append(f"entity IN ({', '.join('?' for _ in entities)})")
        params.extend(entities)

    rows = conn.execute(
        "SELECT id, entity, entity_id, op, revision, actor_user_id, payload_json, created_at"
        " FROM change_log"
        f" WHERE {' AND '.join(where)}"
        " ORDER BY id LIMIT ?",
        (*params, limit + 1),  # 多取一条用于判断 has_more
    ).fetchall()

    has_more_batch = len(rows) > limit
    rows = rows[:limit]
    changes: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["payload"] = jsonutil.loads(item.pop("payload_json", None), None)
        changes.append(item)

    next_cursor = int(rows[-1]["id"]) if rows else cursor
    latest = current_cursor(conn)
    # has_more 的语义是"服务端还有本客户端没拉到的变更"：
    # 既包括本次因 limit 截断，也包括调用方过滤了实体而留下的其它变更。
    # 只按"是否截断"判断会让按实体订阅的客户端永远拿不到提示。
    pending = conn.execute("SELECT 1 FROM change_log WHERE id > ? LIMIT 1", (next_cursor,)).fetchone()
    return {
        "cursor": next_cursor,
        "latest_cursor": latest,
        "changes": changes,
        "has_more": bool(has_more_batch or pending is not None),
    }


# --------------------------------------------------------------------------- #
# 幂等查找 / 冲突判定
# --------------------------------------------------------------------------- #
def find_by_client_uuid(conn: sqlite3.Connection, entity: str, client_uuid: str) -> dict[str, Any] | None:
    table = _table_for(entity)
    row = conn.execute(
        f"SELECT id, revision FROM {table} WHERE client_uuid = ?", (client_uuid,)
    ).fetchone()
    return dict(row) if row is not None else None


def _table_for(entity: str) -> str:
    mapping = {
        "patient": "patient",
        "treatment_record": "treatment_record",
    }
    table = mapping.get(entity)
    if table is None:
        raise Invalid(f"未知实体：{entity}", details={"entity": entity})
    return table


def _client_uuid_owner(conn: sqlite3.Connection, entity: str, client_uuid: str) -> int | None:
    found = find_by_client_uuid(conn, entity, client_uuid)
    return int(found["id"]) if found else None


def _server_revision(conn: sqlite3.Connection, entity: str, entity_id: Any) -> int | None:
    table = _table_for(entity)
    pk = "inpatient_no" if entity == "patient" else "id"
    row = conn.execute(f"SELECT revision FROM {table} WHERE {pk} = ?", (entity_id,)).fetchone()
    return int(row["revision"]) if row is not None else None


def _server_status(conn: sqlite3.Connection, entity: str, entity_id: Any) -> str | None:
    if entity != "treatment_record":
        return None
    row = conn.execute("SELECT status FROM treatment_record WHERE id = ?", (entity_id,)).fetchone()
    return str(row["status"]) if row is not None else None


def resolve_conflict(
    conn: sqlite3.Connection,
    *,
    entity: str,
    entity_id: Any,
    base_revision: int | None,
    is_retry: bool = False,
) -> dict[str, Any] | None:
    """判断是否冲突，并给出该走哪条策略。

    返回 ``None`` 表示**无冲突，可直接应用**；
    否则返回 ``{"resolution": "client_wins" | "server_wins", "server_revision", "reason"}``。

    ``is_retry=True`` 表示"这条变更之前已经推过"（服务端已存在同 `client_uuid` 的记录）。
    客户端重推自己创建的变更时通常**不带** `base_revision`；若把它一律当成
    "缺少基线版本 → 服务端优先"，弱网下每一次重试都会被判成冲突，幂等性就形同虚设。
    因此重试的语义分两种实体：

    - **客户端优先实体**（当前只有 `treatment_record`）：上面那条分支已经覆盖了重试 ——
      服务端仍是 `draft` 时客户端优先；已提交/已锁定则服务端优先（文书以服务端为准，
      重试**不得**静默覆盖，见 `test_retry_after_submit_is_reported_but_never_duplicates`）。
    - **非客户端优先实体**：见下面那条 `is_retry` 分支，重试同一 `client_uuid` 时按客户端优先。
      ⚠️ 这条分支**当前不可达**，原因与保留理由见该分支上方注释。
    """
    server_revision = _server_revision(conn, entity, entity_id)
    if server_revision is None:
        # 服务端没有这条记录 —— 不是冲突，是"新增"，交给调用方按 insert 处理
        return None
    if base_revision is not None and int(base_revision) == server_revision:
        return None  # 版本一致，无冲突

    # 版本不一致（或客户端没给基线版本）：按实体与状态决定策略
    if entity in CLIENT_WINS_ENTITIES:
        status = _server_status(conn, entity, entity_id)
        if status == "draft":
            return {
                "resolution": "client_wins",
                "server_revision": server_revision,
                "reason": "server_still_draft",
            }
        return {
            "resolution": "server_wins",
            "server_revision": server_revision,
            # 分清两种拒绝原因，便于客户端决定怎么提示治疗师
            "reason": "missing_base_revision" if base_revision is None else f"server_status={status}",
        }

    # 非"客户端优先"的实体：仅当确实是无法判断的首次冲突才拒绝；
    # 重试同一 client_uuid 时仍按客户端优先，保证幂等。
    #
    # ⚠️ 当前**不可达**：`PUSHABLE_ENTITIES = ("treatment_record",)`，而
    # `treatment_record` 本身就在 `CLIENT_WINS_ENTITIES` 里，上面那条分支必然先返回；
    # `_push_treatment_record` 虽然传 `is_retry=True`，也同样进不到这里。
    # 保留而不删除的理由：
    #   1. 删它就要顺带处理 `is_retry` 形参 —— 那是 `resolve_conflict` 的公开签名，
    #      测试会直接调用（`test_sync.py::test_resolve_conflict_helper_directly`）；
    #      为一处不可达分支去动签名，风险大于收益。
    #   2. "重试必须幂等"是协议承诺（`docs/sync-protocol.md` 与本函数 docstring），
    #      一旦二期开放 `patient` 等实体的离线推送，这条分支立刻变为可达。
    #   3. 它没有任何分支副作用，留着不影响现有行为。
    if is_retry and base_revision is None:
        return {
            "resolution": "client_wins",
            "server_revision": server_revision,
            "reason": "idempotent_retry",
        }
    return {
        "resolution": "server_wins",
        "server_revision": server_revision,
        "reason": "missing_base_revision" if base_revision is None else "entity_prefers_server",
    }


# --------------------------------------------------------------------------- #
# 推送
# --------------------------------------------------------------------------- #
def _skipped(client_uuid: str, entity: str, reason: str) -> dict[str, Any]:
    """统一的"跳过"结果。

    必须带 outcome 字段：响应模型要求三态之一，缺了会在序列化时炸成 500
    （阶段 4 实测踩到过 —— 返回体形状要和 pydantic 模型严格对齐）。
    """
    return {"outcome": "skipped", "client_uuid": client_uuid, "entity": entity, "reason": reason}


def apply_push(
    conn: sqlite3.Connection,
    *,
    user: dict[str, Any],
    changes: list[dict[str, Any]],
) -> dict[str, Any]:
    """批量应用客户端变更，返回逐条结果。

    逐条独立处理：一条冲突不应让整批失败（离线队列里通常攒了几十条，
    因为一条冲突就整批退回，客户端很难恢复）。
    """
    if len(changes) > MAX_PUSH_BATCH:
        raise Invalid(
            f"单次推送不得超过 {MAX_PUSH_BATCH} 条", details={"count": len(changes)}
        )

    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    seen_uuids: set[str] = set()

    for change in changes:
        entity = str(change.get("entity") or "")
        client_uuid = str(change.get("client_uuid") or "")
        if not entity or not client_uuid:
            raise Invalid("每条变更都必须带 entity 与 client_uuid", details={"change": change})
        if entity not in PUSHABLE_ENTITIES:
            raise Invalid(
                "该实体不在离线可写范围内（只有治疗记录可离线写）",
                details={"entity": entity, "allowed": list(PUSHABLE_ENTITIES)},
            )
        op = str(change.get("op") or "update")
        if op not in ("insert", "update", "delete"):
            raise Invalid(
                f"变更操作非法：{op}", details={"client_uuid": client_uuid, "op": op}
            )
        if client_uuid in seen_uuids:
            # 同一批里重复上报同一个 uuid：后一条忽略，避免自己和自己抢
            skipped.append(_skipped(client_uuid, entity, "duplicate_in_batch"))
            continue
        seen_uuids.add(client_uuid)

        handler = _HANDLERS[entity]
        result = handler(conn, user=user, change=change)
        if result["outcome"] == "applied":
            applied.append(result)
        elif result["outcome"] == "skipped":
            skipped.append(result)
        else:
            conflicts.append(result)

    return {
        "applied": applied,
        "skipped": skipped,
        "conflicts": conflicts,
        "cursor": current_cursor(conn),
    }


def _push_treatment_record(
    conn: sqlite3.Connection, *, user: dict[str, Any], change: dict[str, Any]
) -> dict[str, Any]:
    from app.models import treatment as treatment_model

    client_uuid = str(change["client_uuid"])
    existing = find_by_client_uuid(conn, "treatment_record", client_uuid)
    payload = change.get("payload") or {}

    if existing is None:
        record = treatment_model.create_record(
            conn,
            patient_no=str(payload["patient_no"]),
            therapist_id=int(payload.get("therapist_id") or user["id"]),
            record_date=str(payload["record_date"]),
            session_period=payload.get("session_period"),
            duration_min=payload.get("duration_min"),
            patient_response=payload.get("patient_response"),
            note=payload.get("note"),
            status=str(payload.get("status") or "draft"),
            items=payload.get("items") or [],
        )
        conn.execute(
            "UPDATE treatment_record SET client_uuid = ? WHERE id = ?", (client_uuid, record["id"])
        )
        revision = int(record["revision"])
        record_change(
            conn, entity="treatment_record", entity_id=record["id"], op="insert",
            revision=revision, actor_user_id=int(user["id"]), payload=payload,
        )
        return {"outcome": "applied", "client_uuid": client_uuid, "entity": "treatment_record",
                "entity_id": record["id"], "op": "insert", "revision": revision}

    record_id = int(existing["id"])
    decision = resolve_conflict(
        conn,
        entity="treatment_record",
        entity_id=record_id,
        base_revision=change.get("base_revision"),
        is_retry=True,  # 同 client_uuid 已存在 → 重试
    )
    if decision and decision["resolution"] == "server_wins":
        server = treatment_model.get_record_or_raise(conn, record_id)
        return {
            "outcome": "conflict",
            "client_uuid": client_uuid,
            "entity": "treatment_record",
            "entity_id": record_id,
            "server_revision": decision["server_revision"],
            "server_status": server["status"],
            "reason": decision["reason"],
        }

    updated = treatment_model.update_record(
        conn,
        record_id,
        user_id=int(user["id"]),
        is_admin=user.get("role") == "admin",
        record_date=payload.get("record_date"),
        session_period=payload.get("session_period"),
        duration_min=payload.get("duration_min"),
        patient_response=payload.get("patient_response"),
        note=payload.get("note"),
        items=payload.get("items"),
    )
    revision = int(updated["revision"])
    record_change(
        conn, entity="treatment_record", entity_id=record_id, op="update",
        revision=revision, actor_user_id=int(user["id"]), payload=payload,
    )
    return {"outcome": "applied", "client_uuid": client_uuid, "entity": "treatment_record",
            "entity_id": record_id, "op": "update", "revision": revision}


_HANDLERS = {
    "treatment_record": _push_treatment_record,
}


__all__ = [
    "CLIENT_WINS_ENTITIES",
    "MAX_PULL_LIMIT",
    "MAX_PUSH_BATCH",
    "PULLABLE_ENTITIES",
    "PUSHABLE_ENTITIES",
    "apply_push",
    "current_cursor",
    "find_by_client_uuid",
    "pull_changes",
    "record_change",
    "resolve_conflict",
]
