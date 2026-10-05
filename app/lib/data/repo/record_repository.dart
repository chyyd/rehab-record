import 'dart:convert';
import 'dart:math';

import 'package:drift/drift.dart';

import 'package:rehab_app/core/api_endpoints.dart';
import 'package:rehab_app/core/date_utils.dart';
import 'package:rehab_app/core/error.dart';
// 别名导入：Drift 为 `TreatmentRecords` / `RecordItems` 表生成的数据类也叫
// `TreatmentRecord` / `RecordItem`（见 app_database.g.dart），与常见业务命名冲突。
import 'package:rehab_app/data/local/app_database.dart' as local;
import 'package:rehab_app/data/remote/api_client.dart';
import 'package:rehab_app/data/remote/record_dto.dart';
import 'package:rehab_app/sync/sync_engine.dart';

/// 治疗记录数据访问（离线优先）。
///
/// 记录是**可离线写的第二类实体**（协议 §3.1：`treatment_record` 与 `appointment`），
/// 且草稿的冲突策略是 `client_wins`（协议 §4.4）——治疗师在床旁刚写的东西
/// 不该被服务端的旧版本盖掉。
// 见 api_client.dart 顶部说明：构造器刻意用「公开参数名 + 私有字段」。
// 条件键（`if (x != null) 'k': x`）是构造可选 API 载荷最清楚的写法。
// ignore_for_file: prefer_initializing_formals, use_null_aware_elements
class RecordRepository {
  RecordRepository({
    required ApiClient client,
    required local.AppDatabase db,
    required SyncEngine sync,
  })  : _client = client,
        _db = db,
        _sync = sync;

  final ApiClient _client;
  final local.AppDatabase _db;
  final SyncEngine _sync;

  // ------------------------------------------------------------------------- //
  // 表单（离线优先：联网时拉一份整包缓存，断网时用缓存）
  // ------------------------------------------------------------------------- //
  static String _formCacheKey(String patientNo, int? mainItemId) =>
      'record_form:$patientNo:${mainItemId ?? 'all'}';

  /// 取记录表单。
  ///
  /// ★ **不自己算"上次值/默认值"**：服务端已经按 5 级带入
  /// （上次值 → 个人选项集 → 科室 → 全局 → 字典默认）填好 `current_value` /
  /// `value_source` / `options_resolved`。客户端重算一遍只会产生分歧。
  ///
  /// ★ [mainItemId] **一旦已经加了治疗项目就必须传**：`response_defs` 是
  /// **按主项目分组**的（实测四组各 8/6/5/8 个，无通用组），而服务端
  /// `normalize_responses` 只用**第一个项目的主项目**做校验。不传的话表单返回
  /// 全部 27 个，治疗师选了别组的反应 → 提交 422「未知的患者反应」——
  /// 而且是填完整张表单之后才发现。传了就只返回该组定义。
  ///
  /// 离线时回落到缓存；两者都没有才抛错。
  Future<({RecordFormData form, bool fromCache})> fetchForm(
    String patientNo, {
    int? mainItemId,
  }) async {
    try {
      final data = await _client.request(kRecordForm, query: {
        'patient_no': patientNo,
        if (mainItemId != null) 'main_item_id': mainItemId,
      });
      final json = Map<String, dynamic>.from(data as Map);
      final form = RecordFormData.fromJson(json);
      await _db.into(_db.refCache).insertOnConflictUpdate(
            local.RefCacheCompanion.insert(
              key: _formCacheKey(patientNo, mainItemId),
              payloadJson: jsonEncode(form.toJson()),
              fetchedAt: DateTime.now().toUtc().toIso8601String(),
            ),
          );
      return (form: form, fromCache: false);
    } on AppError {
      final cached = await readCachedForm(patientNo, mainItemId: mainItemId);
      if (cached == null) rethrow;
      return (form: cached, fromCache: true);
    }
  }

  /// 只读缓存（不带网络请求）。
  Future<RecordFormData?> readCachedForm(String patientNo, {int? mainItemId}) async {
    final row = await (_db.select(_db.refCache)
          ..where((t) => t.key.equals(_formCacheKey(patientNo, mainItemId))))
        .getSingleOrNull();
    if (row == null) return null;
    try {
      return RecordFormData.fromJson(
        Map<String, dynamic>.from(jsonDecode(row.payloadJson) as Map),
      );
    } on FormatException {
      // 缓存坏了不该让整个页面打不开。
      return null;
    }
  }

  // ------------------------------------------------------------------------- //
  // 本地草稿
  // ------------------------------------------------------------------------- //
  /// 本地已有记录的该患者记录（含未推送草稿）。
  Stream<List<local.TreatmentRecord>> watchLocal(String patientNo) {
    return (_db.select(_db.treatmentRecords)
          ..where((t) => t.patientNo.equals(patientNo))
          ..orderBy([
            (t) => OrderingTerm.desc(t.recordDate),
            (t) => OrderingTerm.desc(t.id),
          ]))
        .watch();
  }

  /// 取某患者某日某半日的**未推送草稿**（用于"继续上次没写完的"）。
  Future<local.TreatmentRecord?> findDraft({
    required String patientNo,
    required String recordDate,
    String? sessionPeriod,
  }) async {
    final query = _db.select(_db.treatmentRecords)
      ..where((t) => t.patientNo.equals(patientNo))
      ..where((t) => t.recordDate.equals(recordDate))
      ..where((t) => t.status.equals('draft'))
      ..where((t) => t.syncStatus.equals('pending'));
    if (sessionPeriod != null) {
      query.where((t) => t.sessionPeriod.equals(sessionPeriod));
    }
    return query.getSingleOrNull();
  }

  /// 保存草稿：**先本地 + 入离线队列**（床旁弱网也能写）。
  ///
  /// [existingId] 传本地草稿 id 时为更新；否则新建（用负数占位 id）。
  /// 返回本地 id。
  Future<int> saveDraft({
    required int? existingId,
    required String patientNo,
    required int therapistId,
    required String recordDate,
    required String? sessionPeriod,
    required int? appointmentId,
    required int? durationMin,
    required String? note,
    required PatientResponseDraft response,
    required List<RecordItemDraft> items,
    required String status,
  }) async {
    final id = existingId ?? await _nextNegativeId();
    final uuid = await _uuidFor(existingId) ?? _uuidV4();

    await _db.into(_db.treatmentRecords).insertOnConflictUpdate(
          local.TreatmentRecordsCompanion.insert(
            id: Value(id),
            patientNo: patientNo,
            therapistId: therapistId,
            recordDate: recordDate,
            sessionPeriod: Value(sessionPeriod),
            durationMin: Value(durationMin),
            note: Value(note),
            patientResponseJson:
                Value(response.isEmpty ? null : jsonEncode(response.toJson())),
            status: Value(status),
            appointmentId: Value(appointmentId),
            clientUuid: Value(uuid),
            syncStatus: const Value('pending'),
            pendingItemsJson: Value(jsonEncode(items.map((i) => i.toJson()).toList())),
          ),
        );

    final payload = {
      'patient_no': patientNo,
      'record_date': recordDate,
      if (sessionPeriod != null) 'session_period': sessionPeriod,
      if (appointmentId != null) 'appointment_id': appointmentId,
      if (durationMin != null) 'duration_min': durationMin,
      if (note != null && note.isNotEmpty) 'note': note,
      if (!response.isEmpty) 'patient_response': response.toJson(),
      'items': items.map((i) => i.toJson()).toList(),
      'status': status,
    };

    // 已推送过的记录是 update，本地新建是 insert。
    if (existingId != null && existingId > 0) {
      final row = await (_db.select(_db.treatmentRecords)
            ..where((t) => t.id.equals(existingId)))
          .getSingleOrNull();
      await _sync.enqueueUpdate(
        entity: 'treatment_record',
        clientUuid: uuid,
        payload: payload,
        baseRevision: row?.revision,
      );
    } else {
      await _sync.enqueueInsert(
        entity: 'treatment_record',
        clientUuid: uuid,
        payload: payload,
      );
    }
    return id;
  }

  /// 把本地草稿的明细读回来（用于"继续编辑"）。
  Future<List<RecordItemDraft>> readPendingItems(int recordId) async {
    final row = await (_db.select(_db.treatmentRecords)
          ..where((t) => t.id.equals(recordId)))
        .getSingleOrNull();
    final raw = row?.pendingItemsJson;
    if (raw == null || raw.isEmpty) return const [];
    try {
      final list = jsonDecode(raw) as List;
      return list
          .whereType<Map>()
          .map((e) => RecordItemDraft.fromJson(Map<String, dynamic>.from(e)))
          .toList();
    } on FormatException {
      return const [];
    }
  }

  /// 本地草稿的患者反应。
  Future<PatientResponseDraft> readPendingResponse(int recordId) async {
    final row = await (_db.select(_db.treatmentRecords)
          ..where((t) => t.id.equals(recordId)))
        .getSingleOrNull();
    final raw = row?.patientResponseJson;
    if (raw == null || raw.isEmpty) return PatientResponseDraft();
    try {
      return PatientResponseDraft.fromJson(
        Map<String, dynamic>.from(jsonDecode(raw) as Map),
      );
    } on FormatException {
      return PatientResponseDraft();
    }
  }

  /// 待推送的本地记录条数。
  Future<int> pendingCount() => _sync.pendingCount();

  /// 本地新建记录用负数占位 id（避免与服务端自增 id 撞号）。
  Future<int> _nextNegativeId() async {
    final row = await _db
        .customSelect('SELECT MIN(id) AS m FROM treatment_records WHERE id < 0')
        .getSingleOrNull();
    final minId = (row?.data['m'] as int?) ?? 0;
    return minId == 0 ? -1 : minId - 1;
  }

  Future<String?> _uuidFor(int? id) async {
    if (id == null) return null;
    final row = await (_db.select(_db.treatmentRecords)..where((t) => t.id.equals(id)))
        .getSingleOrNull();
    return row?.clientUuid;
  }

  static String _uuidV4() {
    final rnd = Random.secure();
    final bytes = List<int>.generate(16, (_) => rnd.nextInt(256));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    final hex = bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
    return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-'
        '${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
  }

  /// 该患者在当地日期、半日的记录条数（顶部提示"今天已经记过 N 次"）。
  Future<int> countForDay({
    required String patientNo,
    required String recordDate,
    String? sessionPeriod,
  }) async {
    final row = await _db.customSelect(
      'SELECT COUNT(*) AS n FROM treatment_records'
      ' WHERE patient_no = ? AND record_date = ?'
      "${sessionPeriod != null ? ' AND session_period = ?' : ''}",
      variables: [
        Variable.withString(patientNo),
        Variable.withString(recordDate),
        if (sessionPeriod != null) Variable.withString(sessionPeriod),
      ],
    ).getSingleOrNull();
    return (row?.data['n'] as int?) ?? 0;
  }

  /// 今天（本地日期）该患者已有记录数。
  Future<int> countForToday(String patientNo) => countForDay(
        patientNo: patientNo,
        recordDate: formatDate(DateTime.now()),
      );

  /// 记录明细（已同步的部分）。
  Future<List<local.RecordItem>> itemsOf(int recordId) {
    return (_db.select(_db.recordItems)
          ..where((t) => t.recordId.equals(recordId))
          ..orderBy([(t) => OrderingTerm.asc(t.sort)]))
        .get();
  }
}
