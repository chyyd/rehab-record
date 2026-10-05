import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:open_filex/open_filex.dart';

import 'package:rehab_app/core/api_endpoints.dart';
import 'package:rehab_app/core/date_utils.dart';
import 'package:rehab_app/data/remote/timeline_dto.dart';
import 'package:rehab_app/features/timeline/timeline_providers.dart';

/// 按日期汇总 + 打印。
///
/// 汇总与打印都**直接走服务端**（只读、需要全科数据）。
/// 打印是 PDF：必须**自己带 Bearer 下载**再交给系统阅读器 ——
/// 把 URL 直接丢给浏览器只会看到 401（浏览器不知道我们的令牌）。
class SummaryPage extends ConsumerWidget {
  const SummaryPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final day = ref.watch(summaryDateProvider);
    final groupBy = ref.watch(summaryGroupByProvider);
    final async = ref.watch(dateSummaryProvider);
    final print = ref.watch(printControllerProvider);
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('当日汇总'),
        actions: [
          IconButton(
            tooltip: '打印 PDF',
            icon: print.busy
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.print_outlined),
            onPressed: print.busy
                ? null
                : () => ref.read(printControllerProvider.notifier).downloadAndOpen(
                      path: kPrintSummaryDate,
                      filenamePrefix:
                          'date_summary_${formatDate(day).replaceAll('-', '')}',
                      query: {'date': formatDate(day)},
                    ),
          ),
        ],
        bottom: print.message == null
            ? null
            : PreferredSize(
                preferredSize: const Size.fromHeight(30),
                child: _PrintBar(
                  text: print.message!,
                  isError: print.isError,
                  // 路径单独传：不要从消息字符串里解析（那是脆的）。
                  path: print.path,
                  onDismiss: () => ref.read(printControllerProvider.notifier).clear(),
                ),
              ),
      ),
      body: Column(
        children: [
          _DateBar(
            day: day,
            groupBy: groupBy,
            onShift: (d) => ref.read(summaryDateProvider.notifier).shift(d),
            onToday: () => ref.read(summaryDateProvider.notifier).today(),
            onToggleGroup: () =>
                ref.read(summaryGroupByProvider.notifier).toggle(),
          ),
          Expanded(
            child: async.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, _) => Center(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.cloud_off_outlined, size: 44),
                      const SizedBox(height: 10),
                      const Text('汇总需要联网', style: TextStyle(fontWeight: FontWeight.bold)),
                      const SizedBox(height: 6),
                      Text('$e', textAlign: TextAlign.center),
                      const SizedBox(height: 16),
                      OutlinedButton(
                        onPressed: () => ref.invalidate(dateSummaryProvider),
                        child: const Text('重试'),
                      ),
                    ],
                  ),
                ),
              ),
              data: (s) => RefreshIndicator(
                onRefresh: () async => ref.invalidate(dateSummaryProvider),
                child: ListView(
                  physics: const AlwaysScrollableScrollPhysics(),
                  padding: const EdgeInsets.all(12),
                  children: [
                    _TotalsCard(totals: s.totals, title: '${s.date} 总计'),
                    const SizedBox(height: 12),
                    Text(
                      s.groupBy == 'therapist' ? '按治疗师' : '按患者',
                      style: theme.textTheme.titleSmall
                          ?.copyWith(fontWeight: FontWeight.bold),
                    ),
                    const SizedBox(height: 6),
                    if (s.groups.isEmpty)
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 24),
                        child: Center(
                          child: Text('这一天没有治疗记录',
                              style: TextStyle(color: theme.colorScheme.outline)),
                        ),
                      )
                    else
                      for (final g in s.groups) _GroupCard(group: g),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _DateBar extends StatelessWidget {
  const _DateBar({
    required this.day,
    required this.groupBy,
    required this.onShift,
    required this.onToday,
    required this.onToggleGroup,
  });

  final DateTime day;
  final String groupBy;
  final ValueChanged<int> onShift;
  final VoidCallback onToday;
  final VoidCallback onToggleGroup;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(8, 6, 8, 0),
      child: Row(
        children: [
          IconButton(
            onPressed: () => onShift(-1),
            icon: const Icon(Icons.chevron_left),
            tooltip: '前一天',
          ),
          Expanded(
            child: InkWell(
              onTap: () async {
                final picked = await showDatePicker(
                  context: context,
                  initialDate: day,
                  firstDate: DateTime(day.year - 2),
                  lastDate: DateTime(day.year + 1),
                );
                if (picked != null) {
                  // 直接用差值移动，避免为"选定某天"再加一个方法。
                  onShift(picked.difference(startOfDay(day)).inDays);
                }
              },
              child: Column(
                children: [
                  Text(formatDate(day),
                      style: const TextStyle(fontWeight: FontWeight.w600)),
                  Text(weekdayLabel(day),
                      style: const TextStyle(fontSize: 11)),
                ],
              ),
            ),
          ),
          IconButton(
            onPressed: () => onShift(1),
            icon: const Icon(Icons.chevron_right),
            tooltip: '后一天',
          ),
          TextButton(onPressed: onToday, child: const Text('今天')),
          Tooltip(
            message: groupBy == 'therapist' ? '切换为按患者' : '切换为按治疗师',
            child: IconButton(
              onPressed: onToggleGroup,
              icon: Icon(groupBy == 'therapist' ? Icons.groups_outlined : Icons.person_outline),
            ),
          ),
        ],
      ),
    );
  }
}

class _TotalsCard extends StatelessWidget {
  const _TotalsCard({required this.totals, required this.title});

  final SummaryTotals totals;
  final String title;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: theme.textTheme.titleMedium),
            const SizedBox(height: 10),
            Row(
              children: [
                _Metric(label: '记录', value: '${totals.recordCount}'),
                _Metric(label: '项目', value: '${totals.itemCount}'),
                _Metric(label: '患者', value: '${totals.patientCount}'),
                _Metric(label: '时长', value: totals.durationLabel),
              ],
            ),
            if (totals.mainItemCounts.isNotEmpty) ...[
              const Divider(height: 20),
              Text('主项目分布', style: TextStyle(fontSize: 12, color: theme.colorScheme.outline)),
              const SizedBox(height: 4),
              for (final e in totals.mainItemCounts.entries)
                Padding(
                  padding: const EdgeInsets.only(bottom: 2),
                  child: Row(
                    children: [
                      Expanded(child: Text(e.key, style: const TextStyle(fontSize: 12))),
                      Text('${e.value}', style: const TextStyle(fontSize: 12)),
                    ],
                  ),
                ),
            ],
            if (totals.therapistCounts.isNotEmpty) ...[
              const Divider(height: 20),
              Text('治疗师分布', style: TextStyle(fontSize: 12, color: theme.colorScheme.outline)),
              const SizedBox(height: 4),
              for (final e in totals.therapistCounts.entries)
                Padding(
                  padding: const EdgeInsets.only(bottom: 2),
                  child: Row(
                    children: [
                      Expanded(child: Text(e.key, style: const TextStyle(fontSize: 12))),
                      Text('${e.value}', style: const TextStyle(fontSize: 12)),
                    ],
                  ),
                ),
            ],
          ],
        ),
      ),
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Expanded(
      child: Column(
        children: [
          Text(value,
              style: theme.textTheme.titleMedium
                  ?.copyWith(fontWeight: FontWeight.bold)),
          Text(label,
              style: TextStyle(fontSize: 11, color: theme.colorScheme.outline)),
        ],
      ),
    );
  }
}

class _GroupCard extends StatelessWidget {
  const _GroupCard({required this.group});

  final SummaryGroup group;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ExpansionTile(
        title: Text(group.label, style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Text(
          '${group.totals.recordCount} 条 · ${group.totals.itemCount} 项 · '
          '${group.totals.patientCount} 名患者 · ${group.totals.durationLabel}',
          style: const TextStyle(fontSize: 12),
        ),
        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
        children: [
          for (final e in group.totals.subItemCounts.entries)
            Padding(
              padding: const EdgeInsets.only(bottom: 2),
              child: Row(
                children: [
                  Expanded(child: Text(e.key, style: const TextStyle(fontSize: 12))),
                  Text('×${e.value}', style: const TextStyle(fontSize: 12)),
                ],
              ),
            ),
          if (group.patientNos.isNotEmpty) ...[
            const SizedBox(height: 6),
            Align(
              alignment: Alignment.centerLeft,
              child: Text(
                '患者：${group.patientNos.join('、')}',
                style: TextStyle(fontSize: 11, color: theme.colorScheme.outline),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _PrintBar extends StatelessWidget {
  const _PrintBar({
    required this.text,
    required this.isError,
    required this.onDismiss,
    this.path,
  });

  final String text;
  final bool isError;
  final VoidCallback onDismiss;

  /// 已下载到的本地文件路径（成功时非空）。
  final String? path;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      width: double.infinity,
      color: isError ? scheme.errorContainer : scheme.secondaryContainer,
      padding: const EdgeInsets.only(left: 12, right: 4),
      child: Row(
        children: [
          Icon(isError ? Icons.warning_amber_outlined : Icons.picture_as_pdf_outlined,
              size: 16),
          const SizedBox(width: 8),
          Expanded(
            child: Text(text,
                style: const TextStyle(fontSize: 12),
                maxLines: 1,
                overflow: TextOverflow.ellipsis),
          ),
          // 打开文件：下载成功后治疗师通常想立刻看一眼版式对不对。
          // 文件名带时间戳，两份不会互相覆盖。
          if (path != null)
            IconButton(
              tooltip: '用系统阅读器打开',
              icon: const Icon(Icons.open_in_new, size: 16),
              visualDensity: VisualDensity.compact,
              onPressed: () => OpenFilex.open(path!),
            ),
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
