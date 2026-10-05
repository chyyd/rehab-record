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
  int get schemaVersion => 5;

  @override
  MigrationStrategy get migration => MigrationStrategy(
        onCreate: (Migrator m) async {
          await m.createAll();
        },
        onUpgrade: (Migrator m, int from, int to) async {
          // v2：记录页的离线草稿要把"尚未推送的明细"整体存成一列 JSON
          //（本地新建的草稿没有服务端 id，走不了 record_items 表）。
          //
          // 该列在 v5 已随整张表重建删掉，`TreatmentRecords` 里不再有它的定义，
          // 所以这里只能按**列名**写 SQL —— 拿不到 GeneratedColumn 引用
          //（同 v3/v4 里按名字删列的理由）。历史迁移必须保持可执行：
          // 从 v1 升上来的设备仍会走这一句。
          if (from < 2) {
            await customStatement(
              'ALTER TABLE treatment_records ADD COLUMN pending_items_json TEXT',
            );
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
          // v4：临时指派（`temporary_assignment`）彻底删除（服务端迁移 009），
          // 归属简化成"可见归属 = 原归属"两层；本地镜像里那个恒为 'assigned' 的
          // `visibility_state` 列随之删除。
          //
          // 与 v3 同理，这里按**列名**删而不是引用 `patients.visibilityState` ——
          // 该列已从 `Patients` 表定义里移除，Drift 不再认识它。
          if (from < 4) {
            await m.dropColumn(patients, 'visibility_state');
          }
          // v5：治疗记录改成 SOAP 模板驱动（服务端迁移 011/012 之后）。
          //
          // ★ **本地旧记录直接丢弃，不做数据搬运**。理由有三条，缺一不可：
          //   1. 旧行是「主项目 + 子项目 + 参数」结构，新模型是「大类 + 形态 + body」——
          //      两者之间**没有可计算的映射**（子项目 id → 模板字段 key 根本不存在）；
          //   2. 服务端已清空重建（迁移 011）；本地留着一批新模型解释不了的旧行，
          //      只会让记录列表显示出一堆打不开的幽灵记录；
          //   3. 用户已确认「清掉重来」（离线草稿本来就只是"还没上传的草稿"，
          //      上传过的记录在服务端仍在，重新同步即可回来）。
          //
          // 实现上**重建表**而不是逐列 addColumn：新增的 `discipline` / `kind` 是
          // NOT NULL 且没有默认值，SQLite 的 `ALTER TABLE ADD COLUMN` 不允许
          // （即便表里已经没有行）；`record_items` 表也整体不再需要（没有"明细"了），
          // 按表名删掉，避免留下无人使用的孤儿表（同 v3 的 appointments）。
          if (from < 5) {
            await m.deleteTable('treatment_records');
            await m.createTable(treatmentRecords);
            await m.deleteTable('record_items');
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
