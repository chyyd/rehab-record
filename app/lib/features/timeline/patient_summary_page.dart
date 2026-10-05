import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/core/api_endpoints.dart';
import 'package:rehab_app/core/date_utils.dart';
import 'package:rehab_app/data/remote/timeline_dto.dart';
import 'package:rehab_app/features/timeline/pdf_export.dart';
import 'package:rehab_app/features/timeline/timeline_providers.dart';

/// 患者汇总：按天折叠的"这个患者每天做了什么"。
///
/// 数据来自 `GET /summary/patient/{no}`，是服务端按天聚合好的
/// （主项目 / 子项目 / 参数摘要 / 患者反应 / 备注），
/// 所以这里不需要再自己去拼记录明细 —— 而且聚合口径与服务端打印的 PDF 一致，
/// 屏幕上看到的和打出来的是同一份内容。
class PatientSummaryPage extends ConsumerWidget {
  const PatientSummaryPage({super.key, required this.inpatientNo});

  final String inpatientNo;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(patientDailySummaryProvider(inpatientNo));
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('患者汇总'),
        actions: [
          PdfExportButton(
            path: kPrintSummaryPatient(inpatientNo),
            filenamePrefix: 'patient_$inpatientNo',
            jobName: '患者汇总 $inpatientNo',
          ),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(30),
          child: PrintResultBar(),
        ),
      ),
      body: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.cloud_off_outlined, size: 44),
                const SizedBox(height: 10),
                const Text('患者汇总需要联网', style: TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(height: 6),
                Text('$e', textAlign: TextAlign.center),
                const SizedBox(height: 16),
                OutlinedButton(
                  onPressed: () => ref.invalidate(patientDailySummaryProvider(inpatientNo)),
                  child: const Text('重试'),
                ),
              ],
            ),
          ),
        ),
        data: (s) => RefreshIndicator(
          onRefresh: () async => ref.invalidate(patientDailySummaryProvider(inpatientNo)),
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.all(12),
            children: [
              Card(
                margin: EdgeInsets.zero,
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(s.patient.name, style: theme.textTheme.titleMedium),
                      Text(
                        '${s.patient.inpatientNo}'
                        '${s.patient.diagnosis == null ? '' : ' · ${s.patient.diagnosis}'}',
                        style: TextStyle(fontSize: 12, color: theme.colorScheme.outline),
                      ),
                      const Divider(height: 20),
                      Row(
                        children: [
                          _Metric(label: '治疗天数', value: '${s.days.length}'),
                          _Metric(label: '治疗次数', value: '${s.totals.recordCount}'),
                          _Metric(
                              label: '大类', value: '${s.totals.disciplineCounts.length}'),
                          _Metric(label: '文书', value: '${_documentCount(s)}'),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 12),
              if (s.days.isEmpty)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 32),
                  child: Center(
                    child: Text('这个患者还没有治疗记录',
                        style: TextStyle(color: theme.colorScheme.outline)),
                  ),
                )
              else
                for (final day in s.days) _DayCard(day: day),
            ],
          ),
        ),
      ),
    );
  }

  /// 文书总条数（含首评/复评/出院小结 —— 它们不计入治疗次数）。
  static int _documentCount(PatientDailySummary s) =>
      s.days.fold(0, (sum, day) => sum + day.records.length);
}

class _DayCard extends StatelessWidget {
  const _DayCard({required this.day});

  final PatientDailyDay day;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final d = parseDate(day.recordDate);
    final chips = day.disciplines.join('、');

    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ExpansionTile(
        title: Row(
          children: [
            Text(
              '${shortDateFromIso(day.recordDate)}'
              '${d == null ? '' : ' ${weekdayLabel(d)}'}',
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
            if (chips.isNotEmpty) ...[
              const SizedBox(width: 6),
              Text(chips,
                  style: TextStyle(fontSize: 11, color: theme.colorScheme.outline)),
            ],
            if (day.temporary) ...[
              const SizedBox(width: 6),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
                decoration: BoxDecoration(
                  color: theme.colorScheme.tertiaryContainer,
                  borderRadius: BorderRadius.circular(4),
                ),
                child: const Text('临时治疗', style: TextStyle(fontSize: 10)),
              ),
            ],
          ],
        ),
        subtitle: Text(
          [
            if (day.therapists.isNotEmpty) day.therapists.join('、'),
            '${day.recordCount} 次治疗',
            '${day.records.length} 份文书',
          ].join(' · '),
          style: const TextStyle(fontSize: 12),
        ),
        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
        children: [
          // ★ 一天的内容就是当天各份文书的 SOAP 纯文本，按时间顺序往下排。
          for (final row in day.records)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (row.isTemporary)
                    Text('（临时治疗）',
                        style: TextStyle(
                            fontSize: 11, color: theme.colorScheme.tertiary)),
                  SelectableText(
                    row.renderedText.isEmpty ? '（无内容）' : row.renderedText,
                    style: const TextStyle(fontSize: 12, height: 1.5),
                  ),
                ],
              ),
            ),
          if (day.records.isEmpty)
            for (final text in day.texts)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: SelectableText(text,
                    style: const TextStyle(fontSize: 12, height: 1.5)),
              ),
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