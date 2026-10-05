// 见 api_client.dart 顶部说明：构造器刻意用「公开参数名 + 私有字段」。
// ignore_for_file: prefer_initializing_formals

import 'dart:convert';

import 'package:drift/drift.dart';

import 'package:rehab_app/core/api_endpoints.dart';
import 'package:rehab_app/core/error.dart';
import 'package:rehab_app/data/local/app_database.dart';
import 'package:rehab_app/data/remote/api_client.dart';

/// 一次推送的结果分类（与服务端响应的三个数组一一对应）。
enum PushOutcome { applied, skipped, conflict }

/// 单条变更的推送结果。
class PushResultItem {
  const PushResultItem({
    required this.outcome,
    required this.clientUuid,
    required this.entity,
    this.entityId,
    this.revision,
    this.serverRevision,
    this.serverStatus,
    this.reason,
  });

  final PushOutcome outcome;
  final String clientUuid;
  final String entity;
  final Object? entityId;

  /// 服务端确认后的新版本号（`applied` 时有值），必须回写到本地行。
  final int? revision;

  /// 冲突时服务端当前版本与状态，供"以我的版本重提"使用。
  final int? serverRevision;
  final String? serverStatus;

  /// 机器可读的原因，如 `idempotent_retry`、`server_status=submitted`。
  final String? reason;

  factory PushResultItem.fromJson(Map<String, dynamic> json, PushOutcome outcome) => PushResultItem(
        outcome: outcome,
        clientUuid: json['client_uuid'] as String? ?? '',
        entity: json['entity'] as String? ?? '',
        entityId: json['entity_id'],
        revision: (json['revision'] as num?)?.toInt(),
        serverRevision: (json['server_revision'] as num?)?.toInt(),
        serverStatus: json['server_status'] as String?,
        reason: json['reason'] as String?,
      );
}

/// 一次推送的完整结果。
class PushReport {
  const PushReport({
    required this.applied,
    required this.skipped,
    required this.conflicts,
    required this.cursor,
  });

  final List<PushResultItem> applied;
  final List<PushResultItem> skipped;
  final List<PushResultItem> conflicts;

  /// 服务端当前游标，可存下来供下次 pull 使用。
  final int cursor;

  bool get hasConflicts => conflicts.isNotEmpty;
}

/// 同步引擎。
///
/// 严格实现 `docs/sync-protocol.md`。三条最容易写错的约定，在这里集中处理：
///
/// 1. **重试不带 `base_revision`**：客户端重推自己创建的变更时若带上过期基线，
///    服务端会走 `entity_prefers_server` 判成冲突 —— 弱网下每次重试都失败，
///    幂等形同虚设。所以 [enqueue] 与重推路径都**不写** `base_revision`
///    （只有"修改服务端已存在的记录"才需要基线，见 [enqueueUpdate]）。
/// 2. **一条冲突不阻断整批**：服务端逐条独立处理，客户端也必须逐条处理三个数组，
///    不能因为 `conflicts` 非空就丢掉 `applied`。
/// 3. **患者不走 pull**：`change_log` 里永远不会出现 `entity='patient'`，
///    患者必须用 list 接口拉（见 [PatientSyncer]）。
class SyncEngine {
  SyncEngine({required ApiClient client, required AppDatabase db})
      : _client = client,
        _db = db;

  final ApiClient _client;
  final AppDatabase _db;

  /// 服务端约束（[loadContract] 后可用）。
  static const int maxPushBatch = 200;
  static const int maxPullLimit = 500;

  /// 读取服务端同步契约（`GET /sync/info`）。
  Future<Map<String, dynamic>> loadContract() async {
    final data = await _client.request(kSyncInfo);
    return Map<String, dynamic>.from(data as Map);
  }

  // ------------------------------------------------------------------------- //
  // 队列写入
  // ------------------------------------------------------------------------- //
  /// 入队一条**新建**变更。
  ///
  /// `baseRevision` 保持 null —— 新建没有基线，重试也不需要（协议 §4.4 ★）。
  Future<void> enqueueInsert({
    required String entity,
    required String clientUuid,
    required Map<String, dynamic> payload,
  }) =>
      _enqueue(
        entity: entity,
        clientUuid: clientUuid,
        op: 'insert',
        payload: payload,
        baseRevision: null,
      );

  /// 入队一条**修改**变更。
  ///
  /// [baseRevision] 必须是本地记录的、服务端**已知的**版本号。若本地行从未同步过
  /// （`revision == 0` 且无服务端 id），应改用 [enqueueInsert]。
  ///
  /// 但有个例外必须支持**传 null**：本地新建的草稿（负数占位 id）随后又被修改时，
  /// 服务端还不知道这个 `client_uuid`。此时不带 `base_revision` 提交，服务端按
  /// upsert 处理 —— 结果正确，且不违反协议 §4.4（带**过期**基线才会被误判成冲突）。
  Future<void> enqueueUpdate({
    required String entity,
    required String clientUuid,
    required Map<String, dynamic> payload,
    required int? baseRevision,
  }) =>
      _enqueue(
        entity: entity,
        clientUuid: clientUuid,
        op: 'update',
        payload: payload,
        baseRevision: baseRevision,
      );

  Future<void> _enqueue({
    required String entity,
    required String clientUuid,
    required String op,
    required Map<String, dynamic> payload,
    required int? baseRevision,
  }) async {
    await _db.into(_db.changeQueue).insertOnConflictUpdate(
          ChangeQueueCompanion.insert(
            clientUuid: clientUuid,
            entity: entity,
            op: Value(op),
            baseRevision: Value(baseRevision),
            payloadJson: jsonEncode(payload),
            syncStatus: const Value('pending'),
            // createdAt 带 withDefault → companion 参数就是 String，不是 Value<String>。
            createdAt: DateTime.now().toUtc().toIso8601String(),
          ),
        );
  }

  /// 待推送条数（用于 UI 显示"待同步 N 条"）。
  Future<int> pendingCount() async {
    final rows = await _db.select(_db.changeQueue).get();
    return rows.where((r) => r.syncStatus == 'pending' || r.syncStatus == 'conflict').length;
  }

  // ------------------------------------------------------------------------- //
  // 冲突处理（见 docs/sync-protocol.md §4.4 与 §6）
  // ------------------------------------------------------------------------- //
  /// 队列里处于**冲突**状态的条目（按入队时间正序）。
  Future<List<ChangeQueueData>> conflicts() async {
    return (_db.select(_db.changeQueue)
          ..where((t) => t.syncStatus.equals('conflict'))
          ..orderBy([(t) => OrderingTerm.asc(t.createdAt)]))
        .get();
  }

  /// 冲突条数（不查全表，避免每次进页面都读整个队列）。
  Future<int> conflictCount() async {
    final rows = await (_db.select(_db.changeQueue)
          ..where((t) => t.syncStatus.equals('conflict')))
        .get();
    return rows.length;
  }

  /// 观察冲突队列（响应式：裁决后界面自动更新）。
  Stream<List<ChangeQueueData>> watchConflicts() {
    return (_db.select(_db.changeQueue)
          ..where((t) => t.syncStatus.equals('conflict'))
          ..orderBy([(t) => OrderingTerm.asc(t.createdAt)]))
        .watch();
  }

  /// **保留我的版本（第一步）**：清空基线并退回 `pending`，让服务端重新判一次冲突。
  ///
  /// 之所以要清空而不是留着旧基线：留着旧基线时，如果服务和旧基线恰好一致，
  /// 服务端会判"无冲突"并**直接应用**——那就不是"由治疗师确认过才覆盖"了，
  /// 而是"推着推着悄悄覆盖"。清空后服务端一定返回一次冲突，
  /// 附带**当前的** `server_revision`，我们再用它做第二步。
  Future<void> requeueWithoutBase(String clientUuid) async {
    await (_db.update(_db.changeQueue)
          ..where((t) => t.clientUuid.equals(clientUuid)))
        .write(const ChangeQueueCompanion(
      baseRevision: Value(null),
      syncStatus: Value('pending'),
      retryCount: Value(0),
      lastError: Value(null),
    ));
  }

  /// **保留我的版本（第二步）**：把服务端当前 `revision` 作为基线重新排队推送。
  ///
  /// 服务端 `resolve_conflict` 的第一条判定是
  /// `base_revision == server_revision → 无冲突，直接应用`，
  /// 所以"以我的版本覆盖服务端"不需要任何特殊接口，只要把基线对齐到服务端当前版本。
  ///
  /// [serverRevision] 来自冲突响应里的 `server_revision`（协议 §4.4）。
  Future<void> keepMine(String clientUuid, int serverRevision) async {
    await (_db.update(_db.changeQueue)
          ..where((t) => t.clientUuid.equals(clientUuid)))
        .write(ChangeQueueCompanion(
      baseRevision: Value(serverRevision),
      syncStatus: const Value('pending'),
      // 裁决后这是一次全新的尝试，重试计数清零，否则会被退避策略压住。
      retryCount: const Value(0),
      lastError: const Value(null),
    ));
  }

  /// **放弃我的版本**：从队列里移除这条变更（本地副本稍后由拉取覆盖或由调用方清理）。
  ///
  /// 调用方应在之后立刻做一次 `pullIncremental`，否则本地会留着"没推上去的改动"，
  /// 与服务端不一致 —— 这也是"采用服务端版本"的实现方式（不逐个实体重取，
  /// 直接用协议本来就有的拉取机制，比自造重取逻辑可靠）。
  Future<void> discardMine(String clientUuid) async {
    await _db.delete(_db.changeQueue)
        .delete(ChangeQueueCompanion(clientUuid: Value(clientUuid)));
  }

  /// 批量丢弃（如"全部采用服务端"）。
  Future<void> discardMany(Iterable<String> clientUuids) async {
    for (final uuid in clientUuids) {
      await discardMine(uuid);
    }
  }

  /// 推送后重新统计冲突（裁决动作结束后调用，返回最新冲突数）。
  Future<int> refreshConflicts() async {
    await pushPending();
    return conflictCount();
  }

  // ------------------------------------------------------------------------- //
  // 推送
  // ------------------------------------------------------------------------- //
  /// 把队列里待推送的变更分批推给服务端。
  ///
  /// 返回每批的结果合并报告；网络不可用时抛 [AppError]（`code=NETWORK_ERROR`）。
  Future<PushReport> pushPending() async {
    final pending = await (_db.select(_db.changeQueue)
          ..where((t) => t.syncStatus.equals('pending'))
          ..orderBy([(t) => OrderingTerm.asc(t.createdAt)]))
        .get();

    final allApplied = <PushResultItem>[];
    final allSkipped = <PushResultItem>[];
    final allConflicts = <PushResultItem>[];
    var cursor = 0;

    for (var start = 0; start < pending.length; start += maxPushBatch) {
      final batch = pending.sublist(
        start,
        (start + maxPushBatch).clamp(0, pending.length),
      );
      final report = await _pushBatch(batch);
      allApplied.addAll(report.applied);
      allSkipped.addAll(report.skipped);
      allConflicts.addAll(report.conflicts);
      cursor = report.cursor;
    }

    return PushReport(
      applied: allApplied,
      skipped: allSkipped,
      conflicts: allConflicts,
      cursor: cursor,
    );
  }

  Future<PushReport> _pushBatch(List<ChangeQueueData> batch) async {
    // 同一批里 duplicate_in_batch 由服务端记为 skipped，客户端不必预筛。
    final changes = batch
        .map((row) => <String, dynamic>{
              'entity': row.entity,
              'client_uuid': row.clientUuid,
              'op': row.op,
              // ★ 重试路径同样保持 null；见类文档第 1 条。
              if (row.baseRevision != null) 'base_revision': row.baseRevision,
              'payload': jsonDecode(row.payloadJson),
            })
        .toList();

    late Map<String, dynamic> data;
    try {
      data = await _client.request(
        kSyncPush,
        method: 'POST',
        body: {'changes': changes},
      ) as Map<String, dynamic>;
    } on AppError catch (e) {
      // 推送失败：不删队列、记录错误，等待退避后重试（协议 §6）。
      for (final row in batch) {
        await (_db.update(_db.changeQueue)..where((t) => t.clientUuid.equals(row.clientUuid)))
            .write(ChangeQueueCompanion(
          retryCount: Value(row.retryCount + 1),
          lastError: Value(e.code),
        ));
      }
      rethrow;
    }

    final applied = _parse(data['applied'], PushOutcome.applied);
    final skipped = _parse(data['skipped'], PushOutcome.skipped);
    final conflicts = _parse(data['conflicts'], PushOutcome.conflict);

    // applied：回写服务端 id 与 revision，然后出队。
    for (final item in applied) {
      await _applySuccess(item);
    }
    // skipped：不必重试（如 duplicate_in_batch），直接出队避免死循环。
    for (final item in skipped) {
      await _db.delete(_db.changeQueue)
          .delete(ChangeQueueCompanion(clientUuid: Value(item.clientUuid)));
    }
    // conflict：**保留**在队列里并标记，等治疗师处理后重提（不能静默丢弃）。
    for (final item in conflicts) {
      await (_db.update(_db.changeQueue)..where((t) => t.clientUuid.equals(item.clientUuid)))
          .write(const ChangeQueueCompanion(syncStatus: Value('conflict')));
    }

    return PushReport(
      applied: applied,
      skipped: skipped,
      conflicts: conflicts,
      cursor: (data['cursor'] as num?)?.toInt() ?? 0,
    );
  }

  List<PushResultItem> _parse(Object? raw, PushOutcome outcome) {
    if (raw is! List) return const [];
    return raw
        .whereType<Map>()
        .map((e) => PushResultItem.fromJson(Map<String, dynamic>.from(e), outcome))
        .toList();
  }

  /// 推送成功后的本地回写：把服务端 id / revision 写回镜像表，并出队。
  Future<void> _applySuccess(PushResultItem item) async {
    final revision = item.revision;
    // 2026-10-05：`appointment` 实体随排期功能下线，现在只剩治疗记录可离线写。
    if (item.entity == 'treatment_record') {
      await _promoteLocalRecord(
        clientUuid: item.clientUuid,
        serverId: _asInt(item.entityId),
        revision: revision ?? 0,
      );
    }
    await _db.delete(_db.changeQueue)
        .delete(ChangeQueueCompanion(clientUuid: Value(item.clientUuid)));
  }

  /// 把本地新建草稿的**负数占位 id 换成服务端 id**。
  ///
  /// 为什么必须换：本地新建时用负数占位（避免与服务端自增 id 撞号），
  /// 推送成功后如果不换：
  ///   1. 随后 `pull` 回来的那条记录（正数 id）会**再插一行** —— 同一条记录
  ///      在本地变两条，患者页看起来"记了两次"；
  ///   2. 出院流程拿不到这条小结的服务端 id，而
  ///      `POST /patients/{no}/discharge` 的入参就是它。
  /// 两件事都真实存在，所以这一步不是锦上添花。
  ///
  /// 万一服务端那条**已经被 pull 落库**（同一行已在），就删掉本地占位行，
  /// 避免主键冲突。
  Future<void> _promoteLocalRecord({
    required String clientUuid,
    required int? serverId,
    required int revision,
  }) async {
    final row = await (_db.select(_db.treatmentRecords)
          ..where((t) => t.clientUuid.equals(clientUuid)))
        .getSingleOrNull();
    if (row == null) return;

    if (serverId == null || row.id == serverId) {
      await _db.customStatement(
        'UPDATE treatment_records SET revision = ?, sync_status = ? WHERE client_uuid = ?',
        <Object?>[revision, 'synced', clientUuid],
      );
      return;
    }

    final clash = await (_db.select(_db.treatmentRecords)
          ..where((t) => t.id.equals(serverId)))
        .getSingleOrNull();
    if (clash != null) {
      // 服务端版本已经在本地了：本地这份占位草稿是重复的，删掉。
      await (_db.delete(_db.treatmentRecords)
            ..where((t) => t.clientUuid.equals(clientUuid)))
          .go();
      return;
    }

    await _db.customStatement(
      'UPDATE treatment_records SET id = ?, revision = ?, sync_status = ? WHERE client_uuid = ?',
      <Object?>[serverId, revision, 'synced', clientUuid],
    );
  }

  static int? _asInt(Object? raw) {
    if (raw is num) return raw.toInt();
    return int.tryParse('$raw');
  }

  // ------------------------------------------------------------------------- //
  // 拉取
  // ------------------------------------------------------------------------- //
  /// 读取本地游标。
  Future<int> readCursor() async {
    final row = await (_db.select(_db.syncState)..where((t) => t.key.equals('last_cursor')))
        .getSingleOrNull();
    return int.tryParse(row?.value ?? '') ?? 0;
  }

  Future<void> writeCursor(int cursor) async {
    await _db.into(_db.syncState).insertOnConflictUpdate(
          SyncStateCompanion.insert(key: 'last_cursor', value: '$cursor'),
        );
  }

  /// **增量**拉取：不带 `entities` 过滤，循环拉到没有更多为止。
  ///
  /// ★ 不要在这里传 `entities` —— 被过滤掉的变更不返回但游标仍前进，
  /// 增量阶段传过滤会**永久跳过**被过滤实体的中间变更（协议 §5.3）。
  Future<int> pullIncremental() async {
    var cursor = await readCursor();
    while (true) {
      final data = await _client.request(
        kSyncPull,
        query: {'cursor': cursor, 'limit': maxPullLimit},
      ) as Map<String, dynamic>;

      final changes = (data['changes'] as List?) ?? const [];
      for (final raw in changes.whereType<Map>()) {
        await applyChange(Map<String, dynamic>.from(raw));
      }

      cursor = (data['cursor'] as num?)?.toInt() ?? cursor;
      await writeCursor(cursor);
      if (data['has_more'] != true) break;
    }
    return cursor;
  }

  /// **首次全量**拉取：按实体过滤，终点用 `latest_cursor`。
  ///
  /// 只在本地库为空时使用（协议 §5.3）。
  ///
  /// ★ 终点取`pull` 响应里的 `latest_cursor`，**不是** `/sync/info`
  /// —— `SyncInfoOut` 只描述能力（可推送实体、批量上限），没有游标字段。
  /// 过滤模式下游标可能停在中间，所以要以服务端当前最大 id 为基线，
  /// 之后的增量才不会漏。
  Future<int> pullInitial() async {
    var cursor = 0;
    while (true) {
      final data = await _client.request(
        kSyncPull,
        query: {
          'cursor': cursor,
          'limit': maxPullLimit,
          // 患者永远为空，不必带；带上也无害，但语义上容易让人误以为它走同步。
          // 2026-10-05：`appointment` 已在服务端下线，不再出现在同步通道里。
          'entities': 'treatment_record',
        },
      ) as Map<String, dynamic>;

      final changes = (data['changes'] as List?) ?? const [];
      for (final raw in changes.whereType<Map>()) {
        await applyChange(Map<String, dynamic>.from(raw));
      }

      cursor = (data['cursor'] as num?)?.toInt() ?? cursor;
      if (data['has_more'] != true) {
        // 拉完了：用服务端当前最大 id 作为增量起点。
        cursor = (data['latest_cursor'] as num?)?.toInt() ?? cursor;
        break;
      }
    }
    await writeCursor(cursor);
    return cursor;
  }

  /// 应用一条服务端变更到本地库。
  ///
  /// payload 是**完整快照**，所以可以做幂等 upsert，不必先查本地（协议 §5.4）。
  ///
  /// ★ 两个坑（2026-10-05 实测）：
  ///  1. 记录 id 要取变更里的 **`entity_id`**，不能只看 `payload['id']` ——
  ///     离线推送路径写进 `change_log` 的 payload 就是客户端那份
  ///     （没有 `id`，也没有 `rendered_text`），只有 `entity_id` 是权威的；
  ///  2. payload 里可能缺 `therapist_id` 等列 —— 缺就**保留本地已有的值**，
  ///     实在没有才退化成 0，否则 `(json['therapist_id'] as num)` 会直接抛
  ///     类型错误，把整批变更的应用打断。
  Future<void> applyChange(Map<String, dynamic> change) async {
    final entity = change['entity'] as String?;
    final op = change['op'] as String? ?? 'update';
    final entityId = change['entity_id']?.toString();
    final payload = change['payload'];
    if (entity == null || entityId == null) return;

    switch (entity) {
      case 'treatment_record':
        if (op == 'delete') {
          await (_db.delete(_db.treatmentRecords)
                ..where((t) => t.id.equals(int.parse(entityId))))
              .go();
        } else if (payload is Map) {
          await _upsertRecord(
            int.parse(entityId),
            Map<String, dynamic>.from(payload),
          );
        }
      case 'patient':
        // 服务端当前不会写 patient 变更（协议 §1），这里留一个警告便于早发现。
        assert(() {
          // ignore: avoid_print
          print('[sync] 收到 patient 变更：服务端已开始记录？请更新协议 §1');
          return true;
        }());
      case 'appointment':
        // 2026-10-05：排期已整体下线。这里**刻意不做静默忽略** ——
        // 若还有 appointment 变更流下来，说明服务端没删干净，要立刻发现。
        assert(() {
          // ignore: avoid_print
          print('[sync] 收到已下线的 appointment 变更：服务端同步通道可能没删干净');
          return true;
        }());
    }
  }

  /// 落一条记录（SOAP 模型：没有"明细"了，内容就是一列 `body_json`）。
  Future<void> _upsertRecord(int id, Map<String, dynamic> json) async {
    final existing = await (_db.select(_db.treatmentRecords)
          ..where((t) => t.id.equals(id)))
        .getSingleOrNull();

    await _db.into(_db.treatmentRecords).insertOnConflictUpdate(
          TreatmentRecordsCompanion.insert(
            id: Value(id),
            patientNo: (json['patient_no'] as String?) ?? existing?.patientNo ?? '',
            therapistId: (json['therapist_id'] as num?)?.toInt() ??
                existing?.therapistId ??
                0,
            recordDate: (json['record_date'] as String?) ??
                existing?.recordDate ??
                '',
            discipline:
                (json['discipline'] as String?) ?? existing?.discipline ?? '',
            kind: (json['kind'] as String?) ?? existing?.kind ?? 'daily',
            seqNo: Value((json['seq_no'] as num?)?.toInt() ?? existing?.seqNo),
            bodyJson: Value(
              json['body'] == null
                  ? (existing?.bodyJson ?? '{}')
                  : jsonEncode(json['body']),
            ),
            // ★ 离线推送路径的 payload 里没有 `rendered_text`（服务端记的是客户端
            //   那份），这时**保留本地已有的预览文本**，不要覆盖成空。
            renderedText: Value(
              (json['rendered_text'] as String?)?.isNotEmpty == true
                  ? json['rendered_text'] as String
                  : (existing?.renderedText ?? ''),
            ),
            note: Value((json['note'] as String?) ?? existing?.note),
            status: Value((json['status'] as String?) ?? 'draft'),
            editCount: Value((json['edit_count'] as num?)?.toInt() ?? 0),
            revision: Value((json['revision'] as num?)?.toInt() ?? 0),
            clientUuid: Value(
              (json['client_uuid'] as String?) ?? existing?.clientUuid,
            ),
          ),
        );
  }
}
