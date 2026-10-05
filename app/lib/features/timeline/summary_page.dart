import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/core/api_endpoints.dart';
import 'package:rehab_app/core/date_utils.dart';
import 'package:rehab_app/data/remote/timeline_dto.dart';
import 'package:rehab_app/features/timeline/pdf_export.dart';
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
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('当日汇总'),
        actions: [
          PdfExportButton(
            path: kPrintSummaryDate,
            filenamePrefix: 'date_summary_${formatDate(day).replaceAll('-', '')}',
            query: {'date': formatDate(day)},
            jobName: '当日汇总 ${formatDate(day)}',
          ),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(30),
          child: PrintResultBar(),
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
            const SizedBox(height: 4),
            Text(
              '只算日常记录（首评/复评/出院小结是独立文书，不占治疗次数）',
              style: TextStyle(fontSize: 11, color: theme.colorScheme.outline),
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                _Metric(label: '治疗次数', value: '${totals.recordCount}'),
                _Metric(label: '患者', value: '${totals.patientCount}'),
                _Metric(label: '大类', value: '${totals.disciplineCounts.length}'),
              ],
            ),
            if (totals.disciplineCounts.isNotEmpty) ...[
              const Divider(height: 20),
              Text('大类分布',
                  style: TextStyle(fontSize: 12, color: theme.colorScheme.outline)),
              const SizedBox(height: 4),
              for (final e in totals.disciplineCounts.entries)
                _CountRow(label: e.key, count: e.value),
            ],
            if (totals.therapistCounts.isNotEmpty) ...[
              const Divider(height: 20),
              Text('治疗师分布',
                  style: TextStyle(fontSize: 12, color: theme.colorScheme.outline)),
              const SizedBox(height: 4),
              for (final e in totals.therapistCounts.entries)
                _CountRow(label: e.key, count: e.value),
            ],
          ],
        ),
      ),
    );
  }
}

class _CountRow extends StatelessWidget {
  const _CountRow({required this.label, required this.count});

  final String label;
  final int count;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 2),
      child: Row(
        children: [
          Expanded(child: Text(label, style: const TextStyle(fontSize: 12))),
          Text('$count', style: const TextStyle(fontSize: 12)),
        ],
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
          '${group.totals.recordCount} 次治疗 · ${group.totals.patientCount} 名患者',
          style: const TextStyle(fontSize: 12),
        ),
        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
        children: [
          for (final row in group.rows)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${row.recordDate} · ${row.patientName ?? row.patientNo}'
                    ' · ${row.disciplineName ?? ''}${row.kindLabel ?? ''}',
                    style: TextStyle(
                        fontSize: 11, color: theme.colorScheme.outline),
                  ),
                  const SizedBox(height: 2),
                  // ★ 内容就是 SOAP 纯文本（与 PDF 同一份）。
                  SelectableText(
                    row.renderedText.isEmpty ? '（无内容）' : row.renderedText,
                    style: const TextStyle(fontSize: 12, height: 1.4),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}