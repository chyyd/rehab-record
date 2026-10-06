import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/core/config.dart';
import 'package:rehab_app/core/providers.dart';
import 'package:rehab_app/data/repo/settings_repository.dart';
import 'package:rehab_app/features/auth/auth_controller.dart';

/// 登录页。
///
/// 床旁场景的两个要点：
///  1. **工号 + 密码**，不做"记住密码"——令牌已经放在安全存储里自动恢复会话；
///  2. 登录失败**不区分**"工号不存在"与"密码错误"（服务端有意为之，防工号枚举），
///     所以直接展示服务端文案，不自己拼提示。
class LoginPage extends ConsumerStatefulWidget {
  const LoginPage({super.key, this.sessionExpiredReason});

  /// 被动登出的原因（会话失效时由 [AuthSignedOut.reason] 传入）。
  final String? sessionExpiredReason;

  @override
  ConsumerState<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends ConsumerState<LoginPage> {
  final _formKey = GlobalKey<FormState>();
  final _employeeNo = TextEditingController();
  final _password = TextEditingController();
  bool _obscure = true;

  @override
  void dispose() {
    _employeeNo.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    FocusScope.of(context).unfocus();
    await ref
        .read(loginControllerProvider.notifier)
        .submit(_employeeNo.text, _password.text);
  }

  @override
  Widget build(BuildContext context) {
    final login = ref.watch(loginControllerProvider);
    final theme = Theme.of(context);

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Form(
                key: _formKey,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Icon(Icons.medical_services_outlined,
                        size: 56, color: theme.colorScheme.primary),
                    const SizedBox(height: 12),
                    Text(
                      '康复科治疗记录',
                      textAlign: TextAlign.center,
                      style: theme.textTheme.headlineSmall
                          ?.copyWith(fontWeight: FontWeight.bold),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '治疗师床旁记录',
                      textAlign: TextAlign.center,
                      style: theme.textTheme.bodyMedium
                          ?.copyWith(color: theme.colorScheme.outline),
                    ),
                    const SizedBox(height: 28),

                    if (widget.sessionExpiredReason != null) ...[
                      _Banner(
                        icon: Icons.info_outline,
                        text: widget.sessionExpiredReason!,
                        color: theme.colorScheme.tertiaryContainer,
                      ),
                      const SizedBox(height: 12),
                    ],

                    TextFormField(
                      controller: _employeeNo,
                      autofocus: true,
                      textInputAction: TextInputAction.next,
                      autocorrect: false,
                      decoration: const InputDecoration(
                        labelText: '工号',
                        prefixIcon: Icon(Icons.badge_outlined),
                      ),
                      validator: (v) =>
                          (v == null || v.trim().isEmpty) ? '请输入工号' : null,
                    ),
                    const SizedBox(height: 14),
                    TextFormField(
                      controller: _password,
                      obscureText: _obscure,
                      textInputAction: TextInputAction.done,
                      onFieldSubmitted: (_) => _submit(),
                      decoration: InputDecoration(
                        labelText: '密码',
                        prefixIcon: const Icon(Icons.lock_outline),
                        suffixIcon: IconButton(
                          icon: Icon(_obscure
                              ? Icons.visibility_outlined
                              : Icons.visibility_off_outlined),
                          onPressed: () => setState(() => _obscure = !_obscure),
                          tooltip: _obscure ? '显示密码' : '隐藏密码',
                        ),
                      ),
                      validator: (v) =>
                          (v == null || v.isEmpty) ? '请输入密码' : null,
                    ),

                    if (login.hasError) ...[
                      const SizedBox(height: 14),
                      _Banner(
                        icon: Icons.error_outline,
                        text: login.error!,
                        color: theme.colorScheme.errorContainer,
                      ),
                    ],

                    const SizedBox(height: 24),
                    FilledButton(
                      onPressed: login.submitting ? null : _submit,
                      style: FilledButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 16),
                      ),
                      child: login.submitting
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Text('登录', style: TextStyle(fontSize: 16)),
                    ),
                    const SizedBox(height: 16),
                    Text(
                      '登录后即使无网络也能继续记录；数据会在联网后自动上传。',
                      textAlign: TextAlign.center,
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: theme.colorScheme.outline),
                    ),

                    // ★ 2026-10-06：服务器地址入口。
                    //
                    // 必须放在**登录页**：地址填错时人根本进不去设置页，
                    // 那时如果只有设置页能改地址，用户就被锁在门外了
                    //（这是他提出这个需求时的原话场景：
                    //  「如果app找不到后端，那么登录时应该有后端地址的手动设置」）。
                    const SizedBox(height: 20),
                    const Divider(height: 1),
                    const SizedBox(height: 6),
                    _ServerEntry(
                      address: ref.watch(appServicesProvider).value?.config.baseUrl,
                      onTap: _openServerSheet,
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  /// 打开「服务器设置」底部面板。
  Future<void> _openServerSheet() async {
    final services = ref.read(appServicesProvider).value;
    if (services == null) {
      // 启动门还没把服务装配好（正常不会走到：登录页只在服务就绪后渲染）。
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('应用仍在启动，请稍候再试')),
      );
      return;
    }
    final changed = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _ServerSheet(
        repository: services.settings,
        current: services.config.baseUrl,
      ),
    );
    if (changed == true && mounted) {
      // 地址变了：把服务图整个重建（新 baseUrl、新库文件），
      // 并让用户重新登录 —— 旧令牌属于旧服务器，必然无效。
      ref.invalidate(appServicesProvider);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('服务器地址已更新，请登录')),
      );
    }
  }
}

/// 登录页底部的服务器入口（一行文字 + 当前地址）。
class _ServerEntry extends StatelessWidget {
  const _ServerEntry({required this.address, required this.onTap});

  final String? address;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return TextButton.icon(
      onPressed: onTap,
      icon: const Icon(Icons.dns_outlined, size: 18),
      label: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text('服务器设置'),
          Text(
            address ?? '读取中…',
            style: theme.textTheme.bodySmall
                ?.copyWith(color: theme.colorScheme.outline),
          ),
        ],
      ),
    );
  }
}

/// 统一的提示条（错误 / 提示共用，避免两套样式）。
class _Banner extends StatelessWidget {
  const _Banner({required this.icon, required this.text, required this.color});

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

/// 「服务器设置」底部面板：手填后端地址，**探测通过才允许保存**。
///
/// 三道保护，都是为了让现场一次填对：
///  1. **先探测再保存** —— 打 `/health`（无需认证），连不上就不让存，
///     否则会把用户锁在一个打不通的地址上；
///  2. 探测结果里带上服务端自报的**服务名与版本**，让用户确认"连的是哪一套"；
///  3. **换地址会换本地库**（按后端指纹分文件），并在界面上**明确告知** ——
///     本地数据和后台都是按服务端 id 认人的，换服务器后旧数据必然对不上。
class _ServerSheet extends StatefulWidget {
  const _ServerSheet({required this.repository, required this.current});

  final SettingsRepository repository;
  final String current;

  @override
  State<_ServerSheet> createState() => _ServerSheetState();
}

class _ServerSheetState extends State<_ServerSheet> {
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
    final changed = AppConfig.environmentBaseUrl() != widget.current;
    Navigator.of(context).pop(changed);
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
            _Banner(
              icon: Icons.error_outline,
              text: _error!,
              color: theme.colorScheme.errorContainer,
            ),
          ],
          if (_success != null) ...[
            const SizedBox(height: 12),
            _Banner(
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
