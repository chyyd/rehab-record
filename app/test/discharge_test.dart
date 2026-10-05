import 'dart:convert';

import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rehab_app/core/api_endpoints.dart';
import 'package:rehab_app/data/local/app_database.dart';
import 'package:rehab_app/data/repo/patient_repository.dart';

import 'support.dart';

/// 出院流程（用户 2026-10-05 要求）：
/// 「在 app 记录治疗的左侧对称位置添加出院按钮，所有治疗师都可以有出院的权限，
///   点击后就是出院小结」「选择出院必须出院小结」。
///
/// 服务端那边：`POST /patients/{no}/discharge` 的 body 必须是**该患者已提交的
/// 出院小结 id**（"出院不是点按钮，而是文书写完了"），成功后退回
/// `pending_discharge` —— 患者随即从治疗师白板消失。
void main() {
  late AppDatabase db;

  Map<String, Object?> patientJson({
    String status = 'pending_discharge',
  }) =>
      {
        'inpatient_no': 'ZY001',
        'name': '患者甲',
        'diagnosis': '脑卒中恢复期',
        'admin_note': null,
        'assigned_therapist_id': 2,
        'visible_therapist_id': 2,
        'status': status,
        'revision': 3,
      };

  setUp(() async {
    db = AppDatabase.forTesting(NativeDatabase.memory());
    await db.into(db.patients).insertOnConflictUpdate(
          PatientsCompanion.insert(
            inpatientNo: 'ZY001',
            name: '患者甲',
            status: 'in_hospital',
            assignedTherapistId: const Value(2),
            fetchedAt: '2026-10-06T00:00:00Z',
          ),
        );
  });

  tearDown(() async => db.close());

  test('★ 发起出院：POST 到 patients/{no}/discharge，body 是出院小结 id', () async {
    final adapter = ScriptedAdapter({
      kPatientDischarge('ZY001'): (200, patientJson()),
    });
    final client = buildScriptedClient({}, adapter: adapter);
    final repo = PatientRepository(client: client, db: db);

    final status = await repo.requestDischarge('ZY001', 41);

    expect(status, 'pending_discharge');
    final request = adapter.seen.single;
    expect(request.path, '/api/v1/patients/ZY001/discharge');
    expect(request.method, 'POST');
    final body = jsonDecode(request.data as String) as Map<String, dynamic>;
    expect(body, {'record_id': 41});
  });

  test('★ 待出院后本地状态跟着变，并且**立刻从白板消失**（但不删本地行）', () async {
    final adapter = ScriptedAdapter({
      kPatientDischarge('ZY001'): (200, patientJson()),
    });
    final repo = PatientRepository(
      client: buildScriptedClient({}, adapter: adapter),
      db: db,
    );

    await repo.requestDischarge('ZY001', 41);

    final row = await repo.findByNo('ZY001');
    expect(row, isNotNull, reason: '本地绝不删患者行 —— 历史记录还要用患者信息');
    expect(row!.status, 'pending_discharge');
    expect(row.visible, isFalse, reason: '待出院患者已不在治疗师白板上');

    // 列表里看不到他了。
    expect(await repo.listLocal(), isEmpty);
    // 但记录/详情仍然找得到。
    expect((await repo.listLocal(includeHidden: true)).length, 1);
  });

  test('患者状态不是待出院时不隐藏（例如管理员取消待出院后重新拉取）', () async {
    final adapter = ScriptedAdapter({
      kPatientDischarge('ZY001'): (200, patientJson(status: 'in_hospital')),
    });
    final repo = PatientRepository(
      client: buildScriptedClient({}, adapter: adapter),
      db: db,
    );

    final status = await repo.requestDischarge('ZY001', 41);
    expect(status, 'in_hospital');
    expect((await repo.findByNo('ZY001'))!.visible, isTrue);
  });

  test('小结未提交 / 不属于该患者时服务端报错，原样透传（409/422）', () async {
    final adapter = ScriptedAdapter({
      kPatientDischarge('ZY001'): (
        409,
        {
          'code': 'CONFLICT',
          'message': '出院小结尚未提交',
          'details': {'record_id': 41, 'status': 'draft'},
        }
      ),
    });
    final repo = PatientRepository(
      client: buildScriptedClient({}, adapter: adapter),
      db: db,
    );

    await expectLater(
      repo.requestDischarge('ZY001', 41),
      throwsA(
        isA<Exception>().having(
          (e) => '$e',
          'toString',
          contains('出院小结尚未提交'),
        ),
      ),
    );
    // 失败不该把本地患者状态改坏。
    expect((await repo.findByNo('ZY001'))!.status, 'in_hospital');
  });
}
