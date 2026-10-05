import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/core/date_utils.dart';
import 'package:rehab_app/core/worktime.dart';
import 'package:rehab_app/data/remote/timeline_dto.dart';
import 'package:rehab_app/features/patients/patient_detail_page.dart';
import 'package:rehab_app/features/timeline/summary_page.dart';
import 'package:rehab_app/features/timeline/timeline_providers.dart';

/// 时间轴：全科记录流（按日期倒序）。
///
/// ## 为什么直接查服务端而不是本地库
///
/// 这是**全科协作视图** —— 治疗师需要看到别人写的记录（谁给这个患者做了什么、
/// 今天做了几次）。本地库只镜像了自己同步过的部分，用它做时间轴会显示成
/// "别人什么都没做"。只读数据没有离线写入需求，所以直接查服务端。
class TimelinePage extends ConsumerStatefulWidget {
  const TimelinePage({super.key});

  @override
  ConsumerState<TimelinePage> createState() => _TimelinePageState();
}

class _TimelinePageState extends ConsumerState<TimelinePage> {
  final _scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_onScroll);
  }

  @override
  void dispose() {
    _scroll.removeListener(_onScroll);
    _scroll.dispose();
    super.dispose();
  }

  void _onScroll() {
    if (!_scroll.hasClients) return;
    // 距底部 400px 时预取下一页，避免用户等。
    if (_scroll.position.pixels >= _scroll.position.maxScrollExtent - 400) {
      ref.read(timelineControllerProvider.notifier).loadMore();
    }
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(timelineControllerProvider);
    final filter = ref.watch(timelineFilterProvider);

    return Column(
      children: [
        _ScopeBar(
          filter: filter,
          onScope: (s) => ref.read(timelineFilterProvider.notifier).setScope(s),
          onOpenFilter: () => _openFilterSheet(context),
        ),
        Expanded(
          child: async.when(
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (e, _) => _ErrorView(
              message: '$e',
              onRetry: () => ref.read(timelineControllerProvider.notifier).refresh(),
            ),
            data: (state) {
              if (state.isEmpty) {
                return _EmptyView(
                  filter: filter,
                  onRefresh: () =>
                      ref.read(timelineControllerProvider.notifier).refresh(),
                );
              }
              return RefreshIndicator(
                onRefresh: () =>
                    ref.read(timelineControllerProvider.notifier).refresh(),
                child: ListView.builder(
                  controller: _scroll,
                  physics: const AlwaysScrollableScrollPhysics(),
                  itemCount: state.items.length + 1,
                  itemBuilder: (context, i) {
                    if (i == state.items.length) {
                      return _Tail(state: state);
                    }
                    final item = state.items[i];
                    // 日期分隔条：同一天只出现一次。
                    final showDate = i == 0 ||
                        state.items[i - 1].recordDate != item.recordDate;
                    return Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        if (showDate) _DateDivider(date: item.recordDate),
                        _TimelineTile(item: item),
                      ],
                    );
                  },
                ),
              );
            },
          ),
        ),
      ],
    );
  }

  Future<void> _openFilterSheet(BuildContext context) async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (_) => const _FilterSheet(),
    );
  }
}

class _ScopeBar extends StatelessWidget {
  const _ScopeBar({
    required this.filter,
    required this.onScope,
    required this.onOpenFilter,
  });

  final TimelineFilter filter;
  final ValueChanged<TimelineScope> onScope;
  final VoidCallback onOpenFilter;

  @override
  Widget build(BuildContext context) {
    final range = filter.hasDateRange
        ? '${filter.dateFrom == null ? '…' : shortDateFromIso(filter.dateFrom!)}'
            ' – '
            '${filter.dateTo == null ? '…' : shortDateFromIso(filter.dateTo!)}'
        : null;

    return Column(
      children: [
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
          child: Row(
            children: [
              for (final s in TimelineScope.values)
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: ChoiceChip(
                    label: Text(s.label),
                    selected: filter.scope == s,
                    onSelected: (_) => onScope(s),
                  ),
                ),
              const SizedBox(width: 4),
              ActionChip(
                avatar: const Icon(Icons.filter_list, size: 18),
                label: Text(range ?? '筛选'),
                onPressed: onOpenFilter,
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// 筛选面板：日期区间 + 主项目。
class _FilterSheet extends ConsumerWidget {
  const _FilterSheet();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final filter = ref.watch(timelineFilterProvider);
    final controller = ref.read(timelineFilterProvider.notifier);
    final theme = Theme.of(context);

    Future<void> pickRange() async {
      final now = DateTime.now();
      final picked = await showDateRangePicker(
        context: context,
        firstDate: DateTime(now.year - 2),
        lastDate: DateTime(now.year + 1),
        initialDateRange: filter.dateFrom != null && filter.dateTo != null
            ? DateTimeRange(
                start: parseDate(filter.dateFrom!) ?? now,
                end: parseDate(filter.dateTo!) ?? now,
              )
            : null,
      );
      if (picked != null) controller.setDateRange(picked.start, picked.end);
    }

    /// 常用区间：床旁最常看的是"今天/本周"。
    void quick(int days) {
      final today = DateTime.now();
      controller.setDateRange(today.subtract(Duration(days: days - 1)), today);
    }

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('筛选', style: theme.textTheme.titleLarge),
            const SizedBox(height: 12),
            const Text('时间范围', style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 6),
            Wrap(
              spacing: 8,
              children: [
                ActionChip(label: const Text('今天'), onPressed: () => quick(1)),
                ActionChip(label: const Text('近 3 天'), onPressed: () => quick(3)),
                ActionChip(label: const Text('近 7 天'), onPressed: () => quick(7)),
                ActionChip(label: const Text('近 30 天'), onPressed: () => quick(30)),
                ActionChip(
                  avatar: const Icon(Icons.date_range, size: 18),
                  label: const Text('自定义'),
                  onPressed: pickRange,
                ),
              ],
            ),
            if (filter.hasDateRange) ...[
              const SizedBox(height: 6),
              Row(
                children: [
                  Expanded(
                    child: Text(
                      '${filter.dateFrom ?? '不限'} ~ ${filter.dateTo ?? '不限'}',
                      style: TextStyle(fontSize: 12, color: theme.colorScheme.outline),
                    ),
                  ),
                  TextButton(
                    onPressed: controller.clearDateRange,
                    child: const Text('清除'),
                  ),
                ],
              ),
            ],
            const Divider(height: 28),
            // 主项目筛选先留说明：它的选项来自字典树，而时间轴响应里只带名称。
            Text(
              filter.mainItemName == null
                  ? '主项目筛选：未设置'
                  : '主项目筛选：${filter.mainItemName}',
              style: const TextStyle(fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 4),
            Text(
              '时间轴按主项目筛选需要先选定字典里的项目（下一步接入字典选择器）。',
              style: TextStyle(fontSize: 12, color: theme.colorScheme.outline),
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () {
                      controller.reset();
                      Navigator.of(context).pop();
                    },
                    child: const Text('重置全部'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: FilledButton(
                    onPressed: () => Navigator.of(context).pop(),
                    child: const Text('完成'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _DateDivider extends StatelessWidget {
  const _DateDivider({required this.date});

  final String date;

  @override
  Widget build(BuildContext context) {
    final d = parseDate(date);
    final isToday = date == formatDate(DateTime.now());
    final theme = Theme.of(context);
    return Container(
      width: double.infinity,
      color: isToday ? theme.colorScheme.primaryContainer : theme.colorScheme.surfaceContainerHighest,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      child: Text(
        '${shortDateFromIso(date)}'
        '${d == null ? '' : ' ${weekdayLabel(d)}'}'
        '${isToday ? ' · 今天' : ''}',
        style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13),
      ),
    );
  }
}

class _TimelineTile extends ConsumerWidget {
  const _TimelineTile({required this.item});

  final TimelineItem item;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    return ListTile(
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => PatientDetailPage(inpatientNo: item.patientNo),
        ),
      ),
      leading: CircleAvatar(
        backgroundColor: item.status == 'draft'
            ? theme.colorScheme.tertiaryContainer
            : theme.colorScheme.primaryContainer,
        child: Text(item.displayName.characters.first),
      ),
      title: Row(
        children: [
          Flexible(
            child: Text(item.displayName,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontWeight: FontWeight.w600)),
          ),
          if (item.sessionPeriod != null) ...[
            const SizedBox(width: 6),
            Text(periodLabel(item.sessionPeriod!),
                style: TextStyle(fontSize: 11, color: theme.colorScheme.outline)),
          ],
          if (item.seqNo != null) ...[
            const SizedBox(width: 6),
            Text('第 ${item.seqNo} 次',
                style: TextStyle(fontSize: 11, color: theme.colorScheme.outline)),
          ],
        ],
      ),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            [
              item.patientNo,
              if (item.therapistName != null) item.therapistName!,
              item.statusLabel,
              if (item.editCount > 0) '改过 ${item.editCount} 次',
            ].join(' · '),
            style: const TextStyle(fontSize: 12),
          ),
          if (item.mainItemNames.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text(
                item.mainItemNames.join('、'),
                style: TextStyle(fontSize: 12, color: theme.colorScheme.primary),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
        ],
      ),
      trailing: Text('${item.itemCount} 项',
          style: TextStyle(fontSize: 12, color: theme.colorScheme.outline)),
    );
  }
}

class _Tail extends ConsumerWidget {
  const _Tail({required this.state});

  final TimelineState state;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    if (state.error != null) {
      return Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          children: [
            Icon(Icons.warning_amber_outlined, size: 18, color: theme.colorScheme.error),
            const SizedBox(width: 8),
            Expanded(child: Text(state.error!, style: const TextStyle(fontSize: 12))),
            TextButton(
              onPressed: () => ref.read(timelineControllerProvider.notifier).loadMore(),
              child: const Text('重试'),
            ),
          ],
        ),
      );
    }
    if (state.loadingMore) {
      return const Padding(
        padding: EdgeInsets.all(16),
        child: Center(child: SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2))),
      );
    }
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Center(
        child: Text(
          state.hasMore ? '上滑加载更多' : '已显示全部 ${state.total} 条',
          style: TextStyle(fontSize: 12, color: theme.colorScheme.outline),
        ),
      ),
    );
  }
}

class _EmptyView extends StatelessWidget {
  const _EmptyView({required this.filter, required this.onRefresh});

  final TimelineFilter filter;
  final Future<void> Function() onRefresh;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return RefreshIndicator(
      onRefresh: onRefresh,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        children: [
          const SizedBox(height: 80),
          Icon(Icons.timeline, size: 56, color: theme.colorScheme.outline),
          const SizedBox(height: 12),
          Center(
            child: Text(
              switch (filter.scope) {
                TimelineScope.visible => '这段时间没有治疗记录',
                TimelineScope.mine => '这段时间没有我写的记录',
              },
              style: theme.textTheme.bodyLarge,
            ),
          ),
          const SizedBox(height: 6),
          Center(
            child: Text('下拉可刷新',
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.outline)),
          ),
        ],
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.cloud_off_outlined, size: 44),
            const SizedBox(height: 10),
            const Text('时间轴需要联网', style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 6),
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 6),
            Text(
              '记录本身是离线可写的（在患者页），这里只是"看全科"的视图。',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.outline),
            ),
            const SizedBox(height: 16),
            OutlinedButton(onPressed: onRetry, child: const Text('重试')),
          ],
        ),
      ),
    );
  }
}

/// 时间轴页顶部的"汇总"入口（放在 HomeShell 的 AppBar 上）。
class TimelineSummaryButton extends ConsumerWidget {
  const TimelineSummaryButton({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return IconButton(
      tooltip: '当日汇总',
      icon: const Icon(Icons.summarize_outlined),
      onPressed: () => Navigator.of(context).push(
        MaterialPageRoute<void>(builder: (_) => const SummaryPage()),
      ),
    );
  }
}
