import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/core/date_utils.dart';
import 'package:rehab_app/core/error.dart';
import 'package:rehab_app/core/providers.dart';
import 'package:rehab_app/data/local/app_database.dart' as local;
import 'package:rehab_app/data/remote/record_dto.dart';
import 'package:rehab_app/features/auth/auth_controller.dart';
import 'package:rehab_app/features/patients/patients_providers.dart';

/// 记录表单（服务端算好带入值；离线时回落到缓存）。
final recordFormProvider =
    FutureProvider.family<({RecordFormData form, bool fromCache}), String>(
        (ref, patientNo) async {
  final services = ref.watch(appServicesProvider).requireValue;
  return services.records.fetchForm(patientNo);
});

/// 某患者的本地记录（**响应式**：落库即刷新，含未推送草稿）。
///
/// 直接给 Drift 的行类型：UI 只读几个字段，再包一层"视图类"只会多一层要维护的映射。
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
/// 刻意做成一个**不可变快照 + 拷贝更新**的 Notifier：表单里有大量相互独立的
/// 参数控件，散落的可变字段很容易出现"改了没刷新"或"刷新了但没保存"。
class RecordEditorState {
  const RecordEditorState({
    this.args,
    this.patientNo = '',
    this.recordDate = '',
    this.sessionPeriod,
    this.appointmentId,
    this.existingId,
    this.durationMin,
    this.note = '',
    this.items = const [],
    this.responseTags = const <String>{},
    this.responseItems = const <String, dynamic>{},
    this.form,
    this.formFromCache = false,
    this.loading = false,
    this.saving = false,
    this.error,
    this.message,
    this.dirty = false,
  });

  /// 当前编辑目标（`null` = 还没打开过）。
  final RecordEditorArgs? args;

  final String patientNo;
  final String recordDate;
  final String? sessionPeriod;
  final int? appointmentId;

  /// 本地草稿 id（继续编辑时非空）。
  final int? existingId;

  final int? durationMin;
  final String note;
  final List<RecordItemDraft> items;
  final Set<String> responseTags;
  final Map<String, dynamic> responseItems;

  final RecordFormData? form;
  final bool formFromCache;
  final bool loading;
  final bool saving;
  final String? error;
  final String? message;

  /// 是否有未保存的改动（用于"退出前确认"）。
  final bool dirty;

  PatientResponseDraft get response =>
      PatientResponseDraft(tags: responseTags, items: responseItems);

  /// 服务端会算序号，这里给个乐观提示。
  int get nextSeqNo => form?.nextSeqNo ?? 1;

  RecordEditorState copyWith({
    RecordEditorArgs? args,
    String? patientNo,
    String? recordDate,
    Object? sessionPeriod = _sentinel,
    Object? appointmentId = _sentinel,
    Object? existingId = _sentinel,
    Object? durationMin = _sentinel,
    String? note,
    List<RecordItemDraft>? items,
    Set<String>? responseTags,
    Map<String, dynamic>? responseItems,
    Object? form = _sentinel,
    bool? formFromCache,
    bool? loading,
    bool? saving,
    Object? error = _sentinel,
    Object? message = _sentinel,
    bool? dirty,
  }) {
    return RecordEditorState(
      args: args ?? this.args,
      patientNo: patientNo ?? this.patientNo,
      recordDate: recordDate ?? this.recordDate,
      sessionPeriod:
          sessionPeriod == _sentinel ? this.sessionPeriod : sessionPeriod as String?,
      appointmentId:
          appointmentId == _sentinel ? this.appointmentId : appointmentId as int?,
      existingId: existingId == _sentinel ? this.existingId : existingId as int?,
      durationMin: durationMin == _sentinel ? this.durationMin : durationMin as int?,
      note: note ?? this.note,
      items: items ?? this.items,
      responseTags: responseTags ?? this.responseTags,
      responseItems: responseItems ?? this.responseItems,
      form: form == _sentinel ? this.form : form as RecordFormData?,
      formFromCache: formFromCache ?? this.formFromCache,
      loading: loading ?? this.loading,
      saving: saving ?? this.saving,
      error: error == _sentinel ? this.error : error as String?,
      message: message == _sentinel ? this.message : message as String?,
      dirty: dirty ?? this.dirty,
    );
  }
}

/// `copyWith` 里区分"没传"与"显式传 null"。
const Object _sentinel = Object();

/// 记录页的进入参数。
class RecordEditorArgs {
  const RecordEditorArgs({
    required this.patientNo,
    this.recordDate,
    this.sessionPeriod,
    this.appointmentId,
    this.existingId,
  });

  final String patientNo;
  final String? recordDate;
  final String? sessionPeriod;
  final int? appointmentId;

  /// 继续编辑某条本地草稿。
  final int? existingId;

  /// 两个参数是否指向同一次编辑（用于判断要不要重置编辑器）。
  bool sameTarget(RecordEditorArgs? other) =>
      other != null &&
      other.patientNo == patientNo &&
      other.existingId == existingId &&
      other.recordDate == recordDate &&
      other.sessionPeriod == sessionPeriod &&
      other.appointmentId == appointmentId;
}

/// 记录编辑器。
///
/// ★ **刻意不用 `NotifierProvider.family`**：Riverpod 3 把 family notifier 的
/// 基类（`ClassFamily` 那一套）放在内部库里，公开 API 只留了 `Notifier`。
/// 记录编辑本来就是**独占**的（同一时刻只可能填一张表单），所以用单例 +
/// 打开时 [RecordEditorController.start] 更简单，出问题也更好查。
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
      sessionPeriod: args.sessionPeriod,
      appointmentId: args.appointmentId,
      existingId: args.existingId,
      loading: true,
    );
    await _load(args);
  }

  Future<void> _load(RecordEditorArgs args) async {
    final services = ref.read(appServicesProvider).requireValue;
    try {
      final result = await services.records.fetchForm(args.patientNo);
      var next = state.copyWith(
        form: result.form,
        formFromCache: result.fromCache,
        loading: false,
        error: null,
      );

      // 本地草稿：明细与患者反应都在本地的列里。
      if (args.existingId != null && args.existingId! < 0) {
        final items = await services.records.readPendingItems(args.existingId!);
        final response = await services.records.readPendingResponse(args.existingId!);
        next = next.copyWith(
          items: items,
          responseTags: response.tags,
          responseItems: response.items,
          dirty: false,
        );
      }
      state = next;
    } on AppError catch (e) {
      state = state.copyWith(loading: false, error: e.message);
    }
  }

  /// 重新加载表单（错误页的"重试"）。
  Future<void> retry() async {
    final args = state.args;
    if (args == null) return;
    state = state.copyWith(loading: true, error: null);
    await _load(args);
  }

  /// 选中一个子项目 → 加一条明细，参数按服务端的带入值预填。
  ///
  /// **预填直接用服务端的 `current_value`**（它已经按 5 级带入算好了），
  /// 客户端再算一遍只会与服务端分歧。但**类型要归一化**：`multi_select` 的
  /// 带入值可能是空格/顿号分隔的字符串，而服务端提交时要求数组
  ///（见 `FormParam.normalizeValue`）。
  void addSubItem(FormMainItem main, FormSubItem sub) {
    final existing = state.items.where((i) => i.subItemId == sub.id).toList();
    final params = <String, dynamic>{};
    final skipped = <String>[];

    for (final p in sub.params) {
      final fromServer = p.normalizeValue(p.currentValue);
      if (fromServer != null) {
        params[p.paramKey] = fromServer;
        continue;
      }
      final fallback = p.normalizeValue(p.defaultValue);
      if (fallback != null) {
        params[p.paramKey] = fallback;
        continue;
      }
      // 有"想给"的值但都不合法（服务端默认值落在选项集之外）→ 记下来提示。
      // 完全没值的（如 berg_score）属于"本来就没填"，不该打扰用户。
      final wanted = p.currentValue ?? p.defaultValue;
      if (wanted != null && '$wanted'.trim().isNotEmpty && p.isSelect) {
        skipped.add(p.paramName);
      }
    }

    final notes = <String>[
      if (existing.isNotEmpty) '同一项目已加过一次，这是第 ${existing.length + 1} 次',
      if (skipped.isNotEmpty)
        '「${skipped.join('、')}」的字典默认值不在选项集内，已留空待选',
    ];

    state = state.copyWith(
      items: [
        ...state.items,
        RecordItemDraft(
          mainItemId: main.id,
          subItemId: sub.id,
          subItemName: sub.name,
          params: params,
        ),
      ],
      dirty: true,
      message: notes.isEmpty ? null : notes.join('；'),
    );

    // 第一个项目决定了患者反应的**作用域**（服务端只按第一个主项目校验）。
    if (state.items.length == 1) {
      unawaited(_syncResponseScope(main.id));
    }
  }

  /// 按"第一个治疗项目的主项目"重新取患者反应定义。
  ///
  /// 服务端 `response_defs` 是按主项目分组的（无通用组），而提交时
  /// `normalize_responses` 只用第一个项目的主项目做校验。不跟随切换的话，
  /// 界面会显示别组的反应 → 提交 422「未知的患者反应」。
  ///
  /// 切换作用域时**清掉已选反应**：它们属于旧组，留着提交必被拒。
  /// [mainItemId] 传 null（没有项目了）表示取回全部定义。
  Future<void> _syncResponseScope(int? mainItemId) async {
    final services = ref.read(appServicesProvider).requireValue;
    try {
      final result = await services.records.fetchForm(
        state.patientNo,
        mainItemId: mainItemId,
      );
      // 切换作用域前先记下有没有已选反应 —— 有的话要提示用户重选。
      final hadResponse =
          state.responseTags.isNotEmpty || state.responseItems.isNotEmpty;
      state = state.copyWith(
        form: result.form,
        formFromCache: result.fromCache,
        responseTags: <String>{},
        responseItems: <String, dynamic>{},
        message: hadResponse
            ? '已按第一个项目切换患者反应范围，原先选择的反应需要重选'
            : state.message,
      );
    } on AppError {
      // 离线时拿不到新作用域：保留旧定义（至少能看能填），提交时服务端会兜底校验。
    }
  }

  void removeItemAt(int index) {
    final next = [...state.items]..removeAt(index);
    state = state.copyWith(items: next, dirty: true);
    // 删掉了第一个项目 → 反应作用域也跟着变（没项目了则取回全部）。
    final scopeChanged = index == 0 || next.isEmpty;
    if (scopeChanged) {
      unawaited(_syncResponseScope(next.isEmpty ? null : next.first.mainItemId));
    }
  }

  void setItemParam(int index, String paramKey, dynamic value) {
    final next = [...state.items];
    final item = next[index];
    final params = {...item.params};
    if (value == null || (value is String && value.isEmpty) || (value is List && value.isEmpty)) {
      // 空值不提交：服务端按"没填"处理，留着空串反而会写进快照。
      params.remove(paramKey);
    } else {
      params[paramKey] = value;
    }
    next[index] = RecordItemDraft(
      mainItemId: item.mainItemId,
      subItemId: item.subItemId,
      subItemName: item.subItemName,
      params: params,
    );
    state = state.copyWith(items: next, dirty: true);
  }

  void toggleResponseTag(String code) {
    final next = {...state.responseTags};
    next.contains(code) ? next.remove(code) : next.add(code);
    state = state.copyWith(responseTags: next, dirty: true);
  }

  void setResponseItem(String code, dynamic value) {
    final next = {...state.responseItems};
    if (value == null || (value is String && value.isEmpty)) {
      next.remove(code);
    } else {
      next[code] = value;
    }
    state = state.copyWith(responseItems: next, dirty: true);
  }

  void setNote(String value) => state = state.copyWith(note: value, dirty: true);

  void setDuration(int? minutes) =>
      state = state.copyWith(durationMin: minutes, dirty: true);

  void setDate(DateTime d) =>
      state = state.copyWith(recordDate: formatDate(d), dirty: true);

  void setPeriod(String? period) =>
      state = state.copyWith(sessionPeriod: period, dirty: true);

  void clearMessage() => state = state.copyWith(message: null, error: null);

  /// 必填校验：**只在提交时做**，草稿允许残缺（床旁先记一半很常见）。
  String? validateForSubmit() {
    if (state.items.isEmpty) return '至少需要一项治疗内容';
    for (final item in state.items) {
      final main = state.form?.mainItems
          .where((m) => m.id == item.mainItemId)
          .firstOrNull;
      final sub = main?.subItems.where((s) => s.id == item.subItemId).firstOrNull;
      if (sub == null) continue;
      for (final p in sub.params.where((p) => p.required)) {
        final v = item.params[p.paramKey];
        if (v == null || (v is String && v.isEmpty) || (v is List && v.isEmpty)) {
          return '「${sub.name}」的「${p.paramName}」是必填项';
        }
      }
    }
    return null;
  }

  /// 保存（草稿或提交）。
  ///
  /// **先本地 + 入队，再尽力推送一次**：床旁弱网也必须能存下来。
  Future<bool> save({required bool submit}) async {
    final services = ref.read(appServicesProvider).requireValue;
    final user = ref.read(currentUserProvider);
    if (user == null) {
      state = state.copyWith(error: '未登录');
      return false;
    }
    if (submit) {
      final problem = validateForSubmit();
      if (problem != null) {
        state = state.copyWith(error: problem);
        return false;
      }
    }

    state = state.copyWith(saving: true, error: null, message: null);
    try {
      final id = await services.records.saveDraft(
        existingId: state.existingId,
        patientNo: state.patientNo,
        therapistId: user.id,
        recordDate: state.recordDate,
        sessionPeriod: state.sessionPeriod,
        appointmentId: state.appointmentId,
        durationMin: state.durationMin,
        note: state.note,
        response: state.response,
        items: state.items,
        status: submit ? 'submitted' : 'draft',
      );

      final report = await services.sync.pushPending();
      ref.invalidate(localRecordsProvider(state.patientNo));
      ref.invalidate(pendingCountProvider);

      state = state.copyWith(
        saving: false,
        existingId: id,
        dirty: false,
        message: report.hasConflicts
            ? '已保存本地；有 ${report.conflicts.length} 条冲突待处理'
            : submit
                ? '已提交'
                : '草稿已保存（本地）',
        // 冲突是"要处理"的状态，用 error 样式更醒目。
        error: report.hasConflicts ? '有冲突待处理' : null,
      );
      return true;
    } on AppError catch (e) {
      ref.invalidate(localRecordsProvider(state.patientNo));
      ref.invalidate(pendingCountProvider);
      state = state.copyWith(
        saving: false,
        dirty: false,
        message: e.code == 'NETWORK_ERROR' ? '已存入本地，联网后自动上传' : '已存入本地（${e.message}）',
      );
      return true;
    }
  }
}

final recordEditorProvider =
    NotifierProvider<RecordEditorController, RecordEditorState>(
        RecordEditorController.new);
