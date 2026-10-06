import 'dart:convert';

import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rehab_app/core/api_endpoints.dart';
import 'package:rehab_app/data/local/app_database.dart';
import 'package:rehab_app/data/repo/patient_repository.dart';

import 'support.dart';

/// 患者**建档**与**编辑**（2026-10-06）。
///
/// 起因是用户的两条要求：
/// 1. 「在 app 的患者页，右侧偏下悬浮一个 + 号的圆形按钮，用来新建患者」
/// 2. 「取消注意事项的治疗师只读属性」
///
/// 两者都需要后端权限放开（原来 `POST`/`PUT /patients` 都是管理员专属），
/// 这一组测的是**客户端这一半**：请求打对没有、本地写回没有、字段语义对不对。
/// 服务端的权限口径由 `backend/tests/test_auth_and_patients.py` 守。
void main() {
  late AppDatabase db;

  setUp(() {
    db = AppDatabase.forTesting(NativeDatabase.memory());
  });

  tearDown(() async => db.close());

  PatientRepository repoWith(ScriptedAdapter adapter) => PatientRepository(
        client: buildScriptedClient({}, adapter: adapter),
        db: db,
      );

  Map<String, dynamic> patientJson({
    String no = 'ZY100',
    String name = '新患者',
    String? diagnosis,
    String? note,
    String status = 'in_hospital',
  }) =>
      {
        'inpatient_no': no,
        'name': name,
        'diagnosis': diagnosis,
        'admin_note': note,
        'assigned_therapist_id': null,
        'assigned_therapist_name': null,
        'visible_therapist_id': null,
        'status': status,
        'revision': 1,
      };

  group('新建患者', () {
    test('POST 到 /patients，并带上填写的字段', () async {
      final adapter = ScriptedAdapter({kPatients: (201, patientJson())});
      final repo = repoWith(adapter);

      final saved = await repo.create(
        inpatientNo: 'ZY100',
        name: '新患者',
        diagnosis: '脑卒中恢复期',
        adminNote: '防跌倒',
        status: 'in_hospital',
      );

      final req = adapter.seen.single;
      expect(req.path, kPatients);
      expect(req.method, 'POST');
      final body = jsonDecode(req.data as String) as Map<String, dynamic>;
      expect(body['inpatient_no'], 'ZY100');
      expect(body['name'], '新患者');
      expect(body['diagnosis'], '脑卒中恢复期');
      expect(body['admin_note'], '防跌倒');
      expect(saved.inpatientNo, 'ZY100');
      expect(saved.name, '新患者');
    });

    test('★ 建档后**立刻写回本地**：列表不该等下一次同步才看得到', () async {
      final adapter = ScriptedAdapter({kPatients: (201, patientJson())});
      final repo = repoWith(adapter);

      expect(await repo.findByNo('ZY100'), isNull, reason: '建之前本地没有');

      await repo.create(inpatientNo: 'ZY100', name: '新患者');

      final local = await repo.findByNo('ZY100');
      expect(local, isNotNull, reason: '建档成功后本地必须能查到，否则列表里看不到它');
      expect(local!.name, '新患者');
      // 新患者必须是**可见**的，否则会被列表过滤掉
      expect(local.visible, isTrue);
    });

    test('诊断/注意事项留空时不发这两个键（不给后端塞空串）', () async {
      final adapter = ScriptedAdapter({kPatients: (201, patientJson())});
      final repo = repoWith(adapter);

      await repo.create(inpatientNo: 'ZY100', name: '新患者', diagnosis: '', adminNote: '');

      final body = jsonDecode(adapter.seen.single.data as String) as Map<String, dynamic>;
      expect(body.containsKey('diagnosis'), isFalse);
      expect(body.containsKey('admin_note'), isFalse);
    });

    test('住院编号重复 → 抛错，且不写本地库', () async {
      final adapter = ScriptedAdapter({
        kPatients: (409, {'code': 'PATIENT_EXISTS', 'message': '住院编号已存在'}),
      });
      final repo = repoWith(adapter);

      await expectLater(
        repo.create(inpatientNo: 'ZY100', name: '新患者'),
        throwsA(anything),
      );
      expect(await repo.findByNo('ZY100'), isNull, reason: '服务端拒绝就不该留下本地记录');
    });

    test('断网 → 抛错（建档只走在线，不进离线队列）', () async {
      // status 0 = 连接错误（见 support.dart 的约定）
      final adapter = ScriptedAdapter({kPatients: (0, null)});
      final repo = repoWith(adapter);

      await expectLater(
        repo.create(inpatientNo: 'ZY100', name: '新患者'),
        throwsA(anything),
      );
      expect(await repo.findByNo('ZY100'), isNull);
    });
  });

  group('编辑患者', () {
    Future<void> seed(String no, {String? note, String status = 'in_hospital'}) =>
        db.into(db.patients).insertOnConflictUpdate(
              PatientsCompanion.insert(
                inpatientNo: no,
                name: '原名字',
                adminNote: Value(note),
                status: status,
                fetchedAt: '2027-03-01T00:00:00.000Z',
              ),
            );

    test('★ 治疗师改注意事项：PUT 带上 admin_note 并写回本地', () async {
      await seed('ZY001');
      final adapter = ScriptedAdapter({
        kPatient('ZY001'): (200, patientJson(no: 'ZY001', name: '原名字', note: '治疗师补充')),
      });
      final repo = repoWith(adapter);

      final saved = await repo.update('ZY001', adminNote: '治疗师补充');

      final req = adapter.seen.single;
      expect(req.path, kPatient('ZY001'));
      expect(req.method, 'PUT');
      expect((jsonDecode(req.data as String) as Map)['admin_note'], '治疗师补充');
      expect(saved.adminNote, '治疗师补充');
      expect((await repo.findByNo('ZY001'))!.adminNote, '治疗师补充');
    });

    test('★ 只传要改的字段：`null` = 不改（不是清空）', () async {
      await seed('ZY001', note: '原有注意事项');
      final adapter = ScriptedAdapter({
        kPatient('ZY001'): (200, patientJson(no: 'ZY001', name: '新名字', note: '原有注意事项')),
      });
      final repo = repoWith(adapter);

      await repo.update('ZY001', name: '新名字');

      final body = jsonDecode(adapter.seen.single.data as String) as Map<String, dynamic>;
      expect(body['name'], '新名字');
      // 没传的字段**不能出现在 body 里** —— 否则后端会把它当成"改成 null"
      expect(body.containsKey('admin_note'), isFalse);
      expect(body.containsKey('diagnosis'), isFalse);
      expect(body.containsKey('status'), isFalse);
    });

    test('传空串 = 清空（治疗师删掉诊断应当生效）', () async {
      await seed('ZY001', note: '要删掉的');
      final adapter = ScriptedAdapter({
        kPatient('ZY001'): (200, patientJson(no: 'ZY001', name: '原名字')),
      });
      final repo = repoWith(adapter);

      await repo.update('ZY001', adminNote: '');

      expect((jsonDecode(adapter.seen.single.data as String) as Map)['admin_note'], '');
    });

    test('改状态也走同一个接口', () async {
      await seed('ZY001');
      final adapter = ScriptedAdapter({
        kPatient('ZY001'): (200, patientJson(no: 'ZY001', name: '原名字', status: 'paused')),
      });
      final repo = repoWith(adapter);

      final saved = await repo.update('ZY001', status: 'paused');

      expect((jsonDecode(adapter.seen.single.data as String) as Map)['status'], 'paused');
      expect(saved.status, 'paused');
    });

    test('看不到的患者 → 抛错，本地不变', () async {
      await seed('ZY900', note: '原值');
      final adapter = ScriptedAdapter({
        kPatient('ZY900'): (403, {'code': 'PATIENT_NOT_VISIBLE', 'message': '无权查看该患者'}),
      });
      final repo = repoWith(adapter);

      await expectLater(
        repo.update('ZY900', adminNote: '改不动'),
        throwsA(anything),
      );
      expect((await repo.findByNo('ZY900'))!.adminNote, '原值', reason: '服务端拒绝就不能改本地');
    });
  });
}