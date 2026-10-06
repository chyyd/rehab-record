import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/core/providers.dart';
import 'package:rehab_app/features/auth/auth_controller.dart';
import 'package:rehab_app/features/settings/server_settings_sheet.dart';

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
      builder: (_) => ServerSettingsSheet(
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

