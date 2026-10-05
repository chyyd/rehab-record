/// 排期与可排性的传输模型。
///
/// 字段名沿用后端 snake_case（与管理后台、`docs/sync-protocol.md` 同一约定）。
///
// 关闭 use_null_aware_elements：可选用"条件键"表达（`if (x != null) 'k': x`）
// 是构造可选 API 载荷最清楚的写法，改成 `?` 形式反而更难读。
// ignore_for_file: use_null_aware_elements
library;

/// 一条排期。
///
/// **2026-10-03 起半日格子不再互斥**：同一个 `(date, period)` 可以有多条，
/// 所以这里没有"格子被占用"的概念，只有"格子里有几台"。
class Appointment {
  const Appointment({
    required this.id,
    required this.patientNo,
    required this.therapistId,
    required this.date,
    required this.period,
    required this.status,
    this.patientName,
    this.therapistName,
    this.note,
    this.isMine = false,
  });

  final int id;
  final String patientNo;
  final int therapistId;
  final String date;

  /// `am` / `pm`。
  final String period;

  /// `planned` / `arrived` / `in_progress` / `done` / `cancelled` / `no_show` /
  /// `rescheduled`。
  final String status;

  final String? patientName;
  final String? therapistName;
  final String? note;

  /// 是否属于当前登录治疗师（仅用于 UI 区分，不参与权限判断）。
  final bool isMine;

  factory Appointment.fromJson(Map<String, dynamic> json, {int? currentTherapistId}) {
    final therapistId = (json['therapist_id'] as num).toInt();
    return Appointment(
      id: (json['id'] as num).toInt(),
      patientNo: json['patient_no'] as String,
      therapistId: therapistId,
      date: json['date'] as String,
      period: json['period'] as String,
      status: json['status'] as String? ?? 'planned',
      patientName: json['patient_name'] as String?,
      therapistName: json['therapist_name'] as String?,
      note: json['note'] as String?,
      isMine: currentTherapistId != null && therapistId == currentTherapistId,
    );
  }

  String get statusLabel => switch (status) {
        'planned' => '计划',
        'arrived' => '已到',
        'in_progress' => '治疗中',
        'done' => '已完成',
        'cancelled' => '已取消',
        'no_show' => '爽约',
        'rescheduled' => '已改期',
        _ => status,
      };

  /// 取消与改期不占格子、不进汇总。
  bool get isActive => status != 'cancelled' && status != 'rescheduled';
}

/// 一个半日格子的可排性 + 已有内容。
class SlotAvailability {
  const SlotAvailability({
    required this.date,
    required this.period,
    required this.available,
    required this.reasons,
    required this.appointmentCount,
    required this.patients,
    required this.patientAppointments,
  });

  final String date;
  final String period;

  /// 是否可排。**只受休息块与生效请假影响**（格子不互斥，已有排期不影响可排）。
  final bool available;

  /// 不可排原因：`rest_block` / `on_leave`。
  final List<String> reasons;

  final int appointmentCount;

  /// 该治疗师格子里的患者（用于列表展示）。
  final List<SlotPatient> patients;

  /// 指定患者在这些半日的排期（谁在做），仅在请求带 `patient_no` 时非空。
  final List<SlotPatient> patientAppointments;

  factory SlotAvailability.fromJson(Map<String, dynamic> json) => SlotAvailability(
        date: json['date'] as String,
        period: json['period'] as String,
        available: json['available'] == true,
        reasons: ((json['reasons'] as List?) ?? const []).map((e) => '$e').toList(),
        appointmentCount: (json['appointment_count'] as num?)?.toInt() ?? 0,
        patients: _slotPatients(json['patients']),
        patientAppointments: _slotPatients(json['patient_appointments']),
      );

  static List<SlotPatient> _slotPatients(Object? raw) {
    if (raw is! List) return const [];
    return raw
        .whereType<Map>()
        .map((e) => SlotPatient.fromJson(Map<String, dynamic>.from(e)))
        .toList();
  }

  /// 不可排原因的中文说明。
  String get unavailableReasonLabel => switch (reasons) {
        ['rest_block'] => '休息时段',
        ['on_leave'] => '请假中',
        _ when reasons.contains('rest_block') && reasons.contains('on_leave') => '休息且请假',
        _ when reasons.contains('rest_block') => '休息时段',
        _ when reasons.contains('on_leave') => '请假中',
        _ => '',
      };
}

/// 格子里的一位患者（可排性响应里的精简信息）。
class SlotPatient {
  const SlotPatient({required this.patientNo, this.patientName, this.therapistName});

  final String patientNo;
  final String? patientName;
  final String? therapistName;

  factory SlotPatient.fromJson(Map<String, dynamic> json) => SlotPatient(
        patientNo: (json['patient_no'] ?? '') as String,
        patientName: json['patient_name'] as String?,
        therapistName: json['therapist_name'] as String?,
      );

  String get display => patientName?.isNotEmpty == true ? patientName! : patientNo;
}

/// 新建排期时提交的载荷。
class AppointmentDraft {
  const AppointmentDraft({
    required this.patientNo,
    required this.date,
    required this.period,
    this.note,
  });

  final String patientNo;
  final String date;
  final String period;
  final String? note;

  /// 服务端 `SyncChangeIn.payload` 形状。
  Map<String, dynamic> toPayload({int? therapistId}) => {
        'patient_no': patientNo,
        'date': date,
        'period': period,
        if (therapistId != null) 'therapist_id': therapistId,
        'status': 'planned',
        if (note != null && note!.isNotEmpty) 'note': note,
      };
}
