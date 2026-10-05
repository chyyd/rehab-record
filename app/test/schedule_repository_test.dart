import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rehab_app/core/date_utils.dart';
import 'package:rehab_app/data/local/app_database.dart';
import 'package:rehab_app/data/remote/schedule_dto.dart' as dto;
import 'package:rehab_app/data/repo/schedule_repository.dart';
import 'package:rehab_app/sync/sync_engine.dart';

import 'support.dart';

void main() {
  group('日期工具（与服务端约定一致：日期用本地墙钟 YYYY-MM-DD）', () {
    test('formatDate 补零', () {
      expect(formatDate(DateTime(2027, 3, 1)), '2027-03-01');
      expect(formatDate(DateTime(2027, 12, 25)), '2027-12-25');
    });

    test('mondayOf 以周一为一周之始', () {
      // 2027-03-03 是周三
      expect(formatDate(mondayOf(DateTime(2027, 3, 3))), '2027-03-01');
      // 周一本身
      expect(formatDate(mondayOf(DateTime(2027, 3, 1))), '2027-03-01');
      // 周日应回到**同一周**的周一（不是下一周）
      expect(formatDate(mondayOf(DateTime(2027, 3, 7))), '2027-03-01');
    });

    test('weekDays 返回 7 天且从周一起', () {
      final days = weekDays(DateTime(2027, 3, 3));
      expect(days.length, 7);
      expect(formatDate(days.first), '2027-03-01');
      expect(formatDate(days.last), '2027-03-07');
      expect(weekdayLabel(days.first), '周一');
      expect(weekdayLabel(days.last), '周日');
    });

    test('parseDate 对非法输入返回 null 而不是抛异常', () {
      expect(parseDate('2027-03-01'), isNotNull);
      expect(parseDate('不是日期'), isNull);
    });

    test('shortDateFromIso 解析失败时原样返回', () {
      expect(shortDateFromIso('2027-03-01'), '3/1');
      expect(shortDateFromIso('怪值'), '怪值');
    });
  });

  group('排期本地写入（离线优先：先本地 + 入队）', () {
    late AppDatabase db;
    late ScheduleRepository repo;
    late SyncEngine sync;

    setUp(() {
      db = AppDatabase.forTesting(NativeDatabase.memory());
      sync = SyncEngine(client: buildScriptedClient({}), db: db);
      repo = ScheduleRepository(client: buildScriptedClient({}), db: db, sync: sync);
    });

    tearDown(() async => db.close());

    test('新建排期：用负数占位 id、标记 pending、并入队 insert', () async {
      final id = await repo.createLocal(
        const dto.AppointmentDraft(patientNo: 'ZY001', date: '2027-03-01', period: 'am'),
        therapistId: 2,
      );

      // 负数占位：避免与服务端自增 id 撞号。
      expect(id, lessThan(0));

      final row = await db.select(db.appointments).getSingle();
      expect(row.patientNo, 'ZY001');
      expect(row.period, 'am');
      expect(row.syncStatus, 'pending');
      expect(row.clientUuid, isNotNull);

      final queued = await db.select(db.changeQueue).getSingle();
      expect(queued.entity, 'appointment');
      expect(queued.op, 'insert');
      // ★ 新建入队不带基线（协议 §4.4：带上会被判成冲突，幂等失效）。
      expect(queued.baseRevision, isNull);
      expect(queued.payloadJson, contains('ZY001'));
    });

    test('连续新建的占位 id 递减，不会互相覆盖', () async {
      final a = await repo.createLocal(
        const dto.AppointmentDraft(patientNo: 'A', date: '2027-03-01', period: 'am'),
        therapistId: 2,
      );
      final b = await repo.createLocal(
        const dto.AppointmentDraft(patientNo: 'B', date: '2027-03-01', period: 'pm'),
        therapistId: 2,
      );

      expect({a, b}.length, 2, reason: '两次新建必须得到不同 id');
      expect(await db.select(db.appointments).get(), hasLength(2));
    });

    test('观察本地排期是响应式的（离线排班后界面能立刻看到）', () async {
      final emissions = <int>[];
      final sub = repo
          .watchLocal(dateFrom: '2027-03-01', dateTo: '2027-03-07')
          .listen((rows) => emissions.add(rows.length));

      await pumpEventQueue();
      expect(emissions.last, 0);

      await repo.createLocal(
        const dto.AppointmentDraft(patientNo: 'ZY001', date: '2027-03-02', period: 'am'),
        therapistId: 2,
      );
      await pumpEventQueue();
      expect(emissions.last, 1);

      await sub.cancel();
    });

    test('取消排期：状态置 cancelled 且不再出现在默认列表里', () async {
      await db.into(db.appointments).insert(
            AppointmentsCompanion.insert(
              id: const Value(7),
              patientNo: 'ZY001',
              therapistId: 2,
              date: '2027-03-01',
              period: 'am',
              revision: const Value(1),
            ),
          );

      await repo.cancelLocal(7);

      final row = await db.select(db.appointments).getSingle();
      expect(row.status, 'cancelled');
      // 取消与改期不占格子，也不该出现在排期列表里。
      final visible = await repo
          .watchLocal(dateFrom: '2027-03-01', dateTo: '2027-03-07')
          .first;
      expect(visible, isEmpty);
    });

    test('服务端返回的排期落库是幂等 upsert', () async {
      final json = {
        'id': 11,
        'patient_no': 'ZY001',
        'therapist_id': 2,
        'date': '2027-03-01',
        'period': 'am',
        'status': 'planned',
        'revision': 1,
      };
      await repo.upsertFromServer(json);
      await repo.upsertFromServer({...json, 'status': 'done', 'revision': 2});

      final rows = await db.select(db.appointments).get();
      expect(rows, hasLength(1));
      expect(rows.single.status, 'done');
      expect(rows.single.revision, 2);
    });

    test('格子内计数只算有效排期', () async {
      await db.into(db.appointments).insert(AppointmentsCompanion.insert(
            id: const Value(1), patientNo: 'A', therapistId: 2,
            date: '2027-03-01', period: 'am',
          ));
      await db.into(db.appointments).insert(AppointmentsCompanion.insert(
            id: const Value(2), patientNo: 'B', therapistId: 2,
            date: '2027-03-01', period: 'am', status: const Value('cancelled'),
          ));

      // 2026-10-03 起一个格子可以有多台，所以"计数"才是格子的表达方式。
      expect(await repo.localCountIn('2027-03-01', 'am', therapistId: 2), 1);
    });
  });

  group('可排性 DTO（半日格子不互斥：已有排期不让格子变灰）', () {
    test('available 只看休息/请假；已排期数量单独返回', () {
      final slot = dto.SlotAvailability.fromJson({
        'date': '2027-03-01',
        'period': 'am',
        'available': true,
        'reasons': <String>[],
        'appointment_count': 3,
        'appointments': <Map<String, dynamic>>[],
        'patients': [
          {'patient_no': 'ZY001', 'patient_name': '张三'},
        ],
        'patient_appointments': <Map<String, dynamic>>[],
      });

      expect(slot.available, isTrue, reason: '已有 3 台也不影响可排');
      expect(slot.appointmentCount, 3);
      expect(slot.patients.single.display, '张三');
      expect(slot.unavailableReasonLabel, '');
    });

    test('休息与请假有中文说明', () {
      dto.SlotAvailability slot(List<String> reasons) => dto.SlotAvailability.fromJson({
            'date': '2027-03-01',
            'period': 'pm',
            'available': false,
            'reasons': reasons,
            'appointment_count': 0,
            'patients': <Map<String, dynamic>>[],
            'patient_appointments': <Map<String, dynamic>>[],
          });

      expect(slot(['rest_block']).unavailableReasonLabel, '休息时段');
      expect(slot(['on_leave']).unavailableReasonLabel, '请假中');
      expect(slot(['rest_block', 'on_leave']).unavailableReasonLabel, '休息且请假');
    });

    test('患者无姓名时回落到住院号', () {
      final p = dto.SlotPatient.fromJson({'patient_no': 'ZY009'});
      expect(p.display, 'ZY009');
    });
  });
}
