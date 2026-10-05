import 'dart:io';

import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

import 'tables.dart';

part 'app_database.g.dart';

/// 本地 SQLite（Drift）。
///
/// **Drift 迁移独立于服务端 Alembic**（`开发计划.md` M06）：服务端加迁移不代表
/// 本地要跟着升版本，本地只在"镜像表结构真的变了"时才 `schemaVersion++`。
///
/// 打开方式是 `NativeDatabase.createInBackground` —— 把 SQLite 放到独立 isolate，
/// 避免长查询卡住 UI 线程。
@DriftDatabase(
  tables: [
    Patients,
    Appointments,
    TreatmentRecords,
    RecordItems,
    ChangeQueue,
    SyncState,
    RefCache,
  ],
)
class AppDatabase extends _$AppDatabase {
  AppDatabase() : super(_openConnection());

  /// 测试用：注入内存库，不碰设备文件系统。
  AppDatabase.forTesting(super.executor);

  @override
  int get schemaVersion => 2;

  @override
  MigrationStrategy get migration => MigrationStrategy(
        onCreate: (Migrator m) async {
          await m.createAll();
        },
        onUpgrade: (Migrator m, int from, int to) async {
          // v2：记录页的离线草稿要把"尚未推送的明细"整体存成一列 JSON
          //（本地新建的草稿没有服务端 id，走不了 record_items 表）。
          if (from < 2) {
            await m.addColumn(treatmentRecords, treatmentRecords.pendingItemsJson);
          }
        },
        beforeOpen: (details) async {
          // 外键约束默认是关的，必须显式打开（与服务端一致的做法）。
          await customStatement('PRAGMA foreign_keys = ON');
        },
      );
}

QueryExecutor _openConnection() {
  return LazyDatabase(() async {
    final dir = await getApplicationDocumentsDirectory();
    final file = File(p.join(dir.path, 'rehab_app.sqlite'));
    return NativeDatabase.createInBackground(file);
  });
}
