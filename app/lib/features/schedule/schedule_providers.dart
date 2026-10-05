import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/core/date_utils.dart';
import 'package:rehab_app/core/error.dart';
import 'package:rehab_app/core/providers.dart';
import 'package:rehab_app/data/remote/schedule_dto.dart';
import 'package:rehab_app/features/auth/auth_controller.dart';
import 'package:rehab_app/features/patients/patients_providers.dart';

/// 当前查看的周（以周内任意一天表示）。
class ScheduleWeekController extends Notifier<DateTime> {
  @override
  DateTime build() => startOfDay(DateTime.now());

  void setWeekOf(DateTime day) => state = startOfDay(day);

  void previousWeek() => state = state.subtract(const Duration(days: 7));

  void nextWeek() => state = state.add(const Duration(days: 7));

  void today() => state = startOfDay(DateTime.now());
}

final scheduleWeekProvider =
    NotifierProvider<ScheduleWeekController, DateTime>(ScheduleWeekController.new);

/// 是否只看自己的排期。
///
/// 默认**只看自己**：治疗师最关心"我的格子"。但他**有权**看全科
/// （服务端 `_require_can_view_schedule` 全开，床旁协作需要知道谁在哪），
/// 所以给一个开关。
class ScheduleScopeController extends Notifier<bool> {
  @override
  bool build() => true;

  void set(bool onlyMine) => state = onlyMine;
}

final scheduleOnlyMineProvider =
    NotifierProvider<ScheduleScopeController, bool>(ScheduleScopeController.new);

/// 当前周 + 范围的日期边界。
final scheduleRangeProvider = Provider<({String from, String to, List<DateTime> days})>((ref) {
  final week = ref.watch(scheduleWeekProvider);
  final days = weekDays(week);
  return (
    from: formatDate(days.first),
    to: formatDate(days.last),
    days: days,
  );
});

/// 本地排期（响应式，离线可用）。
final scheduleAppointmentsProvider =
    StreamProvider<List<Appointment>>((ref) {
  final services = ref.watch(appServicesProvider).requireValue;
  final range = ref.watch(scheduleRangeProvider);
  final onlyMine = ref.watch(scheduleOnlyMineProvider);
  final user = ref.watch(currentUserProvider);

  return services.schedule.watchLocal(
    dateFrom: range.from,
    dateTo: range.to,
    therapistId: onlyMine ? user?.id : null,
  );
});

/// 可排性（含休息/请假，以及格子内已有排期）。
///
/// 只在联网时可用；失败不阻塞页面（格子仍可从本地排期渲染出来）。
final scheduleAvailabilityProvider =
    FutureProvider<List<SlotAvailability>>((ref) async {
  final services = ref.watch(appServicesProvider).requireValue;
  final range = ref.watch(scheduleRangeProvider);
  final onlyMine = ref.watch(scheduleOnlyMineProvider);
  final user = ref.watch(currentUserProvider);

  return services.schedule.fetchAvailability(
    dateFrom: range.from,
    dateTo: range.to,
    therapistId: onlyMine ? user?.id : null,
  );
});

/// 排期页的同步动作状态。
class ScheduleSyncState {
  const ScheduleSyncState({this.busy = false, this.message, this.isError = false});

  final bool busy;
  final String? message;
  final bool isError;
}

class ScheduleSyncController extends Notifier<ScheduleSyncState> {
  @override
  ScheduleSyncState build() => const ScheduleSyncState();

  /// 刷新当前周的排期与可排性。
  Future<void> refresh() async {
    final services = ref.read(appServicesProvider).requireValue;
    final range = ref.read(scheduleRangeProvider);
    state = const ScheduleSyncState(busy: true);
    try {
      final n = await services.schedule.refreshFromServer(
        dateFrom: range.from,
        dateTo: range.to,
      );
      ref.invalidate(scheduleAvailabilityProvider);
      state = ScheduleSyncState(busy: false, message: '已更新 $n 条排期');
    } on AppError catch (e) {
      state = ScheduleSyncState(
        busy: false,
        isError: e.code != 'NETWORK_ERROR',
        message: e.code == 'NETWORK_ERROR' ? '离线中，显示本地排期' : e.message,
      );
    }
  }

  /// 新建排期：**本地先落库、并入离线队列**（弱网也能排班），随后尽力推送一次。
  Future<bool> create(AppointmentDraft draft) async {
    final services = ref.read(appServicesProvider).requireValue;
    final user = ref.read(currentUserProvider);
    if (user == null) {
      state = const ScheduleSyncState(isError: true, message: '未登录');
      return false;
    }

    state = const ScheduleSyncState(busy: true);
    try {
      await services.schedule.createLocal(draft, therapistId: user.id);
      // 立刻尝试推一次；失败也不回滚（离线优先，队列会重试）。
      final report = await services.sync.pushPending();
      ref.invalidate(scheduleAvailabilityProvider);
      ref.invalidate(pendingCountProvider);
      state = ScheduleSyncState(
        busy: false,
        message: report.hasConflicts
            ? '已排期；有 ${report.conflicts.length} 条冲突待处理'
            : '已排期',
        isError: report.hasConflicts,
      );
      return true;
    } on AppError catch (e) {
      // 离线也算成功：本地已经有了，队列会补推。
      ref.invalidate(scheduleAvailabilityProvider);
      ref.invalidate(pendingCountProvider);
      state = ScheduleSyncState(
        busy: false,
        message: e.code == 'NETWORK_ERROR' ? '已存入本地，联网后自动上传' : '已存入本地（${e.message}）',
        isError: e.code != 'NETWORK_ERROR',
      );
      return true;
    }
  }

  /// 取消排期（本地置 cancelled + 入队）。
  Future<void> cancel(int appointmentId) async {
    final services = ref.read(appServicesProvider).requireValue;
    state = const ScheduleSyncState(busy: true);
    try {
      await services.schedule.cancelLocal(appointmentId);
      await services.sync.pushPending();
      ref.invalidate(scheduleAvailabilityProvider);
      ref.invalidate(pendingCountProvider);
      state = const ScheduleSyncState(message: '已取消');
    } on AppError catch (e) {
      ref.invalidate(scheduleAvailabilityProvider);
      ref.invalidate(pendingCountProvider);
      state = ScheduleSyncState(
        message: e.code == 'NETWORK_ERROR' ? '已本地取消，联网后同步' : e.message,
        isError: e.code != 'NETWORK_ERROR',
      );
    }
  }

  void clearMessage() => state = const ScheduleSyncState();
}

final scheduleSyncControllerProvider =
    NotifierProvider<ScheduleSyncController, ScheduleSyncState>(ScheduleSyncController.new);
