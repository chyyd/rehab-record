// 见 api_client.dart 顶部说明：构造器刻意用「公开参数名 + 私有字段」。
// ignore_for_file: prefer_initializing_formals

import 'package:rehab_app/core/api_endpoints.dart';
import 'package:rehab_app/core/error.dart';
import 'package:rehab_app/data/local/token_store.dart';
import 'package:rehab_app/data/remote/api_client.dart';

/// 登录返回的当前用户。
class AuthUser {
  const AuthUser({
    required this.id,
    required this.employeeNo,
    required this.name,
    required this.role,
  });

  final int id;
  final String employeeNo;
  final String name;

  /// `admin` / `therapist`。
  final String role;

  bool get isAdmin => role == 'admin';

  factory AuthUser.fromJson(Map<String, dynamic> json) => AuthUser(
        id: (json['id'] as num).toInt(),
        employeeNo: json['employee_no'] as String,
        name: json['name'] as String,
        role: json['role'] as String,
      );
}

/// 认证服务。
///
/// 后端令牌交付方式（2026-10-03 核实）：登录**同时**用响应体与 httpOnly Cookie
/// 下发同一个 token；**安卓端继续用响应体**，Cookie 只服务 Web 端。
class AuthService {
  AuthService({required ApiClient client, required TokenStore tokens})
      : _client = client,
        _tokens = tokens;

  final ApiClient _client;
  final TokenStore _tokens;

  AuthUser? _currentUser;
  AuthUser? get currentUser => _currentUser;

  /// 工号 + 密码登录。
  ///
  /// 登录失败**不区分**"工号不存在"与"密码错误"（服务端有意为之，防工号枚举），
  /// 所以 UI 直接展示服务端返回的 `message` 即可，不要自己拼提示。
  Future<AuthUser> login(String employeeNo, String password) async {
    final data = await _client.request(
      kAuthLogin,
      method: 'POST',
      body: {'employee_no': employeeNo, 'password': password},
    ) as Map<String, dynamic>;

    _tokens.setAccessToken(data['access_token'] as String?);
    await _tokens.saveRefreshToken(data['refresh_token'] as String?);

    final user = AuthUser.fromJson(Map<String, dynamic>.from(data['user'] as Map));
    _currentUser = user;
    return user;
  }

  /// 用 refresh token 换新的 access token。
  ///
  /// 返回新的 access token；失败返回 null（调用方据此跳登录页）。
  /// **注意 refresh 是轮换的**：刷新后旧 refresh token 立即作废，
  /// 因此并发刷新必须共用同一个动作（已由 [ApiClient] 保证）。
  Future<String?> refresh() async {
    final refreshToken = await _tokens.readRefreshToken();
    if (refreshToken == null) return null;
    try {
      final data = await _client.request(
        kAuthRefresh,
        method: 'POST',
        body: {'refresh_token': refreshToken},
      ) as Map<String, dynamic>;

      _tokens.setAccessToken(data['access_token'] as String?);
      // 轮换：服务端会返回新的 refresh token，必须覆盖保存。
      await _tokens.saveRefreshToken(data['refresh_token'] as String?);
      return _tokens.accessToken;
    } on AppError {
      // refresh 也失效了（过期/被吊销/被踢下线）：清本地凭证，走登录页。
      await _tokens.clear();
      return null;
    }
  }

  /// 冷启动时用安全存储里的 refresh token 换一次 access token。
  ///
  /// 一期这是**常规路径**（access 只在内存，冷启动必丢）。
  Future<AuthUser?> restoreSession() async {
    final token = await refresh();
    if (token == null) return null;
    try {
      final data = await _client.request(kAuthMe) as Map<String, dynamic>;
      final user = AuthUser.fromJson(data);
      _currentUser = user;
      return user;
    } on AppError {
      return null;
    }
  }

  /// 退出登录：先让服务端吊销会话，再清本地凭证。
  Future<void> logout() async {
    final refreshToken = await _tokens.readRefreshToken();
    try {
      await _client.request(
        kAuthLogout,
        method: 'POST',
        query: refreshToken == null ? null : {'refresh_token': refreshToken},
      );
    } on AppError {
      // 服务端不可达也要能退出——本地清干净更重要。
    } finally {
      await _tokens.clear();
      _currentUser = null;
    }
  }
}
