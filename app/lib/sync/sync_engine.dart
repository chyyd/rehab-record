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
  Future<void> enqueueUpdate({
    required String entity,
    required String clientUuid,
    required Map<String, dynamic> payload,
    required int baseRevision,
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
    if (item.entity == 'appointment') {
      await _db.customStatement(
        'UPDATE appointments SET revision = ?, sync_status = ? WHERE client_uuid = ?',
        <Object?>[revision ?? 0, 'synced', item.clientUuid],
      );
    } else if (item.entity == 'treatment_record') {
      await _db.customStatement(
        'UPDATE treatment_records SET revision = ?, sync_status = ? WHERE client_uuid = ?',
        <Object?>[revision ?? 0, 'synced', item.clientUuid],
      );
    }
    await _db.delete(_db.changeQueue)
        .delete(ChangeQueueCompanion(clientUuid: Value(item.clientUuid)));
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
          'entities': 'treatment_record,appointment',
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
  /// payload 是**完整快照**（治疗记录还带 `items`），所以可以做幂等 upsert，
  /// 不必先查本地（协议 §5.4）。
  Future<void> applyChange(Map<String, dynamic> change) async {
    final entity = change['entity'] as String?;
    final op = change['op'] as String? ?? 'update';
    final entityId = change['entity_id']?.toString();
    final payload = change['payload'];
    if (entity == null || entityId == null) return;

    switch (entity) {
      case 'appointment':
        if (op == 'delete') {
          await (_db.delete(_db.appointments)..where((t) => t.id.equals(int.parse(entityId)))).go();
        } else if (payload is Map) {
          await _upsertAppointment(Map<String, dynamic>.from(payload));
        }
      case 'treatment_record':
        if (op == 'delete') {
          await (_db.delete(_db.treatmentRecords)
                ..where((t) => t.id.equals(int.parse(entityId))))
              .go();
        } else if (payload is Map) {
          await _upsertRecord(Map<String, dynamic>.from(payload));
        }
      case 'patient':
        // 服务端当前不会写 patient 变更（协议 §1），这里留一个警告便于早发现。
        assert(() {
          // ignore: avoid_print
          print('[sync] 收到 patient 变更：服务端已开始记录？请更新协议 §1');
          return true;
        }());
    }
  }

  Future<void> _upsertAppointment(Map<String, dynamic> json) async {
    final id = (json['id'] as num).toInt();
    await _db.into(_db.appointments).insertOnConflictUpdate(
          AppointmentsCompanion.insert(
            id: Value(id),
            patientNo: json['patient_no'] as String,
            therapistId: (json['therapist_id'] as num).toInt(),
            date: json['date'] as String,
            period: json['period'] as String,
            startTime: Value(json['start_time'] as String?),
            endTime: Value(json['end_time'] as String?),
            slotLabel: Value(json['slot_label'] as String?),
            status: Value(json['status'] as String? ?? 'planned'),
            note: Value(json['note'] as String?),
            revision: Value((json['revision'] as num?)?.toInt() ?? 0),
          ),
        );
  }

  Future<void> _upsertRecord(Map<String, dynamic> json) async {
    final id = (json['id'] as num).toInt();
    await _db.into(_db.treatmentRecords).insertOnConflictUpdate(
          TreatmentRecordsCompanion.insert(
            id: Value(id),
            patientNo: json['patient_no'] as String,
            therapistId: (json['therapist_id'] as num).toInt(),
            recordDate: json['record_date'] as String,
            sessionPeriod: Value(json['session_period'] as String?),
            durationMin: Value((json['duration_min'] as num?)?.toInt()),
            note: Value(json['note'] as String?),
            patientResponseJson: Value(
              json['patient_response'] == null ? null : jsonEncode(json['patient_response']),
            ),
            status: Value(json['status'] as String? ?? 'draft'),
            seqNo: Value((json['seq_no'] as num?)?.toInt()),
            editCount: Value((json['edit_count'] as num?)?.toInt() ?? 0),
            revision: Value((json['revision'] as num?)?.toInt() ?? 0),
            appointmentId: Value((json['appointment_id'] as num?)?.toInt()),
            isTemporary: Value(json['is_temporary'] == true),
            originalTherapistId: Value((json['original_therapist_id'] as num?)?.toInt()),
          ),
        );

    final items = json['items'];
    if (items is List) {
      // 明细整体替换：payload 是完整快照，先删后插最简单也最不容易错。
      await (_db.delete(_db.recordItems)..where((t) => t.recordId.equals(id))).go();
      var sort = 0;
      for (final raw in items.whereType<Map>()) {
        final item = Map<String, dynamic>.from(raw);
        await _db.into(_db.recordItems).insertOnConflictUpdate(
              RecordItemsCompanion.insert(
                id: Value((item['id'] as num).toInt()),
                recordId: id,
                mainItemId: (item['main_item_id'] as num).toInt(),
                subItemId: (item['sub_item_id'] as num).toInt(),
                subItemNameSnapshot: Value(item['sub_item_name_snapshot'] as String?),
                paramsJson: jsonEncode(item['params'] ?? const <String, dynamic>{}),
                paramsSnapshotJson: Value(
                  item['params_snapshot'] == null ? null : jsonEncode(item['params_snapshot']),
                ),
                sort: Value(sort++),
              ),
            );
      }
    }
  }
}
