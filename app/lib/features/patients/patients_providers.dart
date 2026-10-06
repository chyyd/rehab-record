import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/core/disciplines.dart';
import 'package:rehab_app/core/error.dart';
import 'package:rehab_app/core/providers.dart';
import 'package:rehab_app/data/repo/patient_repository.dart';
import 'package:rehab_app/features/auth/auth_controller.dart';

/// 患者列表的筛选。
///
/// 注意这不是服务端 `scope` 的直接映射：服务端 `scope=dept` 拿全科，
/// 客户端再本地按归属分组。**已出院患者默认不出现**（服务端已过滤），
/// 本地还有一层软隐藏标记 `visible`（协议 §2）。
enum PatientFilter {
  /// 全科白板（默认）。
  dept('全科'),

  /// 归属我或未分配 —— 对应服务端 `scope=mine` + `unassigned` 的本地近似。
  mine('我的'),

  /// 仅未分配（可以认领的）。
  unassigned('未分配');

  const PatientFilter(this.label);
  final String label;
}

/// 当前筛选（未用 `StateProvider`：它在 Riverpod 3 里已归入 legacy）。
class PatientFilterController extends Notifier<PatientFilter> {
  @override
  PatientFilter build() => PatientFilter.dept;

  void set(PatientFilter value) => state = value;
}

final patientFilterProvider =
    NotifierProvider<PatientFilterController, PatientFilter>(PatientFilterController.new);

/// 搜索关键字（**本地过滤**，离线可用）。
class PatientKeywordController extends Notifier<String> {
  @override
  String build() => '';

  void set(String value) => state = value;
}

final patientKeywordProvider =
    NotifierProvider<PatientKeywordController, String>(PatientKeywordController.new);

/// 患者列表（**响应式** + 离线优先）。
///
/// ★ 用 `StreamProvider` 而不是 `FutureProvider`：后台首次同步落库之后，
/// Drift 的 `.watch()` 会自己重新发射。用一次性快照的话，实测会出现
/// "同步其实成功了（本地库有 14 名患者），但界面一直显示空列表，
/// 要手动下拉才出来" —— 床旁场景下等于看不到患者。
final patientListProvider = StreamProvider<List<PatientView>>((ref) {
  final services = ref.watch(appServicesProvider).requireValue;
  final filter = ref.watch(patientFilterProvider);
  final user = ref.watch(currentUserProvider);

  final visibleFilter = filter == PatientFilter.unassigned
      // 「未分配」由 `onlyMine` 之外的条件决定，这里取全量再本地筛。
      ? PatientFilter.dept
      : filter;

  return services.patients.watchLocal(
    onlyMine: visibleFilter == PatientFilter.mine,
    therapistId: user?.id,
  );
});

/// 在 [patientListProvider] 基础上套用「未分配」筛选与关键字（都在本地，离线可用）。
final filteredPatientListProvider = Provider<AsyncValue<List<PatientView>>>((ref) {
  final async = ref.watch(patientListProvider);
  final filter = ref.watch(patientFilterProvider);
  final keyword = ref.watch(patientKeywordProvider).trim().toLowerCase();

  // 用 switch **表达式**按当前状态派生（不用 `AsyncValue.map`：它在 Riverpod 3 里
  // 的回调带额外可选参数，写起来反而绕）。
  return switch (async) {
    AsyncData(:final value) => AsyncData<List<PatientView>>(
        _applyLocalFilters(value, filter: filter, keyword: keyword),
      ),
    AsyncError(:final error, :final stackTrace) =>
      AsyncError<List<PatientView>>(error, stackTrace),
    _ => const AsyncLoading<List<PatientView>>(),
  };
});

/// 「未分配」筛选与关键字匹配都在本地做，保证离线可用。
List<PatientView> _applyLocalFilters(
  List<PatientView> rows, {
  required PatientFilter filter,
  required String keyword,
}) {
  var result = rows;
  if (filter == PatientFilter.unassigned) {
    result = result.where((p) => p.assignedTherapistId == null).toList();
  }
  if (keyword.isNotEmpty) {
    result = result
        .where((p) =>
            p.name.toLowerCase().contains(keyword) ||
            p.inpatientNo.toLowerCase().contains(keyword))
        .toList();
  }
  return result;
}

/// 单患者详情（本地）。
final patientDetailProvider =
    FutureProvider.family<PatientView?, String>((ref, inpatientNo) async {
  final services = ref.watch(appServicesProvider).requireValue;
  return services.patients.findByNo(inpatientNo);
});

// --------------------------------------------------------------------------- //
// 四大类摘要（患者详情页的"记录治疗"区域）
// --------------------------------------------------------------------------- //

/// 一个大类的状态摘要（详情页按钮上要显示的那两个数字）。
///
/// 数据直接来自记录表单接口 —— 它本来就返回 `total_daily`（该大类已记录次数）
/// 与 `days_until_reassessment`（距复评应做日还有几天），
/// 以及 `pending_document`（点进去会先弹哪份评估文书）。
/// **不本地重算**：序号/复评口径的唯一真源在服务端。
///
/// 2026-10-06：复评周期从"每 20 次日常"改成"30 个自然日"，
/// 所以摘要里带的是**天**而不是次数。
class DisciplineSummary {
  const DisciplineSummary({
    required this.key,
    required this.name,
    this.totalDaily = 0,
    this.daysUntilReassessment,
    this.reassessmentIntervalDays = 30,
    this.pendingDocument,
    this.pendingDocumentLabel,
    this.fromCache = false,
    this.error,
  });

  final String key;
  final String name;
  final int totalDaily;

  /// 距复评应做日还有几天（负数 = 已逾期；null = 该大类还没有评估）。
  final int? daysUntilReassessment;
  final int reassessmentIntervalDays;

  /// 非 null 表示"点进去要先填这份评估文书"（首评 / 复评）。
  final String? pendingDocument;
  final String? pendingDocumentLabel;

  /// 数据是否来自离线缓存。
  final bool fromCache;

  /// 取不到时（离线且没缓存过）的提示。
  final String? error;

  bool get needsDocument => pendingDocument != null;
}

/// 四个大类各自的摘要（并发取，互不阻塞）。
///
/// 每个大类一次 `GET /records/form`：请求很小，换来的是**准确**的次数与复评倒计时，
/// 同时顺带把该大类的表单缓存到本地（之后点进记录页即使断网也能打开）。
final disciplineSummariesProvider =
    FutureProvider.family<List<DisciplineSummary>, String>((ref, patientNo) async {
  final services = ref.watch(appServicesProvider).requireValue;
  return Future.wait(
    Discipline.all.map((d) async {
      try {
        final result = await services.records.fetchForm(patientNo, d.key);
        return DisciplineSummary(
          key: d.key,
          name: result.form.disciplineName.isEmpty
              ? d.name
              : result.form.disciplineName,
          totalDaily: result.form.totalDaily,
          daysUntilReassessment: result.form.daysUntilReassessment,
          reassessmentIntervalDays: result.form.reassessmentIntervalDays,
          pendingDocument: result.form.pendingDocument,
          pendingDocumentLabel: result.form.pendingDocumentLabel,
          fromCache: result.fromCache,
        );
      } on AppError catch (e) {
        // 一个大类取不到不该让整块区域消失：如实说明，按钮照样可点
        //（点进去会自己再取一次表单）。
        return DisciplineSummary(
          key: d.key,
          name: d.name,
          error: e.code == 'NETWORK_ERROR' ? '离线' : e.message,
        );
      }
    }),
  );
});

/// 同步动作的结果，供 UI 提示。
class PatientSyncState {
  const PatientSyncState({
    this.syncing = false,
    this.message,
    this.isError = false,
    this.lastFailed = false,
    this.messageSeq = 0,
  });

  final bool syncing;
  final String? message;
  final bool isError;

  /// 上一次同步是否**因故障失败**（离线/服务端不可达）。
  ///
  /// 与 [isError] 分开：`isError` 是**给用户看的**（冲突也算"需要注意"），
  /// 而 [lastFailed] 只用于**决定要不要退避**。
  /// 冲突不该让定时同步退避 —— 那只是有一条要人处理，网络是好的。
  final bool lastFailed;

  /// 消息序号：**每出现一条新提示就 +1**。
  ///
  /// 顶部横幅靠它做 `ValueKey`，从而"每条新消息重新计时渐隐"。
  /// 用 `message` 本身当 key 是不行的：同一个文案（如连续两次「已更新 6 名患者」）
  /// 会被当成同一条，横幅不再重新计时，第二次就"闪一下就没"甚至不显示。
  final int messageSeq;
}

/// 手动/自动刷新：先把本地队列推出去，再拉患者列表与游标增量。
class PatientSyncController extends Notifier<PatientSyncState> {
  @override
  PatientSyncState build() => const PatientSyncState();

  /// 正在进行的同步。**必须防重入**。
  ///
  /// 加了 30 秒定时同步之后（2026-10-06），并发调用从"可能"变成了"必然"：
  /// 定时器到点时用户可能正好点了同步按钮、或刚从详情页返回触发了 `didPopNext`。
  ///
  /// 不加防护的后果不只是浪费流量：`pushPending` 会**重推整个离线队列**，
  /// 两条并发链路可能对同一条记录各推一次 —— 服务端靠 `client_uuid` 幂等能挡住，
  /// 但两条链路的 `pullIncremental` 会互相覆盖游标，还会把 UI 状态刷成"已更新"，
  /// 让人以为同步成功了（其实另一条失败了）。
  ///
  /// 所以这里让**后来者等待同一次同步**（而不是各自再跑一遍，也不是直接丢弃）——
  /// 调用方拿到的结果始终是"一次真实的同步结果"。
  Future<void>? _inFlight;

  /// 连续离线/故障次数（成功一次即归零）。
  ///
  /// ★ 2026-10-06 用户：「连续多次离线后安静下来、不再提示」。
  ///
  /// 治疗师回家后 App 仍在跑定时同步，每 30 秒失败一次 ——
  /// 如果每次都把「离线中，显示本地数据」推上顶部横幅，会一直闪，
  /// 而这条信息他早就知道了（离线优先本来就是设计目标）。
  ///
  /// 所以连续失败到一定次数后**不再更新提示**（同步照跑，只是不吵），
  /// 直到成功或用户主动同步为止。
  int _consecutiveFailures = 0;

  /// 每出现一条新提示就 +1（见 [PatientSyncState.messageSeq]）。
  int _messageSeq = 0;

  /// 连续失败多少次后不再提示。
  static const int quietAfterFailures = 3;

  /// **顺序很重要：先 push 再 pull。**
  ///
  /// 反过来的话，刚在本地录的记录会立刻被服务端返回的旧快照覆盖
  /// （拉回来的 payload 版本更低），表现为"我录的东西没了"。
  ///
  /// [announce]：这次同步要不要把**成功结果**写进顶部提示。
  ///
  /// - **手动**（下拉刷新、同步按钮、返回页面）：`true` —— 用户正等着反馈；
  /// - **定时**：`false` —— 每 30 秒顶一条「已更新 N 名患者」会一直闪，
  ///   而"上次同步时间"在「我的」页随时看得到。
  ///
  /// **冲突不受 [announce] 影响，永远提示** —— 那需要人做决定，
  /// 不能被"安静"策略吞掉。
  Future<void> refresh({bool pushFirst = true, bool announce = true}) {
    // 已有同步在跑 → 共用它（并发调用拿到的是同一个结果）
    return _inFlight ??=
        _runRefresh(pushFirst: pushFirst, announce: announce).whenComplete(() {
      _inFlight = null;
    });
  }

  Future<void> _runRefresh({
    required bool pushFirst,
    required bool announce,
  }) async {
    final services = ref.read(appServicesProvider).requireValue;
    state = const PatientSyncState(syncing: true);
    try {
      String? conflictNote;
      if (pushFirst) {
        final report = await services.sync.pushPending();
        if (report.hasConflicts) {
          conflictNote = '有 ${report.conflicts.length} 条冲突待处理';
        }
      }
      final count = await services.patients.refreshFromServer();
      await services.sync.pullIncremental();
      // 不需要手动 invalidate：patientListProvider 是 Drift 流，落库即自动重建。
      ref.invalidate(pendingCountProvider);
      ref.invalidate(lastPatientSyncProvider);

      _consecutiveFailures = 0;
      final successMessage = conflictNote ?? (announce ? '已更新 $count 名患者' : null);
      if (successMessage != null) _messageSeq += 1;
      state = PatientSyncState(
        syncing: false,
        // 冲突永远报；成功只在"用户主动要反馈"时报。
        message: successMessage,
        messageSeq: _messageSeq,
        isError: conflictNote != null,
      );
    } on AppError catch (e) {
      final offline = e.code == 'NETWORK_ERROR';
      _consecutiveFailures += 1;

      // 连续失败够多就**不再提示**（同步照跑）。用 `null` 而不是空串：
      // 空串会让横幅渲染成一条空白条，比不显示更难看。
      final quiet = offline && _consecutiveFailures > quietAfterFailures;
      final failMessage = quiet ? null : (offline ? '离线中，显示本地数据' : e.message);
      if (failMessage != null) _messageSeq += 1;
      state = PatientSyncState(
        syncing: false,
        isError: !offline,
        lastFailed: true,
        // 离线不是错误状态，文案要中性（离线优先）。
        message: failMessage,
        messageSeq: _messageSeq,
      );
    }
  }

  /// 定时同步用：**不抛异常**，只回报成败（失败已写进 [state]）。
  ///
  /// 不能让 `refresh()` 本身抛：它的调用方（`initState` 的 post-frame、
  /// `didPopNext`、按钮 `onPressed`）都**没有 catch** —— 抛出会变成未处理异常，
  /// 在 Flutter 里是一条刺眼的红屏日志，而不是一次安静的失败重试。
  ///
  /// `announce: false`：定时同步不报成功（只报失败与冲突）。
  Future<bool> refreshQuietly() async {
    await refresh(announce: false);
    return !state.lastFailed;
  }

  void clearMessage() => state = const PatientSyncState();
}

final patientSyncControllerProvider =
    NotifierProvider<PatientSyncController, PatientSyncState>(PatientSyncController.new);

/// 上次患者同步时间（提示"数据可能不是最新"）。
final lastPatientSyncProvider = FutureProvider<DateTime?>((ref) async {
  final services = ref.watch(appServicesProvider).requireValue;
  return services.patients.lastSyncedAt();
});

/// 待同步条数（离线队列长度），供 UI 显示"待同步 N 条"。
final pendingCountProvider = FutureProvider<int>((ref) async {
  final services = ref.watch(appServicesProvider).requireValue;
  return services.sync.pendingCount();
});
