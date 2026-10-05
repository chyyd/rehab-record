import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/core/disciplines.dart';
import 'package:rehab_app/features/sync/conflict_providers.dart';

/// 离线冲突处理页。
///
/// ## 为什么会有冲突
///
/// 离线队列里的改动推上去时，服务端发现**这条数据已经不是当初那个版本了**
/// （别人改过它，或者它已经被提交/锁定）。此时不能静默覆盖，
/// 也不能静默丢弃 —— 必须让治疗师看一眼再裁决（协议 §4.4 / §6）。
///
/// ## 两个选择的代价必须讲清楚
///
/// - **保留我的**：会用本地内容覆盖服务端**当前**版本。如果这条记录别人也在改，
///   对方的改动就没了 —— 所以点之前要确认。
/// - **采用服务端**：丢弃本地这份改动。如果本地是刚在床旁记的内容，会真的丢掉。
///
/// 两个都不是"安全选项"，所以这里不做默认高亮，也不做"一键全部保留我的"。
/// 只提供"全部采用服务端"（它至少是保守方向：不覆盖别人）。
class ConflictsPage extends ConsumerStatefulWidget {
  const ConflictsPage({super.key});

  @override
  ConsumerState<ConflictsPage> createState() => _ConflictsPageState();
}

class _ConflictsPageState extends ConsumerState<ConflictsPage> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) ref.read(conflictControllerProvider.notifier).reload();
    });
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(conflictControllerProvider);
    final controller = ref.read(conflictControllerProvider.notifier);
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('待处理的冲突'),
        actions: [
          if (state.items.length > 1)
            TextButton(
              onPressed: state.busy ? null : () => _confirmUseServerForAll(context, controller, state),
              child: const Text('全部采用服务端'),
            ),
        ],
        bottom: state.message == null
            ? null
            : PreferredSize(
                preferredSize: const Size.fromHeight(30),
                child: _Bar(
                  text: state.message!,
                  isError: state.isError,
                  onDismiss: controller.clearMessage,
                ),
              ),
      ),
      body: state.busy
          ? const Center(child: CircularProgressIndicator())
          : state.isEmpty
              ? _Empty(theme: theme)
              : ListView.builder(
                  padding: const EdgeInsets.all(12),
                  itemCount: state.items.length,
                  itemBuilder: (context, i) => _ConflictCard(
                    item: state.items[i],
                    onKeepMine: () => _confirmKeepMine(context, controller, state.items[i]),
                    onUseServer: () => controller.useServer(state.items[i]),
                  ),
                ),
    );
  }

  Future<void> _confirmKeepMine(
    BuildContext context,
    ConflictController controller,
    ConflictItem item,
  ) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('用我的版本覆盖服务端？'),
        content: Text(
          '这会把服务端当前的这条${item.entityLabel}覆盖成你本地这份内容。\n\n'
          '如果别人也在改这条记录，对方的改动会丢失。\n'
          '只有当你能确认"服务端那份是旧的或不对的"时才这么做。',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('确认覆盖'),
          ),
        ],
      ),
    );
    if (ok == true) await controller.keepMine(item);
  }

  Future<void> _confirmUseServerForAll(
    BuildContext context,
    ConflictController controller,
    ConflictState state,
  ) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('全部采用服务端（${state.items.length} 条）？'),
        content: Text(
          '本地这 ${state.items.length} 条改动都会被丢弃，改成服务端当前的版本。\n'
          '这是保守方向（不会覆盖别人的改动），但本地内容会真的丢掉。',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('全部丢弃'),
          ),
        ],
      ),
    );
    if (ok == true) await controller.useServerForAll();
  }
}

class _ConflictCard extends StatelessWidget {
  const _ConflictCard({
    required this.item,
    required this.onKeepMine,
    required this.onUseServer,
  });

  final ConflictItem item;
  final VoidCallback onKeepMine;
  final VoidCallback onUseServer;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Chip(
                  visualDensity: VisualDensity.compact,
                  label: Text(item.entityLabel, style: const TextStyle(fontSize: 11)),
                ),
                const SizedBox(width: 6),
                Text(item.opLabel, style: const TextStyle(fontWeight: FontWeight.bold)),
                const Spacer(),
                Text(
                  item.dateLabel,
                  style: TextStyle(fontSize: 12, color: theme.colorScheme.outline),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              '患者 ${item.patientNo ?? '—'} · ${item.kindLabel}'
              '${item.discipline == null ? '' : ' · ${Discipline.nameOf(item.discipline!)}'}'
              '${item.itemCount > 0 ? ' · 填了 ${item.itemCount} 项' : ''}',
              style: const TextStyle(fontSize: 13),
            ),
            const SizedBox(height: 6),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: theme.colorScheme.errorContainer,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(Icons.report_problem_outlined,
                      size: 16, color: theme.colorScheme.onErrorContainer),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      item.reasonLabel,
                      style: TextStyle(
                        fontSize: 12,
                        color: theme.colorScheme.onErrorContainer,
                      ),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 6),
            _PayloadView(item: item),
            const Divider(height: 18),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: onUseServer,
                    icon: const Icon(Icons.cloud_download_outlined, size: 18),
                    label: const Text('采用服务端'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: FilledButton.icon(
                    onPressed: onKeepMine,
                    icon: const Icon(Icons.upload_outlined, size: 18),
                    label: const Text('保留我的'),
                  ),
                ),
              ],
            ),
            if (item.retryCount > 0)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  '已重试 ${item.retryCount} 次',
                  style: TextStyle(fontSize: 11, color: theme.colorScheme.outline),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// 本地这一版到底改了什么 —— 治疗师必须看得到才能判断。
class _PayloadView extends StatelessWidget {
  const _PayloadView({required this.item});

  final ConflictItem item;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final rows = <(String, String)>[];

    final p = item.payload;
    if (p['record_date'] != null || p['date'] != null) {
      rows.add(('日期', '${p['record_date'] ?? p['date']}'));
    }
    if (p['kind'] != null) {
      rows.add(('形态', item.kindLabel));
    }
    if (p['discipline'] != null) {
      rows.add(('大类', Discipline.nameOf('${p['discipline']}')));
    }
    if (p['status'] != null) rows.add(('状态', '${p['status']}'));
    if (p['note'] != null && '${p['note']}'.isNotEmpty) {
      rows.add(('备注', '${p['note']}'));
    }
    // SOAP 模型：内容就是一整个 `body`（`{field_key: value}`）。
    final body = p['body'];
    if (body is Map && body.isNotEmpty) {
      final parts = body.entries
          .map((e) {
            final value = e.value;
            final text = value is List ? value.join('/') : '$value';
            return '${e.key}=$text';
          })
          .join('；');
      rows.add(('内容', parts));
    }

    if (rows.isEmpty) {
      // 载荷里没有可读字段（或解析失败）：如实说明，不要假装"没有改动"。
      return Text(
        '这份改动的内容无法解析（载荷为空或格式异常）',
        style: TextStyle(fontSize: 12, color: theme.colorScheme.outline),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('本地这一版的内容',
            style: TextStyle(fontSize: 11, color: theme.colorScheme.outline)),
        const SizedBox(height: 2),
        for (final (label, value) in rows)
          Padding(
            padding: const EdgeInsets.only(bottom: 2),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  width: 68,
                  child: Text(label,
                      style: TextStyle(fontSize: 12, color: theme.colorScheme.outline)),
                ),
                Expanded(child: Text(value, style: const TextStyle(fontSize: 12))),
              ],
            ),
          ),
      ],
    );
  }
}

class _Empty extends StatelessWidget {
  const _Empty({required this.theme});

  final ThemeData theme;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.check_circle_outline, size: 56, color: theme.colorScheme.primary),
            const SizedBox(height: 12),
            const Text('没有待处理的冲突',
                style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
            const SizedBox(height: 6),
            Text(
              '离线期间记录的改动都已同步成功。\n'
              '出现冲突时，这里会列出"本地这一版"供你裁决。',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12, color: theme.colorScheme.outline),
            ),
          ],
        ),
      ),
    );
  }
}

class _Bar extends StatelessWidget {
  const _Bar({required this.text, required this.isError, required this.onDismiss});

  final String text;
  final bool isError;
  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      width: double.infinity,
      color: isError ? scheme.errorContainer : scheme.secondaryContainer,
      padding: const EdgeInsets.only(left: 12, right: 4),
      child: Row(
        children: [
          Icon(isError ? Icons.warning_amber_outlined : Icons.cloud_done_outlined, size: 16),
          const SizedBox(width: 8),
          Expanded(child: Text(text, style: const TextStyle(fontSize: 12))),
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
