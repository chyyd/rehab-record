import 'package:flutter_riverpod/flutter_riverpod.dart';

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

/// 同步动作的结果，供 UI 提示。
class PatientSyncState {
  const PatientSyncState({this.syncing = false, this.message, this.isError = false});

  final bool syncing;
  final String? message;
  final bool isError;
}

/// 手动/自动刷新：先把本地队列推出去，再拉患者列表与游标增量。
class PatientSyncController extends Notifier<PatientSyncState> {
  @override
  PatientSyncState build() => const PatientSyncState();

  /// **顺序很重要：先 push 再 pull。**
  ///
  /// 反过来的话，刚在本地录的记录会立刻被服务端返回的旧快照覆盖
  /// （拉回来的 payload 版本更低），表现为"我录的东西没了"。
  Future<void> refresh({bool pushFirst = true}) async {
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
      state = PatientSyncState(
        syncing: false,
        message: conflictNote ?? '已更新 $count 名患者',
        isError: conflictNote != null,
      );
    } on AppError catch (e) {
      state = PatientSyncState(
        syncing: false,
        isError: e.code != 'NETWORK_ERROR',
        // 离线不是错误状态，文案要中性（离线优先）。
        message: e.code == 'NETWORK_ERROR' ? '离线中，显示本地数据' : e.message,
      );
    }
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
