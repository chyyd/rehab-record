import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/core/date_utils.dart';
import 'package:rehab_app/core/worktime.dart';
import 'package:rehab_app/features/patients/patients_providers.dart';
import 'package:rehab_app/features/records/record_page.dart';
import 'package:rehab_app/features/records/record_providers.dart';

/// 患者详情。
///
/// **注意事项（`admin_note`）要醒目**：治疗师只读、由管理员维护，
/// 床旁最怕漏看"注意防跌倒"这类信息，所以放在最上面且用错误色。
///
/// 记录列表走**本地库**（响应式）：离线也能看历史、继续写没写完的草稿。
class PatientDetailPage extends ConsumerWidget {
  const PatientDetailPage({super.key, required this.inpatientNo});

  final String inpatientNo;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final patient = ref.watch(patientDetailProvider(inpatientNo));
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(title: const Text('患者详情')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _openRecord(context, null),
        icon: const Icon(Icons.edit_note),
        label: const Text('记录治疗'),
      ),
      body: patient.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('$e')),
        data: (p) {
          if (p == null) {
            return const Center(child: Text('本地没有这名患者，请先同步'));
          }

          final note = p.adminNote?.trim() ?? '';
          final records = ref.watch(localRecordsProvider(inpatientNo));

          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
            children: [
              if (note.isNotEmpty)
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: theme.colorScheme.errorContainer,
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(Icons.warning_amber_rounded,
                          color: theme.colorScheme.onErrorContainer),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '注意事项',
                              style: TextStyle(
                                fontWeight: FontWeight.bold,
                                color: theme.colorScheme.onErrorContainer,
                              ),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              note,
                              style: TextStyle(color: theme.colorScheme.onErrorContainer),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              if (note.isNotEmpty) const SizedBox(height: 16),

              Text(p.name, style: theme.textTheme.headlineSmall),
              const SizedBox(height: 4),
              Text(
                p.inpatientNo,
                style: theme.textTheme.titleMedium
                    ?.copyWith(color: theme.colorScheme.outline),
              ),
              const SizedBox(height: 16),

              _InfoRow(label: '诊断', value: p.diagnosis ?? '—'),
              _InfoRow(
                label: '状态',
                value: switch (p.status) {
                  'in_hospital' => '在院',
                  'paused' => '暂停',
                  'discharged' => '已出院',
                  _ => p.status,
                },
              ),
              _InfoRow(
                label: '归属',
                value: p.assignedTherapistId == null
                    ? '未分配'
                    : '治疗师 #${p.assignedTherapistId}',
              ),

              const Divider(height: 32),
              Text('治疗记录', style: theme.textTheme.titleMedium),
              const SizedBox(height: 4),
              Text(
                '按日期倒序；未上传的草稿标「待上传」',
                style: TextStyle(fontSize: 12, color: theme.colorScheme.outline),
              ),
              const SizedBox(height: 8),

              records.when(
                loading: () => const Padding(
                  padding: EdgeInsets.all(16),
                  child: Center(child: CircularProgressIndicator()),
                ),
                error: (e, _) => Text('$e'),
                data: (rows) => rows.isEmpty
                    ? const Padding(
                        padding: EdgeInsets.symmetric(vertical: 16),
                        child: Text('还没有治疗记录'),
                      )
                    : Column(
                        children: [
                          for (final r in rows)
                            ListTile(
                              contentPadding: EdgeInsets.zero,
                              leading: CircleAvatar(
                                radius: 18,
                                child: Text('${r.seqNo ?? '草'}',
                                    style: const TextStyle(fontSize: 12)),
                              ),
                              title: Text(
                                '${shortDateFromIso(r.recordDate)}'
                                '${r.sessionPeriod == null ? '' : ' ${periodLabel(r.sessionPeriod!)}'}'
                                ' · ${r.status == 'draft' ? '草稿' : '已提交'}',
                              ),
                              subtitle: Text(
                                [
                                  if (r.seqNo != null) '第 ${r.seqNo} 次',
                                  if (r.durationMin != null) '${r.durationMin} 分钟',
                                  if (r.note != null && r.note!.isNotEmpty) r.note!,
                                  if (r.syncStatus == 'pending') '待上传',
                                ].join(' · '),
                              ),
                              trailing: r.syncStatus == 'pending'
                                  ? Icon(Icons.cloud_upload_outlined,
                                      size: 18, color: theme.colorScheme.outline)
                                  : const Icon(Icons.chevron_right),
                              // 只允许继续编辑本地草稿；已推送的记录属于"时间轴/修正"
                              // 的范畴，留到下一步做（避免这里出现半套编辑语义）。
                              onTap: r.id < 0
                                  ? () => _openRecord(context, r.id)
                                  : null,
                            ),
                        ],
                      ),
              ),
            ],
          );
        },
      ),
    );
  }

  void _openRecord(BuildContext context, int? existingId) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => RecordPage(
          args: RecordEditorArgs(
            patientNo: inpatientNo,
            existingId: existingId,
            recordDate: formatDate(DateTime.now()),
          ),
        ),
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 96,
            child: Text(label,
                style: TextStyle(color: theme.colorScheme.outline)),
          ),
          Expanded(child: Text(value)),
        ],
      ),
    );
  }
}
