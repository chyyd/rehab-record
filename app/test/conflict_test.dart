import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rehab_app/core/api_endpoints.dart';
import 'package:rehab_app/data/local/app_database.dart';
import 'package:rehab_app/features/sync/conflict_providers.dart';
import 'package:rehab_app/sync/sync_engine.dart';

import 'support.dart';

/// 冲突处理（`docs/sync-protocol.md` §4.4 / §6）。
///
/// 这里测的是**本地一半**的行为：队列状态怎么变、基线怎么对齐。
/// 服务端的判定规则由后端测试覆盖（`backend/tests/test_sync.py`），
/// 两边通过协议文档对齐。
void main() {
  late AppDatabase db;
  late SyncEngine engine;

  /// 服务端返回的推送响应（形状取自 `PushResponse`）。
  Map<String, Object?> pushResponse({
    List<Map<String, Object?>> applied = const [],
    List<Map<String, Object?>> skipped = const [],
    List<Map<String, Object?>> conflicts = const [],
  }) =>
      {
        'applied': applied,
        'skipped': skipped,
        'conflicts': conflicts,
        'cursor': 7,
      };

  Future<void> seedPending({
    required String uuid,
    required String entity,
    int? baseRevision,
    String status = 'pending',
  }) async {
    await db.into(db.changeQueue).insertOnConflictUpdate(
          ChangeQueueCompanion.insert(
            clientUuid: uuid,
            entity: entity,
            op: const Value('update'),
            baseRevision: Value(baseRevision),
            payloadJson: '{"patient_no":"S2B","record_date":"2027-07-08",'
                '"session_period":"am","status":"submitted",'
                '"items":[{"main_item_id":1,"sub_item_id":1,"params":{}}]}',
            syncStatus: Value(status),
            createdAt: '2027-07-08T00:00:00Z',
          ),
        );
  }

  setUp(() {
    db = AppDatabase.forTesting(NativeDatabase.memory());
    engine = SyncEngine(client: buildScriptedClient({}), db: db);
  });

  tearDown(() async => db.close());

  group('冲突标记（服务端说冲突 → 保留在队列里等裁决）', () {
    test('冲突条目被标记为 conflict 且**不**出队', () async {
      await seedPending(uuid: 'u1', entity: 'treatment_record', baseRevision: 1);
      final engineWithServer = SyncEngine(
        client: buildScriptedClient({
          kSyncPush: (
            200,
            pushResponse(conflicts: [
              {
                'client_uuid': 'u1',
                'entity': 'treatment_record',
                'server_revision': 3,
                'server_status': 'submitted',
                'reason': 'server_status=submitted',
              },
            ]),
          ),
        }),
        db: db,
      );

      final report = await engineWithServer.pushPending();
      expect(report.hasConflicts, isTrue);
      expect(report.conflicts.single.serverRevision, 3);

      // 关键：冲突**不能静默丢弃** —— 内容还在，等治疗师裁决。
      final row = await db.select(db.changeQueue).getSingle();
      expect(row.syncStatus, 'conflict');
      expect(row.payloadJson, contains('S2B'));
      // 冲突条目仍算"待同步"，否则「我的」页会显示 0 条而实际上有事没完。
      expect(await engineWithServer.pendingCount(), 1);
    });

    test('applied 的条目出队并回写 revision', () async {
      await seedPending(uuid: 'u2', entity: 'appointment', baseRevision: 1);
      final engineWithServer = SyncEngine(
        client: buildScriptedClient({
          kSyncPush: (
            200,
            pushResponse(applied: [
              {'client_uuid': 'u2', 'entity': 'appointment', 'entity_id': 59, 'revision': 2},
            ]),
          ),
        }),
        db: db,
      );

      await engineWithServer.pushPending();
      expect(await db.select(db.changeQueue).get(), isEmpty);
    });

    test('skipped 的条目也出队（避免死循环重试）', () async {
      await seedPending(uuid: 'u3', entity: 'appointment');
      final engineWithServer = SyncEngine(
        client: buildScriptedClient({
          kSyncPush: (
            200,
            pushResponse(skipped: [
              {'client_uuid': 'u3', 'entity': 'appointment', 'reason': 'duplicate_in_batch'},
            ]),
          ),
        }),
        db: db,
      );

      await engineWithServer.pushPending();
      expect(await db.select(db.changeQueue).get(), isEmpty);
    });
  });

  group('★ 裁决动作（同步引擎侧）', () {
    test('requeueWithoutBase：清空基线、退回 pending、重试计数清零', () async {
      await seedPending(
        uuid: 'u4',
        entity: 'treatment_record',
        baseRevision: 1,
        status: 'conflict',
      );
      // 先制造"已重试 3 次、带错误原因"的状态。
      await (db.update(db.changeQueue)..where((t) => t.clientUuid.equals('u4')))
          .write(const ChangeQueueCompanion(
        retryCount: Value(3),
        lastError: Value('server_status=submitted'),
      ));

      await engine.requeueWithoutBase('u4');

      final row = await db.select(db.changeQueue).getSingle();
      expect(row.syncStatus, 'pending');
      // ★ 必须清空：留着旧基线若恰好与服务端一致，服务端会直接应用，
      // 那就成了"推着推着悄悄覆盖"，而不是治疗师确认后的覆盖。
      expect(row.baseRevision, isNull);
      expect(row.retryCount, 0, reason: '裁决后是新尝试，不能被退避策略压住');
      expect(row.lastError, isNull);
    });

    test('keepMine：把服务端当前 revision 作为新基线', () async {
      await seedPending(
        uuid: 'u5',
        entity: 'treatment_record',
        baseRevision: null,
        status: 'conflict',
      );

      await engine.keepMine('u5', 3);

      final row = await db.select(db.changeQueue).getSingle();
      expect(row.baseRevision, 3,
          reason: '服务端判定 base_revision == server_revision 时无冲突 → 直接应用');
      expect(row.syncStatus, 'pending');
      expect(row.retryCount, 0);
    });

    test('discardMine：条目从队列移除', () async {
      await seedPending(uuid: 'u6', entity: 'appointment', status: 'conflict');
      await engine.discardMine('u6');
      expect(await db.select(db.changeQueue).get(), isEmpty);
    });

    test('discardMany：批量移除', () async {
      await seedPending(uuid: 'a', entity: 'appointment', status: 'conflict');
      await seedPending(uuid: 'b', entity: 'appointment', status: 'conflict');
      await seedPending(uuid: 'c', entity: 'treatment_record', status: 'pending');

      await engine.discardMany(['a', 'b']);

      final rows = await db.select(db.changeQueue).get();
      expect(rows.map((r) => r.clientUuid), ['c'], reason: '待推送的不该被牵连');
    });

    test('conflictCount / conflicts 只取冲突条目', () async {
      await seedPending(uuid: 'x', entity: 'appointment', status: 'conflict');
      await seedPending(uuid: 'y', entity: 'appointment', status: 'pending');
      await seedPending(uuid: 'z', entity: 'appointment', status: 'conflict');

      expect(await engine.conflictCount(), 2);
      expect((await engine.conflicts()).map((r) => r.clientUuid), ['x', 'z']);
    });

    test('watchConflicts 是响应式的（裁决后界面自动少一条）', () async {
      await seedPending(uuid: 'w1', entity: 'appointment', status: 'conflict');
      await seedPending(uuid: 'w2', entity: 'appointment', status: 'conflict');

      final emissions = <int>[];
      final sub = engine.watchConflicts().listen((rows) => emissions.add(rows.length));

      await pumpEventQueue();
      expect(emissions.last, 2);

      await engine.discardMine('w1');
      await pumpEventQueue();
      expect(emissions.last, 1);

      await sub.cancel();
    });
  });

  group('冲突条目的 UI 视图（ConflictItem）', () {
    ChangeQueueData row({
      required String payload,
      String? lastError,
      int? baseRevision,
      int retryCount = 0,
    }) =>
        ChangeQueueData(
          clientUuid: 'view-1',
          entity: 'treatment_record',
          op: 'update',
          baseRevision: baseRevision,
          payloadJson: payload,
          syncStatus: 'conflict',
          retryCount: retryCount,
          lastError: lastError,
          createdAt: '2027-07-08T00:00:00Z',
        );

    test('解析载荷并给出中文标签', () {
      final item = ConflictItem.fromRow(row(payload: '''
{"patient_no":"S2B","record_date":"2027-07-08","session_period":"am",
 "status":"submitted","duration_min":45,"note":"首次",
 "items":[{"main_item_id":1,"sub_item_id":1,"params":{}},
          {"main_item_id":1,"sub_item_id":2,"params":{}}]}
'''));

      expect(item.entityLabel, '治疗记录');
      expect(item.opLabel, '修改');
      expect(item.patientNo, 'S2B');
      expect(item.dateLabel, '2027-07-08');
      expect(item.itemCount, 2);
    });

    test('载荷损坏时不崩，并如实说明无法解析', () {
      final item = ConflictItem.fromRow(row(payload: '这不是 JSON'));
      expect(item.payload, isEmpty);
      expect(item.patientNo, isNull);
      expect(item.itemCount, 0);
    });

    test('冲突原因翻成人话（服务端的四种取值）', () {
      String label(String? reason) =>
          ConflictItem.fromRow(row(payload: '{}', lastError: reason)).reasonLabel;

      expect(label('missing_base_revision'), contains('没有版本基线'));
      expect(label('entity_prefers_server'), contains('以服务端为准'));
      expect(label('server_status=submitted'), contains('已提交'));
      expect(label('server_status=locked'), contains('已锁定'));
      // 未知原因不吞掉：原样显示，便于排查。
      expect(label('some_new_reason'), 'some_new_reason');
      expect(label(null), contains('另一个版本'));
    });

    test('排期冲突用 date 字段（不是 record_date）', () {
      final item = ConflictItem.fromRow(ChangeQueueData(
        clientUuid: 'appt-1',
        entity: 'appointment',
        op: 'insert',
        baseRevision: null,
        payloadJson: '{"patient_no":"S2B","date":"2027-07-09","period":"pm"}',
        syncStatus: 'conflict',
        retryCount: 0,
        lastError: null,
        createdAt: '2027-07-08T00:00:00Z',
      ));
      expect(item.entityLabel, '排期');
      expect(item.opLabel, '新建');
      expect(item.dateLabel, '2027-07-09');
      expect(item.itemCount, 0, reason: '排期没有明细项');
    });
  });
}
