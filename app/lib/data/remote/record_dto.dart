/// 治疗记录的传输模型（**SOAP 模板驱动**，迁移 011 之后的新契约）。
///
/// 字段名沿用后端 snake_case（与管理后台、`docs/sync-protocol.md` 同一约定）。
///
/// ★ 与旧模型的区别（2026-10-05 脊柱级改造）：
///  - **没有**字典树 / 子项目 / 参数 / 选项集 / 患者反应 —— 那些表已随迁移 011/012 删除；
///  - 记录页的数据源只有一个：`GET /api/v1/records/form`，它直接返回
///    「这次该填哪份文书 + 四段字段定义 + 预填值 + 已存在的那条」；
///  - 记录内容是一个扁平的 `body`：`{field_key: value}`，键就是模板里的 `key`；
///  - 展示用**服务端冻结的 SOAP 纯文本** `rendered_text`，客户端不再拼表格。
///
/// ★ 客户端**不自己算**"该填什么/预填什么"：`kind`（含"缺评估文书时先弹那份"）、
/// `prefill`、`prefill_source`、`next_seq`、`sessions_until_reassessment`
/// 全部由服务端算好。客户端重算一遍只会与服务端分歧。
// ignore_for_file: use_null_aware_elements
library;

/// SOAP 里的一个字段定义（模板 `soap[].fields[]` 的原样透传）。
///
/// `type` 只有四种：`single`（单选 chip）/ `multi`（多选 chip）/
/// `number`（数值 + `unit`）/ `text`（多行文本）。
class SoapField {
  const SoapField({
    required this.key,
    required this.type,
    required this.label,
    this.options = const [],
    this.required = false,
    this.unit,
    this.hint,
    this.allowOther = false,
    this.auto = false,
  });

  /// 提交时 `body` 的键。
  final String key;

  /// `single` / `multi` / `number` / `text`。
  final String type;

  /// 中文标签（渲染与 422 的 `details.missing` 都用它）。
  final String label;

  /// `single` / `multi` 的候选项（服务端已把 `options_source` 展开成真实清单，
  /// 例如把 `therapy_options` 展开成该大类的 58 个疗法名）。
  final List<String> options;

  final bool required;

  /// `number` 的单位（如 `分` / `s` / `级`）。
  final String? unit;

  /// `text` 的输入提示（placeholder）。
  final String? hint;

  /// 允许"其他"自由输入 —— 有它时 `single`/`multi` 也允许不在 `options` 里的值。
  final bool allowOther;

  /// 自动生成的字段（如出院小结的「治疗过程汇总」）：只读，由服务端算好。
  final bool auto;

  bool get isSingle => type == 'single';
  bool get isMulti => type == 'multi';
  bool get isNumber => type == 'number';

  /// 未知类型一律按文本处理（服务端将来加类型时至少不崩、不至于丢数据）。
  bool get isText => !isSingle && !isMulti && !isNumber;

  bool get hasOptions => options.isNotEmpty;

  factory SoapField.fromJson(Map<String, dynamic> json) => SoapField(
        key: '${json['key']}',
        type: '${json['type'] ?? 'text'}',
        label: '${json['label'] ?? json['key']}',
        options: ((json['options'] as List?) ?? const []).map((e) => '$e').toList(),
        required: json['required'] == true,
        unit: json['unit'] as String?,
        hint: json['hint'] as String?,
        allowOther: json['allow_other'] == true,
        // `auto` 是字符串（如 `latest_vs_initial`）而不是布尔，凡非空即自动字段。
        auto: json['auto'] != null && json['auto'] != false,
      );

  Map<String, dynamic> toJson() => {
        'key': key,
        'type': type,
        'label': label,
        if (options.isNotEmpty) 'options': options,
        if (required) 'required': true,
        if (unit != null) 'unit': unit,
        if (hint != null) 'hint': hint,
        if (allowOther) 'allow_other': true,
        if (auto) 'auto': true,
      };

  /// 该值算不算"填了"（与后端 `record_template._has_value` 同口径）。
  ///
  /// `0` 算填了（VAS 0 分是真实数据），空串不算，空数组不算。
  static bool hasValue(dynamic value) {
    if (value == null) return false;
    if (value is String) return value.trim().isNotEmpty;
    if (value is List) return value.any(hasValue);
    return true;
  }

  /// 把界面上的值归一化成**可直接提交**的类型。
  ///
  /// - `multi` 必须是数组（后端渲染器按多选处理，传字符串会被当成单值）；
  /// - `number` 存成数字（`3分` 的 `3` 要参与后续统计与对比）；
  /// - 其余原样（空串 / 空数组 → null，表示"没填"，不写进 body）。
  dynamic normalize(dynamic raw) {
    if (!hasValue(raw)) return null;
    if (isMulti) {
      if (raw is List) {
        final values = raw.map((e) => '$e').where((e) => e.trim().isNotEmpty).toList();
        return values.isEmpty ? null : values;
      }
      final text = '$raw'.trim();
      if (text.isEmpty) return null;
      // 两种分隔符都见过：`/`（渲染时用的）与顿号/空格。
      final parts = text
          .split(RegExp(r'[/、,\s]+'))
          .where((e) => e.isNotEmpty)
          .toList();
      return parts.isEmpty ? null : parts;
    }
    if (isNumber) {
      if (raw is num) return raw;
      final text = '$raw'.trim();
      if (text.isEmpty) return null;
      return num.tryParse(text) ?? text;
    }
    if (raw is String) {
      final text = raw.trim();
      return text.isEmpty ? null : text;
    }
    return raw;
  }

  /// 界面上显示的文本（多选用 `/` 连接，与渲染器一致）。
  static String display(dynamic value) {
    if (!hasValue(value)) return '';
    if (value is List) return value.map((e) => '$e').join('/');
    return '$value';
  }
}

/// SOAP 里的一段（S / O / A / P）。
class SoapSection {
  const SoapSection({
    required this.key,
    required this.label,
    required this.heading,
    this.fields = const [],
  });

  /// `s` / `o` / `a` / `p`。
  final String key;

  /// `S` / `O` / `A` / `P`。
  final String label;

  /// 中文段名（`主观资料`…），渲染时是「段名：字段；字段」。
  final String heading;

  final List<SoapField> fields;

  factory SoapSection.fromJson(Map<String, dynamic> json) => SoapSection(
        key: '${json['key']}',
        label: '${json['label'] ?? json['key']}',
        heading: '${json['heading'] ?? json['label'] ?? json['key']}',
        fields: ((json['fields'] as List?) ?? const [])
            .whereType<Map>()
            .map((e) => SoapField.fromJson(Map<String, dynamic>.from(e)))
            .toList(),
      );

  Map<String, dynamic> toJson() => {
        'key': key,
        'label': label,
        'heading': heading,
        'fields': fields.map((f) => f.toJson()).toList(),
      };
}

/// 一条治疗记录（`RecordOut` / 列表项 / 离线草稿都用它）。
///
/// `body` 是 `{field_key: value}`；`renderedText` 是服务端在落库时**冻结**的
/// SOAP 纯文本（历史病历的措辞不随模板后续修改而变）。
class RecordData {
  const RecordData({
    required this.id,
    required this.patientNo,
    required this.therapistId,
    required this.recordDate,
    required this.discipline,
    required this.kind,
    required this.status,
    this.disciplineName,
    this.kindLabel,
    this.seqNo,
    this.spanSeq,
    this.body = const {},
    this.renderedText = '',
    this.renderedExcerpt = '',
    this.note,
    this.editCount = 0,
    this.revision = 1,
    this.clientUuid,
    this.isTemporary = false,
  });

  final int id;
  final String patientNo;
  final int therapistId;
  final String recordDate;

  /// `PT` / `OT` / `ST_SW` / `ST_SP`。
  final String discipline;
  final String? disciplineName;

  /// `initial` / `daily` / `reassessment` / `discharge`。
  final String kind;
  final String? kindLabel;

  /// 第几次**日常**记录；评估文书不占次数，所以它们是 null。
  final int? seqNo;

  /// 评估文书挂靠的日常序号。
  final int? spanSeq;

  final Map<String, dynamic> body;

  /// 冻结的 SOAP 纯文本（列表与详情都直接显示它）。
  final String renderedText;

  /// 列表用的一行摘要（服务端算好）。
  final String renderedExcerpt;

  final String? note;
  final String status;
  final int editCount;
  final int revision;
  final String? clientUuid;
  final bool isTemporary;

  bool get isDraft => status == 'draft';
  bool get isSubmitted => status == 'submitted';
  bool get isLocked => status == 'locked';

  String get statusLabel => switch (status) {
        'draft' => '草稿',
        'submitted' => '已提交',
        'locked' => '已锁定',
        _ => status,
      };

  /// 只有**日常记录**才有"第 N 次"（评估文书不占次数，用户 2026-10-05 纠正）。
  bool get countsAsSession => kind == 'daily';

  factory RecordData.fromJson(Map<String, dynamic> json) => RecordData(
        id: (json['id'] as num?)?.toInt() ?? 0,
        patientNo: '${json['patient_no'] ?? ''}',
        therapistId: (json['therapist_id'] as num?)?.toInt() ?? 0,
        recordDate: '${json['record_date'] ?? ''}',
        discipline: '${json['discipline'] ?? ''}',
        disciplineName: json['discipline_name'] as String?,
        kind: '${json['kind'] ?? 'daily'}',
        kindLabel: json['kind_label'] as String?,
        seqNo: (json['seq_no'] as num?)?.toInt(),
        spanSeq: (json['span_seq'] as num?)?.toInt(),
        body: Map<String, dynamic>.from((json['body'] as Map?) ?? const {}),
        renderedText: '${json['rendered_text'] ?? ''}',
        renderedExcerpt: '${json['rendered_excerpt'] ?? ''}',
        note: json['note'] as String?,
        status: '${json['status'] ?? 'draft'}',
        editCount: (json['edit_count'] as num?)?.toInt() ?? 0,
        revision: (json['revision'] as num?)?.toInt() ?? 1,
        clientUuid: json['client_uuid'] as String?,
        isTemporary: (json['is_temporary'] as num?)?.toInt() == 1 ||
            json['is_temporary'] == true,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'patient_no': patientNo,
        'therapist_id': therapistId,
        'record_date': recordDate,
        'discipline': discipline,
        if (disciplineName != null) 'discipline_name': disciplineName,
        'kind': kind,
        if (kindLabel != null) 'kind_label': kindLabel,
        if (seqNo != null) 'seq_no': seqNo,
        if (spanSeq != null) 'span_seq': spanSeq,
        'body': body,
        'rendered_text': renderedText,
        if (renderedExcerpt.isNotEmpty) 'rendered_excerpt': renderedExcerpt,
        if (note != null) 'note': note,
        'status': status,
        'edit_count': editCount,
        'revision': revision,
        if (clientUuid != null) 'client_uuid': clientUuid,
        'is_temporary': isTemporary ? 1 : 0,
      };

  /// 列表里显示的一行文本：优先服务端摘要，退化成 `rendered_text` 的第一段。
  String get summaryLine {
    if (renderedExcerpt.isNotEmpty) return renderedExcerpt;
    for (final line in renderedText.split('\n')) {
      final text = line.trim();
      if (text.isNotEmpty && !text.startsWith('治疗日期') && text.contains('：')) {
        return text.length <= 80 ? text : '${text.substring(0, 79)}…';
      }
    }
    return '';
  }
}

/// 记录表单（`GET /api/v1/records/form`）。
///
/// 一次请求回答四个问题：该填哪份文书、长什么样、预填什么、是不是已经在填了。
class RecordFormData {
  const RecordFormData({
    required this.patientNo,
    required this.patientName,
    required this.discipline,
    required this.disciplineName,
    required this.kind,
    required this.kindLabel,
    required this.title,
    this.patientStatus,
    this.nextSeq = 1,
    this.totalDaily = 0,
    this.sessionsUntilReassessment = 0,
    this.pendingDocument,
    this.pendingDocumentLabel,
    this.templateVersion = 1,
    this.soap = const [],
    this.prefill = const {},
    this.prefillSource = const {},
    this.footer = const [],
    this.existing,
  });

  final String patientNo;
  final String patientName;

  /// `in_hospital` / `paused` / `pending_discharge` / `discharged`。
  final String? patientStatus;

  final String discipline;
  final String disciplineName;

  /// 本次要填的形态：**缺评估文书时它就是那份评估文书**（服务端门禁决定）。
  final String kind;
  final String kindLabel;

  /// 文书标题（如「康复治疗记录（PT运动）」）。
  final String title;

  /// 这次是第几次日常（评估文书不占次数，这里仍是它挂靠的那次）。
  final int nextSeq;

  /// 该大类已完成（含草稿）的日常记录数。
  final int totalDaily;

  /// 距下一次复评还差几次日常。
  final int sessionsUntilReassessment;

  /// 还缺哪份评估文书（`initial` / `reassessment`），null = 不缺。
  final String? pendingDocument;
  final String? pendingDocumentLabel;

  final int templateVersion;

  /// 四段字段定义，**直接渲染**。
  final List<SoapSection> soap;

  /// 服务端预填的答案（`{field_key: value}`）。
  final Map<String, dynamic> prefill;

  /// 每个预填值来自哪里（`last_daily` / `same_day_first` / `last_assessment` / `auto`）。
  final Map<String, String> prefillSource;

  final List<String> footer;

  /// 已存在的那条记录（非 null → **继续编辑**而不是重复新建）。
  final RecordData? existing;

  /// 是否评估文书（首评 / 复评 / 出院小结）。评估文书**不显示序号**。
  bool get isAssessment => kind != 'daily';

  bool get isDischarge => kind == 'discharge';

  /// 是否显示「第 N 次」——只有日常记录显示（后端渲染器同一规则）。
  bool get showsSeqNo => kind == 'daily';

  /// 患者待出院时不能再记新记录（服务端 409）。
  bool get patientPendingDischarge => patientStatus == 'pending_discharge';

  List<SoapField> get allFields =>
      [for (final s in soap) ...s.fields];

  SoapField? field(String key) {
    for (final f in allFields) {
      if (f.key == key) return f;
    }
    return null;
  }

  /// 422 的 `details.missing` 只给**中文标签**，靠这张表把标签映射回字段。
  Map<String, SoapField> get byLabel => {for (final f in allFields) f.label: f};

  /// 界面的初值：服务端 `prefill` + （若有）已存在记录的内容。
  ///
  /// 已存在的那条**覆盖**预填：治疗师要接着改自己刚写的东西，
  /// 而不是看着服务端从"上次日常"带出来的值。
  Map<String, dynamic> initialValues() {
    final values = <String, dynamic>{};
    for (final f in allFields) {
      final raw = prefill[f.key];
      final value = f.normalize(raw);
      if (value != null) values[f.key] = value;
    }
    final existingBody = existing?.body;
    if (existingBody != null) {
      for (final f in allFields) {
        if (!existingBody.containsKey(f.key)) continue;
        final value = f.normalize(existingBody[f.key]);
        if (value == null) {
          values.remove(f.key);
        } else {
          values[f.key] = value;
        }
      }
    }
    return values;
  }

  factory RecordFormData.fromJson(Map<String, dynamic> json) {
    final p = Map<String, dynamic>.from((json['patient'] as Map?) ?? const {});
    final existing = json['existing'];
    return RecordFormData(
      patientNo: '${p['inpatient_no'] ?? ''}',
      patientName: '${p['name'] ?? ''}',
      patientStatus: p['status'] as String?,
      discipline: '${json['discipline'] ?? ''}',
      disciplineName: '${json['discipline_name'] ?? ''}',
      kind: '${json['kind'] ?? 'daily'}',
      kindLabel: '${json['kind_label'] ?? ''}',
      title: '${json['title'] ?? '治疗记录'}',
      nextSeq: (json['next_seq'] as num?)?.toInt() ?? 1,
      totalDaily: (json['total_daily'] as num?)?.toInt() ?? 0,
      sessionsUntilReassessment:
          (json['sessions_until_reassessment'] as num?)?.toInt() ?? 0,
      pendingDocument: json['pending_document'] as String?,
      pendingDocumentLabel: json['pending_document_label'] as String?,
      templateVersion: (json['template_version'] as num?)?.toInt() ?? 1,
      soap: ((json['soap'] as List?) ?? const [])
          .whereType<Map>()
          .map((e) => SoapSection.fromJson(Map<String, dynamic>.from(e)))
          .toList(),
      prefill: Map<String, dynamic>.from((json['prefill'] as Map?) ?? const {}),
      prefillSource: ((json['prefill_source'] as Map?) ?? const {})
          .map((k, v) => MapEntry('$k', '$v')),
      footer: ((json['footer'] as List?) ?? const []).map((e) => '$e').toList(),
      existing: existing is Map
          ? RecordData.fromJson(Map<String, dynamic>.from(existing))
          : null,
    );
  }

  /// 回写成服务端形状（离线缓存整份表单用）。
  Map<String, dynamic> toJson() => {
        'patient': {
          'inpatient_no': patientNo,
          'name': patientName,
          if (patientStatus != null) 'status': patientStatus,
        },
        'discipline': discipline,
        'discipline_name': disciplineName,
        'kind': kind,
        'kind_label': kindLabel,
        'title': title,
        'next_seq': nextSeq,
        'total_daily': totalDaily,
        'sessions_until_reassessment': sessionsUntilReassessment,
        'pending_document': pendingDocument,
        'pending_document_label': pendingDocumentLabel,
        'template_version': templateVersion,
        'soap': soap.map((s) => s.toJson()).toList(),
        'prefill': prefill,
        'prefill_source': prefillSource,
        'footer': footer,
        'existing': existing?.toJson(),
      };
}
