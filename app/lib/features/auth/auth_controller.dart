import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/core/error.dart';
import 'package:rehab_app/core/providers.dart';
import 'package:rehab_app/data/remote/auth_service.dart';

/// 认证状态。
sealed class AuthState {
  const AuthState();
}

/// 尚未判断（启动中，正在用 refresh token 试着恢复会话）。
class AuthUnknown extends AuthState {
  const AuthUnknown();
}

/// 未登录（或会话已失效）。
class AuthSignedOut extends AuthState {
  const AuthSignedOut({this.reason});

  /// 被动登出的原因（如 refresh 失效），用于在登录页给出提示。
  final String? reason;
}

/// 已登录。
class AuthSignedIn extends AuthState {
  const AuthSignedIn({required this.user, required this.syncing});

  final AuthUser user;

  /// 登录后的"首次数据落地"是否仍在进行。
  ///
  /// 它不影响能否进入主界面 —— **离线优先**：先让人看到本地已有的数据，
  /// 数据刷新在后台跑；没网也不该卡在登录页。
  final bool syncing;
}

/// 登录表单的提交状态。
class LoginState {
  const LoginState({this.submitting = false, this.error});

  final bool submitting;
  final String? error;

  bool get hasError => error != null;

  LoginState copyWith({bool? submitting, String? error}) =>
      LoginState(submitting: submitting ?? this.submitting, error: error);
}

/// 认证状态机。
class AuthController extends Notifier<AuthState> {
  @override
  AuthState build() => const AuthUnknown();

  /// 冷启动：用安全存储里的 refresh token 换一次 access token。
  ///
  /// 一期这是**常规路径**（access token 只放内存，冷启动必丢）。
  Future<void> restore() async {
    final AppServices services;
    try {
      services = ref.read(appServicesProvider).requireValue;
    } on StateError {
      // 服务图还没就绪；等 UI 在就绪后再调一次。
      return;
    }

    final user = await services.auth.restoreSession();
    state = user == null
        ? const AuthSignedOut()
        : AuthSignedIn(user: user, syncing: false);
  }

  /// 工号 + 密码登录。
  ///
  /// 成功后立刻返回（进入主界面），**首次同步在后台进行**：
  /// 床旁场景下不应该让治疗师盯着转圈等数据拉完才能用。
  Future<void> signIn(String employeeNo, String password) async {
    final services = ref.read(appServicesProvider).requireValue;
    final user = await services.auth.login(employeeNo, password);
    state = AuthSignedIn(user: user, syncing: true);

    // 后台首次同步：失败了也只是"数据旧"，不该把用户踢回登录页。
    await _initialSync(services);
    state = AuthSignedIn(user: user, syncing: false);
  }

  Future<void> _initialSync(AppServices services) async {
    try {
      // 参考数据与患者走各自的接口（患者**不走**同步接口，见协议 §1）。
      await services.patients.refreshFromServer();
      // 记录/排期走游标：本地库为空时做一次全量。
      if (await services.sync.readCursor() == 0) {
        await services.sync.pullInitial();
      } else {
        await services.sync.pullIncremental();
      }
    } on AppError {
      // 离线或服务端不可达：保持本地数据，稍后由用户手动同步。
    }
  }

  Future<void> signOut() async {
    final services = ref.read(appServicesProvider).requireValue;
    await services.auth.logout();
    state = const AuthSignedOut();
  }

  /// 会话被动失效（refresh token 过期/被踢下线）时调用。
  void markSessionExpired(String reason) {
    state = AuthSignedOut(reason: reason);
  }
}

final authControllerProvider =
    NotifierProvider<AuthController, AuthState>(AuthController.new);

/// 登录表单状态（与认证状态分开：表单错误不该影响已登录态）。
class LoginController extends Notifier<LoginState> {
  @override
  LoginState build() => const LoginState();

  Future<bool> submit(String employeeNo, String password) async {
    if (employeeNo.trim().isEmpty || password.isEmpty) {
      state = state.copyWith(error: '请填写工号与密码');
      return false;
    }
    state = const LoginState(submitting: true);
    try {
      await ref.read(authControllerProvider.notifier).signIn(employeeNo.trim(), password);
      state = const LoginState();
      return true;
    } on AppError catch (e) {
      // 后端**有意**不区分"工号不存在"与"密码错误"（防枚举），
      // 所以直接展示服务端文案，不要自己拼提示。
      state = LoginState(error: e.message);
      return false;
    } catch (e) {
      state = LoginState(error: '登录失败：$e');
      return false;
    }
  }
}

final loginControllerProvider =
    NotifierProvider<LoginController, LoginState>(LoginController.new);

/// 当前登录用户（未登录为 null）。
final currentUserProvider = Provider<AuthUser?>((ref) {
  final state = ref.watch(authControllerProvider);
  return state is AuthSignedIn ? state.user : null;
});
