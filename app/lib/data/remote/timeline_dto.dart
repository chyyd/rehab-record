/// 时间轴与汇总的传输模型（**SOAP 纯文本口径**，2026-10-05 改造后）。
///
/// 字段名沿用后端 snake_case（与管理后台、`docs/sync-protocol.md` 同一约定）。
///
/// ★ 与旧模型的区别：记录内容不再是"主项目 / 子项目 / 参数 / 患者反应"表格，
/// 而是服务端在落库时**冻结**的 `rendered_text`（SOAP 纯文本）。
/// 汇总里的 `item_count` / `total_duration_min` / `main_item_counts` /
/// `sub_item_counts` / `session_periods` **全部消失**，换成
/// `record_count` / `patient_count` / `therapist_counts` / `discipline_counts`
/// 与逐条的 SOAP 文本。
// ignore_for_file: use_null_aware_elements
library;

/// 一条记录的公共字段（时间轴项、汇总行、总览项都是它）。
class RecordSummaryRow {
  const RecordSummaryRow({
    required this.recordId,
    required this.recordDate,
    this.patientNo = '',
    this.patientName,
    this.therapistId,
    this.therapistName,
    this.discipline = '',
    this.disciplineName,
    this.kind = 'daily',
    this.kindLabel,
    this.seqNo,
    this.status = 'submitted',
    this.note,
    this.renderedText = '',
    this.isTemporary = false,
  });

  final int recordId;
  final String recordDate;
  final String patientNo;
  final String? patientName;
  final int? therapistId;
  final String? therapistName;

  /// `PT` / `OT` / `ST_SW` / `ST_SP`。
  final String discipline;
  final String? disciplineName;

  /// `initial` / `daily` / `reassessment` / `discharge`。
  final String kind;
  final String? kindLabel;

  final int? seqNo;
  final String status;
  final String? note;

  /// 冻结的 SOAP 纯文本 —— **屏幕与 PDF 显示的是同一份**。
  final String renderedText;

  final bool isTemporary;

  factory RecordSummaryRow.fromJson(Map<String, dynamic> json) {
    // 汇总行用 `record_id`，时间轴/列表项用 `id` —— 两种都兼容。
    final rawId = json['record_id'] ?? json['id'];
    return RecordSummaryRow(
      recordId: rawId is num ? rawId.toInt() : 0,
      recordDate: '${json['record_date'] ?? ''}',
      patientNo: '${json['patient_no'] ?? ''}',
      patientName: json['patient_name'] as String?,
      therapistId: (json['therapist_id'] as num?)?.toInt(),
      therapistName: json['therapist_name'] as String?,
      discipline: '${json['discipline'] ?? ''}',
      disciplineName: json['discipline_name'] as String?,
      kind: '${json['kind'] ?? 'daily'}',
      kindLabel: json['kind_label'] as String?,
      seqNo: (json['seq_no'] as num?)?.toInt(),
      status: '${json['status'] ?? 'submitted'}',
      note: json['note'] as String?,
      renderedText: '${json['rendered_text'] ?? ''}',
      isTemporary: (json['is_temporary'] as num?)?.toInt() == 1 ||
          json['is_temporary'] == true,
    );
  }

  String get statusLabel => switch (status) {
        'draft' => '草稿',
        'submitted' => '已提交',
        'locked' => '已锁定',
        _ => status,
      };

  /// 列表里的一行摘要：跳过标题行取第一段正文（与服务端 `rendered_excerpt` 同口径）。
  String get excerpt {
    for (final line in renderedText.split('\n')) {
      final text = line.trim();
      if (text.isEmpty) continue;
      if (text.startsWith('治疗日期')) continue;
      if (text.contains('：')) {
        return text.length <= 80 ? text : '${text.substring(0, 79)}…';
      }
    }
    return '';
  }
}

/// 时间轴里的一条记录（`TimelineItemOut` = `RecordListItemOut`）。
class TimelineItem {
  const TimelineItem({
    required this.id,
    required this.patientNo,
    required this.therapistId,
    required this.recordDate,
    required this.status,
    this.patientName,
    this.therapistName,
    this.discipline = '',
    this.disciplineName,
    this.kind = 'daily',
    this.kindLabel,
    this.seqNo,
    this.editCount = 0,
    this.renderedText = '',
    this.renderedExcerpt = '',
  });

  final int id;
  final String patientNo;
  final String? patientName;
  final int therapistId;
  final String? therapistName;
  final String recordDate;

  /// `PT` / `OT` / `ST_SW` / `ST_SP`。
  final String discipline;
  final String? disciplineName;

  /// `initial` / `daily` / `reassessment` / `discharge`。
  final String kind;
  final String? kindLabel;

  /// 第几次**日常**记录（评估文书为 null）。
  final int? seqNo;
  final String status;
  final int editCount;

  /// 冻结的 SOAP 纯文本。
  final String renderedText;
  final String renderedExcerpt;

  factory TimelineItem.fromJson(Map<String, dynamic> json) => TimelineItem(
        id: (json['id'] as num).toInt(),
        patientNo: json['patient_no'] as String,
        patientName: json['patient_name'] as String?,
        therapistId: (json['therapist_id'] as num).toInt(),
        therapistName: json['therapist_name'] as String?,
        recordDate: json['record_date'] as String,
        discipline: '${json['discipline'] ?? ''}',
        disciplineName: json['discipline_name'] as String?,
        kind: '${json['kind'] ?? 'daily'}',
        kindLabel: json['kind_label'] as String?,
        seqNo: (json['seq_no'] as num?)?.toInt(),
        status: json['status'] as String? ?? 'draft',
        editCount: (json['edit_count'] as num?)?.toInt() ?? 0,
        renderedText: '${json['rendered_text'] ?? ''}',
        renderedExcerpt: '${json['rendered_excerpt'] ?? ''}',
      );

  String get statusLabel => switch (status) {
        'draft' => '草稿',
        'submitted' => '已提交',
        'locked' => '已锁定',
        _ => status,
      };

  String get displayName => patientName?.isNotEmpty == true ? patientName! : patientNo;

  /// 列表里显示的一行：优先服务端摘要，退化成自己截取。
  String get line {
    if (renderedExcerpt.isNotEmpty) return renderedExcerpt;
    for (final raw in renderedText.split('\n')) {
      final text = raw.trim();
      if (text.isEmpty || text.startsWith('治疗日期')) continue;
      if (text.contains('：')) {
        return text.length <= 80 ? text : '${text.substring(0, 79)}…';
      }
    }
    return '';
  }
}

/// 时间轴一页。
class TimelinePageData {
  const TimelinePageData({
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

  factory TimelinePageData.fromJson(Map<String, dynamic> json) => TimelinePageData(
        items: ((json['items'] as List?) ?? const [])
            .whereType<Map>()
            .map((e) => TimelineItem.fromJson(Map<String, dynamic>.from(e)))
            .toList(),
        total: (json['total'] as num?)?.toInt() ?? 0,
        page: (json['page'] as num?)?.toInt() ?? 1,
        pageSize: (json['page_size'] as num?)?.toInt() ?? 20,
      );
}

/// 汇总总计（`TotalsOut`）。
///
/// 口径：只算 `kind='daily'` 且已提交/已锁定的记录 —— 首评/复评/出院小结是
/// 独立的评估文书，**不占治疗次数**。
class SummaryTotals {
  const SummaryTotals({
    this.recordCount = 0,
    this.patientCount = 0,
    this.therapistCounts = const {},
    this.disciplineCounts = const {},
  });

  /// 治疗次数（日常记录，按记录去重）。
  final int recordCount;
  final int patientCount;
  final Map<String, int> therapistCounts;

  /// 键为大类中文名（运动 / 生活技能 / 吞咽 / 言语）。
  final Map<String, int> disciplineCounts;

  factory SummaryTotals.fromJson(Map<String, dynamic> json) => SummaryTotals(
        recordCount: (json['record_count'] as num?)?.toInt() ?? 0,
        patientCount: (json['patient_count'] as num?)?.toInt() ?? 0,
        therapistCounts: _intMap(json['therapist_counts']),
        disciplineCounts: _intMap(json['discipline_counts']),
      );

  static Map<String, int> _intMap(Object? raw) {
    if (raw is! Map) return const {};
    return raw.map((k, v) => MapEntry('$k', (v as num?)?.toInt() ?? 0));
  }
}

/// 按日期汇总里的一个分组（按治疗师或按患者）。
class SummaryGroup {
  const SummaryGroup({
    required this.key,
    required this.label,
    required this.totals,
    this.rows = const [],
  });

  final String key;
  final String label;
  final SummaryTotals totals;

  /// 该组的记录（含 SOAP 文本）。
  final List<RecordSummaryRow> rows;

  factory SummaryGroup.fromJson(Map<String, dynamic> json) => SummaryGroup(
        key: '${json['key'] ?? ''}',
        label: '${json['label'] ?? json['key'] ?? ''}',
        totals: SummaryTotals.fromJson(
          Map<String, dynamic>.from((json['totals'] as Map?) ?? const {}),
        ),
        rows: ((json['rows'] as List?) ?? const [])
            .whereType<Map>()
            .map((e) => RecordSummaryRow.fromJson(Map<String, dynamic>.from(e)))
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

/// 患者每日汇总里的一天（`PatientDailyRowOut`）。
class PatientDailyDay {
  const PatientDailyDay({
    required this.recordDate,
    this.recordCount = 0,
    this.therapists = const [],
    this.disciplines = const [],
    this.temporary = false,
    this.records = const [],
    this.texts = const [],
  });

  final String recordDate;

  /// 当天的**日常**记录条数（评估文书不计）。
  final int recordCount;

  final List<String> therapists;
  final List<String> disciplines;
  final bool temporary;

  /// 当天所有文书（含首评/复评/出院小结）。
  final List<RecordSummaryRow> records;

  /// 当天各条文书的 SOAP 纯文本（按时间顺序）。
  final List<String> texts;

  factory PatientDailyDay.fromJson(Map<String, dynamic> json) => PatientDailyDay(
        recordDate: json['record_date'] as String,
        recordCount: (json['record_count'] as num?)?.toInt() ?? 0,
        therapists:
            ((json['therapists'] as List?) ?? const []).map((e) => '$e').toList(),
        disciplines:
            ((json['disciplines'] as List?) ?? const []).map((e) => '$e').toList(),
        temporary: json['temporary'] == true,
        records: ((json['records'] as List?) ?? const [])
            .whereType<Map>()
            .map((e) => RecordSummaryRow.fromJson(Map<String, dynamic>.from(e)))
            .toList(),
        texts: ((json['texts'] as List?) ?? const []).map((e) => '$e').toList(),
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
    this.assignedTherapistId,
    this.assignedTherapistName,
  });

  final String inpatientNo;
  final String name;
  final String? diagnosis;
  final String? adminNote;
  final String? status;
  final int? assignedTherapistId;
  final String? assignedTherapistName;

  factory SummaryPatientBrief.fromJson(Map<String, dynamic> json) => SummaryPatientBrief(
        inpatientNo: '${json['inpatient_no']}',
        name: '${json['name']}',
        diagnosis: json['diagnosis'] as String?,
        adminNote: json['admin_note'] as String?,
        status: json['status'] as String?,
        assignedTherapistId: (json['assigned_therapist_id'] as num?)?.toInt(),
        assignedTherapistName: json['assigned_therapist_name'] as String?,
      );
}

/// 按患者每日汇总（`PatientDailySummaryOut`）。
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
  final List<PatientDailyDay> days;
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
            .map((e) => PatientDailyDay.fromJson(Map<String, dynamic>.from(e)))
            .toList(),
        dateFrom: json['date_from'] as String?,
        dateTo: json['date_to'] as String?,
      );
}
