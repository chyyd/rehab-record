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
  int get schemaVersion => 3;

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
          // v3：排期功能整体下线（2026-10-05），本地镜像表随之删除；
          // 记录表里那个只为"从排期进入"存在的 appointment_id 一并去掉。
          //
          // 注意 `appointments` 必须用 `deleteTable('appointments')` 按**表名**删：
          // 该表已从 `@DriftDatabase(tables:)` 里移除，Drift 不再认识它，
          // 拿不到 GeneratedTable，只能按 SQL 名删。不删就会留下一张孤儿表
          //（schema 里还在、代码里没人用），后来的人会以为它有用。
          if (from < 3) {
            await m.deleteTable('appointments');
            await m.dropColumn(treatmentRecords, 'appointment_id');
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
