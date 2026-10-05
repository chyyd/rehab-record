/// 时间轴与汇总的传输模型。
///
/// 字段名沿用后端 snake_case（与管理后台、`docs/sync-protocol.md` 同一约定）。
// ignore_for_file: use_null_aware_elements
library;

/// 时间轴里的一条记录。
///
/// 时间轴走**服务端只读接口**（`GET /timeline`）而不是本地库：它是"全科协作视图"，
/// 需要看到别人写的记录，而本地库只镜像了自己同步过的部分。
class TimelineItem {
  const TimelineItem({
    required this.id,
    required this.patientNo,
    required this.therapistId,
    required this.recordDate,
    required this.status,
    this.patientName,
    this.therapistName,
    this.sessionPeriod,
    this.seqNo,
    this.editCount = 0,
    this.itemCount = 0,
    this.mainItemNames = const [],
  });

  final int id;
  final String patientNo;
  final String? patientName;
  final int therapistId;
  final String? therapistName;
  final String recordDate;
  final String? sessionPeriod;
  final int? seqNo;
  final String status;
  final int editCount;
  final int itemCount;

  /// 这条记录涉及的主项目名（服务端聚合好的，供列表一眼看出做了什么）。
  final List<String> mainItemNames;

  factory TimelineItem.fromJson(Map<String, dynamic> json) => TimelineItem(
        id: (json['id'] as num).toInt(),
        patientNo: json['patient_no'] as String,
        patientName: json['patient_name'] as String?,
        therapistId: (json['therapist_id'] as num).toInt(),
        therapistName: json['therapist_name'] as String?,
        recordDate: json['record_date'] as String,
        sessionPeriod: json['session_period'] as String?,
        seqNo: (json['seq_no'] as num?)?.toInt(),
        status: json['status'] as String? ?? 'draft',
        editCount: (json['edit_count'] as num?)?.toInt() ?? 0,
        itemCount: (json['item_count'] as num?)?.toInt() ?? 0,
        mainItemNames:
            ((json['main_item_names'] as List?) ?? const []).map((e) => '$e').toList(),
      );

  String get statusLabel => switch (status) {
        'draft' => '草稿',
        'submitted' => '已提交',
        'locked' => '已锁定',
        _ => status,
      };

  String get displayName => patientName?.isNotEmpty == true ? patientName! : patientNo;
}

/// 时间轴一页。
class TimelinePage {
  const TimelinePage({
    required this.items,
    required this.total,
    required this.page,
    required this.pageSize,
  });

  final List<TimelineItem> items;
  final int total;
  final int page;
  final int pageSize;

  bool get hasMore => page * pageSize < total;

  factory TimelinePage.fromJson(Map<String, dynamic> json) => TimelinePage(
        items: ((json['items'] as List?) ?? const [])
            .whereType<Map>()
            .map((e) => TimelineItem.fromJson(Map<String, dynamic>.from(e)))
            .toList(),
        total: (json['total'] as num?)?.toInt() ?? 0,
        page: (json['page'] as num?)?.toInt() ?? 1,
        pageSize: (json['page_size'] as num?)?.toInt() ?? 20,
      );
}

/// 汇总的总计行（`TotalsOut`）。
class SummaryTotals {
  const SummaryTotals({
    this.recordCount = 0,
    this.itemCount = 0,
    this.totalDurationMin = 0,
    this.patientCount = 0,
    this.mainItemCounts = const {},
    this.subItemCounts = const {},
    this.therapistCounts = const {},
  });

  final int recordCount;
  final int itemCount;
  final int totalDurationMin;
  final int patientCount;

  /// 键为名称、值为条数（服务端已按名称聚合）。
  final Map<String, int> mainItemCounts;
  final Map<String, int> subItemCounts;
  final Map<String, int> therapistCounts;

  factory SummaryTotals.fromJson(Map<String, dynamic> json) => SummaryTotals(
        recordCount: (json['record_count'] as num?)?.toInt() ?? 0,
        itemCount: (json['item_count'] as num?)?.toInt() ?? 0,
        totalDurationMin: (json['total_duration_min'] as num?)?.toInt() ?? 0,
        patientCount: (json['patient_count'] as num?)?.toInt() ?? 0,
        mainItemCounts: _intMap(json['main_item_counts']),
        subItemCounts: _intMap(json['sub_item_counts']),
        therapistCounts: _intMap(json['therapist_counts']),
      );

  static Map<String, int> _intMap(Object? raw) {
    if (raw is! Map) return const {};
    return raw.map((k, v) => MapEntry('$k', (v as num?)?.toInt() ?? 0));
  }

  /// `1 小时 20 分` 这类可读时长。
  String get durationLabel {
    if (totalDurationMin <= 0) return '0 分钟';
    final h = totalDurationMin ~/ 60;
    final m = totalDurationMin % 60;
    if (h == 0) return '$m 分钟';
    if (m == 0) return '$h 小时';
    return '$h 小时 $m 分';
  }
}

/// 按日期汇总里的一个分组（按治疗师或按患者）。
class SummaryGroup {
  const SummaryGroup({
    required this.key,
    required this.label,
    required this.totals,
    this.patientNos = const [],
  });

  /// 分组键（治疗师名或患者住院号）。
  final String key;
  final String label;
  final SummaryTotals totals;

  /// 该组涉及的患者住院号（按患者分组时是自己）。
  final List<String> patientNos;

  factory SummaryGroup.fromJson(Map<String, dynamic> json) => SummaryGroup(
        key: '${json['key'] ?? json['label'] ?? ''}',
        label: '${json['label'] ?? json['key'] ?? ''}',
        totals: SummaryTotals.fromJson(
          Map<String, dynamic>.from((json['totals'] as Map?) ?? const {}),
        ),
        patientNos: ((json['patient_nos'] as List?) ?? const [])
            .map((e) => '$e')
            .toList(),
      );
}

/// 按日期汇总。
class DateSummary {
  const DateSummary({
    required this.date,
    required this.groupBy,
    required this.totals,
    required this.groups,
  });

  final String date;

  /// `therapist` / `patient`。
  final String groupBy;

  final SummaryTotals totals;
  final List<SummaryGroup> groups;

  factory DateSummary.fromJson(Map<String, dynamic> json) => DateSummary(
        date: json['date'] as String,
        groupBy: json['group_by'] as String? ?? 'therapist',
        totals: SummaryTotals.fromJson(
          Map<String, dynamic>.from((json['totals'] as Map?) ?? const {}),
        ),
        groups: ((json['groups'] as List?) ?? const [])
            .whereType<Map>()
            .map((e) => SummaryGroup.fromJson(Map<String, dynamic>.from(e)))
            .toList(),
      );
}

/// 患者每日汇总里的一天。
class PatientDailyRow {
  const PatientDailyRow({
    required this.recordDate,
    this.sessionPeriods = const [],
    this.therapists = const [],
    this.mainItems = const [],
    this.subItems = const [],
    this.params = const [],
    this.responses = const [],
    this.notes = const [],
    this.durationMin = 0,
    this.temporary = false,
  });

  final String recordDate;
  final List<String> sessionPeriods;
  final List<String> therapists;
  final List<String> mainItems;
  final List<String> subItems;
  final List<String> params;
  final List<String> responses;
  final List<String> notes;
  final int durationMin;

  /// 是否含"临时治疗"（记录人 ≠ 患者归属人）。
  final bool temporary;

  factory PatientDailyRow.fromJson(Map<String, dynamic> json) => PatientDailyRow(
        recordDate: json['record_date'] as String,
        sessionPeriods:
            ((json['session_periods'] as List?) ?? const []).map((e) => '$e').toList(),
        therapists:
            ((json['therapists'] as List?) ?? const []).map((e) => '$e').toList(),
        mainItems: ((json['main_items'] as List?) ?? const []).map((e) => '$e').toList(),
        subItems: ((json['sub_items'] as List?) ?? const []).map((e) => '$e').toList(),
        params: ((json['params'] as List?) ?? const []).map((e) => '$e').toList(),
        responses:
            ((json['responses'] as List?) ?? const []).map((e) => '$e').toList(),
        notes: ((json['notes'] as List?) ?? const []).map((e) => '$e').toList(),
        durationMin: (json['duration_min'] as num?)?.toInt() ?? 0,
        temporary: json['temporary'] == true,
      );
}

/// 患者简要信息（汇总响应里带的）。
class SummaryPatientBrief {
  const SummaryPatientBrief({
    required this.inpatientNo,
    required this.name,
    this.diagnosis,
    this.adminNote,
    this.status,
  });

  final String inpatientNo;
  final String name;
  final String? diagnosis;
  final String? adminNote;
  final String? status;

  factory SummaryPatientBrief.fromJson(Map<String, dynamic> json) => SummaryPatientBrief(
        inpatientNo: '${json['inpatient_no']}',
        name: '${json['name']}',
        diagnosis: json['diagnosis'] as String?,
        adminNote: json['admin_note'] as String?,
        status: json['status'] as String?,
      );
}

/// 按患者每日汇总。
class PatientDailySummary {
  const PatientDailySummary({
    required this.patient,
    required this.totals,
    required this.days,
    this.dateFrom,
    this.dateTo,
  });

  final SummaryPatientBrief patient;
  final SummaryTotals totals;
  final List<PatientDailyRow> days;
  final String? dateFrom;
  final String? dateTo;

  factory PatientDailySummary.fromJson(Map<String, dynamic> json) => PatientDailySummary(
        patient: SummaryPatientBrief.fromJson(
          Map<String, dynamic>.from((json['patient'] as Map?) ?? const {}),
        ),
        totals: SummaryTotals.fromJson(
          Map<String, dynamic>.from((json['totals'] as Map?) ?? const {}),
        ),
        days: ((json['days'] as List?) ?? const [])
            .whereType<Map>()
            .map((e) => PatientDailyRow.fromJson(Map<String, dynamic>.from(e)))
            .toList(),
        dateFrom: json['date_from'] as String?,
        dateTo: json['date_to'] as String?,
      );
}
