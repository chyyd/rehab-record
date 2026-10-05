/// Drift 表定义。
///
/// 与 `docs/sync-protocol.md` §7.2 一一对应。设计要点：
///
/// 1. **主键用服务端的 id**（治疗记录、排期），患者用 `inpatient_no`；
/// 2. `client_uuid` 建唯一索引 —— 与服务端的 `ux_record_client_uuid` /
///    `ux_appt_client_uuid` 对称，是幂等推送的本地保障；
/// 3. 时间戳字段一律**文本 UTC ISO8601 带毫秒**，与服务端约定一致
///    （禁止本地时区，避免 +08:00 下偏移）；
/// 4. 参考数据（字典/选项集/模板/反应定义）**不进表**，整包 JSON 存 `ref_cache`——
///    它们只读，建成表换不来查询收益，反而多一套迁移（协议 §7.1）。
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
  TextColumn get visibilityState => text().nullable()();
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
class TreatmentRecords extends Table {
  IntColumn get id => integer()();
  TextColumn get patientNo => text()();
  IntColumn get therapistId => integer()();
  TextColumn get recordDate => text()();
  TextColumn get sessionPeriod => text().nullable()();
  IntColumn get durationMin => integer().nullable()();
  TextColumn get note => text().nullable()();

  /// `patient_response_json` 原样保存：`{"tags": [...], "items": [...]}`。
  /// 不做结构化拆解——服务端已保证 `json_valid()`，客户端只需原样回传。
  TextColumn get patientResponseJson => text().nullable()();
  TextColumn get status => text().withDefault(const Constant('draft'))();

  /// 该患者第几次治疗；**草稿不占号**，提交后才有值。
  IntColumn get seqNo => integer().nullable()();
  IntColumn get editCount => integer().withDefault(const Constant(0))();
  IntColumn get revision => integer().withDefault(const Constant(0))();

  /// 2026-10-03 起"全科白板"，实测这两个字段恒为 false/NULL（协议 §10）。
  /// 保留只为与服务端字段一一对应，**不要**再用它做 UI 判断。
  BoolColumn get isTemporary => boolean().withDefault(const Constant(false))();
  IntColumn get originalTherapistId => integer().nullable()();

  TextColumn get clientUuid => text().nullable()();
  TextColumn get syncStatus => text().withDefault(const Constant('synced'))();

  /// 明细快照（JSON 数组），**仅用于离线草稿**。
  ///
  /// 为什么需要它：服务端返回的 `payload.items` 里带着两层快照
  /// （`sub_item_name_snapshot` + `params_snapshot_json`），所以**已同步**记录的明细
  /// 走 `record_items` 表。但本地新建、**尚未推送**的草稿没有服务端 id，
  /// 明细只能先整体存成一列 JSON；推送成功后由同步引擎落成 `record_items` 行。
  TextColumn get pendingItemsJson => text().nullable()();

  @override
  Set<Column> get primaryKey => {id};
}

/// 治疗记录明细（含两层快照）。
class RecordItems extends Table {
  IntColumn get id => integer()();
  IntColumn get recordId => integer()();
  IntColumn get mainItemId => integer()();
  IntColumn get subItemId => integer()();

  /// 第一层快照：子项目**当时**的名称，字典改名后历史仍显示原文。
  TextColumn get subItemNameSnapshot => text().nullable()();

  /// 实际提交的参数值（键为 `param_key`）。
  TextColumn get paramsJson => text()();

  /// 第二层快照：参数**当时**的显示名、取值与选项文本。
  TextColumn get paramsSnapshotJson => text().nullable()();
  IntColumn get sort => integer().withDefault(const Constant(0))();

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
