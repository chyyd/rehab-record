import 'package:flutter/material.dart';

import 'package:rehab_app/core/config.dart';
import 'package:rehab_app/data/repo/settings_repository.dart';

/// 「服务器设置」面板：手填后端地址，**探测通过才允许保存**。
///
/// 两个入口共用同一份实现（2026-10-06）：
///  - **登录页底部** —— 必需。地址填错时人根本进不去设置页，
///    那时如果只有设置页能改，用户就被锁在门外了；
///  - **「我的」→ 后端地址** —— 方便一个 App 在多套环境间切换。
///
/// 三道保护，都是为了让现场一次填对：
///  1. **先探测再保存** —— 打 `/health`（无需认证），连不上就不让存，
///     否则会把用户锁在一个打不通的地址上；
///  2. 探测结果里带上服务端自报的**服务名与版本**，让用户确认"连的是哪一套"；
///  3. **换地址会换本地库**（按后端指纹分文件），并在界面上**明确告知** ——
///     本地数据和后台都是按服务端 id 认人的，换服务器后旧数据必然对不上。
///
/// 返回值（`Navigator.pop`）：
///  - `null`：没改（用户取消、或只测试了连接）
///  - `true`：地址已变更，调用方需要重建服务图并让用户重新登录
class ServerSettingsSheet extends StatefulWidget {
  const ServerSettingsSheet({
    super.key,
    required this.repository,
    required this.current,
  });

  final SettingsRepository repository;
  final String current;

  @override
  State<ServerSettingsSheet> createState() => _ServerSettingsSheetState();
}

class _ServerSettingsSheetState extends State<ServerSettingsSheet> {
  late final TextEditingController _url =
      TextEditingController(text: widget.current);
  bool _busy = false;
  String? _error;
  String? _success;

  @override
  void dispose() {
    _url.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    FocusScope.of(context).unfocus();
    setState(() {
      _busy = true;
      _error = null;
      _success = null;
    });

    final result = await widget.repository.probe(_url.text);
    if (!mounted) return;

    if (!result.ok) {
      setState(() {
        _busy = false;
        _error = result.message ?? '连接失败';
      });
      return;
    }

    final changed = result.baseUrl != widget.current;
    await widget.repository.save(result.baseUrl);
    if (!mounted) return;
    setState(() {
      _busy = false;
      _success = '连接成功${result.message == null ? '' : '：${result.message}'}'
          '${changed ? '（本地数据已切换到该服务器的独立副本）' : ''}';
    });
    // 让调用方刷新服务图；地址没变就不用重建。
    if (changed) {
      await Future<void>.delayed(const Duration(milliseconds: 900));
      if (mounted) Navigator.of(context).pop(true);
    }
  }

  Future<void> _reset() async {
    setState(() => _busy = true);
    await widget.repository.resetToDefault();
    if (!mounted) return;
    Navigator.of(context).pop(AppConfig.environmentBaseUrl() != widget.current);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 18,
        bottom: MediaQuery.of(context).viewInsets.bottom + 20,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              const Icon(Icons.dns_outlined),
              const SizedBox(width: 8),
              Text('服务器设置', style: theme.textTheme.titleMedium),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            '填后端服务地址（不含 /api/v1）。换服务器会切换到对应服务器的'
            '本地数据副本 —— 两台服务器的记录编号互不相通，不能混用。',
            style: theme.textTheme.bodySmall
                ?.copyWith(color: theme.colorScheme.outline),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _url,
            autofocus: true,
            keyboardType: TextInputType.url,
            autocorrect: false,
            decoration: const InputDecoration(
              labelText: '服务器地址',
              hintText: 'http://10.0.0.8:8000',
              prefixIcon: Icon(Icons.link),
            ),
            onSubmitted: (_) => _busy ? null : _save(),
          ),
          const SizedBox(height: 8),
          Text(
            '当前：${widget.current}',
            style: theme.textTheme.bodySmall
                ?.copyWith(color: theme.colorScheme.outline),
          ),
          if (_error != null) ...[
            const SizedBox(height: 12),
            _SheetBanner(
              icon: Icons.error_outline,
              text: _error!,
              color: theme.colorScheme.errorContainer,
            ),
          ],
          if (_success != null) ...[
            const SizedBox(height: 12),
            _SheetBanner(
              icon: Icons.check_circle_outline,
              text: _success!,
              color: theme.colorScheme.tertiaryContainer,
            ),
          ],
          const SizedBox(height: 18),
          FilledButton(
            onPressed: _busy ? null : _save,
            child: _busy
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text('测试连接并保存'),
          ),
          TextButton(
            onPressed: _busy ? null : _reset,
            child: const Text('恢复默认地址'),
          ),
        ],
      ),
    );
  }
}

/// 面板内的提示条（与登录页那份同形，避免两处样式漂移）。
class _SheetBanner extends StatelessWidget {
  const _SheetBanner({
    required this.icon,
    required this.text,
    required this.color,
  });

  final IconData icon;
  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 18),
          const SizedBox(width: 8),
          Expanded(child: Text(text)),
        ],
      ),
    );
  }
}
