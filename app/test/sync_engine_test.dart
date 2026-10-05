import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rehab_app/data/local/app_database.dart';
import 'package:rehab_app/sync/sync_engine.dart';

import 'support.dart';

/// 同步引擎的本地行为测试。
///
/// 只测**不依赖服务端**的部分：队列写入、游标读写、变更应用。
/// 这些恰恰是协议里最容易写错的地方（见 `docs/sync-protocol.md` §4.4、§5.4）。
void main() {
  late AppDatabase db;
  late SyncEngine engine;

  setUp(() {
    db = AppDatabase.forTesting(NativeDatabase.memory());
    engine = SyncEngine(client: buildScriptedClient({}), db: db);
  });

  tearDown(() async => db.close());

  group('推送队列（协议 §4.4 ★ 重试不带 base_revision）', () {
    test('新建变更入队时 base_revision 必须为 null', () async {
      await engine.enqueueInsert(
        entity: 'treatment_record',
        clientUuid: 'uuid-insert-1',
        payload: {'patient_no': 'ZY001'},
      );

      final row = await db.select(db.changeQueue).getSingle();
      expect(row.clientUuid, 'uuid-insert-1');
      expect(row.entity, 'treatment_record');
      expect(row.op, 'insert');
      // 关键：带上过期基线会被服务端判成冲突（entity_prefers_server），
      // 弱网下每次重试都失败，幂等就失效了。
      expect(row.baseRevision, isNull);
      expect(row.syncStatus, 'pending');
      expect(row.retryCount, 0);
    });

    test('修改变更才带 base_revision', () async {
      await engine.enqueueUpdate(
        entity: 'treatment_record',
        clientUuid: 'uuid-update-1',
        payload: {'note': '改了'},
        baseRevision: 3,
      );

      final row = await db.select(db.changeQueue).getSingle();
      expect(row.op, 'update');
      expect(row.baseRevision, 3);
    });

    test('同一 client_uuid 重复入队是覆盖而不是新增（幂等键）', () async {
      await engine.enqueueInsert(
        entity: 'treatment_record',
        clientUuid: 'uuid-dup',
        payload: {'record_date': '2027-03-01'},
      );
      await engine.enqueueInsert(
        entity: 'treatment_record',
        clientUuid: 'uuid-dup',
        payload: {'record_date': '2027-03-02'},
      );

      final rows = await db.select(db.changeQueue).get();
      expect(rows.length, 1);
      expect(rows.single.payloadJson, contains('2027-03-02'));
    });

    test('pendingCount 统计 pending 与 conflict（冲突不能静默丢弃）', () async {
      await engine.enqueueInsert(
        entity: 'treatment_record',
        clientUuid: 'a',
        payload: const {},
      );
      await engine.enqueueInsert(
        entity: 'treatment_record',
        clientUuid: 'b',
        payload: const {},
      );
      await (db.update(db.changeQueue)..where((t) => t.clientUuid.equals('b')))
          .write(const ChangeQueueCompanion(syncStatus: Value('conflict')));

      expect(await engine.pendingCount(), 2);
    });
  });

  group('游标（协议 §5.3 用 change_log.id，不用时间戳）', () {
    test('初始游标为 0', () async {
      expect(await engine.readCursor(), 0);
    });

    test('写入后可读回，且是覆盖语义', () async {
      await engine.writeCursor(128);
      expect(await engine.readCursor(), 128);

      await engine.writeCursor(129);
      expect(await engine.readCursor(), 129);
      final rows = await db.select(db.syncState).get();
      expect(rows.length, 1, reason: 'sync_state 是键值对，不该堆多行');
    });
  });

  group('应用服务端变更（payload 是完整快照 → 幂等 upsert）', () {
    test('治疗记录 insert 落库', () async {
      await engine.applyChange({
        'id': 11,
        'entity': 'treatment_record',
        'entity_id': '11',
        'op': 'insert',
        'revision': 1,
        'payload': {
          'id': 11,
          'patient_no': 'ZY001',
          'therapist_id': 2,
          'record_date': '2027-03-01',
          'session_period': 'am',
          'duration_min': 30,
          'status': 'draft',
          'revision': 1,
        },
      });

      final row = await db.select(db.treatmentRecords).getSingle();
      expect(row.id, 11);
      expect(row.patientNo, 'ZY001');
      expect(row.sessionPeriod, 'am');
      expect(row.revision, 1);
    });

    test('同一实体重复应用不产生重复行（弱网重放安全）', () async {
      final change = {
        'id': 12,
        'entity': 'treatment_record',
        'entity_id': '12',
        'op': 'insert',
        'revision': 1,
        'payload': {
          'id': 12,
          'patient_no': 'ZY002',
          'therapist_id': 3,
          'record_date': '2027-03-01',
          'session_period': 'pm',
          'duration_min': 45,
          'status': 'draft',
          'revision': 1,
        },
      };
      await engine.applyChange(change);
      await engine.applyChange({...change, 'revision': 2, 'payload': {...change['payload']! as Map, 'revision': 2}});

      final rows = await db.select(db.treatmentRecords).get();
      expect(rows.length, 1);
      expect(rows.single.revision, 2, reason: '第二次应用应更新成新版本');
    });

    test('治疗记录带 items 一起落库（明细整体替换）', () async {
      await engine.applyChange({
        'id': 21,
        'entity': 'treatment_record',
        'entity_id': '21',
        'op': 'insert',
        'revision': 1,
        'payload': {
          'id': 21,
          'patient_no': 'ZY001',
          'therapist_id': 2,
          'record_date': '2027-03-01',
          'status': 'submitted',
          'revision': 1,
          'items': [
            {'id': 101, 'main_item_id': 1, 'sub_item_id': 11, 'params': {'side': '左'}},
            {'id': 102, 'main_item_id': 1, 'sub_item_id': 12, 'params': {'side': '右'}},
          ],
        },
      });

      final record = await db.select(db.treatmentRecords).getSingle();
      expect(record.status, 'submitted');
      final items = await db.select(db.recordItems).get();
      expect(items.length, 2);
      expect(items.map((i) => i.recordId), everyElement(21));
    });

    test('记录更新后明细被整体替换，不残留旧明细', () async {
      Map<String, dynamic> payload(List<Map<String, dynamic>> items) => {
            'id': 31,
            'patient_no': 'ZY001',
            'therapist_id': 2,
            'record_date': '2027-03-01',
            'status': 'draft',
            'revision': 1,
            'items': items,
          };

      await engine.applyChange({
        'id': 31, 'entity': 'treatment_record', 'entity_id': '31', 'op': 'insert', 'revision': 1,
        'payload': payload([
          {'id': 201, 'main_item_id': 1, 'sub_item_id': 11, 'params': const {}},
          {'id': 202, 'main_item_id': 1, 'sub_item_id': 12, 'params': const {}},
        ]),
      });
      await engine.applyChange({
        'id': 32, 'entity': 'treatment_record', 'entity_id': '31', 'op': 'update', 'revision': 2,
        'payload': payload([
          {'id': 201, 'main_item_id': 1, 'sub_item_id': 11, 'params': const {}},
        ]),
      });

      final items = await db.select(db.recordItems).get();
      expect(items.length, 1, reason: '明细按快照整体替换');
      expect(items.single.id, 201);
    });

    test('delete 变更移除本地行', () async {
      await engine.applyChange({
        'id': 41, 'entity': 'treatment_record', 'entity_id': '41', 'op': 'insert', 'revision': 1,
        'payload': {
          'id': 41, 'patient_no': 'ZY009', 'therapist_id': 2,
          'record_date': '2027-03-05', 'session_period': 'am', 'status': 'draft', 'revision': 1,
        },
      });
      expect((await db.select(db.treatmentRecords).get()).length, 1);

      await engine.applyChange({
        'id': 42, 'entity': 'treatment_record', 'entity_id': '41', 'op': 'delete', 'revision': 1,
        'payload': null,
      });
      expect(await db.select(db.treatmentRecords).get(), isEmpty);
    });

    test('payload 为 null 的非删除变更不崩', () async {
      await engine.applyChange({
        'id': 51, 'entity': 'treatment_record', 'entity_id': '51', 'op': 'update', 'revision': 1,
        'payload': null,
      });
      expect(await db.select(db.treatmentRecords).get(), isEmpty);
    });

    test('已下线的 appointment 变更不写库（assert 下会打印告警）', () async {
      // 排期已整体下线（2026-10-05）。若服务端同步通道没删干净还有 appointment
      // 流下来，本地**不能**写任何行，也不该抛异常中断整批变更的应用。
      await engine.applyChange({
        'id': 61, 'entity': 'appointment', 'entity_id': '61', 'op': 'insert', 'revision': 1,
        'payload': {
          'id': 61, 'patient_no': 'ZY009', 'therapist_id': 2,
          'date': '2027-03-05', 'period': 'am', 'status': 'planned', 'revision': 1,
        },
      });
      expect(await db.select(db.treatmentRecords).get(), isEmpty);
      expect(await db.select(db.recordItems).get(), isEmpty);
    });
  });
}
