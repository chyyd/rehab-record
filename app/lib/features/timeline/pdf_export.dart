import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:open_filex/open_filex.dart';

import 'package:rehab_app/features/timeline/timeline_providers.dart';

/// PDF 导出按钮：一个入口，三种去向。
///
/// 三种去向对应科室里真实的三种用法：
///  - **发送给微信**：把 PDF 发给护士站/家属（走系统分享面板，微信装了就会出现）；
///  - **系统打印**：无线打印机（走 Android 打印服务，不是"分享文件"）；
///  - **打开**：先自己看一眼版式对不对，再决定发不发。
///
/// 下载、命名（带时间戳）、错误文案都在 [PrintController] 里，这里只管交互。
class PdfExportButton extends ConsumerWidget {
  const PdfExportButton({
    super.key,
    required this.path,
    required this.filenamePrefix,
    this.query,
    this.jobName,
  });

  /// 服务端打印接口路径（如 `kPrintSummaryDate`）。
  final String path;

  /// 文件名前缀（会拼上时间戳）。
  final String filenamePrefix;

  final Map<String, dynamic>? query;

  /// 打印任务名（缺省用文件名）。
  final String? jobName;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final busy = ref.watch(printControllerProvider).busy;

    Future<void> pick(String action) async {
      final controller = ref.read(printControllerProvider.notifier);
      switch (action) {
        case 'share':
          await controller.share(
            path: path,
            filenamePrefix: filenamePrefix,
            query: query,
          );
        case 'print':
          await controller.print(
            path: path,
            filenamePrefix: filenamePrefix,
            query: query,
            jobName: jobName,
          );
        case 'open':
          await controller.downloadAndOpen(
            path: path,
            filenamePrefix: filenamePrefix,
            query: query,
          );
          final p = ref.read(printControllerProvider).path;
          if (p != null) await OpenFilex.open(p);
      }
    }

    return PopupMenuButton<String>(
      tooltip: '导出 PDF',
      enabled: !busy,
      onSelected: pick,
      icon: busy
          ? const SizedBox(
              width: 18,
              height: 18,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          : const Icon(Icons.ios_share),
      itemBuilder: (_) => const [
        PopupMenuItem(
          value: 'share',
          child: ListTile(
            dense: true,
            contentPadding: EdgeInsets.zero,
            leading: Icon(Icons.share_outlined),
            title: Text('发送给微信 / 其他应用'),
          ),
        ),
        PopupMenuItem(
          value: 'print',
          child: ListTile(
            dense: true,
            contentPadding: EdgeInsets.zero,
            leading: Icon(Icons.print_outlined),
            title: Text('系统打印（含无线打印机）'),
          ),
        ),
        PopupMenuItem(
          value: 'open',
          child: ListTile(
            dense: true,
            contentPadding: EdgeInsets.zero,
            leading: Icon(Icons.open_in_new),
            title: Text('先打开看看'),
          ),
        ),
      ],
    );
  }
}

/// PDF 导出结果的提示条（成功/失败共用，两个汇总页共用）。
class PrintResultBar extends ConsumerWidget {
  const PrintResultBar({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final print = ref.watch(printControllerProvider);
    if (print.message == null) return const SizedBox.shrink();

    final scheme = Theme.of(context).colorScheme;
    return Container(
      width: double.infinity,
      color: print.isError ? scheme.errorContainer : scheme.secondaryContainer,
      padding: const EdgeInsets.only(left: 12, right: 4),
      child: Row(
        children: [
          Icon(
            print.isError
                ? Icons.warning_amber_outlined
                : Icons.picture_as_pdf_outlined,
            size: 16,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              print.message!,
              style: const TextStyle(fontSize: 12),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ),
          // 已下载到本地时给一个"打开"的快捷入口。
          if (print.path != null)
            IconButton(
              tooltip: '打开',
              icon: const Icon(Icons.open_in_new, size: 16),
              visualDensity: VisualDensity.compact,
              onPressed: () => OpenFilex.open(print.path!),
            ),
          IconButton(
            icon: const Icon(Icons.close, size: 16),
            tooltip: '关闭',
            visualDensity: VisualDensity.compact,
            onPressed: () => ref.read(printControllerProvider.notifier).clear(),
          ),
        ],
      ),
    );
  }
}
