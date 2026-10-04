// 见 api_client.dart 顶部说明：构造器刻意用「公开参数名 + 私有字段」。
// ignore_for_file: prefer_initializing_formals

import 'dart:convert';

import 'package:drift/drift.dart' show Value;

import 'package:rehab_app/core/api_endpoints.dart';
import 'package:rehab_app/data/local/app_database.dart';
import 'package:rehab_app/data/remote/api_client.dart';

/// 患者（App 侧模型，字段名沿用后端 snake_case）。
///
/// 名字带 `View` 后缀是**必需的**：Drift 会为 `Patients` 表生成一个同名的数据类
/// `Patient`（见 `app_database.g.dart`）。若这里也叫 `Patient`，在本文件的
/// 作用域里会**遮蔽**生成的那个，导致 `Patient.fromRow` 找不到 Drift 的行类型
/// （实测报 `Undefined class 'PatientRow'` 与 `List<dynamic>` 返回值错误）。
class PatientView {
  const PatientView({
    required this.inpatientNo,
    required this.name,
    required this.status,
    this.diagnosis,
    this.adminNote,
    this.assignedTherapistId,
    this.visibleTherapistId,
    this.visibilityState,
    required this.revision,
    required this.visible,
  });

  final String inpatientNo;
  final String name;
  final String status;
  final String? diagnosis;

  /// 注意事项（治疗师**只读**，仅管理员能改）。
  final String? adminNote;
  final int? assignedTherapistId;
  final int? visibleTherapistId;
  final String? visibilityState;
  final int revision;

  /// 本地是否仍在可见范围内（已出院患者会从白板消失，但本地不删，见协议 §2）。
  final bool visible;

  bool get isInHospital => status == 'in_hospital';
  bool get isPaused => status == 'paused';
  bool get isDischarged => status == 'discharged';

  /// 从 Drift 行构造。参数类型显式写成生成的 `Patient`。
  static PatientView fromRow(Patient row) => PatientView(
        inpatientNo: row.inpatientNo,
        name: row.name,
        status: row.status,
        diagnosis: row.diagnosis,
        adminNote: row.adminNote,
        assignedTherapistId: row.assignedTherapistId,
        visibleTherapistId: row.visibleTherapistId,
        visibilityState: row.visibilityState,
        revision: row.revision,
        visible: row.visible,
      );
}

/// 患者数据访问（离线优先）。
///
/// ★ **患者不走同步接口**（协议 §1）：`change_log` 里永远不会有 `entity='patient'`，
/// 因为变更日志没有"按人可见性"维度，把患者写进去会导致越权与语义污染。
/// 所以这里用 `GET /api/v1/patients` 分页拉取，并把它做成独立任务
/// （登录后 + 进入前台 + 下拉刷新），与记录/排期的同步解耦。
class PatientRepository {
  PatientRepository({required ApiClient client, required AppDatabase db})
      : _client = client,
        _db = db;

  final ApiClient _client;
  final AppDatabase _db;

  /// 本机一次拉取的患者页大小。
  static const int _pageSize = 100;

  /// 从**本地库**读患者列表（离线可用）。
  ///
  /// [onlyMine] 为 true 时只返回归属自己或未分配的（对应服务端 `scope=mine`/`unassigned`
  /// 的本地近似）；默认返回全部可见患者（白板）。
  Future<List<PatientView>> listLocal({
    bool includeHidden = false,
    int? therapistId,
    bool onlyMine = false,
  }) async {
    final query = _db.select(_db.patients);
    if (!includeHidden) {
      query.where((t) => t.visible.equals(true));
    }
    final rows = await query.get();

    var patients = rows.map(PatientView.fromRow).toList();
    if (onlyMine && therapistId != null) {
      patients = patients
          .where((p) =>
              p.assignedTherapistId == therapistId || p.assignedTherapistId == null)
          .toList();
    }
    // 与服务端一致的排序语义："我的患者优先 → 未分配 → 其他"。
    patients.sort((a, b) => _rank(a, therapistId).compareTo(_rank(b, therapistId)));
    return patients;
  }

  int _rank(PatientView p, int? therapistId) {
    if (therapistId != null && p.assignedTherapistId == therapistId) return 0;
    if (p.assignedTherapistId == null) return 1;
    return 2;
  }

  Future<PatientView?> findByNo(String inpatientNo) async {
    final row = await (_db.select(_db.patients)
          ..where((t) => t.inpatientNo.equals(inpatientNo)))
        .getSingleOrNull();
    return row == null ? null : PatientView.fromRow(row);
  }

  /// 从服务端**分页刷新**患者列表（全科白板：在院 + 暂停）。
  ///
  /// 返回本次同步到的患者数。
  ///
  /// 行为约定（协议 §2）：
  /// - 服务端返回的患者标记 `visible = true`；
  /// - **本地已有、但本次没返回的患者**标记 `visible = false`（软隐藏）——
  ///   典型是"已出院"或"被暂停后从白板移除"。**绝不删除本地行**，
  ///   否则历史治疗记录会失去患者信息。
  Future<int> refreshFromServer({String scope = 'dept'}) async {
    final seen = <String>{};
    var page = 1;

    while (true) {
      final data = await _client.request(
        kPatients,
        query: {'scope': scope, 'page': page, 'page_size': _pageSize},
      ) as Map<String, dynamic>;

      final items = (data['items'] as List?) ?? const [];
      for (final raw in items.whereType<Map>()) {
        final json = Map<String, dynamic>.from(raw);
        final no = json['inpatient_no'] as String;
        seen.add(no);
        await _upsert(json);
      }

      final total = (data['total'] as num?)?.toInt() ?? seen.length;
      if (items.isEmpty || seen.length >= total) break;
      page++;
    }

    // 软隐藏：本次没返回的本地患者标记为不可见（不删除）。
    final now = DateTime.now().toUtc().toIso8601String();
    await _db.customStatement(
      'UPDATE patients SET visible = 0 WHERE inpatient_no NOT IN '
      '(${List.filled(seen.length, '?').join(',')})',
      seen.toList(),
    );
    if (seen.isEmpty) {
      // 一条都没拉到（服务端为空）：全部软隐藏，同样不删。
      await _db.customStatement('UPDATE patients SET visible = 0');
    }
    await _db.into(_db.syncState).insertOnConflictUpdate(
          SyncStateCompanion.insert(key: 'last_patient_sync_at', value: now),
        );
    return seen.length;
  }

  Future<void> _upsert(Map<String, dynamic> json) async {
    await _db.into(_db.patients).insertOnConflictUpdate(
          PatientsCompanion.insert(
            inpatientNo: json['inpatient_no'] as String,
            name: json['name'] as String,
            diagnosis: Value(json['diagnosis'] as String?),
            adminNote: Value(json['admin_note'] as String?),
            assignedTherapistId: Value((json['assigned_therapist_id'] as num?)?.toInt()),
            visibleTherapistId: Value((json['visible_therapist_id'] as num?)?.toInt()),
            visibilityState: Value(json['visibility_state'] as String?),
            // status / fetchedAt 在表定义里带 withDefault，Drift 生成的 companion
            // 字段类型是**非空** `Value<T>`，构造器参数直接收 `T`，不能再包 Value()。
            status: json['status'] as String? ?? 'in_hospital',
            revision: Value((json['revision'] as num?)?.toInt() ?? 0),
            visible: const Value(true),
            fetchedAt: DateTime.now().toUtc().toIso8601String(),
          ),
        );
  }

  /// 上次患者同步时间（用于 UI 显示"数据可能不是最新"）。
  Future<DateTime?> lastSyncedAt() async {
    final row = await (_db.select(_db.syncState)
          ..where((t) => t.key.equals('last_patient_sync_at')))
        .getSingleOrNull();
    if (row == null) return null;
    return DateTime.tryParse(row.value);
  }

  /// 把注意事项里的换行压平，便于列表单行展示。
  static String flattenNote(String? note) {
    if (note == null || note.isEmpty) return '';
    return note.replaceAll(RegExp(r'\s+'), ' ').trim();
  }

  /// 调试用：本地库概要。
  Future<String> debugSummary() async {
    final patients = await _db.select(_db.patients).get();
    return jsonEncode({
      'patients': patients.length,
      'visible': patients.where((p) => p.visible).length,
      'cursor': (await (_db.select(_db.syncState)..where((t) => t.key.equals('last_cursor')))
              .getSingleOrNull())
          ?.value,
    });
  }
}
