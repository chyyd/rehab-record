import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rehab_app/core/api_endpoints.dart';
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
    test('治疗记录 insert 落库（SOAP 模型：body + rendered_text）', () async {
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
          'record_date': '2026-10-06',
          'discipline': 'PT',
          'kind': 'daily',
          'seq_no': 4,
          'body': {'mental': '良好', 'therapy_items': ['偏瘫肢体综合训练']},
          'rendered_text': '康复治疗记录（PT运动）\n\n主观资料：精神状态：良好',
          'status': 'draft',
          'revision': 1,
        },
      });

      final row = await db.select(db.treatmentRecords).getSingle();
      expect(row.id, 11);
      expect(row.patientNo, 'ZY001');
      expect(row.discipline, 'PT');
      expect(row.kind, 'daily');
      expect(row.seqNo, 4);
      expect(row.bodyJson, contains('偏瘫肢体综合训练'));
      expect(row.renderedText, contains('主观资料'));
      expect(row.revision, 1);
    });

    test('★ 离线推送路径的 payload（没有 id / therapist_id / rendered_text）不崩', () async {
      // 服务端 `_push_treatment_record` 写进 change_log 的 payload 就是**客户端那份**：
      // 没有 id、没有 therapist_id、没有 rendered_text，只有 entity_id 是权威的。
      // 老代码在这里 `(json['therapist_id'] as num)` 会直接抛类型错误，
      // 把整批变更的应用打断。
      await engine.applyChange({
        'id': 21,
        'entity': 'treatment_record',
        'entity_id': '21',
        'op': 'insert',
        'revision': 1,
        'payload': {
          'patient_no': 'ZY002',
          'record_date': '2026-10-06',
          'discipline': 'OT',
          'kind': 'daily',
          'body': {'mental': '一般'},
          'status': 'submitted',
        },
      });

      final row = await db.select(db.treatmentRecords).getSingle();
      expect(row.id, 21, reason: 'id 取 entity_id');
      expect(row.therapistId, 0, reason: 'payload 里没有就退化成 0，而不是抛异常');
      expect(row.kind, 'daily');
      expect(row.status, 'submitted');
    });

    test('payload 缺 rendered_text 时保留本地已有的预览文本', () async {
      await db.into(db.treatmentRecords).insertOnConflictUpdate(
            TreatmentRecordsCompanion.insert(
              id: const Value(31),
              patientNo: 'ZY003',
              therapistId: 2,
              recordDate: '2026-10-06',
              discipline: 'PT',
              kind: 'daily',
              renderedText: const Value('本地预览文本'),
            ),
          );

      await engine.applyChange({
        'entity': 'treatment_record',
        'entity_id': '31',
        'op': 'update',
        'revision': 2,
        'payload': {'status': 'submitted', 'body': {'mental': '良好'}},
      });

      final row = await db.select(db.treatmentRecords).getSingle();
      expect(row.renderedText, '本地预览文本');
      expect(row.status, 'submitted');
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
          'record_date': '2026-10-06',
          'discipline': 'PT',
          'kind': 'daily',
          'status': 'draft',
          'revision': 1,
        },
      };
      await engine.applyChange(change);
      await engine.applyChange({
        ...change,
        'revision': 2,
        'payload': {...change['payload']! as Map, 'revision': 2},
      });

      final rows = await db.select(db.treatmentRecords).get();
      expect(rows.length, 1);
      expect(rows.single.revision, 2, reason: '第二次应用应更新成新版本');
    });

    test('delete 变更移除本地行', () async {
      await engine.applyChange({
        'id': 41, 'entity': 'treatment_record', 'entity_id': '41', 'op': 'insert', 'revision': 1,
        'payload': {
          'id': 41, 'patient_no': 'ZY009', 'therapist_id': 2,
          'record_date': '2026-10-05', 'discipline': 'PT', 'kind': 'daily',
          'status': 'draft', 'revision': 1,
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
          'date': '2026-10-05', 'period': 'am', 'status': 'planned', 'revision': 1,
        },
      });
      expect(await db.select(db.treatmentRecords).get(), isEmpty);
    });
  });

  group('★ 推送成功后把本地占位 id 换成服务端 id', () {
    /// 造一条本地新建（负数占位）的草稿 + 一条待推送的队列条目。
    Future<void> seedLocalDraft({required int localId, required String uuid}) async {
      await db.into(db.treatmentRecords).insertOnConflictUpdate(
            TreatmentRecordsCompanion.insert(
              id: Value(localId),
              patientNo: 'ZY001',
              therapistId: 2,
              recordDate: '2026-10-06',
              discipline: 'PT',
              kind: 'daily',
              clientUuid: Value(uuid),
              syncStatus: const Value('pending'),
            ),
          );
      await engine.enqueueInsert(
        entity: 'treatment_record',
        clientUuid: uuid,
        payload: {'patient_no': 'ZY001'},
      );
    }

    test('两条记录不重复：占位行被改名而不是新插一行', () async {
      await seedLocalDraft(localId: -1, uuid: 'u-local');

      final engineWithServer = SyncEngine(
        client: buildScriptedClient({
          kSyncPush: (
            200,
            {
              'applied': [
                {
                  'client_uuid': 'u-local',
                  'entity': 'treatment_record',
                  'entity_id': 77,
                  'revision': 4,
                },
              ],
              'skipped': <Object?>[],
              'conflicts': <Object?>[],
              'cursor': 9,
            },
          ),
        }),
        db: db,
      );

      await engineWithServer.pushPending();

      final rows = await db.select(db.treatmentRecords).get();
      expect(rows.length, 1, reason: '同一 uuid 只能有一行');
      expect(rows.single.id, 77, reason: '本地占位 id → 服务端 id（出院要用它）');
      expect(rows.single.syncStatus, 'synced');
      expect(rows.single.revision, 4);
    });

    test('服务端那条已经被 pull 落库时，删掉本地占位行而不是撞主键', () async {
      // pull 先到（正数 id 已在本地），随后 push 成功。
      await db.into(db.treatmentRecords).insertOnConflictUpdate(
            TreatmentRecordsCompanion.insert(
              id: const Value(77),
              patientNo: 'ZY001',
              therapistId: 2,
              recordDate: '2026-10-06',
              discipline: 'PT',
              kind: 'daily',
            ),
          );
      await seedLocalDraft(localId: -1, uuid: 'u-local');

      final engineWithServer = SyncEngine(
        client: buildScriptedClient({
          kSyncPush: (
            200,
            {
              'applied': [
                {
                  'client_uuid': 'u-local',
                  'entity': 'treatment_record',
                  'entity_id': 77,
                  'revision': 4,
                },
              ],
              'skipped': <Object?>[],
              'conflicts': <Object?>[],
              'cursor': 9,
            },
          ),
        }),
        db: db,
      );

      await engineWithServer.pushPending();

      final rows = await db.select(db.treatmentRecords).get();
      expect(rows.length, 1);
      expect(rows.single.id, 77);
      expect(rows.single.clientUuid, isNull);
    });
  });
}
