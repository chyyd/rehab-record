import 'dart:math';

// 需要**完整导入** drift（不能用 `show ...`）：`isBiggerOrEqualValue` 等比较方法是
// `ComparableExpr` 上的**扩展方法**，少 `show` 一个名字就报 "method isn't defined"
// （实测踩到）。`OrderingTerm` / `Variable` 也都在这一层。
import 'package:drift/drift.dart';

import 'package:rehab_app/core/api_endpoints.dart';
import 'package:rehab_app/data/local/app_database.dart';
import 'package:rehab_app/data/remote/api_client.dart';
// 别名导入：Drift 为 `Appointments` 表生成的数据类也叫 `Appointment`（见 app_database.g.dart），
// 直接 import 会与本文件的排期 DTO 撞名（与 `Patient` 同一个坑）。
import 'package:rehab_app/data/remote/schedule_dto.dart' as dto;
import 'package:rehab_app/sync/sync_engine.dart';

/// 排期数据访问（离线优先）。
///
/// 与患者不同，**排期走同步通道**（协议 §3.1：可离线写的就是 `treatment_record`
/// 与 `appointment`）。因此：
///  - 读：先给本地（离线可用），联网时从 `GET /schedule` 刷新；
///  - 写：**先写本地 + 入队**，再由 [SyncEngine] 推送（弱网也能排班）。
// 见 api_client.dart 顶部说明：构造器刻意用「公开参数名 + 私有字段」。
// 条件键（`if (x != null) 'k': x`）是构造可选 API 载荷最清楚的写法。
// ignore_for_file: prefer_initializing_formals, use_null_aware_elements
class ScheduleRepository {
  ScheduleRepository({
    required ApiClient client,
    required AppDatabase db,
    required SyncEngine sync,
  })  : _client = client,
        _db = db,
        _sync = sync;

  final ApiClient _client;
  final AppDatabase _db;
  final SyncEngine _sync;

  // ------------------------------------------------------------------------- //
  // 读
  // ------------------------------------------------------------------------- //
  /// 本地排期（离线可用）。[therapistId] 为空表示全部治疗师。
  Stream<List<dto.Appointment>> watchLocal({
    required String dateFrom,
    required String dateTo,
    int? therapistId,
    bool includeInactive = false,
  }) {
    final query = _db.select(_db.appointments)
      ..where((t) => t.date.isBiggerOrEqualValue(dateFrom))
      ..where((t) => t.date.isSmallerOrEqualValue(dateTo));
    if (therapistId != null) {
      query.where((t) => t.therapistId.equals(therapistId));
    }
    if (!includeInactive) {
      query.where((t) => t.status.isNotIn(const ['cancelled', 'rescheduled']));
    }
    query.orderBy([
      (t) => OrderingTerm.asc(t.date),
      (t) => OrderingTerm.asc(t.period),
    ]);

    return query.watch().map((rows) => rows.map(_toDto).toList());
  }

  dto.Appointment _toDto(Appointment row) => dto.Appointment(
        id: row.id,
        patientNo: row.patientNo,
        therapistId: row.therapistId,
        date: row.date,
        period: row.period,
        status: row.status,
        note: row.note,
      );

  /// 从服务端刷新一个日期范围的排期。
  ///
  /// 返回条数。服务端的 `/schedule` 默认返回**全科**（互相知道谁在哪，
  /// 见 `api/v1/schedule.py` 的 `_require_can_view_schedule`），所以一次就能拿到全貌。
  Future<int> refreshFromServer({
    required String dateFrom,
    required String dateTo,
    int? therapistId,
  }) async {
    final data = await _client.request(
      kSchedule,
      query: {
        'from': dateFrom,
        'to': dateTo,
        if (therapistId != null) 'therapist_id': therapistId,
      },
    );
    final items = (data as List?) ?? const [];
    for (final raw in items.whereType<Map>()) {
      await upsertFromServer(Map<String, dynamic>.from(raw));
    }
    return items.length;
  }

  /// 把服务端返回的一条排期落入本地（幂等 upsert）。
  Future<void> upsertFromServer(Map<String, dynamic> json) async {
    final id = (json['id'] as num).toInt();
    await _db.into(_db.appointments).insertOnConflictUpdate(
          AppointmentsCompanion.insert(
            id: Value(id),
            patientNo: json['patient_no'] as String,
            therapistId: (json['therapist_id'] as num).toInt(),
            date: json['date'] as String,
            period: json['period'] as String,
            status: Value(json['status'] as String? ?? 'planned'),
            note: Value(json['note'] as String?),
            revision: Value((json['revision'] as num?)?.toInt() ?? 0),
            syncStatus: const Value('synced'),
          ),
        );
  }

  /// 可排性查询（含格子内已有排期）。
  Future<List<dto.SlotAvailability>> fetchAvailability({
    required String dateFrom,
    required String dateTo,
    int? therapistId,
    String? patientNo,
  }) async {
    final data = await _client.request(
      kScheduleAvailability,
      query: {
        'from': dateFrom,
        'to': dateTo,
        if (therapistId != null) 'therapist_id': therapistId,
        if (patientNo != null) 'patient_no': patientNo,
      },
    );
    final list = (data as List?) ?? const [];
    return list
        .whereType<Map>()
        .map((e) => dto.SlotAvailability.fromJson(Map<String, dynamic>.from(e)))
        .toList();
  }

  // ------------------------------------------------------------------------- //
  // 写（离线优先：先本地入队，联网后推送）
  // ------------------------------------------------------------------------- //
  /// 新建排期：**先写本地并入队**，返回本地临时 id。
  ///
  /// 本地 id 用**负数**占位，以免与服务端自增 id 撞号；推送成功后再回写真实 id
  /// （`SyncEngine` 负责把 revision/sync_status 落回）。
  Future<int> createLocal(dto.AppointmentDraft draft, {required int therapistId}) async {
    final localId = await _nextNegativeId();
    final uuid = _uuidV4();

    await _db.into(_db.appointments).insert(
          AppointmentsCompanion.insert(
            id: Value(localId),
            patientNo: draft.patientNo,
            therapistId: therapistId,
            date: draft.date,
            period: draft.period,
            status: const Value('planned'),
            note: Value(draft.note),
            clientUuid: Value(uuid),
            syncStatus: const Value('pending'),
          ),
        );

    await _sync.enqueueInsert(
      entity: 'appointment',
      clientUuid: uuid,
      payload: draft.toPayload(therapistId: therapistId),
    );
    return localId;
  }

  /// 取消排期：本地置为 `cancelled` 并入队。
  Future<void> cancelLocal(int appointmentId) async {
    final row = await (_db.select(_db.appointments)
          ..where((t) => t.id.equals(appointmentId)))
        .getSingleOrNull();
    if (row == null) return;

    await (_db.update(_db.appointments)..where((t) => t.id.equals(appointmentId)))
        .write(const AppointmentsCompanion(
      status: Value('cancelled'),
      syncStatus: Value('pending'),
    ));

    // 未同步过的本地新建（负 id）没法按 id 让服务端取消，它的 uuid 还在队列里，
    // 属于"取消了还没上传的新排期"——这里只更新本地状态，推送时由服务端按 uuid 落库。
    if (appointmentId < 0) return;

    final uuid = row.clientUuid ?? _uuidV4();
    if (row.clientUuid == null) {
      await (_db.update(_db.appointments)..where((t) => t.id.equals(appointmentId)))
          .write(AppointmentsCompanion(clientUuid: Value(uuid)));
    }
    await _sync.enqueueUpdate(
      entity: 'appointment',
      clientUuid: uuid,
      payload: {
        'patient_no': row.patientNo,
        'date': row.date,
        'period': row.period,
        'status': 'cancelled',
      },
      baseRevision: row.revision,
    );
  }

  /// 本地还没有真实 id 的行，用"当前最小负 id − 1"继续往下占。
  Future<int> _nextNegativeId() async {
    final row = await _db
        .customSelect('SELECT MIN(id) AS m FROM appointments WHERE id < 0')
        .getSingleOrNull();
    final minId = (row?.data['m'] as int?) ?? 0;
    return minId == 0 ? -1 : minId - 1;
  }

  /// 生成 UUIDv4（不引第三方依赖：只在本地生成、服务端只当字符串键用）。
  static String _uuidV4() {
    final rnd = Random.secure();
    final bytes = List<int>.generate(16, (_) => rnd.nextInt(256));
    bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
    bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 10
    final hex = bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
    return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-'
        '${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
  }

  /// 本地某半天已有多少台（用于格子角标）。
  Future<int> localCountIn(String date, String period, {int? therapistId}) async {
    final row = await _db.customSelect(
      'SELECT COUNT(*) AS n FROM appointments'
      ' WHERE date = ? AND period = ? AND status NOT IN (\'cancelled\', \'rescheduled\')'
      '${therapistId != null ? ' AND therapist_id = ?' : ''}',
      variables: [
        Variable.withString(date),
        Variable.withString(period),
        if (therapistId != null) Variable.withInt(therapistId),
      ],
    ).getSingleOrNull();
    return (row?.data['n'] as int?) ?? 0;
  }
}
