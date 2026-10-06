import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/core/route_observer.dart';
import 'package:rehab_app/data/repo/patient_repository.dart';
import 'package:rehab_app/features/auth/auth_controller.dart';
import 'package:rehab_app/features/patients/patient_detail_page.dart';
import 'package:rehab_app/features/patients/patients_providers.dart';

/// 患者列表（全科白板，离线优先）。
///
/// 排序由服务端语义搬到了本地：**我的 → 未分配 → 其他**（设计与排序都基于
/// `assigned_therapist_id`；2026-10-03 起归属只影响排序，不再是可见性闸门）。
class PatientListPage extends ConsumerStatefulWidget {
  const PatientListPage({super.key});

  @override
  ConsumerState<PatientListPage> createState() => _PatientListPageState();
}

class _PatientListPageState extends ConsumerState<PatientListPage> with RouteAware {
  @override
  void initState() {
    super.initState();
    // 第一次进来也刷一次：患者状态是**服务端**的，本地镜像可能已经过时
    //（别人把他置了待出院 / 患者已出院）。
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) ref.read(patientSyncControllerProvider.notifier).refresh();
    });
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final route = ModalRoute.of(context);
    if (route is PageRoute) appRouteObserver.subscribe(this, route);
  }

  @override
  void dispose() {
    appRouteObserver.unsubscribe(this);
    super.dispose();
  }

  /// 从患者详情（或它下面的记录页）返回 → 再刷一次。
  ///
  /// 用户 2026-10-05：「每次返回患者页自动刷新」。典型场景是刚在详情里
  /// 点了「出院」把患者置为待出院 —— 退回列表后他必须**立刻消失**，
  /// 否则治疗师会以为还能继续记。
  @override
  void didPopNext() {
    if (!mounted) return;
    ref.read(patientSyncControllerProvider.notifier).refresh();
  }

  @override
  Widget build(BuildContext context) {
    final patients = ref.watch(filteredPatientListProvider);
    final filter = ref.watch(patientFilterProvider);
    final user = ref.watch(currentUserProvider);

    return Column(
      children: [
        _FilterBar(
          current: filter,
          onChanged: (f) => ref.read(patientFilterProvider.notifier).set(f),
        ),
        _SearchField(
          onChanged: (v) => ref.read(patientKeywordProvider.notifier).set(v),
        ),
        Expanded(
          child: patients.when(
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (e, _) => _ErrorView(
              message: '$e',
              onRetry: () =>
                  ref.read(patientSyncControllerProvider.notifier).refresh(),
            ),
            data: (rows) {
              if (rows.isEmpty) {
                return _EmptyView(
                  filter: filter,
                  onRefresh: () =>
                      ref.read(patientSyncControllerProvider.notifier).refresh(),
                );
              }
              return RefreshIndicator(
                onRefresh: () =>
                    ref.read(patientSyncControllerProvider.notifier).refresh(),
                child: ListView.separated(
                  // 离线时也要保证下拉刷新可用（列表短于一屏时）。
                  physics: const AlwaysScrollableScrollPhysics(),
                  itemCount: rows.length,
                  separatorBuilder: (_, _) => const Divider(height: 1),
                  itemBuilder: (context, i) => _PatientTile(
                    patient: rows[i],
                    currentTherapistId: user?.id,
                  ),
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}

class _FilterBar extends StatelessWidget {
  const _FilterBar({required this.current, required this.onChanged});

  final PatientFilter current;
  final ValueChanged<PatientFilter> onChanged;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      child: Row(
        children: [
          for (final f in PatientFilter.values)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: ChoiceChip(
                label: Text(f.label),
                selected: current == f,
                onSelected: (_) => onChanged(f),
              ),
            ),
        ],
      ),
    );
  }
}

class _SearchField extends StatelessWidget {
  const _SearchField({required this.onChanged});

  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
      child: TextField(
        onChanged: onChanged,
        textInputAction: TextInputAction.search,
        decoration: const InputDecoration(
          isDense: true,
          hintText: '搜索姓名或住院号',
          prefixIcon: Icon(Icons.search),
        ),
      ),
    );
  }
}

class _PatientTile extends StatelessWidget {
  const _PatientTile({required this.patient, required this.currentTherapistId});

  final PatientView patient;
  final int? currentTherapistId;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    // `isMine` 只剩一个用途：给"我的患者"的头像上色（归属标签已按用户要求隐藏）。
    final isMine = currentTherapistId != null &&
        patient.assignedTherapistId == currentTherapistId;
    final note = PatientRepository.flattenNote(patient.adminNote);

    return ListTile(
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => PatientDetailPage(inpatientNo: patient.inpatientNo),
        ),
      ),
      leading: CircleAvatar(
        backgroundColor: isMine
            ? theme.colorScheme.primaryContainer
            : theme.colorScheme.surfaceContainerHighest,
        child: Text(
          patient.name.characters.first,
          style: TextStyle(
            color: isMine ? theme.colorScheme.onPrimaryContainer : null,
            fontWeight: FontWeight.bold,
          ),
        ),
      ),
      title: Row(
        children: [
          Flexible(
            child: Text(
              patient.name,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
          ),
          const SizedBox(width: 8),
          // ★ 2026-10-06 用户要求：「在患者页的患者名后面，隐藏掉归属标签」。
          //
          // 原来这里会标「我的」/「未分配」。**归属仍然影响排序**（我的 →
          // 未分配 → 其他，由服务端算），只是不再用标签把它写在名字后面 ——
          // 治疗师要的是"我最近治过谁排在前面"，而不是被贴一个归属身份。
          //
          // 「暂停」是**患者状态**、不是归属，所以保留。
          if (patient.isPaused) const _Tag(text: '暂停', tone: _TagTone.warn),
        ],
      ),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('${patient.inpatientNo}'
              '${patient.diagnosis == null ? '' : ' · ${patient.diagnosis}'}'),
          if (note.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Row(
                children: [
                  Icon(Icons.info_outline, size: 14, color: theme.colorScheme.error),
                  const SizedBox(width: 4),
                  Expanded(
                    child: Text(
                      note,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(color: theme.colorScheme.error),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
      trailing: const Icon(Icons.chevron_right),
    );
  }
}

enum _TagTone { primary, neutral, warn }

class _Tag extends StatelessWidget {
  const _Tag({required this.text, required this.tone});

  final String text;
  final _TagTone tone;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final (bg, fg) = switch (tone) {
      _TagTone.primary => (scheme.primaryContainer, scheme.onPrimaryContainer),
      _TagTone.neutral => (scheme.surfaceContainerHighest, scheme.onSurfaceVariant),
      _TagTone.warn => (scheme.tertiaryContainer, scheme.onTertiaryContainer),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(4)),
      child: Text(text, style: TextStyle(fontSize: 11, color: fg)),
    );
  }
}

class _EmptyView extends StatelessWidget {
  const _EmptyView({required this.filter, required this.onRefresh});

  final PatientFilter filter;
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
          Icon(Icons.inbox_outlined, size: 56, color: theme.colorScheme.outline),
          const SizedBox(height: 12),
          Center(
            child: Text(
              switch (filter) {
                PatientFilter.dept => '本地还没有患者数据',
                PatientFilter.mine => '没有归属我的患者',
                PatientFilter.unassigned => '没有未分配的患者',
              },
              style: theme.textTheme.bodyLarge,
            ),
          ),
          const SizedBox(height: 6),
          Center(
            child: Text(
              '下拉可尝试同步',
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.outline),
            ),
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
            const Icon(Icons.error_outline, size: 44),
            const SizedBox(height: 10),
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            OutlinedButton(onPressed: onRetry, child: const Text('重试')),
          ],
        ),
      ),
    );
  }
}
