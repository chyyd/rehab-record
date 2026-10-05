import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/core/date_utils.dart';
import 'package:rehab_app/core/error.dart';
import 'package:rehab_app/core/providers.dart';
import 'package:rehab_app/data/local/app_database.dart' as local;
import 'package:rehab_app/data/remote/record_dto.dart';
import 'package:rehab_app/features/auth/auth_controller.dart';
import 'package:rehab_app/features/patients/patients_providers.dart';
import 'package:rehab_app/features/records/record_failure.dart';
import 'package:rehab_app/sync/sync_engine.dart';

/// 保存失败的文案规则表（纯函数）由 `record_failure.dart` 提供，
/// 这里**转出去**，让只 import 记录编辑器的页面/测试也能拿到。
export 'package:rehab_app/features/records/record_failure.dart';

/// 某患者某大类的记录表单（服务端算好"该填哪份文书 + 预填值"）。
///
/// family 键是 `patientNo|discipline`：同一个患者的不同大类是**完全不同的文书**。
final recordFormProvider = FutureProvider.family<
    ({RecordFormData form, bool fromCache}), (String, String)>((ref, key) async {
  final services = ref.watch(appServicesProvider).requireValue;
  final (patientNo, discipline) = key;
  return services.records.fetchForm(patientNo, discipline);
});

/// 某患者的本地记录（**响应式**：落库即刷新，含未推送草稿）。
final localRecordsProvider =
    StreamProvider.family<List<local.TreatmentRecord>, String>((ref, patientNo) {
  final services = ref.watch(appServicesProvider).requireValue;
  return services.records.watchLocal(patientNo);
});

// --------------------------------------------------------------------------- //
// 编辑器状态
// --------------------------------------------------------------------------- //

/// 记录编辑器状态。
///
/// 刻意做成一个**不可变快照 + 拷贝更新**的 Notifier：表单里每个字段是独立的
/// chip / 输入框，散落的可变字段很容易出现"改了没刷新"或"刷新了但没保存"。
class RecordEditorState {
  const RecordEditorState({
    this.args,
    this.patientNo = '',
    this.recordDate = '',
    this.discipline = '',
    this.forcedKind,
    this.existingLocalId,
    this.values = const {},
    this.recent = const {},
    this.missingLabels = const <String>{},
    this.form,
    this.formFromCache = false,
    this.loading = false,
    this.saving = false,
    this.error,
    this.message,
    this.dirty = false,
    this.discharged = false,
  });

  /// 当前编辑目标（`null` = 还没打开过）。
  final RecordEditorArgs? args;

  final String patientNo;
  final String recordDate;
  final String discipline;

  /// 强制形态（只有出院小结用：门禁推不出"该出院了"）。
  final String? forcedKind;

  /// 本地记录 id（继续编辑时非空；新建时为空）。
  final int? existingLocalId;

  /// 答案：`{field_key: value}`（键是模板字段的 `key`）。
  final Map<String, dynamic> values;

  /// 字段的"最近用过"顺序（多选/单选：把每天重复的那几项排到最前）。
  final Map<String, List<String>> recent;

  /// 服务端 422 回给我们的**中文标签**（显示在对应字段上）。
  final Set<String> missingLabels;

  final RecordFormData? form;
  final bool formFromCache;
  final bool loading;
  final bool saving;
  final String? error;
  final String? message;

  /// 是否有未保存的改动（用于"退出前确认"）。
  final bool dirty;

  /// 出院是否已经提交成功（页面据此返回并提示）。
  final bool discharged;

  RecordEditorState copyWith({
    RecordEditorArgs? args,
    String? patientNo,
    String? recordDate,
    String? discipline,
    Object? forcedKind = _sentinel,
    Object? existingLocalId = _sentinel,
    Map<String, dynamic>? values,
    Map<String, List<String>>? recent,
    Set<String>? missingLabels,
    Object? form = _sentinel,
    bool? formFromCache,
    bool? loading,
    bool? saving,
    Object? error = _sentinel,
    Object? message = _sentinel,
    bool? dirty,
    bool? discharged,
  }) {
    return RecordEditorState(
      args: args ?? this.args,
      patientNo: patientNo ?? this.patientNo,
      recordDate: recordDate ?? this.recordDate,
      discipline: discipline ?? this.discipline,
      forcedKind:
          forcedKind == _sentinel ? this.forcedKind : forcedKind as String?,
      existingLocalId: existingLocalId == _sentinel
          ? this.existingLocalId
          : existingLocalId as int?,
      values: values ?? this.values,
      recent: recent ?? this.recent,
      missingLabels: missingLabels ?? this.missingLabels,
      form: form == _sentinel ? this.form : form as RecordFormData?,
      formFromCache: formFromCache ?? this.formFromCache,
      loading: loading ?? this.loading,
      saving: saving ?? this.saving,
      error: error == _sentinel ? this.error : error as String?,
      message: message == _sentinel ? this.message : message as String?,
      dirty: dirty ?? this.dirty,
      discharged: discharged ?? this.discharged,
    );
  }
}

/// `copyWith` 里区分"没传"与"显式传 null"。
const Object _sentinel = Object();

/// 记录页的进入参数。
class RecordEditorArgs {
  const RecordEditorArgs({
    required this.patientNo,
    required this.discipline,
    this.recordDate,
    this.existingId,
    this.kind,
  });

  final String patientNo;

  /// `PT` / `OT` / `ST_SW` / `ST_SP` —— **必填**，服务端按它选模板。
  final String discipline;

  final String? recordDate;

  /// 继续编辑某条本地记录。
  final int? existingId;

  /// 强制形态：出院小结传 `discharge`（其余留空，由服务端门禁决定）。
  final String? kind;

  bool get isDischarge => kind == 'discharge';

  /// 两个参数是否指向同一次编辑（用于判断要不要重置编辑器）。
  bool sameTarget(RecordEditorArgs? other) =>
      other != null &&
      other.patientNo == patientNo &&
      other.discipline == discipline &&
      other.existingId == existingId &&
      other.recordDate == recordDate &&
      other.kind == kind;
}

/// 记录编辑器。
///
/// ★ **刻意不用 `NotifierProvider.family`**：Riverpod 3 把 family notifier 的
/// 基类放在内部库里，公开 API 只留了 `Notifier`。记录编辑本来就是**独占**的
/// （同一时刻只可能填一张表单），所以用单例 + 打开时 [RecordEditorController.start]。
class RecordEditorController extends Notifier<RecordEditorState> {
  @override
  RecordEditorState build() => const RecordEditorState();

  /// 打开一次编辑（页面 `initState` 调用）。
  ///
  /// 同一个目标重复调用是**幂等**的：避免热重载/重建把已填内容清空。
  Future<void> start(RecordEditorArgs args) async {
    if (state.args?.sameTarget(args) == true && (state.loading || state.form != null)) {
      return;
    }

    state = RecordEditorState(
      args: args,
      patientNo: args.patientNo,
      recordDate: args.recordDate ?? formatDate(DateTime.now()),
      discipline: args.discipline,
      forcedKind: args.kind,
      existingLocalId: args.existingId,
      loading: true,
    );
    await _load(args);
  }

  Future<void> _load(RecordEditorArgs args) async {
    final services = ref.read(appServicesProvider).requireValue;
    try {
      // ★ 不自己判断"该填哪份文书"：`kind` 只做出院小结的显式指定，
      // 其余由服务端门禁算（缺首评/复评时它直接返回那份文书）。
      final result = await services.records.fetchForm(
        args.patientNo,
        args.discipline,
        date: state.recordDate,
        kind: args.kind,
      );
      final form = result.form;

      var values = form.initialValues();
      // 继续编辑一条已有记录：**它的内容覆盖服务端预填**。
      //
      // 两种情况要分开（2026-10-05）：
      //  · 本地草稿（id < 0）：只在本机，直接读本地 `body_json`；
      //  · 服务端记录（id > 0）：用户要求「在原始记录上进行修改」，所以**回服务端取一次**
      //    —— 本地镜像可能是旧的（别人改过、或还没同步过来）；
      //    取不到（离线/被删）就退回本地内容，让治疗师至少还能在床上改。
      final localId = args.existingId;
      if (localId != null && localId < 0) {
        values = {...values, ...await services.records.readLocalBody(localId)};
      } else if (localId != null && localId > 0) {
        try {
          final existing = await services.records.fetchRecord(localId);
          values = {...values, ...existing.body};
        } on AppError {
          values = {...values, ...await services.records.readLocalBody(localId)};
        }
      }

      // 多选字段的"最近用过"（模板里"本次训练项目"有 58 项）。
      final recent = <String, List<String>>{};
      for (final section in form.soap) {
        for (final field in section.fields) {
          if (!field.isMulti && !field.isSingle) continue;
          final used = await services.records.recentOptions(field.key);
          if (used.isNotEmpty) recent[field.key] = used;
        }
      }

      state = state.copyWith(
        form: form,
        formFromCache: result.fromCache,
        values: values,
        recent: recent,
        // 服务端说"这条已经在填了"（今天的草稿）→ 继续编辑而不是重复新建。
        existingLocalId: localId ?? _serverExistingId(form),
        loading: false,
        error: null,
        dirty: false,
      );
    } on AppError catch (e) {
      state = state.copyWith(loading: false, error: e.message);
    }
  }

  static int? _serverExistingId(RecordFormData form) {
    final id = form.existing?.id;
    return id != null && id > 0 ? id : null;
  }

  /// 重新加载表单（错误页的"重试"，以及"缺评估文书 → 改填那份文书"）。
  Future<void> retry() async {
    final args = state.args;
    if (args == null) return;
    state = state.copyWith(loading: true, error: null, message: null);
    await _load(args);
  }

  /// 改一个字段的值；空值表示"没填"（不写进 `body`）。
  void setValue(SoapField field, dynamic raw) {
    final value = field.normalize(raw);
    final values = {...state.values};
    if (value == null) {
      values.remove(field.key);
    } else {
      values[field.key] = value;
    }
    // 该字段已经填了 → 把缺失标记清掉（不必等下一次 422）。
    final missing = {...state.missingLabels}..remove(field.label);
    state = state.copyWith(values: values, missingLabels: missing, dirty: true);
  }

  /// 单选 chip：点一下选中，**再点取消**（用户："点一下就是选中"）。
  void toggleSingle(SoapField field, String option) {
    final current = SoapField.display(state.values[field.key]);
    setValue(field, current == option ? null : option);
  }

  /// 多选 chip：点一下加入，再点移出。
  void toggleMulti(SoapField field, String option) {
    final current = state.values[field.key];
    final selected = <String>{
      if (current is List) ...current.map((e) => '$e'),
    };
    selected.contains(option) ? selected.remove(option) : selected.add(option);
    setValue(field, selected.toList());
  }

  /// 界面上该字段的选项顺序：**最近用过的排最前**，其余保持模板顺序。
  List<String> orderedOptions(SoapField field) {
    final used = state.recent[field.key] ?? const <String>[];
    if (used.isEmpty) return field.options;
    final head = [
      for (final value in used)
        if (field.options.contains(value)) value,
    ];
    if (head.isEmpty) return field.options;
    return [
      ...head,
      for (final option in field.options)
        if (!head.contains(option)) option,
    ];
  }

  bool isRecent(SoapField field, String option) =>
      (state.recent[field.key] ?? const <String>[]).contains(option);

  void setDate(DateTime d) =>
      state = state.copyWith(recordDate: formatDate(d), dirty: true);

  void clearMessage() => state = state.copyWith(message: null, error: null);

  /// 提交时要写的 `body`：空值一律不写（服务端按"没填"处理）。
  Map<String, dynamic> buildBody(RecordFormData form) {
    final body = <String, dynamic>{};
    for (final field in form.allFields) {
      final value = field.normalize(state.values[field.key]);
      if (value != null) body[field.key] = value;
    }
    return body;
  }

  /// 必填但没填的字段（**本地预检**，最终以服务端 422 为准）。
  List<SoapField> missingRequired(RecordFormData form) => [
        for (final field in form.allFields)
          if (field.required && !SoapField.hasValue(field.normalize(state.values[field.key])))
            field,
      ];

  /// 本地预览文本（写进本地草稿的 `rendered_text`，格式与后端渲染器一致）。
  String previewText(RecordFormData form, Map<String, dynamic> body) {
    final lines = <String>[form.title];
    final header = <String>['治疗日期：${state.recordDate}'];
    // 评估文书**不显示序号**（用户 2026-10-05 纠正：评定不占日常次数）。
    if (form.showsSeqNo) header.add('第 ${form.nextSeq} 次');
    lines.add(header.join('   '));
    for (final section in form.soap) {
      final parts = <String>[];
      for (final field in section.fields) {
        final value = body[field.key];
        if (!SoapField.hasValue(value)) continue;
        var text = SoapField.display(value);
        if (field.isNumber && field.unit != null) text = '$text${field.unit}';
        parts.add('${field.label}：$text');
      }
      if (parts.isEmpty) continue;
      lines.add('');
      lines.add('${section.heading}：${parts.join('；')}');
    }
    if (form.footer.isNotEmpty) {
      lines.add('');
      lines.addAll(form.footer);
    }
    return lines.join('\n');
  }

  /// 保存（草稿或提交）。
  ///
  /// **先本地 + 入队，再尽力推送一次**：床旁弱网也必须能存下来。
  /// 推送失败时按服务端的 `details` 给出**具体**原因（缺哪几项必填 / 缺哪份文书 /
  /// 当天条数超限 / 患者待出院），而不是一句"出错了"。
  Future<bool> save({required bool submit}) async {
    final services = ref.read(appServicesProvider).requireValue;
    final user = ref.read(currentUserProvider);
    final form = state.form;
    if (form == null) return false;
    if (user == null) {
      state = state.copyWith(error: '未登录');
      return false;
    }

    // 草稿允许残缺（床旁先记一半很常见）；**提交**才做本地必填预检，
    // 目的只是省一次往返，真正的判据仍在服务端（422 details.missing）。
    if (submit) {
      final missing = missingRequired(form);
      if (missing.isNotEmpty) {
        state = state.copyWith(
          error: '还有必填项没填：${missing.map((f) => f.label).join('、')}',
          missingLabels: {for (final f in missing) f.label},
        );
        return false;
      }
    }

    state = state.copyWith(saving: true, error: null, message: null);
    final body = buildBody(form);

    try {
      final saved = await services.records.save(
        existingId: state.existingLocalId,
        patientNo: state.patientNo,
        therapistId: user.id,
        recordDate: state.recordDate,
        discipline: form.discipline,
        kind: form.kind,
        body: body,
        status: submit ? 'submitted' : 'draft',
        renderedText: previewText(form, body),
      );

      // 记住这次用过的选项（下次排最前）。
      for (final field in form.allFields) {
        final value = state.values[field.key];
        if (value is List) {
          await services.records.rememberOptions(
            field.key,
            value.map((e) => '$e'),
          );
        } else if (SoapField.hasValue(value)) {
          await services.records.rememberOptions(field.key, ['$value']);
        }
      }

      await _syncAndReport(saved, form: form, submit: submit);
    } on AppError catch (e) {
      _applyServerError(e);
      return false;
    }
    return true;
  }

  /// 推送一次并解释结果（冲突 / 成功 / 出院）。
  Future<void> _syncAndReport(
    ({int localId, String clientUuid}) saved, {
    required RecordFormData form,
    required bool submit,
  }) async {
    final services = ref.read(appServicesProvider).requireValue;
    ref.invalidate(localRecordsProvider(state.patientNo));
    ref.invalidate(pendingCountProvider);

    late final PushReport report;
    try {
      report = await services.sync.pushPending();
    } on AppError catch (e) {
      // 网络不可用：本地已经存下了，联网后会自动重推。
      ref.invalidate(localRecordsProvider(state.patientNo));
      state = state.copyWith(
        saving: false,
        existingLocalId: saved.localId,
        dirty: false,
        message: e.code == 'NETWORK_ERROR'
            ? (form.isDischarge
                ? '出院小结已存入本地；联网后回到患者页再点「出院」即可完成'
                : '已存入本地，联网后自动上传')
            : '已存入本地（${e.message}）',
      );
      return;
    }

    ref.invalidate(localRecordsProvider(state.patientNo));
    ref.invalidate(pendingCountProvider);

    if (report.hasConflicts) {
      state = state.copyWith(
        saving: false,
        existingLocalId: saved.localId,
        dirty: false,
        message: '已保存本地；有 ${report.conflicts.length} 条冲突待处理',
        error: '有冲突待处理',
      );
      return;
    }

    state = state.copyWith(
      saving: false,
      existingLocalId: saved.localId,
      dirty: false,
      message: submit ? '已提交' : '草稿已保存（本地）',
      error: null,
    );

    // 出院小结提交后要**显式**调一次出院接口（用户："选择出院必须出院小结"）。
    if (form.isDischarge && submit) {
      await requestDischarge(serverRecordId: serverIdFor(report, saved.clientUuid));
      return;
    }

    // ★ 刚刚补完评估文书（首评/复评）→ **自动切到当天的日常记录**。
    //
    // 用户的原话是「先弹评估文书」，服务端也确实是这么实现的：补完那份文书后
    // 再取一次表单，`kind` 就变成日常记录了。这里顺手替治疗师取一次，
    // 省掉"退出 → 回患者页 → 再点大类"三步（本次改造就是为了少点几下）。
    if (submit && form.pendingDocument != null) {
      await retry();
      state = state.copyWith(
        message: '${form.kindLabel}已提交，现在记当天的日常治疗记录',
      );
    }
  }

  /// 办理出院（`POST /patients/{no}/discharge`）。
  ///
  /// [serverRecordId] 为空表示这次小结还没拿到服务端 id（离线保存）——
  /// 那就只提示治疗师联网后再点一次「出院」：**出院小结已经存在**，
  /// 再次点「出院」时表单会带着这份小结回来，直接调接口即可，不需要重填。
  Future<void> requestDischarge({int? serverRecordId}) async {
    final services = ref.read(appServicesProvider).requireValue;
    final recordId = serverRecordId ?? _serverExistingId(state.form!);
    if (recordId == null) {
      state = state.copyWith(
        message: '出院小结已保存；联网后回到患者页再点「出院」即可完成（不必重填）',
      );
      return;
    }
    state = state.copyWith(saving: true, error: null);
    try {
      await services.patients.requestDischarge(state.patientNo, recordId);
      ref.invalidate(patientDetailProvider(state.patientNo));
      state = state.copyWith(
        saving: false,
        discharged: true,
        message: '已提交出院，患者进入「待出院」',
      );
    } on AppError catch (e) {
      state = state.copyWith(saving: false, error: e.message);
    }
  }

  /// 把服务端错误翻成治疗师能照着做的话，并把缺失字段标回界面上。
  void _applyServerError(AppError e) {
    final failure = explainRecordError(e);
    state = state.copyWith(
      saving: false,
      dirty: !failure.reloadForm,
      error: failure.message,
      missingLabels: failure.missingLabels,
    );
    if (failure.reloadForm) unawaited(retry());
  }
}

final recordEditorProvider =
    NotifierProvider<RecordEditorController, RecordEditorState>(
        RecordEditorController.new);

/// 这次推上去的那条记录的服务端 id（没有则 null）。
///
/// 出院流程要用它：`POST /patients/{no}/discharge` 的 body 必须是
/// **已提交的出院小结 id**（"出院不是点按钮，而是文书写完了"）。
int? serverIdFor(PushReport report, String clientUuid) {
  for (final item in report.applied) {
    if (item.clientUuid != clientUuid) continue;
    final id = item.entityId;
    if (id is num) return id.toInt();
    return int.tryParse('$id');
  }
  return null;
}
