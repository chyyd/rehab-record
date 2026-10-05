/// Drift 表定义。
///
/// 与 `docs/sync-protocol.md` §7.2 一一对应。设计要点：
///
/// 1. **主键用服务端的 id**（治疗记录、排期），患者用 `inpatient_no`；
/// 2. `client_uuid` 建唯一索引 —— 与服务端的 `ux_record_client_uuid` /
///    `ux_appt_client_uuid` 对称，是幂等推送的本地保障；
/// 3. 时间戳字段一律**文本 UTC ISO8601 带毫秒**，与服务端约定一致
///    （禁止本地时区，避免 +08:00 下偏移）；
/// 4. 参考数据**不进表**，整包 JSON 存 `ref_cache`——它们只读，建成表换不来查询收益，
///    反而多一套迁移（协议 §7.1）。2026-10-05 起这里只放两样东西：
///    记录页表单的离线缓存、以及多选字段的"最近用过"顺序（见 `RecordRepository`）。
library;

import 'package:drift/drift.dart';

/// 患者镜像表（★ 不走同步接口，用 `GET /api/v1/patients` 分页刷新，协议 §1）。
class Patients extends Table {
  TextColumn get inpatientNo => text()();
  TextColumn get name => text()();
  TextColumn get diagnosis => text().nullable()();
  TextColumn get adminNote => text().nullable()();
  IntColumn get assignedTherapistId => integer().nullable()();
  IntColumn get visibleTherapistId => integer().nullable()();

  /// 2026-10-05：`visibility_state` 列**已删除**（本地库 schemaVersion 3 → 4）。
  ///
  /// 它缓存的是服务端 `v_patient_visibility.visibility_state`，而那个字段随临时指派
  /// 删除后**恒为 `'assigned'`**（服务端的"可见归属"现在直接等于 `assigned_therapist_id`）。
  /// 一个恒为常量的镜像列没有任何查询价值，继续留着只会让后来的人以为本地有归属状态机。
  /// 服务端仍返回该字段（为兼容既有客户端），但 App **不再读也不再写**它。
  TextColumn get status => text()();

  /// 服务端 `revision`，用于推送时做乐观锁基线。
  IntColumn get revision => integer().withDefault(const Constant(0))();

  /// 本地是否仍在该治疗师的可见范围内。
  ///
  /// ★ 已出院患者会从"全科白板"消失，但本地**不能**直接删——否则历史记录会失去
  /// 患者信息（协议 §2）。用这个标记软隐藏。
  BoolColumn get visible => boolean().withDefault(const Constant(true))();

  TextColumn get fetchedAt => text()();

  @override
  Set<Column> get primaryKey => {inpatientNo};
}

/// 治疗记录镜像表（可离线写）。
///
/// ★ 2026-10-05 脊柱级改造（Schema v5）：记录从「表格 + 明细」变成
/// **SOAP 模板驱动的一段文本 + 一个扁平答案表**，所以：
///   - 删 `session_period` / `duration_min`（半日与时长两个字段整体下线）；
///   - 删 `patient_response_json`（患者反应表 `response_def` 已随迁移 012 删除）；
///   - 删 `pending_items_json`（没有"明细"了，答案就是一个 `body_json`）；
///   - 新增 `discipline` / `kind` / `body_json` / `rendered_text`。
class TreatmentRecords extends Table {
  IntColumn get id => integer()();
  TextColumn get patientNo => text()();
  IntColumn get therapistId => integer()();
  TextColumn get recordDate => text()();

  /// `PT` / `OT` / `ST_SW` / `ST_SP`（四大类）。
  TextColumn get discipline => text()();

  /// `initial` / `daily` / `reassessment` / `discharge`（形态）。
  TextColumn get kind => text()();

  /// 第几次**日常**记录；评估文书（首评/复评/出院小结）不占次数 → 为 null。
  IntColumn get seqNo => integer().nullable()();

  /// 答案：`{field_key: value}`（键就是模板字段的 `key`）。
  ///
  /// 这是**唯一**的记录内容载体：服务端 `body` 原样存取，App 不再拆表。
  TextColumn get bodyJson => text().withDefault(const Constant('{}'))();

  /// 服务端在落库时**冻结**的 SOAP 纯文本（时间轴/详情直接显示它）。
  ///
  /// 本地草稿也存一份客户端预览（见 `RecordRepository`），推送成功后会被
  /// 服务端返回的正式文本覆盖。
  TextColumn get renderedText => text().withDefault(const Constant(''))();

  TextColumn get note => text().nullable()();
  TextColumn get status => text().withDefault(const Constant('draft'))();

  IntColumn get editCount => integer().withDefault(const Constant(0))();
  IntColumn get revision => integer().withDefault(const Constant(0))();

  /// 2026-10-03 起"全科白板"，实测这两个字段恒为 false/NULL（协议 §10）。
  /// 保留只为与服务端字段一一对应，**不要**再用它做 UI 判断。
  BoolColumn get isTemporary => boolean().withDefault(const Constant(false))();
  IntColumn get originalTherapistId => integer().nullable()();

  TextColumn get clientUuid => text().nullable()();
  TextColumn get syncStatus => text().withDefault(const Constant('synced'))();

  @override
  Set<Column> get primaryKey => {id};
}

/// 本地变更队列（离线写入待推送的实体）。
///
/// ★ `client_uuid` 是主键，同时也是**幂等键**：重试必须复用同一个值。
/// 服务端按它做 upsert，弱网整批重推不会产生重复数据（协议 §4.4）。
class ChangeQueue extends Table {
  TextColumn get clientUuid => text()();
  TextColumn get entity => text()();
  TextColumn get op => text().withDefault(const Constant('insert'))();

  /// 乐观锁基线。**重试时保持为 null**——带上过期基线会被服务端判成冲突
  /// （`entity_prefers_server`），幂等就失效了（协议 §4.4 的 ★）。
  IntColumn get baseRevision => integer().nullable()();

  /// 推送体（服务端 `SyncChangeIn.payload`）。
  TextColumn get payloadJson => text()();
  TextColumn get syncStatus => text().withDefault(const Constant('pending'))();
  IntColumn get retryCount => integer().withDefault(const Constant(0))();
  TextColumn get lastError => text().nullable()();
  TextColumn get createdAt => text()();

  @override
  Set<Column> get primaryKey => {clientUuid};
}

/// 同步状态（键值对）：`last_cursor`、`last_patient_sync_at` 等。
///
/// 只存 `last_cursor`，**不本地复制 `change_log`**（协议 §5.4）。
class SyncState extends Table {
  TextColumn get key => text()();
  TextColumn get value => text()();

  @override
  Set<Column> get primaryKey => {key};
}

/// 参考数据缓存：字典树、选项集解析结果、模板、患者反应定义。
///
/// **整包原子替换**（先写再改 key），避免出现半套数据。
class RefCache extends Table {
  /// 如 `dict_tree`、`options:side`、`templates`、`response_defs`。
  TextColumn get key => text()();
  TextColumn get payloadJson => text()();
  TextColumn get fetchedAt => text()();
  TextColumn get etag => text().nullable()();

  @override
  Set<Column> get primaryKey => {key};
}
