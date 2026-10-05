import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rehab_app/data/local/app_database.dart';
import 'package:rehab_app/data/repo/patient_repository.dart';

import 'support.dart';

/// 患者数据层的回归测试。
///
/// 重点守住一个**实测踩到的缺陷**：列表必须是**响应式**的。
/// 早先用一次性快照（`FutureProvider` + `listLocal`），登录后的后台首次同步
/// 虽然成功落库（本地库确实有 14 名患者），但界面一直显示空列表，
/// 必须手动下拉才出来 —— 床旁场景下等于看不到患者。
void main() {
  late AppDatabase db;
  late PatientRepository repo;

  setUp(() {
    db = AppDatabase.forTesting(NativeDatabase.memory());
    repo = PatientRepository(client: buildScriptedClient({}), db: db);
  });

  tearDown(() async => db.close());

  Future<void> seed(String no, String name, {int? therapistId, String status = 'in_hospital'}) {
    return db.into(db.patients).insertOnConflictUpdate(
          PatientsCompanion.insert(
            inpatientNo: no,
            name: name,
            assignedTherapistId: Value(therapistId),
            status: status,
            fetchedAt: '2027-03-01T00:00:00.000Z',
          ),
        );
  }

  group('响应式患者列表', () {
    test('落库后自动发射，不需要外部 invalidate', () async {
      final emissions = <List<PatientView>>[];
      final sub = repo.watchLocal().listen(emissions.add);

      // 初次：空
      await pumpEventQueue();
      expect(emissions.last, isEmpty);

      // 模拟后台首次同步写入
      await seed('ZY001', '张三');
      await pumpEventQueue();
      expect(emissions.last.map((p) => p.inpatientNo), ['ZY001']);

      await seed('ZY002', '李四');
      await pumpEventQueue();
      expect(emissions.last.length, 2);

      await sub.cancel();
    });

    test('软隐藏的患者不出现在列表里（已出院不能消失成"没有数据"，但也不该展示）', () async {
      await seed('ZY001', '在院患者');
      await seed('ZY002', '已出院患者');
      await (db.update(db.patients)..where((t) => t.inpatientNo.equals('ZY002')))
          .write(const PatientsCompanion(visible: Value(false)));

      final rows = await repo.listLocal();
      expect(rows.map((p) => p.inpatientNo), ['ZY001']);
    });

    test('软隐藏的行仍然在库里（历史记录不能失去患者信息）', () async {
      await seed('ZY001', '患者');
      await (db.update(db.patients)..where((t) => t.inpatientNo.equals('ZY001')))
          .write(const PatientsCompanion(visible: Value(false)));

      expect(await repo.findByNo('ZY001'), isNotNull);
      expect((await repo.listLocal(includeHidden: true)).length, 1);
    });
  });

  group('排序与服务端语义一致（我的 → 未分配 → 其他）', () {
    test('我的患者排最前，未分配次之', () async {
      await seed('A', '别人的', therapistId: 9);
      await seed('B', '未分配');
      await seed('C', '我的', therapistId: 3);

      final rows = await repo.listLocal(therapistId: 3);
      expect(rows.map((p) => p.inpatientNo), ['C', 'B', 'A']);
    });

    test('onlyMine 只保留我的与未分配的', () async {
      await seed('A', '别人的', therapistId: 9);
      await seed('B', '未分配');
      await seed('C', '我的', therapistId: 3);

      final rows = await repo.listLocal(therapistId: 3, onlyMine: true);
      expect(rows.map((p) => p.inpatientNo), ['C', 'B']);
    });
  });

  group('本地筛选（离线可用）', () {
    test('未分配筛选与关键字匹配', () async {
      await seed('ZY001', '张三', therapistId: 3);
      await seed('ZY002', '李四');

      final unassigned = await repo.listLocal();
      expect(
        unassigned.where((p) => p.assignedTherapistId == null).map((p) => p.inpatientNo),
        ['ZY002'],
      );
      expect(
        unassigned.where((p) => p.name.contains('张')).map((p) => p.inpatientNo),
        ['ZY001'],
      );
    });
  });

  group('注意事项压平', () {
    test('多行注意事项压成单行，便于列表展示', () {
      expect(PatientRepository.flattenNote('注意防跌倒\n左侧偏瘫'), '注意防跌倒 左侧偏瘫');
      expect(PatientRepository.flattenNote(null), '');
      expect(PatientRepository.flattenNote('   '), '');
    });
  });
}
