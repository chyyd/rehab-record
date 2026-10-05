import 'dart:io';

import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;
import 'package:rehab_app/data/local/app_database.dart';

/// 本地库迁移 **4 → 5**（治疗记录：表格模型 → SOAP 模板驱动）。
///
/// 这个迁移有一条**刻意的决定**：本地旧记录**直接丢弃，不做数据搬运** ——
/// 旧的「主项目 + 子项目 + 参数」结构与新模型之间没有可计算的映射
///（子项目 id 对不上模板字段 key），服务端也已清空重建，用户确认「清掉重来」。
/// 所以这里守的是四件事：
///   1. 旧行真的没了（不留解释不了的幽灵记录）；
///   2. 新列（discipline / kind / body_json / rendered_text）可用；
///   3. 旧列（session_period / duration_min / patient_response_json）彻底消失；
///   4. `record_items` 表被删掉（没有"明细"了）。
void main() {
  /// 造一个 v4 库用的最小 user：只设置版本号，迁移回调什么都不做
  ///（真正的旧表结构由测试自己用 SQL 建，才叫"测迁移"）。
  late Directory tempDir;

  setUp(() async {
    tempDir = await Directory.systemTemp.createTemp('rehab_migration_');
  });

  tearDown(() async {
    if (tempDir.existsSync()) await tempDir.delete(recursive: true);
  });

  test('★ 4 → 5：清空旧行、重建 treatment_records、删掉 record_items', () async {
    final file = File(p.join(tempDir.path, 'rehab_app.sqlite'));

    // 1) 手工造一个 v4 的库：旧表结构 + 一行旧记录。
    final legacy = NativeDatabase(file);
    await legacy.ensureOpen(_LegacyV4User());
    await legacy.runCustom(_legacyTreatmentRecordsSql, const []);
    await legacy.runCustom(_legacyRecordItemsSql, const []);
    await legacy.runCustom(
      "INSERT INTO treatment_records"
      " (id, patient_no, therapist_id, record_date, session_period, duration_min,"
      "  status, seq_no, pending_items_json)"
      " VALUES (7, 'ZY001', 2, '2026-10-01', 'am', 30, 'submitted', 3,"
      "  '[{\"main_item_id\":1,\"sub_item_id\":11,\"params\":{\"side\":\"左\"}}]')",
      const [],
    );
    await legacy.runCustom(
      'INSERT INTO record_items (id, record_id, main_item_id, sub_item_id, params_json)'
      " VALUES (101, 7, 1, 11, '{\"side\":\"左\"}')",
      const [],
    );
    await legacy.close();

    // 2) 用当前 AppDatabase 打开同一个文件 → 触发 onUpgrade(4, 5)。
    final db = AppDatabase.forTesting(NativeDatabase(file));
    addTearDown(db.close);

    // 旧行被清空（服务的记录重新同步会回来，本地草稿本来就只是"没上传的草稿"）。
    expect(await db.select(db.treatmentRecords).get(), isEmpty);

    // 新列就位，旧列消失。
    final columns = await _columnsOf(db, 'treatment_records');
    expect(
      columns,
      containsAll(<String>[
        'discipline',
        'kind',
        'seq_no',
        'body_json',
        'rendered_text',
        'status',
        'client_uuid',
      ]),
    );
    expect(columns, isNot(contains('session_period')));
    expect(columns, isNot(contains('duration_min')));
    expect(columns, isNot(contains('patient_response_json')));
    expect(columns, isNot(contains('pending_items_json')));

    // record_items 表整体删除（新模型没有"明细"）。
    //
    // ★ 2026-10-05：这里原来还断言 `contains('patients')` / `contains('treatment_records')`，
    //   但本用例的 v4 库是**手工造的最小库**（只建 `treatment_records` 与 `record_items`），
    //   压根没有 `patients` 表 —— 断言 `contains('patients')` 必然失败，
    //   而且它也不在 `from < 5` 的迁移范围内。改成断言迁移真正保证的事：
    //   **该删的删掉、该在的还在**。
    final tables = await _tablesOf(db);
    expect(tables, isNot(contains('record_items')));
    expect(tables, contains('treatment_records'));

    // 3) 建出来的新表真能写能读（列名与 Drift 定义一致）。
    await db.into(db.treatmentRecords).insertOnConflictUpdate(
          TreatmentRecordsCompanion.insert(
            id: const Value(9),
            patientNo: 'ZY001',
            therapistId: 2,
            recordDate: '2026-10-06',
            discipline: 'PT',
            kind: 'daily',
            bodyJson: const Value('{"mental":"良好"}'),
            renderedText: const Value('康复治疗记录（PT运动）'),
          ),
        );
    final row = await db.select(db.treatmentRecords).getSingle();
    expect(row.discipline, 'PT');
    expect(row.kind, 'daily');
    expect(row.bodyJson, '{"mental":"良好"}');
    expect(row.renderedText, '康复治疗记录（PT运动）');
    expect(row.status, 'draft', reason: 'withDefault 生效');
  });

  test('全新的库（onCreate）直接就是 v5：没有 record_items、有新列', () async {
    final db = AppDatabase.forTesting(NativeDatabase.memory());
    addTearDown(db.close);

    final tables = await _tablesOf(db);
    expect(tables, isNot(contains('record_items')));
    expect(
      await _columnsOf(db, 'treatment_records'),
      containsAll(<String>['discipline', 'kind', 'body_json', 'rendered_text']),
    );
  });
}

Future<List<String>> _columnsOf(AppDatabase db, String table) async {
  final rows = await db.customSelect('PRAGMA table_info($table)').get();
  return rows.map((r) => r.read<String>('name')).toList();
}

Future<List<String>> _tablesOf(AppDatabase db) async {
  final rows = await db
      .customSelect("SELECT name FROM sqlite_master WHERE type = 'table'")
      .get();
  return rows.map((r) => r.read<String>('name')).toList();
}

/// v4 的 `treatment_records`（**含**后来被删掉的列，一个字都不能少）。
const String _legacyTreatmentRecordsSql = '''
CREATE TABLE treatment_records (
  id INTEGER NOT NULL,
  patient_no TEXT NOT NULL,
  therapist_id INTEGER NOT NULL,
  record_date TEXT NOT NULL,
  session_period TEXT,
  duration_min INTEGER,
  note TEXT,
  patient_response_json TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  seq_no INTEGER,
  edit_count INTEGER NOT NULL DEFAULT 0,
  revision INTEGER NOT NULL DEFAULT 0,
  is_temporary INTEGER NOT NULL DEFAULT 0,
  original_therapist_id INTEGER,
  client_uuid TEXT,
  sync_status TEXT NOT NULL DEFAULT 'synced',
  pending_items_json TEXT,
  PRIMARY KEY (id)
)''';

/// v4 的 `record_items`（v5 整体删除）。
const String _legacyRecordItemsSql = '''
CREATE TABLE record_items (
  id INTEGER NOT NULL,
  record_id INTEGER NOT NULL,
  main_item_id INTEGER NOT NULL,
  sub_item_id INTEGER NOT NULL,
  sub_item_name_snapshot TEXT,
  params_json TEXT NOT NULL,
  params_snapshot_json TEXT,
  sort INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (id)
)''';

/// 只负责"把库标成 v4"的最小 user（迁移回调刻意留空）。
class _LegacyV4User implements QueryExecutorUser {
  @override
  int get schemaVersion => 4;

  @override
  Future<void> beforeOpen(QueryExecutor executor, OpeningDetails details) async {}
}
