import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/core/providers.dart';
import 'package:rehab_app/core/route_observer.dart';
import 'package:rehab_app/features/auth/auth_controller.dart';
import 'package:rehab_app/features/auth/login_page.dart';
import 'package:rehab_app/features/home/home_shell.dart';

/// 应用根。
///
/// 分三层门：
///  1. `appServicesProvider` 就绪（读 CA、开库）—— 未就绪时是真正的 loading；
///  2. 认证状态判定中（`AuthUnknown`，正在用 refresh token 恢复会话）；
///  3. 已定：登录页 或 主界面。
///
/// 注意第 2 层必须单独处理：直接按"未登录"渲染登录页会导致已登录用户
/// **每次冷启动都闪一下登录页**。
class RehabApp extends ConsumerWidget {
  const RehabApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return MaterialApp(
      title: '康复科治疗记录',
      debugShowCheckedModeBanner: false,
      theme: _buildTheme(),
      // 让页面能在"从子页返回、我又可见"时刷新（用户：「每次返回患者页自动刷新」）。
      // 见 `core/route_observer.dart` 里为什么 `initState` 不够。
      navigatorObservers: [appRouteObserver],
      home: const _BootstrapGate(),
    );
  }

  ThemeData _buildTheme() {
    // 床旁使用：字号偏大、对比偏强，减少误触与看不清。
    final scheme = ColorScheme.fromSeed(seedColor: const Color(0xFF00696D));
    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      visualDensity: VisualDensity.comfortable,
      listTileTheme: const ListTileThemeData(minVerticalPadding: 14),
      inputDecorationTheme: const InputDecorationTheme(
        border: OutlineInputBorder(),
        contentPadding: EdgeInsets.symmetric(horizontal: 14, vertical: 16),
      ),
    );
  }
}

class _BootstrapGate extends ConsumerStatefulWidget {
  const _BootstrapGate();

  @override
  ConsumerState<_BootstrapGate> createState() => _BootstrapGateState();
}

class _BootstrapGateState extends ConsumerState<_BootstrapGate> {
  bool _restoreRequested = false;

  @override
  Widget build(BuildContext context) {
    final services = ref.watch(appServicesProvider);

    return services.when(
      loading: () => const _SplashScreen(message: '正在启动…'),
      error: (error, stack) => _StartupFailure(message: '$error'),
      data: (_) {
        // 服务图就绪后再触发一次会话恢复（冷启动用 refresh token 换 access）。
        if (!_restoreRequested) {
          _restoreRequested = true;
          WidgetsBinding.instance.addPostFrameCallback((_) {
            ref.read(authControllerProvider.notifier).restore();
          });
        }

        final auth = ref.watch(authControllerProvider);
        return switch (auth) {
          AuthUnknown() => const _SplashScreen(message: '正在恢复登录状态…'),
          AuthSignedOut(:final reason) => LoginPage(sessionExpiredReason: reason),
          AuthSignedIn() => const HomeShell(),
        };
      },
    );
  }
}

class _SplashScreen extends StatelessWidget {
  const _SplashScreen({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(
              width: 36,
              height: 36,
              child: CircularProgressIndicator(strokeWidth: 3),
            ),
            const SizedBox(height: 16),
            Text(message, style: Theme.of(context).textTheme.bodyLarge),
          ],
        ),
      ),
    );
  }
}

class _StartupFailure extends ConsumerWidget {
  const _StartupFailure({required this.message});

  final String message;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.error_outline, size: 44),
              const SizedBox(height: 12),
              const Text('启动失败', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              Text(message, textAlign: TextAlign.center),
              const SizedBox(height: 20),
              FilledButton(
                onPressed: () => ref.invalidate(appServicesProvider),
                child: const Text('重试'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
