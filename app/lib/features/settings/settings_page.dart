import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/core/providers.dart';
import 'package:rehab_app/features/auth/auth_controller.dart';
import 'package:rehab_app/features/patients/patients_providers.dart';
import 'package:rehab_app/features/sync/conflict_providers.dart';
import 'package:rehab_app/features/sync/conflicts_page.dart';

/// "我的"页签：当前用户、同步状态、退出登录。
///
/// 顺带把服务端地址与本地库概况露出来 —— 内网部署时排障（"到底连的是哪个后端"
/// "本地有多少数据"）全靠它，比让人去翻日志快得多。
class SettingsPage extends ConsumerWidget {
  const SettingsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(currentUserProvider);
    final services = ref.watch(appServicesProvider).value;
    final pending = ref.watch(pendingCountProvider);
    final conflicts = ref.watch(conflictCountProvider);
    final lastSync = ref.watch(lastPatientSyncProvider);
    final conflictCount = conflicts.value ?? 0;

    return ListView(
      children: [
        ListTile(
          leading: const CircleAvatar(child: Icon(Icons.person)),
          title: Text(user?.name ?? '未登录'),
          subtitle: Text(
            '${user?.employeeNo ?? ''}'
            '${user?.isAdmin == true ? ' · 管理员' : ' · 治疗师'}',
          ),
        ),
        const Divider(),

        // 冲突放在最上面：它需要治疗师做决定，不能埋在设置里被忽略。
        ListTile(
          leading: Icon(
            conflictCount > 0 ? Icons.report_problem_outlined : Icons.check_circle_outline,
            color: conflictCount > 0 ? Theme.of(context).colorScheme.error : null,
          ),
          title: Text(conflictCount > 0 ? '待处理的冲突（$conflictCount）' : '待处理的冲突'),
          subtitle: Text(
            conflictCount > 0
                ? '有 $conflictCount 条改动没能上传，需要你决定保留哪一版'
                : '没有冲突',
          ),
          trailing: conflictCount > 0 ? const Icon(Icons.chevron_right) : null,
          onTap: () => Navigator.of(context).push(
            MaterialPageRoute<void>(builder: (_) => const ConflictsPage()),
          ),
        ),

        ListTile(
          leading: const Icon(Icons.dns_outlined),
          title: const Text('后端地址'),
          subtitle: Text(services?.config.baseUrl ?? '—'),
        ),
        ListTile(
          leading: const Icon(Icons.lock_outline),
          title: const Text('内网证书'),
          subtitle: Text(
            services?.config.trustedCaAsset == null
                ? '使用系统信任链'
                : '已内置 ${services!.config.trustedCaAsset}',
          ),
        ),
        ListTile(
          leading: const Icon(Icons.cloud_upload_outlined),
          title: const Text('待同步'),
          subtitle: Text(
            pending.when(
              data: (n) => n == 0 ? '无（本地已全部上传）' : '$n 条待上传',
              loading: () => '…',
              error: (e, _) => '$e',
            ),
          ),
        ),
        ListTile(
          leading: const Icon(Icons.history),
          title: const Text('上次同步患者'),
          subtitle: Text(
            lastSync.when(
              data: (t) => t == null
                  ? '尚未同步'
                  : t.toLocal().toString().split('.').first,
              loading: () => '…',
              error: (e, _) => '$e',
            ),
          ),
        ),

        const Divider(),
        ListTile(
          leading: const Icon(Icons.sync),
          title: const Text('立即同步'),
          onTap: () => ref.read(patientSyncControllerProvider.notifier).refresh(),
        ),
        ListTile(
          leading: Icon(Icons.logout, color: Theme.of(context).colorScheme.error),
          title: Text(
            '退出登录',
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
          subtitle: const Text('会同时吊销服务端会话，但保留本地数据'),
          onTap: () => _confirmSignOut(context, ref),
        ),
        const SizedBox(height: 24),
        Center(
          child: Text(
            '康复科治疗过程记录系统 · 安卓端',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ),
        const SizedBox(height: 16),
      ],
    );
  }

  Future<void> _confirmSignOut(BuildContext context, WidgetRef ref) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('退出登录'),
        content: const Text(
          '本地已录入的数据**不会**被删除，重新登录后会继续上传。\n'
          '确定退出吗？',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('退出')),
        ],
      ),
    );
    if (ok != true) return;
    await ref.read(authControllerProvider.notifier).signOut();
  }
}
