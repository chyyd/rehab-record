import 'dart:convert';
import 'dart:math';

import 'package:drift/drift.dart';

import 'package:rehab_app/core/api_endpoints.dart';
import 'package:rehab_app/core/date_utils.dart';
import 'package:rehab_app/core/error.dart';
// 别名导入：Drift 为 `TreatmentRecords` 表生成的数据类也叫 `TreatmentRecord`
//（见 app_database.g.dart），与业务命名冲突。
import 'package:rehab_app/data/local/app_database.dart' as local;
import 'package:rehab_app/data/remote/api_client.dart';
import 'package:rehab_app/data/remote/record_dto.dart';
import 'package:rehab_app/sync/sync_engine.dart';

/// 记录数据访问（离线优先）。
///
/// 记录是**可离线写的实体**（协议 §3.1）。草稿的冲突策略是 `client_wins`
/// （协议 §4.4）—— 治疗师在床旁刚写的东西不该被服务端的旧版本盖掉。
///
/// ★ 2026-10-05 起记录是 **SOAP 模板驱动**的：本地只需要
/// `discipline` / `kind` / `body_json` / `rendered_text` 四样东西，
/// 没有"明细表"了（`record_items` 已随 schemaVersion 5 删除）。
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

  /// 多选字段"最近用过"的本地记忆上限。
  static const int recentOptionsLimit = 12;

  // ------------------------------------------------------------------------- //
  // 表单（离线优先：联网时拉一份整包缓存，断网时用缓存）
  // ------------------------------------------------------------------------- //
  /// 表单缓存键。
  ///
  /// ★ 必须带上 `discipline` 与 `kind`：它们是**两份内容完全不同**的表单
  ///（PT 运动 58 个疗法 vs 吞咽 4 个；出院小结 vs 日常记录），
  /// 共用一个 key 会互相覆盖 —— 离线时治疗师会看到另一份文书的字段。
  /// `date` 不参与 key（同一天的表单内容一致；不同天由服务端重新算序号）。
  static String formCacheKey(
    String patientNo,
    String discipline, {
    String? kind,
  }) =>
      'record_form:$patientNo:$discipline:${kind ?? 'auto'}';

  /// 取记录表单（`GET /records/form`）。
  ///
  /// [kind] 只在**出院**时显式传（`discharge`）——其余形态由服务端门禁决定：
  /// 缺首评/复评时服务端会把 `kind` 直接给成那份评估文书，并在
  /// `pending_document` 里说明。客户端**不自己判断**该弹哪份文书。
  ///
  /// 离线时回落到缓存；两者都没有才抛错。
  Future<({RecordFormData form, bool fromCache})> fetchForm(
    String patientNo,
    String discipline, {
    String? date,
    String? kind,
  }) async {
    try {
      final data = await _client.request(kRecordForm, query: {
        'patient_no': patientNo,
        'discipline': discipline,
        if (date != null) 'date': date,
        if (kind != null) 'kind': kind,
      });
      final json = Map<String, dynamic>.from(data as Map);
      final form = RecordFormData.fromJson(json);
      await _db.into(_db.refCache).insertOnConflictUpdate(
            local.RefCacheCompanion.insert(
              key: formCacheKey(patientNo, discipline, kind: kind),
              payloadJson: jsonEncode(form.toJson()),
              fetchedAt: DateTime.now().toUtc().toIso8601String(),
            ),
          );
      return (form: form, fromCache: false);
    } on AppError {
      final cached = await readCachedForm(patientNo, discipline, kind: kind);
      if (cached == null) rethrow;
      return (form: cached, fromCache: true);
    }
  }

  /// 只读缓存（不带网络请求）。
  Future<RecordFormData?> readCachedForm(
    String patientNo,
    String discipline, {
    String? kind,
  }) async {
    final row = await (_db.select(_db.refCache)
          ..where((t) => t.key.equals(formCacheKey(patientNo, discipline, kind: kind))))
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
  // 多选字段的"最近用过"（模板里"本次训练项目"有 58 项，靠它才能一点就中）
  // ------------------------------------------------------------------------- //
  static String _recentKey(String fieldKey) => 'recent_options:$fieldKey';

  /// 该字段最近用过的值（**最近的在前**）。
  ///
  /// 只是**排序偏好**，不参与任何校验：界面把它排到选项列表最前面，
  /// 治疗师每天重复做的那几项因此不需要搜索。
  Future<List<String>> recentOptions(String fieldKey) async {
    final row = await (_db.select(_db.refCache)
          ..where((t) => t.key.equals(_recentKey(fieldKey))))
        .getSingleOrNull();
    if (row == null) return const [];
    try {
      final decoded = jsonDecode(row.payloadJson);
      if (decoded is! List) return const [];
      return decoded.map((e) => '$e').toList();
    } on FormatException {
      return const [];
    }
  }

  /// 记下这次用过的值（**最近的在前**，去重后最多 [recentOptionsLimit] 个）。
  ///
  /// ★ 2026-10-05 修 bug：原来写成 `[新值..., ...旧值]`，于是**本次刚用过的排到了最后** ——
  /// 正好与「最近用过排最前」相反，界面把最不可能再用的项顶到 58 项列表的开头。
  /// 现在把本次的值放在最前，旧值里**本次没用到的**按原序接在后面。
  ///
  /// 同一字段做多次治疗时，重复出现的值会被提到最前（MRU 语义）：
  /// 连续两次只勾「偏瘫肢体综合训练」，它就会一直排在搜索区第一位。
  Future<void> rememberOptions(String fieldKey, Iterable<String> used) async {
    final fresh = used.where((e) => e.trim().isNotEmpty).toList();
    if (fresh.isEmpty) return;
    final previous = await recentOptions(fieldKey);
    final merged = [
      ...fresh,
      // 旧值里排除本次已经出现过的（`fresh` 已在最前，再出现就是重复）
      for (final value in previous)
        if (!fresh.contains(value)) value,
    ].take(recentOptionsLimit).toList();
    await _db.into(_db.refCache).insertOnConflictUpdate(
          local.RefCacheCompanion.insert(
            key: _recentKey(fieldKey),
            payloadJson: jsonEncode(merged),
            fetchedAt: DateTime.now().toUtc().toIso8601String(),
          ),
        );
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

  /// 取某条本地记录（继续编辑要靠它把 `body` 读回来）。
  Future<local.TreatmentRecord?> findByLocalId(int recordId) {
    return (_db.select(_db.treatmentRecords)..where((t) => t.id.equals(recordId)))
        .getSingleOrNull();
  }

  /// 该患者某日某大类的**未推送草稿**（离线时"继续上次没写完的"）。
  Future<local.TreatmentRecord?> findLocalDraft({
    required String patientNo,
    required String recordDate,
    required String discipline,
  }) {
    return (_db.select(_db.treatmentRecords)
          ..where((t) => t.patientNo.equals(patientNo))
          ..where((t) => t.recordDate.equals(recordDate))
          ..where((t) => t.discipline.equals(discipline))
          ..where((t) => t.status.equals('draft'))
          ..where((t) => t.syncStatus.equals('pending'))
          ..orderBy([(t) => OrderingTerm.desc(t.id)]))
        .getSingleOrNull();
  }

  /// 把本地草稿的 `body` 读回来。
  Future<Map<String, dynamic>> readLocalBody(int recordId) async {
    final row = await findByLocalId(recordId);
    return decodeBody(row?.bodyJson);
  }

  /// 按**服务端 id** 读一条记录（含 `body` / `status` / `kind` / `discipline`）。
  ///
  /// ★ 2026-10-05 新增：用户要求「患者详情页的治疗记录要可以点进去，**在原始记录上进行修改**」。
  /// 本地只镜像了最近同步过的记录，而患者详情页列的是本地库里的行 ——
  /// 已提交的记录在本地**只存了 `rendered_text` + `body_json`**，
  /// 但"最近同步过"不等于"内容最新"（别人可能改过），所以编辑前**回服务端取一次**。
  ///
  /// 离线时抛 `AppError`，由调用方决定是否降级为"只用本地内容编辑"。
  Future<RecordData> fetchRecord(int recordId) async {
    final data = await _client.request(kRecord(recordId));
    return RecordData.fromJson(Map<String, dynamic>.from(data as Map));
  }

  /// 把 `body_json` 解出来（坏了当空表，不让页面炸掉）。
  static Map<String, dynamic> decodeBody(String? raw) {
    if (raw == null || raw.isEmpty) return {};
    try {
      final decoded = jsonDecode(raw);
      if (decoded is Map) return Map<String, dynamic>.from(decoded);
    } on FormatException {
      return {};
    }
    return {};
  }

  /// 保存（草稿或提交）：**先本地 + 入离线队列**（床旁弱网也能写）。
  ///
  /// [existingId] 传本地记录 id 时为更新；否则新建（用负数占位 id）。
  /// 返回本地 id 与幂等键 `client_uuid`（出院流程要靠它找回服务端 id）。
  Future<({int localId, String clientUuid})> save({
    required int? existingId,
    required String patientNo,
    required int therapistId,
    required String recordDate,
    required String discipline,
    required String kind,
    required Map<String, dynamic> body,
    required String status,
    String? renderedText,
    String? note,
  }) async {
    final id = existingId ?? await _nextNegativeId();
    final uuid = await _uuidFor(existingId) ?? _uuidV4();

    await _db.into(_db.treatmentRecords).insertOnConflictUpdate(
          local.TreatmentRecordsCompanion.insert(
            id: Value(id),
            patientNo: patientNo,
            therapistId: therapistId,
            recordDate: recordDate,
            discipline: discipline,
            kind: kind,
            bodyJson: Value(jsonEncode(body)),
            // 本地先存一份**预览**文本（由编辑器按模板字段拼），
            // 推送成功后服务端返回的正式 `rendered_text` 会覆盖它。
            renderedText: Value(renderedText ?? ''),
            note: Value(note),
            status: Value(status),
            clientUuid: Value(uuid),
            syncStatus: const Value('pending'),
          ),
        );

    final payload = {
      'patient_no': patientNo,
      'record_date': recordDate,
      'discipline': discipline,
      'kind': kind,
      'body': body,
      'status': status,
      if (note != null && note.isNotEmpty) 'note': note,
    };

    // 已推送过的记录是 update，本地新建是 insert。
    if (existingId != null && existingId > 0) {
      final row = await findByLocalId(existingId);
      // ★ 2026-10-05：`base_revision` **只在可信时带上**（即 > 0）。
      //
      // 为什么不能带 0：乐观锁的语义是"我基于第 N 版改的"。本地 `revision == 0`
      // 意味着这份基线**不可信**（这条记录在服务端已经存在——它有正数 id——
      // 所以服务端那版至少是 1）。带 0 上去必然对不上，服务端只能回一个含糊的
      // `server_status=submitted`，治疗师看到的就是"一保存就冲突"。
      //
      // 改成本地 0 时**不带基线**：服务端会明确回 `missing_base_revision` +
      // **真实的 `server_revision`**，而"保留我的"正是用那个值一步对齐基线
      //（见 `ConflictController.keepMine`）。把一个说不清的冲突，
      // 换成一个能被正确处理、并且能自愈的冲突。
      final base = (row?.revision ?? 0) > 0 ? row!.revision : null;
      await _sync.enqueueUpdate(
        entity: 'treatment_record',
        clientUuid: uuid,
        payload: payload,
        baseRevision: base,
      );
    } else {
      await _sync.enqueueInsert(
        entity: 'treatment_record',
        clientUuid: uuid,
        payload: payload,
      );
    }
    return (localId: id, clientUuid: uuid);
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
    final row = await findByLocalId(id);
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

  /// 该患者当天该大类已记了几条（含未推送草稿）。
  ///
  /// 服务端规则是"同一天同一大类**至多 2 条**"（用户 2026-10-05 明确要求），
  /// 界面用它提前提示，而不是等 409。
  Future<int> countForDay({
    required String patientNo,
    required String recordDate,
    required String discipline,
  }) async {
    final row = await _db.customSelect(
      'SELECT COUNT(*) AS n FROM treatment_records'
      ' WHERE patient_no = ? AND record_date = ? AND discipline = ?',
      variables: [
        Variable.withString(patientNo),
        Variable.withString(recordDate),
        Variable.withString(discipline),
      ],
    ).getSingleOrNull();
    return (row?.data['n'] as int?) ?? 0;
  }

  /// 今天（本地日期）该患者在该大类已有记录数。
  Future<int> countForToday(String patientNo, String discipline) => countForDay(
        patientNo: patientNo,
        recordDate: formatDate(DateTime.now()),
        discipline: discipline,
      );
}
