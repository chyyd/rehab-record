/// 治疗记录与记录表单的传输模型。
///
/// 字段名沿用后端 snake_case（与管理后台、`docs/sync-protocol.md` 同一约定）。
///
/// ★ 表单**不自己算"上次值/默认值"**：服务端 `GET /records/form` 已经按
/// 5 级带入（上次值 → 个人选项集 → 科室 → 全局 → 字典默认）填好了
/// `current_value` / `value_source` / `options_resolved`。客户端重算一遍
/// 只会与服务端产生分歧，所以这里只做**原样透传**。
// ignore_for_file: use_null_aware_elements
library;

/// 一个参数字段（含服务端解析好的当前值与选项）。
class FormParam {
  const FormParam({
    required this.id,
    required this.subItemId,
    required this.paramKey,
    required this.paramName,
    required this.inputType,
    required this.required,
    this.options = const [],
    this.defaultValue,
    this.unit,
    this.sort = 0,
    this.optionsResolved,
    this.currentValue,
    this.valueSource,
    this.lastValue,
  });

  final int id;
  final int subItemId;
  final String paramKey;
  final String paramName;

  /// `select` / `multi_select` / `number` / `text` / `date` / `bool` …
  final String inputType;

  final bool required;

  /// 字典里的静态候选值（`options_resolved` 为空时用它）。
  final List<String> options;

  final String? defaultValue;
  final String? unit;
  final int sort;

  /// 服务端解析出的选项集：`{source, option_set_name, options:[{value,label}], defaults:[…]}`。
  final Map<String, dynamic>? optionsResolved;

  /// 服务端带入的当前值（可能是 String / List / num）。
  final dynamic currentValue;

  /// 值来源，用于在界面上小字标注"来自上次/个人/科室/全局/默认"。
  final String? valueSource;

  final dynamic lastValue;

  factory FormParam.fromJson(Map<String, dynamic> json) => FormParam(
        id: (json['id'] as num).toInt(),
        subItemId: (json['sub_item_id'] as num).toInt(),
        paramKey: json['param_key'] as String,
        paramName: json['param_name'] as String,
        inputType: json['input_type'] as String,
        required: (json['required'] as num?)?.toInt() == 1,
        options: ((json['options'] as List?) ?? const []).map((e) => '$e').toList(),
        defaultValue: json['default_value'] as String?,
        unit: json['unit'] as String?,
        sort: (json['sort'] as num?)?.toInt() ?? 0,
        optionsResolved: json['options_resolved'] == null
            ? null
            : Map<String, dynamic>.from(json['options_resolved'] as Map),
        currentValue: json['current_value'],
        valueSource: json['value_source'] as String?,
        lastValue: json['last_value'],
      );

  /// 界面上可选的候选项：优先选项集解析结果，其次字典静态选项。
  List<FormOption> get candidates {
    final resolved = optionsResolved;
    if (resolved != null) {
      final list = (resolved['options'] as List?) ?? const [];
      final items = list
          .whereType<Map>()
          .map((e) => FormOption(
                value: '${e['value']}',
                label: '${e['label'] ?? e['value']}',
              ))
          .toList();
      if (items.isNotEmpty) return items;
    }
    return options.map((o) => FormOption(value: o, label: o)).toList();
  }

  /// 选项集来源（个人/科室/全局/内置），供界面标注。
  String? get optionsSourceLabel {
    final source = optionsResolved?['source'] as String?;
    return switch (source) {
      'personal' => '个人选项集',
      'dept' => '科室选项集',
      'global' => '全局选项集',
      'builtin' => '字典默认',
      _ => null,
    };
  }

  /// 值来源的中文标注。
  String? get valueSourceLabel => switch (valueSource) {
        'last_value' => '上次值',
        'option_set_default' => '选项集默认',
        'dict_default' => '字典默认',
        _ => null,
      };

  /// 回写成服务端形状（供离线缓存整份表单）。
  Map<String, dynamic> toJson() => {
        'id': id,
        'sub_item_id': subItemId,
        'param_key': paramKey,
        'param_name': paramName,
        'input_type': inputType,
        'options': options,
        if (defaultValue != null) 'default_value': defaultValue,
        'required': required ? 1 : 0,
        if (unit != null) 'unit': unit,
        'sort': sort,
        if (optionsResolved != null) 'options_resolved': optionsResolved,
        'current_value': currentValue,
        if (valueSource != null) 'value_source': valueSource,
        'last_value': lastValue,
      };

  bool get isMulti => inputType == 'multi_select';
  bool get isNumber => inputType == 'number';
  bool get isBool => inputType == 'bool';
  bool get isSelect => inputType == 'select' || isMulti;
  bool get isText => inputType == 'text' || (!isSelect && !isNumber && !isBool);

  /// 带入值是否**能直接提交**。
  ///
  /// ★ 实测（2026-10-05）服务端的带入值与选项集**可能自相矛盾**：
  /// `GET /records/form` 给出 `current_value = 部分辅助`（来源 `dict_default`），
  /// 但同一响应里 `options_resolved` 的合法选项是
  /// `完全辅助/最大辅助/中等辅助/最小辅助/监护/独立` —— 照表单预填直接提交必被
  /// 422「取值不在选项内」。全量表里 **89 个参数中有 19 个**（21%）如此，
  /// 集中在 `assistance_level`(7)、`train_content`(4)、`body_part`(2)、
  /// `items`(2)、`assist_mode`/`food_texture`/`scene`/`train_mode`(各 1)。
  ///
  /// 根因在**后端种子**：`option_seed.json` 里这些 `param_key` 只定义了
  /// `variant: 0`（`is_primary: true`），而同一个 `param_key` 在不同子项目下
  /// 语义完全不同（`body_part` 在「口腔感觉训练」是舌/腭，在「肌力训练」是肩/肘/腕…），
  /// 却共用同一个全局选项集。客户端的词典默认值（如"部分辅助"）因此落在选项集之外。
  ///
  /// 在后端修种子/解析前，客户端**必须**自己挡住：预填一个提交必被拒的值，
  /// 比不预填糟糕得多 —— 治疗师会填完整张表单才发现提交失败。
  bool isValueSubmittable(dynamic value) {
    if (value == null) return false;
    if (isSelect) {
      final allowed = candidates.map((c) => c.value).toSet();
      // 没有候选项（如 builtin 选项集）时无法判断，交给服务端。
      if (allowed.isEmpty) return true;
      if (value is List) {
        if (value.isEmpty) return false;
        return value.every((v) => allowed.contains('$v'));
      }
      return allowed.contains('$value');
    }
    if (isNumber) return num.tryParse('$value') != null;
    if (value is String && value.trim().isEmpty) return false;
    return true;
  }

  /// 把带入值归一化成**可直接提交**的类型。
  ///
  /// 归一化两件事：
  ///  1. 类型：`multi_select` 必须是数组（后端 `_validate_value` 明确要求，
  ///     传字符串会 422「多选参数取值必须是数组」）；
  ///  2. 合法性：不在候选项内的值直接丢掉（见 [isValueSubmittable]）。
  dynamic normalizeValue(dynamic raw) {
    if (raw == null) return null;
    final normalized = _coerce(raw);
    if (normalized == null) return null;
    return isValueSubmittable(normalized) ? normalized : null;
  }

  /// 只做类型归一化，不判合法性。
  dynamic _coerce(dynamic raw) {
    if (isMulti) {
      if (raw is List) return raw.isEmpty ? null : raw;
      final text = '$raw'.trim();
      if (text.isEmpty) return null;
      // 两种分隔符都见过：空格与顿号。
      final parts =
          text.split(RegExp(r'[、,\s]+')).where((e) => e.isNotEmpty).toList();
      return parts.isEmpty ? null : parts;
    }
    if (isNumber) {
      if (raw is num) return raw;
      final text = '$raw'.trim();
      if (text.isEmpty) return null;
      return num.tryParse(text) ?? text;
    }
    if (isBool) {
      if (raw is bool) return raw;
      return '$raw' == 'true' || '$raw' == '1';
    }
    if (raw is String && raw.trim().isEmpty) return null;
    return raw;
  }
}

/// 一个候选项。
class FormOption {
  const FormOption({required this.value, required this.label});
  final String value;
  final String label;
}

/// 子项目（一次治疗里的一项操作）。
class FormSubItem {
  const FormSubItem({
    required this.id,
    required this.mainItemId,
    required this.name,
    this.code,
    this.alias,
    this.sort = 0,
    this.params = const [],
  });

  final int id;
  final int mainItemId;
  final String name;
  final String? code;
  final String? alias;
  final int sort;
  final List<FormParam> params;

  factory FormSubItem.fromJson(Map<String, dynamic> json) => FormSubItem(
        id: (json['id'] as num).toInt(),
        mainItemId: (json['main_item_id'] as num).toInt(),
        name: json['name'] as String,
        code: json['code'] as String?,
        alias: json['alias'] as String?,
        sort: (json['sort'] as num?)?.toInt() ?? 0,
        params: ((json['params'] as List?) ?? const [])
            .whereType<Map>()
            .map((e) => FormParam.fromJson(Map<String, dynamic>.from(e)))
            .toList(),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'main_item_id': mainItemId,
        'name': name,
        if (code != null) 'code': code,
        if (alias != null) 'alias': alias,
        'sort': sort,
        'params': params.map((p) => p.toJson()).toList(),
      };
}

/// 主项目（一类治疗）。
class FormMainItem {
  const FormMainItem({
    required this.id,
    required this.name,
    this.code,
    this.alias,
    this.sort = 0,
    this.subItems = const [],
  });

  final int id;
  final String name;
  final String? code;
  final String? alias;
  final int sort;
  final List<FormSubItem> subItems;

  factory FormMainItem.fromJson(Map<String, dynamic> json) => FormMainItem(
        id: (json['id'] as num).toInt(),
        name: json['name'] as String,
        code: json['code'] as String?,
        alias: json['alias'] as String?,
        sort: (json['sort'] as num?)?.toInt() ?? 0,
        subItems: ((json['sub_items'] as List?) ?? const [])
            .whereType<Map>()
            .map((e) => FormSubItem.fromJson(Map<String, dynamic>.from(e)))
            .toList(),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        if (code != null) 'code': code,
        if (alias != null) 'alias': alias,
        'sort': sort,
        'sub_items': subItems.map((s) => s.toJson()).toList(),
      };

  String get display => (alias?.isNotEmpty == true ? alias! : name);
}

/// 患者反应定义（三种控件：tag / number / select / text）。
class ResponseDef {
  const ResponseDef({
    required this.id,
    required this.code,
    required this.label,
    required this.valueType,
    this.mainItemId,
    this.valueKey,
    this.valueUnit,
    this.valueMin,
    this.valueMax,
    this.options = const [],
  });

  final int id;
  final String code;
  final String label;

  /// `tag` / `number` / `select` / `text`。
  final String valueType;

  final int? mainItemId;
  final String? valueKey;
  final String? valueUnit;
  final double? valueMin;
  final double? valueMax;
  final List<String> options;

  factory ResponseDef.fromJson(Map<String, dynamic> json) => ResponseDef(
        id: (json['id'] as num).toInt(),
        code: json['code'] as String,
        label: json['label'] as String,
        valueType: json['value_type'] as String? ?? 'tag',
        mainItemId: (json['main_item_id'] as num?)?.toInt(),
        valueKey: json['value_key'] as String?,
        valueUnit: json['value_unit'] as String?,
        valueMin: (json['value_min'] as num?)?.toDouble(),
        valueMax: (json['value_max'] as num?)?.toDouble(),
        options: ((json['options'] as List?) ?? const []).map((e) => '$e').toList(),
      );

  /// 该定义是否适用于某个主项目。
  ///
  /// 定义自身没绑主项目（`mainItemId == null`）表示**通用**，适用于所有项目。
  bool appliesTo(int? mainItemId) =>
      this.mainItemId == null || this.mainItemId == mainItemId;

  Map<String, dynamic> toJson() => {
        'id': id,
        'code': code,
        'label': label,
        'value_type': valueType,
        if (mainItemId != null) 'main_item_id': mainItemId,
        if (valueKey != null) 'value_key': valueKey,
        if (valueUnit != null) 'value_unit': valueUnit,
        if (valueMin != null) 'value_min': valueMin,
        if (valueMax != null) 'value_max': valueMax,
        'options': options,
      };
}

/// 记录表单（服务端已算好带入值）。
class RecordFormData {
  const RecordFormData({
    required this.patientNo,
    required this.patientName,
    required this.mainItems,
    required this.responseDefs,
    required this.lastCompletedSeqNo,
    this.diagnosis,
    this.adminNote,
    this.referenceDate,
  });

  final String patientNo;
  final String patientName;
  final String? diagnosis;
  final String? adminNote;
  final List<FormMainItem> mainItems;
  final List<ResponseDef> responseDefs;

  /// 该患者已完成治疗次数；本次是第 `lastCompletedSeqNo + 1` 次。
  final int lastCompletedSeqNo;

  final String? referenceDate;

  factory RecordFormData.fromJson(Map<String, dynamic> json) {
    final p = Map<String, dynamic>.from((json['patient'] as Map?) ?? const {});
    return RecordFormData(
      patientNo: '${p['inpatient_no']}',
      patientName: '${p['name']}',
      diagnosis: p['diagnosis'] as String?,
      adminNote: p['admin_note'] as String?,
      mainItems: ((json['main_items'] as List?) ?? const [])
          .whereType<Map>()
          .map((e) => FormMainItem.fromJson(Map<String, dynamic>.from(e)))
          .toList(),
      responseDefs: ((json['response_defs'] as List?) ?? const [])
          .whereType<Map>()
          .map((e) => ResponseDef.fromJson(Map<String, dynamic>.from(e)))
          .toList(),
      lastCompletedSeqNo: (json['last_completed_seq_no'] as num?)?.toInt() ?? 0,
      referenceDate: json['reference_date'] as String?,
    );
  }

  Map<String, dynamic> toJson() => {
        'patient': {
          'inpatient_no': patientNo,
          'name': patientName,
          if (diagnosis != null) 'diagnosis': diagnosis,
          if (adminNote != null) 'admin_note': adminNote,
        },
        'main_items': mainItems.map((m) => m.toJson()).toList(),
        'response_defs': responseDefs.map((r) => r.toJson()).toList(),
        'last_completed_seq_no': lastCompletedSeqNo,
        if (referenceDate != null) 'reference_date': referenceDate,
      };

  int get nextSeqNo => lastCompletedSeqNo + 1;
}

/// 一次治疗里的一项（主项目 + 子项目 + 参数值）。
class RecordItemDraft {
  RecordItemDraft({
    required this.mainItemId,
    required this.subItemId,
    required this.subItemName,
    Map<String, dynamic>? params,
  }) : params = params ?? <String, dynamic>{};

  final int mainItemId;
  final int subItemId;
  final String subItemName;

  /// 键为 `param_key`；**空值不提交**（服务端按"没填"处理）。
  final Map<String, dynamic> params;

  Map<String, dynamic> toJson() => {
        'main_item_id': mainItemId,
        'sub_item_id': subItemId,
        'params': params,
      };

  factory RecordItemDraft.fromJson(Map<String, dynamic> json) => RecordItemDraft(
        mainItemId: (json['main_item_id'] as num).toInt(),
        subItemId: (json['sub_item_id'] as num).toInt(),
        subItemName: '${json['sub_item_name_snapshot'] ?? json['sub_item_name'] ?? ''}',
        params: Map<String, dynamic>.from((json['params'] as Map?) ?? const {}),
      );
}

/// 患者反应草稿。
///
/// 形状与后端一致：`{"tags": [...], "items": [{"code": ..., "value": ...}]}`。
class PatientResponseDraft {
  PatientResponseDraft({Set<String>? tags, Map<String, dynamic>? items})
      : tags = tags ?? <String>{},
        items = items ?? <String, dynamic>{};

  final Set<String> tags;
  final Map<String, dynamic> items;

  bool get isEmpty => tags.isEmpty && items.isEmpty;

  Map<String, dynamic> toJson() => {
        'tags': tags.toList(),
        'items': items.entries
            .map((e) => {'code': e.key, 'value': e.value})
            .toList(),
      };

  static PatientResponseDraft fromJson(Map<String, dynamic> json) {
    final tags = ((json['tags'] as List?) ?? const []).map((e) => '$e').toSet();
    final items = <String, dynamic>{};
    for (final raw in ((json['items'] as List?) ?? const []).whereType<Map>()) {
      final code = raw['code'];
      if (code != null) items['$code'] = raw['value'];
    }
    return PatientResponseDraft(tags: tags, items: items);
  }
}
