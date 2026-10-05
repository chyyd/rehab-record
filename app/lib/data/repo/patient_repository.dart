// 见 api_client.dart 顶部说明：构造器刻意用「公开参数名 + 私有字段」。
// ignore_for_file: prefer_initializing_formals

import 'dart:convert';

import 'package:drift/drift.dart' show Selectable, TableUpdateQuery, Value, Variable;

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

  /// 2026-10-05：`visibilityState` 字段**已删除**。服务端那个
  /// `visibility_state` 随临时指派删除后恒为 `'assigned'`（可见归属直接等于原归属），
  /// 镜像一个常量没有意义；本地库 schemaVersion 3 → 4 已把该列删掉。
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
    final rows = await _visibleQuery(includeHidden: includeHidden).get();
    final treated = await _lastTreatedQuery(therapistId: therapistId).get();
    return _shape(
      rows,
      therapistId: therapistId,
      onlyMine: onlyMine,
      lastTreated: _index(treated),
    );
  }

  /// **响应式**版本：本地库一变就重新发射（患者或治疗记录变动都算）。
  ///
  /// ★ 必须用它而不是 [listLocal]：登录后的首次同步是后台写的，
  /// 一次性快照不会因为落库而重建 —— 实测表现为"同步成功但界面一直空列表，
  /// 除非手动下拉刷新"。床旁场景下这等于看不到患者。
  ///
  /// ★ 排序要同时看**治疗记录**：2026-10-05 起患者列表按"我最近一次已提交治疗"
  /// 排（与服务端 `v_patient_last_treated` 同一语义）。所以订阅的是
  /// `tableUpdates`（两张表任一变动都会触发）而不是单表查询流 ——
  /// 只观察 `patients` 的话，刚提交一条记录后列表顺序不会变，
  /// 而"接着记今天做过的患者"正是这个排序存在的理由。
  Stream<List<PatientView>> watchLocal({
    bool includeHidden = false,
    int? therapistId,
    bool onlyMine = false,
  }) {
    // 排序同时依赖 `patients` 与 `treatment_records`，所以两张表都要观察：
    // 只订阅单表查询流的话，刚提交一条记录后列表顺序不会变 ——
    // 而"接着记今天做过的患者"正是这个排序存在的理由。
    final query = TableUpdateQuery.allOf([
      TableUpdateQuery.onTable(_db.patients),
      TableUpdateQuery.onTable(_db.treatmentRecords),
    ]);
    // ★ 订阅时必须**先立刻发射一帧当前快照**：`tableUpdates` 只在表被写入时发事件
    // （drift `DatabaseConnectionUser.tableUpdates` 的语义），而它替换掉的
    // `select().watch()` 是"订阅即发射"的。少了这一帧，"启动后没有任何写入"
    //（例如完全离线、本地库已是最新）时列表会一直空着 —— 正是本文件开头
    // 记录的那个缺陷在离线场景下的翻版（`patient_repository_test.dart`
    // "落库后自动发射" 那条用例守的就是它）。
    return Stream<void>.multi((controller) {
      controller.add(null);
      final sub = _db.tableUpdates(query).listen(
            (_) => controller.add(null),
            onError: controller.addError,
            onDone: controller.close,
          );
      controller.onCancel = sub.cancel;
    }, isBroadcast: true)
        .asyncMap((_) async => listLocal(
              includeHidden: includeHidden,
              therapistId: therapistId,
              onlyMine: onlyMine,
            ))
        .distinct(_sameRows);
  }

  /// 只有真的"内容或顺序变了"才发射，避免无谓重建。
  bool _sameRows(List<PatientView> a, List<PatientView> b) {
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (a[i].inpatientNo != b[i].inpatientNo) return false;
    }
    return true;
  }

  Selectable<Patient> _visibleQuery({required bool includeHidden}) {
    final query = _db.select(_db.patients);
    if (!includeHidden) {
      query.where((t) => t.visible.equals(true));
    }
    return query;
  }

  /// 「我最近一次已提交治疗」的日期（与服务端 `v_patient_last_treated` 同口径）。
  ///
  /// 只算 `status = 'submitted'`：草稿不算，否则"写了一半没提交"会把患者顶到最前，
  /// 而那条记录在汇总/时间轴里都还不存在，看起来像系统错乱。
  Selectable<LastTreatedRow> _lastTreatedQuery({required int? therapistId}) {
    return _db.customSelect(
      'SELECT patient_no AS patient_no, MAX(record_date) AS last_date'
      ' FROM treatment_records'
      " WHERE status = 'submitted'"
      '${therapistId == null ? '' : ' AND therapist_id = ?'}'
      ' GROUP BY patient_no',
      variables: [if (therapistId != null) Variable.withInt(therapistId)],
      readsFrom: {_db.treatmentRecords},
    ).map(
      (row) => LastTreatedRow(
        patientNo: row.read<String>('patient_no'),
        lastDate: row.read<String>('last_date'),
      ),
    );
  }

  Map<String, String> _index(List<LastTreatedRow> rows) =>
      {for (final r in rows) r.patientNo: r.lastDate};

  List<PatientView> _shape(
    List<Patient> rows, {
    required int? therapistId,
    required bool onlyMine,
    required Map<String, String> lastTreated,
  }) {
    var patients = rows.map(PatientView.fromRow).toList();
    if (onlyMine && therapistId != null) {
      patients = patients
          .where((p) =>
              p.assignedTherapistId == therapistId || p.assignedTherapistId == null)
          .toList();
    }
    // 与服务端一致的排序语义：
    //   我的患者优先 → 未分配 → 其他；组内按"我最近一次已提交治疗"**降序**
    //   （从没治过的排最后）。
    //
    // 为什么组内是"最近治疗的"而不是"下一个排期的"：本系统不做排班，
    // 治疗师打开列表是为了**接着记今天做过的患者**，所以"我刚治过谁"才是正确依据。
    patients.sort((a, b) {
      final byRank = _rank(a, therapistId).compareTo(_rank(b, therapistId));
      if (byRank != 0) return byRank;
      final aDate = lastTreated[a.inpatientNo];
      final bDate = lastTreated[b.inpatientNo];
      if (aDate == null && bDate == null) {
        return a.inpatientNo.compareTo(b.inpatientNo);
      }
      if (aDate == null) return 1; // 没治过的排后面
      if (bDate == null) return -1;
      final byDate = bDate.compareTo(aDate); // 降序：最近的在前
      if (byDate != 0) return byDate;
      return a.inpatientNo.compareTo(b.inpatientNo);
    });
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
            // 服务端仍会回 `visibility_state`，但它是恒为 'assigned' 的兼容字段，
            // App 本地不再镜像它（schemaVersion 4 已删列），这里刻意不读。
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

/// 「某患者最近一次已提交治疗的日期」的一行。
///
/// 与服务端视图 `v_patient_last_treated` 同口径：只算 `status = 'submitted'`。
/// 做成独立类型而不是元组：Drift 的 `customSelect(...).map(...)` 需要能构造的类，
/// 而且排序逻辑读起来更清楚。
class LastTreatedRow {
  const LastTreatedRow({required this.patientNo, required this.lastDate});

  final String patientNo;

  /// `YYYY-MM-DD`（本地墙钟日期，与服务端一致）。
  final String lastDate;
}
