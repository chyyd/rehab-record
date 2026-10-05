import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/features/patients/patients_providers.dart';

/// 患者详情（一期只读）。
///
/// **注意事项（`admin_note`）要醒目**：治疗师只读、由管理员维护，
/// 床旁最怕漏看"注意防跌倒"这类信息，所以放在最上面且用错误色。
///
/// 时间轴与治疗记录列表在下一步接入（依赖记录表单），此处先给出明确占位，
/// 不用假的空列表 —— 那会让人以为"这个患者没做过治疗"。
class PatientDetailPage extends ConsumerWidget {
  const PatientDetailPage({super.key, required this.inpatientNo});

  final String inpatientNo;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final patient = ref.watch(patientDetailProvider(inpatientNo));
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(title: const Text('患者详情')),
      body: patient.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('$e')),
        data: (p) {
          if (p == null) {
            return const Center(child: Text('本地没有这名患者，请先同步'));
          }

          final note = p.adminNote?.trim() ?? '';
          return ListView(
            padding: const EdgeInsets.all(16),
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
              _InfoRow(label: '可见归属解析', value: p.visibilityState ?? '—'),

              const Divider(height: 32),
              Row(
                children: [
                  Icon(Icons.construction_outlined, color: theme.colorScheme.outline),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      '治疗记录与时间轴将在记录页接入后显示在此处（下一步）。',
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: theme.colorScheme.outline),
                    ),
                  ),
                ],
              ),
            ],
          );
        },
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
