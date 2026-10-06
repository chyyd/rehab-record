// 见 api_client.dart 顶部说明：构造器刻意用「公开参数名 + 私有字段」。
// ignore_for_file: prefer_initializing_formals

import 'dart:convert';

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
    // 缓存身份，供**离线冷启动**用（治疗师回家断网后点开 App 也能进主界面）。
    await _tokens.saveCachedUser(
      jsonEncode(Map<String, dynamic>.from(data['user'] as Map)),
    );
    return user;
  }

  /// 用 refresh token 换新的 access token。
  ///
  /// 返回新的 access token；失败返回 null（调用方据此跳登录页）。
  /// **注意 refresh 是轮换的**：刷新后旧 refresh token 立即作废，
  /// 因此并发刷新必须共用同一个动作（已由 [ApiClient] 保证）。
  ///
  /// ## ★ 2026-10-06：网络不通**不能**清凭证
  ///
  /// 这里原来是 `on AppError` 一律 `_tokens.clear()` —— 把"离线"当成了"会话失效"。
  /// 后果正是用户担心的那个场景：**治疗师下班回家（脱离内网）点开 App，
  /// refresh 请求自然失败，本地凭证被清掉，第二天上班必须重新登录**；
  /// 更糟的是睡前他连离线记录都用不了（界面停在登录页）。
  ///
  /// 这个 App 是**离线优先**的：本地库能独立工作、顶多数据旧一点。
  /// 所以只有服务端**明确拒绝**（4xx：过期/被吊销/被踢下线）才清凭证；
  /// 连不上/超时就保留凭证，让调用方走"离线模式"。
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
      // 顺手更新离线缓存：这里拿到的用户信息是最新的。
      final user = data['user'];
      if (user is Map) {
        await _tokens.saveCachedUser(jsonEncode(Map<String, dynamic>.from(user)));
      }
      return _tokens.accessToken;
    } on AppError catch (e) {
      if (e.code == 'NETWORK_ERROR') {
        // 离线：凭证保留，让调用方用缓存用户进"离线模式"。
        return null;
      }
      // 服务端明确拒绝（refresh 过期/被吊销/被踢下线）：清本地凭证，走登录页。
      await _tokens.clear();
      return null;
    }
  }

  /// 冷启动时恢复会话。
  ///
  /// 一期这是**常规路径**（access 只在内存，冷启动必丢）。
  ///
  /// ## 离线冷启动（2026-10-06）
  ///
  /// 换不到 access 时**不再一律回登录页**：
  ///
  /// - 若本地还有 refresh token（= "上次确实登录过"的证据），且缓存里有用户信息，
  ///   就**用缓存用户进入离线模式** —— 本地库照常可用，联网后第一次请求
  ///   （或定时同步）会把真实的会话状态问清楚；
  /// - 若缓存用户也没有（老版本升级上来、或换过服务器），才回登录页。
  ///
  /// ⚠ 这里**不校验** refresh token 是否真的还有效 —— 那需要联网，
  /// 而离线时正是问不了的时候。宁可先让人用（本地数据本来就在设备上），
  /// 也不要因为问不到就把人挡在门外。真失效时下一个请求会 401，那时再回登录页。
  Future<AuthUser?> restoreSession() async {
    final token = await refresh();
    if (token != null) {
      try {
        final data = await _client.request(kAuthMe) as Map<String, dynamic>;
        final user = AuthUser.fromJson(data);
        _currentUser = user;
        // 成功后刷新缓存，保证下次离线冷启动拿到的是最新身份。
        await _tokens.saveCachedUser(jsonEncode(data));
        return user;
      } on AppError catch (e) {
        // `/auth/me` 只读不写：网络抖动不该把已建立的会话丢掉，
        // 但拿不到用户信息就只能交给离线缓存兜底（见下）。
        if (e.code != 'NETWORK_ERROR') rethrow;
      }
    }
    return _restoreFromCache();
  }

  /// 用离线缓存的用户信息恢复会话（没有则返回 null）。
  Future<AuthUser?> _restoreFromCache() async {
    final raw = await _tokens.readCachedUser();
    if (raw == null) return null;
    try {
      final user = AuthUser.fromJson(
        Map<String, dynamic>.from(jsonDecode(raw) as Map),
      );
      _currentUser = user;
      return user;
    } catch (_) {
      // 缓存损坏（升级改过字段等）：删掉它，回登录页，别一直读到坏数据。
      await _tokens.saveCachedUser(null);
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
