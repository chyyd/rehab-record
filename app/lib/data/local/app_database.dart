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
  /// [backendFingerprint] 让**每台后端一个独立的库文件**。
  ///
  /// 2026-10-06 加运行期"手填后端地址"之后，必须这么分：
  /// 本地库把服务端主键当自己的主键用（`treatment_records.id` 就是服务端记录 id、
  /// `patients.inpatient_no` 就是服务端住院号、`sync_state.last_cursor` 是服务端
  /// 变更日志游标）。换一台服务器，这些标识全部对不上 ——
  /// 同一个住院号在两边是不同的患者、同一个记录 id 在两边是不同的记录。
  ///
  /// 分文件是**比"切地址时记得清库"更可靠**的做法：清库依赖每个切换路径都写对，
  /// 而分文件是**结构上不可能串**。旧库文件留在设备上不碍事（也能留作排障），
  /// 想省空间可以后续加一招"清理非当前指纹的库"。
  AppDatabase({DatabaseNaming? naming})
      : super(_openConnection(naming ?? const DatabaseNaming(
          backendFingerprint: 'default',
          isEnvironmentDefault: true,
        )));

  /// 测试用：注入内存库，不碰设备文件系统。
  AppDatabase.forTesting(super.executor);

  @override
  int get schemaVersion => 6;

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
          // v6：患者表加 `assigned_therapist_name`（归属治疗师姓名）。
          //
          // 原来详情页显示「治疗师 #2」—— 原始 id 对治疗师没有意义。
          // 姓名由**服务端**解析后随患者下发（本地没有 user 表，也不应该为了显示
          // 姓名去镜像账号体系）。纯新增可空列，`addColumn` 就够，不动存量数据。
          if (from < 6) {
            await m.addColumn(patients, patients.assignedTherapistName);
          }
        },
        beforeOpen: (details) async {
          // 外键约束默认是关的，必须显式打开（与服务端一致的做法）。
          await customStatement('PRAGMA foreign_keys = ON');
        },
      );
}

QueryExecutor _openConnection(DatabaseNaming naming) {
  return LazyDatabase(() async {
    final dir = await getApplicationDocumentsDirectory();
    final file = File(p.join(dir.path, databaseFileName(naming)));
    return NativeDatabase.createInBackground(file);
  });
}

/// 本地库该用哪个文件。
///
/// - [backendFingerprint]：当前后端的指纹。
/// - [isEnvironmentDefault]：当前后端**就是编译期默认的那台**。
///
/// 为什么需要第二个字段：升级前的库文件就叫 `rehab_app.sqlite`，
/// 而那时只有一台后端（编译期注入）。把"默认后端"继续映射到这个名字，
/// 老用户升级后数据还在，不会因为改名被"清空"。
///
/// ⚠ 这里**不能**用 `fingerprint == 'default'` 来判断 ——
/// `backendFingerprint()` 只在地址解析不出 host 时才返回 `'default'`，
/// 真实地址（如 `10.0.2.2:8000`）的指纹是 `10_0_2_2_8000`，
/// 拿 `'default'` 比会永远不相等，兼容逻辑等于没写（我第一版就是这么错的）。
String databaseFileName(DatabaseNaming naming) =>
    naming.isEnvironmentDefault
        ? 'rehab_app.sqlite'
        : 'rehab_app_${naming.backendFingerprint}.sqlite';

/// [databaseFileName] 的入参（把两个容易搞混的字段绑在一起，避免传错顺序）。
class DatabaseNaming {
  const DatabaseNaming({
    required this.backendFingerprint,
    required this.isEnvironmentDefault,
  });

  final String backendFingerprint;
  final bool isEnvironmentDefault;
}
