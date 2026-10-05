import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/core/date_utils.dart';
import 'package:rehab_app/core/providers.dart';
import 'package:rehab_app/core/worktime.dart';
import 'package:rehab_app/data/remote/schedule_dto.dart';
import 'package:rehab_app/data/repo/patient_repository.dart';
import 'package:rehab_app/features/auth/auth_controller.dart';
import 'package:rehab_app/features/schedule/schedule_providers.dart';

/// 排期页：**半日格子**（日期为列、上午/下午为行）。
///
/// ## 2026-10-03 起的语义（与旧版最大的区别）
///
/// 半日格子**不再互斥**：一个格子可以有多台（同一治疗师多台、或同一患者被多个
/// 治疗师各排一台）。所以：
///  - 格子里显示的是**已有几台**，不是"被占用"；
///  - 只有**休息块**与**生效请假**会让格子置灰（服务端给 `available=false`）；
///  - 不再有"拖完才发现冲突"，因为冲突只剩休息/请假两类。
class SchedulePage extends ConsumerWidget {
  const SchedulePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final week = ref.watch(scheduleWeekProvider);
    final range = ref.watch(scheduleRangeProvider);
    final onlyMine = ref.watch(scheduleOnlyMineProvider);
    final appointments = ref.watch(scheduleAppointmentsProvider);
    final availability = ref.watch(scheduleAvailabilityProvider);
    final sync = ref.watch(scheduleSyncControllerProvider);

    // 按 (日期, 半日) 归拢本地排期 —— 格子要显示"有几台、都是谁"。
    final bySlot = <String, List<Appointment>>{};
    for (final a in appointments.value ?? const <Appointment>[]) {
      bySlot.putIfAbsent('${a.date}|${a.period}', () => []).add(a);
    }

    // 可排性按格子索引（服务端返回的可能比本地排期更全：含休息/请假）。
    final availBySlot = <String, SlotAvailability>{};
    for (final s in availability.value ?? const <SlotAvailability>[]) {
      availBySlot['${s.date}|${s.period}'] = s;
    }

    return Column(
      children: [
        _WeekBar(
          week: week,
          onlyMine: onlyMine,
          busy: sync.busy,
          onPrev: () => ref.read(scheduleWeekProvider.notifier).previousWeek(),
          onNext: () => ref.read(scheduleWeekProvider.notifier).nextWeek(),
          onToday: () => ref.read(scheduleWeekProvider.notifier).today(),
          onToggleScope: (v) => ref.read(scheduleOnlyMineProvider.notifier).set(v),
          onRefresh: () => ref.read(scheduleSyncControllerProvider.notifier).refresh(),
        ),
        if (sync.message != null)
          _MessageBar(
            text: sync.message!,
            isError: sync.isError,
            onDismiss: () => ref.read(scheduleSyncControllerProvider.notifier).clearMessage(),
          ),
        if (availability.hasError)
          _MessageBar(
            text: '可排性暂时取不到（离线中）；休息/请假判断可能不是最新',
            isError: false,
            onDismiss: () => ref.invalidate(scheduleAvailabilityProvider),
          ),
        Expanded(
          child: RefreshIndicator(
            onRefresh: () => ref.read(scheduleSyncControllerProvider.notifier).refresh(),
            child: SingleChildScrollView(
              physics: const AlwaysScrollableScrollPhysics(),
              child: Padding(
                padding: const EdgeInsets.all(8),
                child: Column(
                  children: [
                    _HeaderRow(days: range.days, week: week),
                    for (final period in kPeriods)
                      _PeriodRow(
                        period: period,
                        days: range.days,
                        bySlot: bySlot,
                        availBySlot: availBySlot,
                        onTapSlot: (day, p) => _openSlot(context, ref, day, p),
                      ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }

  /// 点格子 → 底部弹层：列出格子内已有排期，并可新建。
  Future<void> _openSlot(BuildContext context, WidgetRef ref, DateTime day, String period) async {
    final date = formatDate(day);
    final appointments = ref.read(scheduleAppointmentsProvider).value ?? const <Appointment>[];
    final slot = appointments
        .where((a) => a.date == date && a.period == period)
        .toList();
    final avail = (ref.read(scheduleAvailabilityProvider).value ?? const <SlotAvailability>[])
        .where((s) => s.date == date && s.period == period)
        .firstOrNull;

    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _SlotSheet(
        date: date,
        period: period,
        appointments: slot,
        availability: avail,
      ),
    );
  }
}

class _WeekBar extends StatelessWidget {
  const _WeekBar({
    required this.week,
    required this.onlyMine,
    required this.busy,
    required this.onPrev,
    required this.onNext,
    required this.onToday,
    required this.onToggleScope,
    required this.onRefresh,
  });

  final DateTime week;
  final bool onlyMine;
  final bool busy;
  final VoidCallback onPrev;
  final VoidCallback onNext;
  final VoidCallback onToday;
  final ValueChanged<bool> onToggleScope;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    final days = weekDays(week);
    final label = '${shortDate(days.first)} – ${shortDate(days.last)}';
    return Padding(
      padding: const EdgeInsets.fromLTRB(8, 6, 8, 0),
      child: Row(
        children: [
          IconButton(onPressed: onPrev, icon: const Icon(Icons.chevron_left), tooltip: '上一周'),
          Expanded(
            child: Text(
              label,
              textAlign: TextAlign.center,
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
          ),
          IconButton(onPressed: onNext, icon: const Icon(Icons.chevron_right), tooltip: '下一周'),
          TextButton(onPressed: onToday, child: const Text('本周')),
          IconButton(
            onPressed: busy ? null : onRefresh,
            tooltip: '刷新',
            icon: busy
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.sync),
          ),
          // 只看自己 / 看全科：服务端允许治疗师看全科（床旁协作需要知道谁在哪）。
          Tooltip(
            message: onlyMine ? '只看我的' : '看全科',
            child: Switch(
              value: onlyMine,
              onChanged: onToggleScope,
            ),
          ),
        ],
      ),
    );
  }
}

class _HeaderRow extends StatelessWidget {
  const _HeaderRow({required this.days, required this.week});

  final List<DateTime> days;
  final DateTime week;

  @override
  Widget build(BuildContext context) {
    final today = formatDate(DateTime.now());
    return Row(
      children: [
        const SizedBox(width: 52),
        for (final d in days)
          Expanded(
            child: Container(
              padding: const EdgeInsets.symmetric(vertical: 6),
              decoration: BoxDecoration(
                color: formatDate(d) == today
                    ? Theme.of(context).colorScheme.primaryContainer
                    : null,
                borderRadius: BorderRadius.circular(6),
              ),
              child: Column(
                children: [
                  Text(weekdayLabel(d), style: const TextStyle(fontSize: 11)),
                  Text(
                    shortDate(d),
                    style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }
}

class _PeriodRow extends StatelessWidget {
  const _PeriodRow({
    required this.period,
    required this.days,
    required this.bySlot,
    required this.availBySlot,
    required this.onTapSlot,
  });

  final String period;
  final List<DateTime> days;
  final Map<String, List<Appointment>> bySlot;
  final Map<String, SlotAvailability> availBySlot;
  final void Function(DateTime day, String period) onTapSlot;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 52,
            child: Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Text(
                periodLabel(period),
                style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
              ),
            ),
          ),
          for (final day in days)
            Expanded(
              child: _SlotCell(
                appointments: bySlot['${formatDate(day)}|$period'] ?? const [],
                availability: availBySlot['${formatDate(day)}|$period'],
                onTap: () => onTapSlot(day, period),
              ),
            ),
        ],
      ),
    );
  }
}

class _SlotCell extends StatelessWidget {
  const _SlotCell({required this.appointments, required this.availability, required this.onTap});

  final List<Appointment> appointments;
  final SlotAvailability? availability;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    // 只有休息/请假会让格子不可排；"已有排期"不置灰（格子不再互斥）。
    final blocked = availability?.available == false;
    final count = appointments.isEmpty
        ? (availability?.appointmentCount ?? 0)
        : appointments.length;

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 2),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(6),
        child: Container(
          constraints: const BoxConstraints(minHeight: 64),
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
          decoration: BoxDecoration(
            color: blocked
                ? scheme.surfaceContainerHighest
                : count > 0
                    ? scheme.secondaryContainer
                    : scheme.surfaceContainerLow,
            borderRadius: BorderRadius.circular(6),
            border: Border.all(
              color: blocked ? scheme.outlineVariant : scheme.outlineVariant.withValues(alpha: 0.5),
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (blocked)
                Row(
                  children: [
                    Icon(Icons.block, size: 12, color: scheme.outline),
                    const SizedBox(width: 2),
                    Flexible(
                      child: Text(
                        availability?.unavailableReasonLabel ?? '不可排',
                        style: TextStyle(fontSize: 10, color: scheme.outline),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                )
              else if (count == 0)
                Icon(Icons.add, size: 14, color: scheme.outline)
              else ...[
                Text(
                  '$count 台',
                  style: TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.bold,
                    color: scheme.onSecondaryContainer,
                  ),
                ),
                const SizedBox(height: 2),
                // 最多列两个名字，其余用 +N 表示（格子很小，宁可少显示也不要挤爆）。
                for (final a in appointments.take(2))
                  Text(
                    a.patientName ?? a.patientNo,
                    style: const TextStyle(fontSize: 10),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                if (appointments.length > 2)
                  Text('+${appointments.length - 2}', style: const TextStyle(fontSize: 10)),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _MessageBar extends StatelessWidget {
  const _MessageBar({required this.text, required this.isError, required this.onDismiss});

  final String text;
  final bool isError;
  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      width: double.infinity,
      color: isError ? scheme.errorContainer : scheme.secondaryContainer,
      padding: const EdgeInsets.only(left: 12, right: 4),
      child: Row(
        children: [
          Icon(isError ? Icons.warning_amber_outlined : Icons.info_outline, size: 16),
          const SizedBox(width: 8),
          Expanded(child: Text(text, style: const TextStyle(fontSize: 13))),
          IconButton(
            icon: const Icon(Icons.close, size: 16),
            onPressed: onDismiss,
            tooltip: '关闭',
            visualDensity: VisualDensity.compact,
          ),
        ],
      ),
    );
  }
}

/// 点开一个半日格子：看已有排期 / 新建。
class _SlotSheet extends ConsumerWidget {
  const _SlotSheet({
    required this.date,
    required this.period,
    required this.appointments,
    required this.availability,
  });

  final String date;
  final String period;
  final List<Appointment> appointments;
  final SlotAvailability? availability;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final blocked = availability?.available == false;
    final scheme = Theme.of(context).colorScheme;

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '${shortDateFromIso(date)} ${periodLabel(period)}',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 4),
            Text(
              blocked
                  ? '该半日不可排：${availability?.unavailableReasonLabel ?? ''}'
                  : '该半日可排；已有 ${appointments.length} 台（同一格子可以多台）',
              style: TextStyle(
                fontSize: 13,
                color: blocked ? scheme.error : scheme.outline,
              ),
            ),
            const SizedBox(height: 12),

            if (appointments.isEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 12),
                child: Text('这个半日还没有排期'),
              )
            else
              ...appointments.map(
                (a) => ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: CircleAvatar(
                    radius: 16,
                    child: Text((a.patientName ?? a.patientNo).characters.first),
                  ),
                  title: Text(a.patientName ?? a.patientNo),
                  subtitle: Text('${a.patientNo} · ${a.therapistName ?? '治疗师 #${a.therapistId}'}'
                      '${a.note == null || a.note!.isEmpty ? '' : ' · ${a.note}'}'),
                  trailing: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(a.statusLabel, style: const TextStyle(fontSize: 12)),
                      if (a.isActive) ...[
                        const SizedBox(width: 4),
                        IconButton(
                          tooltip: '取消这台',
                          icon: const Icon(Icons.close, size: 18),
                          onPressed: () async {
                            final ok = await _confirmCancel(context, a);
                            if (!ok) return;
                            await ref
                                .read(scheduleSyncControllerProvider.notifier)
                                .cancel(a.id);
                            if (context.mounted) Navigator.of(context).pop();
                          },
                        ),
                      ],
                    ],
                  ),
                ),
              ),

            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => Navigator.of(context).pop(),
                    child: const Text('关闭'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: FilledButton.icon(
                    // 不可排就禁用 —— 休息/请假是硬冲突，不该让用户白填一遍。
                    onPressed: blocked ? null : () => _pickPatient(context, ref),
                    icon: const Icon(Icons.add),
                    label: const Text('排一位患者'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Future<bool> _confirmCancel(BuildContext context, Appointment a) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('取消这台排期'),
        content: Text('${a.patientName ?? a.patientNo} · ${shortDateFromIso(a.date)} '
            '${periodLabel(a.period)}'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('不取消')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('取消排期')),
        ],
      ),
    );
    return ok == true;
  }

  /// 选患者（从**本地**患者列表选，离线也能排班）。
  ///
  /// 直接读仓库而不是读 UI 的筛选后列表：排班不该受"患者页当前筛了什么"影响，
  /// 而且 `filteredPatientListProvider` 是 `Provider<AsyncValue<...>>`（不是
  /// `FutureProvider`），没有 `.future` 可 await。
  Future<void> _pickPatient(BuildContext context, WidgetRef ref) async {
    final services = ref.read(appServicesProvider).requireValue;
    final user = ref.read(currentUserProvider);
    final patients = await services.patients.listLocal(therapistId: user?.id);
    if (!context.mounted) return;

    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => _PatientPickerSheet(
        patients: patients,
        onPick: (patientNo) async {
          Navigator.of(ctx).pop();
          await ref.read(scheduleSyncControllerProvider.notifier).create(
                AppointmentDraft(patientNo: patientNo, date: date, period: period),
              );
          if (context.mounted) Navigator.of(context).pop();
        },
      ),
    );
  }
}

/// 选患者。刻意不做服务端搜索：本地全科患者已在库里，离线也能用。
class _PatientPickerSheet extends StatefulWidget {
  const _PatientPickerSheet({required this.patients, required this.onPick});

  final List<PatientView> patients;
  final ValueChanged<String> onPick;

  @override
  State<_PatientPickerSheet> createState() => _PatientPickerSheetState();
}

class _PatientPickerSheetState extends State<_PatientPickerSheet> {
  String _keyword = '';

  @override
  Widget build(BuildContext context) {
    final rows = widget.patients.where((p) {
      return _keyword.isEmpty ||
          p.name.toLowerCase().contains(_keyword) ||
          p.inpatientNo.toLowerCase().contains(_keyword);
    }).toList();

    return SafeArea(
      child: Padding(
        padding: EdgeInsets.only(
          left: 16,
          right: 16,
          top: 12,
          bottom: MediaQuery.of(context).viewInsets.bottom + 12,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              autofocus: true,
              decoration: const InputDecoration(
                isDense: true,
                hintText: '搜索姓名或住院号',
                prefixIcon: Icon(Icons.search),
              ),
              onChanged: (v) => setState(() => _keyword = v.trim().toLowerCase()),
            ),
            const SizedBox(height: 8),
            SizedBox(
              height: 320,
              child: rows.isEmpty
                  ? const Center(child: Text('没有匹配的患者'))
                  : ListView.builder(
                      itemCount: rows.length,
                      itemBuilder: (_, i) {
                        final p = rows[i];
                        return ListTile(
                          title: Text(p.name),
                          subtitle: Text(p.inpatientNo),
                          trailing: const Icon(Icons.chevron_right),
                          onTap: () => widget.onPick(p.inpatientNo),
                        );
                      },
                    ),
            ),
          ],
        ),
      ),
    );
  }
}
