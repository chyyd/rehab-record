import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/features/auth/auth_controller.dart';
import 'package:rehab_app/features/patients/patient_list_page.dart';
import 'package:rehab_app/features/patients/patients_providers.dart';
import 'package:rehab_app/features/settings/settings_page.dart';
import 'package:rehab_app/features/sync/conflict_providers.dart';
import 'package:rehab_app/features/sync/conflicts_page.dart';
import 'package:rehab_app/features/timeline/timeline_page.dart';

/// 主界面外壳：底部导航 + 顶部同步状态。
///
/// 页签按竖切顺序逐步加：患者 → 排期 → 时间轴 → （汇总/打印从时间轴进入）。
/// 不预先塞空占位页 —— 空页签会让人以为功能坏了。
class HomeShell extends ConsumerStatefulWidget {
  const HomeShell({super.key});

  @override
  ConsumerState<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends ConsumerState<HomeShell> {
  int _index = 0;

  static const _titles = ['患者', '时间轴', '我的'];

  @override
  Widget build(BuildContext context) {
    final sync = ref.watch(patientSyncControllerProvider);
    final user = ref.watch(currentUserProvider);
    final conflictCount = ref.watch(conflictCountProvider).value ?? 0;

    // 冲突优先显示：它需要治疗师做决定，不能被"已更新 N 名患者"这种消息盖住。
    final banner = conflictCount > 0
        ? (
            text: '有 $conflictCount 条改动冲突待处理',
            isError: true,
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute<void>(builder: (_) => const ConflictsPage()),
            ),
            onDismiss: () {},
          )
        : sync.message == null
            ? null
            : (
                text: sync.message!,
                isError: sync.isError,
                onTap: null,
                onDismiss: () =>
                    ref.read(patientSyncControllerProvider.notifier).clearMessage(),
              );

    return Scaffold(
      appBar: AppBar(
        title: Text(_titles[_index]),
        actions: [
          // 患者页的同步按钮只作用于患者与记录；排期页自带刷新（它按周取数）；
          // 时间轴是服务端只读视图，刷新在它自己的空态/下拉里。
          if (_index == 0)
            IconButton(
              tooltip: '同步',
              onPressed: sync.syncing
                  ? null
                  : () => ref.read(patientSyncControllerProvider.notifier).refresh(),
              icon: sync.syncing
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.sync),
            ),
          // 时间轴是第 2 个页签（下标 1）—— 排期页签下线后前移了一位。
          if (_index == 1) const TimelineSummaryButton(),
          if (conflictCount > 0)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: Badge(
                label: Text('$conflictCount'),
                child: IconButton(
                  tooltip: '待处理的冲突',
                  icon: const Icon(Icons.report_problem_outlined),
                  onPressed: () => Navigator.of(context).push(
                    MaterialPageRoute<void>(builder: (_) => const ConflictsPage()),
                  ),
                ),
              ),
            ),
        ],
        bottom: banner == null
            ? null
            : PreferredSize(
                preferredSize: const Size.fromHeight(28),
                child: _SyncBanner(
                  text: banner.text,
                  isError: banner.isError,
                  onTap: banner.onTap,
                  onDismiss: banner.onDismiss,
                ),
              ),
      ),
      body: IndexedStack(
        index: _index,
        children: const [
          PatientListPage(),
          TimelinePage(),
          SettingsPage(),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: [
          const NavigationDestination(
            icon: Icon(Icons.people_outline),
            selectedIcon: Icon(Icons.people),
            label: '患者',
          ),
          const NavigationDestination(
            icon: Icon(Icons.timeline_outlined),
            selectedIcon: Icon(Icons.timeline),
            label: '时间轴',
          ),
          NavigationDestination(
            icon: const Icon(Icons.person_outline),
            selectedIcon: const Icon(Icons.person),
            // 把当前用户放在页签上，床旁一眼能确认是不是自己登录的。
            label: user?.name ?? '我的',
          ),
        ],
      ),
    );
  }
}

/// 同步结果提示条（成功/离线/冲突共用）。
class _SyncBanner extends StatelessWidget {
  const _SyncBanner({
    required this.text,
    required this.isError,
    required this.onDismiss,
    this.onTap,
  });

  final String text;
  final bool isError;
  final VoidCallback onDismiss;

  /// 可点时整条都能点（冲突提示点了直接进冲突页）。
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final content = Container(
      width: double.infinity,
      color: isError ? scheme.errorContainer : scheme.secondaryContainer,
      padding: const EdgeInsets.only(left: 16, right: 4),
      child: Row(
        children: [
          Icon(
            isError ? Icons.warning_amber_outlined : Icons.cloud_done_outlined,
            size: 16,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(text, style: const TextStyle(fontSize: 13)),
          ),
          if (onTap != null) Icon(Icons.chevron_right, size: 16),
          IconButton(
            icon: const Icon(Icons.close, size: 16),
            onPressed: onDismiss,
            tooltip: '关闭',
            visualDensity: VisualDensity.compact,
          ),
        ],
      ),
    );
    if (onTap == null) return content;
    return InkWell(onTap: onTap, child: content);
  }
}
