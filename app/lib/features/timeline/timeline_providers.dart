import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/core/date_utils.dart';
import 'package:rehab_app/core/error.dart';
import 'package:rehab_app/core/providers.dart';
import 'package:rehab_app/data/remote/timeline_dto.dart';

/// 时间轴的可见范围。
///
/// 与服务端 `scope` 一一对应：
///  - `visible`：我能看到的全部患者（全科协作视图）；
///  - `mine`：只有我写的记录；
///  - `temp`：只看"临时治疗"（记录人 ≠ 患者归属人）——治疗师在单日假期间
///    接管他人患者后需要复查的部分。
enum TimelineScope {
  visible('全科', 'visible'),
  mine('我写的', 'mine'),
  temp('临时治疗', 'temp');

  const TimelineScope(this.label, this.wire);
  final String label;
  final String wire;
}

/// 时间轴筛选条件。
class TimelineFilter {
  const TimelineFilter({
    this.scope = TimelineScope.visible,
    this.dateFrom,
    this.dateTo,
    this.mainItemId,
    this.mainItemName,
  });

  final TimelineScope scope;
  final String? dateFrom;
  final String? dateTo;
  final int? mainItemId;
  final String? mainItemName;

  bool get hasDateRange => dateFrom != null || dateTo != null;

  TimelineFilter copyWith({
    TimelineScope? scope,
    Object? dateFrom = _sentinel,
    Object? dateTo = _sentinel,
    Object? mainItemId = _sentinel,
    Object? mainItemName = _sentinel,
  }) =>
      TimelineFilter(
        scope: scope ?? this.scope,
        dateFrom: dateFrom == _sentinel ? this.dateFrom : dateFrom as String?,
        dateTo: dateTo == _sentinel ? this.dateTo : dateTo as String?,
        mainItemId: mainItemId == _sentinel ? this.mainItemId : mainItemId as int?,
        mainItemName:
            mainItemName == _sentinel ? this.mainItemName : mainItemName as String?,
      );

  /// 与 [other] 是否"同一批数据"（用于判断要不要重置分页）。
  bool sameQuery(TimelineFilter other) =>
      other.scope == scope &&
      other.dateFrom == dateFrom &&
      other.dateTo == dateTo &&
      other.mainItemId == mainItemId;
}

const Object _sentinel = Object();

/// 时间轴列表状态（累积分页）。
class TimelineState {
  const TimelineState({
    this.items = const [],
    this.total = 0,
    this.page = 0,
    this.loadingMore = false,
    this.initialLoading = true,
    this.error,
  });

  final List<TimelineItem> items;
  final int total;

  /// 已加载到第几页（0 表示还没加载）。
  final int page;

  final bool loadingMore;
  final bool initialLoading;
  final String? error;

  bool get hasMore => items.length < total;
  bool get isEmpty => items.isEmpty && !initialLoading;
}

/// 时间轴控制器。
///
/// 用 `AsyncNotifier`：它天然带 loading/error 状态，且 `build()` 里 `watch` 到
/// 筛选条件变化时会**自动重建**（不需要手写 invalidate），筛选切换因此不会漏刷新。
class TimelineController extends AsyncNotifier<TimelineState> {
  static const int _pageSize = 20;

  TimelineFilter get _filter => ref.read(timelineFilterProvider);

  @override
  Future<TimelineState> build() async {
    final filter = ref.watch(timelineFilterProvider);
    return _fetchFirstPage(filter);
  }

  Future<TimelineState> _fetchFirstPage(TimelineFilter filter) async {
    final services = ref.read(appServicesProvider).requireValue;
    final page = await services.timeline.fetchTimeline(
      page: 1,
      pageSize: _pageSize,
      scope: filter.scope.wire,
      dateFrom: filter.dateFrom,
      dateTo: filter.dateTo,
      mainItemId: filter.mainItemId,
    );
    return TimelineState(
      items: page.items,
      total: page.total,
      page: 1,
      initialLoading: false,
    );
  }

  /// 加载下一页（滚动到底部时调用）。
  Future<void> loadMore() async {
    // Riverpod 3 里是 `.value`（`valueOrNull` 已移除）。
    final current = state.value;
    if (current == null || current.loadingMore || !current.hasMore) return;

    state = AsyncData(TimelineState(
      items: current.items,
      total: current.total,
      page: current.page,
      initialLoading: false,
      loadingMore: true,
    ));

    final filter = _filter;
    try {
      final services = ref.read(appServicesProvider).requireValue;
      final page = await services.timeline.fetchTimeline(
        page: current.page + 1,
        pageSize: _pageSize,
        scope: filter.scope.wire,
        dateFrom: filter.dateFrom,
        dateTo: filter.dateTo,
        mainItemId: filter.mainItemId,
      );
      state = AsyncData(TimelineState(
        items: [...current.items, ...page.items],
        total: page.total,
        page: current.page + 1,
        initialLoading: false,
      ));
    } on AppError catch (e) {
      // 追加失败不该清空已加载的内容：保留列表，只在末尾给个错误。
      state = AsyncData(TimelineState(
        items: current.items,
        total: current.total,
        page: current.page,
        initialLoading: false,
        error: e.message,
      ));
    }
  }

  /// 下拉刷新（回到第一页）。
  Future<void> refresh() async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(() => _fetchFirstPage(_filter));
  }
}

final timelineFilterProvider =
    NotifierProvider<TimelineFilterController, TimelineFilter>(
        TimelineFilterController.new);

class TimelineFilterController extends Notifier<TimelineFilter> {
  @override
  TimelineFilter build() => const TimelineFilter();

  void setScope(TimelineScope scope) => state = state.copyWith(scope: scope);

  void setDateRange(DateTime? from, DateTime? to) => state = state.copyWith(
        dateFrom: from == null ? null : formatDate(from),
        dateTo: to == null ? null : formatDate(to),
      );

  void clearDateRange() => state = state.copyWith(dateFrom: null, dateTo: null);

  void setMainItem(int? id, String? name) =>
      state = state.copyWith(mainItemId: id, mainItemName: name);

  void reset() => state = const TimelineFilter();
}

final timelineControllerProvider =
    AsyncNotifierProvider<TimelineController, TimelineState>(
        TimelineController.new);

// --------------------------------------------------------------------------- //
// 汇总
// --------------------------------------------------------------------------- //

/// 汇总页的日期（默认今天）。
class SummaryDateController extends Notifier<DateTime> {
  @override
  DateTime build() => DateTime.now();

  void set(DateTime day) => state = day;

  void shift(int days) => state = state.add(Duration(days: days));

  void today() => state = DateTime.now();
}

final summaryDateProvider =
    NotifierProvider<SummaryDateController, DateTime>(SummaryDateController.new);

/// 汇总分组方式：按治疗师 / 按患者。
class SummaryGroupByController extends Notifier<String> {
  @override
  String build() => 'therapist';

  void toggle() =>
      state = state == 'therapist' ? 'patient' : 'therapist';
}

final summaryGroupByProvider =
    NotifierProvider<SummaryGroupByController, String>(SummaryGroupByController.new);

/// 按日期汇总。
final dateSummaryProvider = FutureProvider<DateSummary>((ref) async {
  final services = ref.watch(appServicesProvider).requireValue;
  final day = ref.watch(summaryDateProvider);
  final groupBy = ref.watch(summaryGroupByProvider);
  return services.timeline.fetchDateSummary(
    date: formatDate(day),
    groupBy: groupBy,
  );
});

/// 按患者每日汇总（患者详情/时间轴里点进去看）。
final patientDailySummaryProvider =
    FutureProvider.family<PatientDailySummary, String>((ref, inpatientNo) async {
  final services = ref.watch(appServicesProvider).requireValue;
  return services.timeline.fetchPatientDaily(inpatientNo);
});

// --------------------------------------------------------------------------- //
// 打印（PDF）
// --------------------------------------------------------------------------- //

/// 打印动作状态。
class PrintState {
  const PrintState({this.busy = false, this.message, this.isError = false, this.path});

  final bool busy;
  final String? message;
  final bool isError;

  /// 下载到本地的文件路径（成功时非空）。
  final String? path;
}

class PrintController extends Notifier<PrintState> {
  @override
  PrintState build() => const PrintState();

  /// 下载并交给系统阅读器打开。
  ///
  /// 文件名带上时间戳：同一份汇总打印两次不该互相覆盖，
  /// 而且治疗师可能会把两份都发给护士站对比。
  Future<void> downloadAndOpen({
    required String path,
    required String filenamePrefix,
    Map<String, dynamic>? query,
  }) async {
    state = const PrintState(busy: true);
    try {
      final services = ref.read(appServicesProvider).requireValue;
      final stamp = DateTime.now()
          .toIso8601String()
          .substring(0, 19)
          .replaceAll(RegExp(r'[:\-T]'), '');
      final file = await services.timeline.downloadPdf(
        path: path,
        filename: '${filenamePrefix}_$stamp.pdf',
        query: query,
      );
      // 只显示文件名：完整路径是应用私有目录（/data/user/0/...），
      // 对治疗师没有意义，反而像是出错了。要打开就用旁边的按钮。
      state = PrintState(
        message: 'PDF 已生成：${file.uri.pathSegments.last}',
        path: file.path,
      );
    } on AppError catch (e) {
      state = PrintState(
        isError: true,
        message: e.code == 'NETWORK_ERROR' ? '离线中，打印需要联网' : e.message,
      );
    }
  }

  void clear() => state = const PrintState();
}

final printControllerProvider =
    NotifierProvider<PrintController, PrintState>(PrintController.new);
