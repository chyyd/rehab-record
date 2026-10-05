import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

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
                  ],
                ),
              ),
            ),
          ),
        ),
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
