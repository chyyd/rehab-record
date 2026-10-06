import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/features/auth/auth_controller.dart';
import 'package:rehab_app/features/patients/patient_list_page.dart';
import 'package:rehab_app/features/patients/patients_providers.dart';
import 'package:rehab_app/features/settings/settings_page.dart';
import 'package:rehab_app/features/sync/conflict_providers.dart';
import 'package:rehab_app/features/sync/conflicts_page.dart';
import 'package:rehab_app/features/timeline/timeline_page.dart';
import 'package:rehab_app/sync/auto_sync.dart';

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

  /// ★ 2026-10-06：主动定时同步。
  ///
  /// 挂在这里而不是各页面：主界面外壳只在**登录后**存在，
  /// 生命周期与"有人正在用这个 App"一致 —— 登录页不需要同步，
  /// 退出登录后也不该继续跑（`dispose` 会停表）。
  late final AutoSync _autoSync = AutoSync(
    tick: () =>
        ref.read(patientSyncControllerProvider.notifier).refreshQuietly(),
  );

  @override
  void initState() {
    super.initState();
    // 等首帧再启动：`initState` 里读 provider 会撞上"服务图尚未就绪"。
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _autoSync.start();
    });
  }

  @override
  void dispose() {
    _autoSync.stop();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final sync = ref.watch(patientSyncControllerProvider);
    final user = ref.watch(currentUserProvider);
    final conflictCount = ref.watch(conflictCountProvider).value ?? 0;

    // 冲突优先显示：它需要治疗师做决定，不能被"已更新 N 名患者"这种消息盖住。
    //
    // `autoFade`：**只有成功提示自己消失**（用户 2026-10-06：「显示"已更新X名患者"后，
    // 2 秒后渐隐」）。冲突与报错要留到人处理 —— 自己消失等于把问题藏起来。
    final banner = conflictCount > 0
        ? (
            text: '有 $conflictCount 条改动冲突待处理',
            isError: true,
            seq: 0,
            autoFade: false,
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
                seq: sync.messageSeq,
                // 成功 → 渐隐；离线/报错 → 留着
                autoFade: !sync.isError,
                onTap: null,
                onDismiss: () =>
                    ref.read(patientSyncControllerProvider.notifier).clearMessage(),
              );

    return Scaffold(
      appBar: AppBar(
        title: Text(_titles[_index]),
        actions: [
          // 患者页的同步按钮只作用于患者与治疗记录；
          // 时间轴是服务端只读视图（没有离线写入），刷新在它自己的空态/下拉里。
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
                child: FadeOutAfter(
                  // ★ 用 `messageSeq` 当 key（而不是 `text`）：每条**新**提示
                  //   重新计时渐隐。用文案当 key 的话，连续两次
                  //   「已更新 6 名患者」会被当成同一条，第二次不再重新计时。
                  key: ValueKey(banner.seq),
                  // 冲突/报错要留到人处理，不能自己消失。
                  duration: banner.autoFade
                      ? const Duration(seconds: 2)
                      : Duration.zero,
                  onFaded: banner.onDismiss,
                  child: _SyncBanner(
                    text: banner.text,
                    isError: banner.isError,
                    onTap: banner.onTap,
                    onDismiss: banner.onDismiss,
                  ),
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

/// 显示 [duration] 后**渐隐并回调** [onFaded]；[duration] 为零则常驻。
///
/// 2026-10-06 用户：「显示"已更新X名患者"后，2 秒后渐隐」。
///
/// 抽成独立 widget 而不是写在 `_SyncBanner` 里，是为了**能单测**：
/// 渐隐靠定时器 + 动画，混在业务页面里只能靠肉眼看。
class FadeOutAfter extends StatefulWidget {
  const FadeOutAfter({
    super.key,
    required this.child,
    required this.duration,
    required this.onFaded,
  });

  final Widget child;

  /// 停留多久后开始渐隐；[Duration.zero] 表示**不**自动消失。
  final Duration duration;

  /// 渐隐结束后调用（通常用来清掉上层状态，让横幅真正移除）。
  final VoidCallback onFaded;

  @override
  State<FadeOutAfter> createState() => _FadeOutAfterState();
}

class _FadeOutAfterState extends State<FadeOutAfter> {
  /// 渐隐动画时长。与 [FadeOutAfter.duration]（停留时间）是两件事：
  /// 先「完整显示 2 秒」，再「用 300ms 淡出」。
  static const Duration _fade = Duration(milliseconds: 300);

  double _opacity = 1;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _schedule();
  }

  @override
  void didUpdateWidget(FadeOutAfter oldWidget) {
    super.didUpdateWidget(oldWidget);
    // key 变了会走新的 State，所以这里只需处理"同一个实例 duration 变了"。
    if (oldWidget.duration != widget.duration) {
      _timer?.cancel();
      _opacity = 1;
      _schedule();
    }
  }

  void _schedule() {
    if (widget.duration == Duration.zero) return;
    _timer = Timer(widget.duration, () {
      if (!mounted) return;
      setState(() => _opacity = 0);
      // 等淡出动画跑完再回调，避免"还没淡完就被移除"的突兀感。
      Future<void>.delayed(_fade, () {
        if (mounted) widget.onFaded();
      });
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (widget.duration == Duration.zero) return widget.child;
    return AnimatedOpacity(
      opacity: _opacity,
      duration: _fade,
      child: widget.child,
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
