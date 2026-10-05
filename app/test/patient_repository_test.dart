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

  /// ★ 2026-10-05：患者列表排序改成"我最近一次**已提交**治疗"降序。
  ///
  /// 这个语义原先是用排期算的（服务端 `v_patient_next_appointment` 的"下一个排期日期"），
  /// 排期下线后换成按治疗记录算。**本地必须与服务端同口径**，否则服务端排序与
  /// App 显示会漂移（同一个患者在两边位置不同）。
  group('★ 我最近一次已提交治疗优先（与服务端 v_patient_last_treated 同口径）', () {
    /// 落一条治疗记录（本地镜像表）。
    Future<void> record(
      String patientNo,
      String date, {
      required int therapistId,
      String status = 'submitted',
    }) {
      return db.into(db.treatmentRecords).insertOnConflictUpdate(
            TreatmentRecordsCompanion.insert(
              patientNo: patientNo,
              therapistId: therapistId,
              recordDate: date,
              status: Value(status),
            ),
          );
    }

    test('组内按最近治疗日期降序（越近越靠前）', () async {
      await seed('P1', '甲', therapistId: 3);
      await seed('P2', '乙', therapistId: 3);
      await seed('P3', '丙', therapistId: 3);

      // P2 最近、P1 中间、P3 从没治过
      await record('P1', '2027-03-05', therapistId: 3);
      await record('P2', '2027-03-09', therapistId: 3);

      final rows = await repo.listLocal(therapistId: 3);
      expect(rows.map((p) => p.inpatientNo), ['P2', 'P1', 'P3'],
          reason: '最近治过的在最前；从没治过的排最后');
    });

    test('★ 草稿不参与排序（否则"写了一半没提交"会把患者顶到最前）', () async {
      await seed('P1', '甲', therapistId: 3);
      await seed('P2', '乙', therapistId: 3);

      await record('P1', '2027-03-05', therapistId: 3); // 已提交（较早）
      await record('P2', '2027-03-20', therapistId: 3, status: 'draft'); // 草稿（更近）

      final rows = await repo.listLocal(therapistId: 3);
      expect(rows.map((p) => p.inpatientNo), ['P1', 'P2'],
          reason: '草稿不算治疗 —— 否则那条记录在汇总/时间轴里还不存在，看起来像系统错乱');
    });

    test('锁定同样不计入（与服务端视图一致：只算 submitted）', () async {
      await seed('P1', '甲', therapistId: 3);
      await seed('P2', '乙', therapistId: 3);

      await record('P1', '2027-03-01', therapistId: 3);
      await record('P2', '2027-03-20', therapistId: 3, status: 'locked');

      final rows = await repo.listLocal(therapistId: 3);
      expect(rows.map((p) => p.inpatientNo), ['P1', 'P2']);
    });

    test('只算**我自己**的治疗：别人治过不算我最近治过', () async {
      await seed('P1', '甲', therapistId: 3);
      await seed('P2', '乙', therapistId: 3);

      await record('P1', '2027-03-01', therapistId: 3);
      // 别人（治疗师 9）最近治过 P2 —— 从治疗师 3 的视角不该因此把它提前
      await record('P2', '2027-03-20', therapistId: 9);

      final rows = await repo.listLocal(therapistId: 3);
      expect(rows.map((p) => p.inpatientNo), ['P1', 'P2']);
    });

    test('归属分组优先于治疗历史（别人的患者治过也仍在最后一组）', () async {
      await seed('P1', '我的', therapistId: 3);
      await seed('P2', '别人的', therapistId: 9);

      await record('P2', '2027-03-20', therapistId: 3); // 我最近给别人的患者治过
      await record('P1', '2027-03-01', therapistId: 3);

      final rows = await repo.listLocal(therapistId: 3);
      expect(rows.map((p) => p.inpatientNo), ['P1', 'P2'],
          reason: '分组是第一关键字；否则"我偶尔替别人做了一次"会把它顶到我自己的患者前面');
    });

    test('写一条记录后列表顺序自动变（响应式，不需要手动刷新）', () async {
      await seed('P1', '甲', therapistId: 3);
      await seed('P2', '乙', therapistId: 3);
      await record('P1', '2027-03-05', therapistId: 3);

      final emissions = <List<String>>[];
      final sub = repo
          .watchLocal(therapistId: 3)
          .listen((rows) => emissions.add(rows.map((p) => p.inpatientNo).toList()));

      await pumpEventQueue();
      expect(emissions.last, ['P1', 'P2'], reason: '首帧必须发射（不是只有写入才发射）');

      // 给 P2 记一条更新的 —— 治疗记录表变了，排序也该跟着变
      await record('P2', '2027-03-09', therapistId: 3);
      await pumpEventQueue();
      expect(emissions.last, ['P2', 'P1'],
          reason: '排序依赖治疗记录表，所以只订阅 patients 是不够的');

      await sub.cancel();
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
