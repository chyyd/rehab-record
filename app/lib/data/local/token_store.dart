import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// 令牌安全存储。
///
/// 2026-10-03 决定（见 `app/README.md`）：
/// - **refresh token 进安全存储**（Android Keystore）；
/// - **access token 只放内存**（32 天有效期，落盘等于把长期凭证暴露在 root/备份里）。
///
/// 一期 access token 有效期 30 天（D01），因此"每次冷启动用 refresh 换一次 access"
/// 是**常规路径**而不是异常路径：靠 refresh 拿到新 access 后再拉数据。
///
/// > `flutter_secure_storage 11.x` 起 `AndroidOptions.encryptedSharedPreferences`
/// > 已被移除（密钥与密文默认就由 Keystore 管理），所以这里用默认选项即可。
class TokenStore {
  TokenStore({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;

  static const String _kRefreshToken = 'kb_refresh_token';
  static const String _kCachedUser = 'kb_cached_user';

  /// 内存中的 access token。**不落盘。**
  String? _accessToken;

  String? get accessToken => _accessToken;
  bool get hasAccessToken => _accessToken != null && _accessToken!.isNotEmpty;

  /// 记录登录响应里的 access token（仅内存）。
  void setAccessToken(String? token) => _accessToken = token;

  /// 缓存"上次登录的是谁"，供**离线冷启动**使用。
  ///
  /// 2026-10-06：治疗师下班回家、脱离内网后点开 App，如果只能靠 `/auth/refresh`
  /// 才知道自己是谁，就会**在离线时被登出** —— 而他明明有本地数据、也能离线记录。
  /// 所以把用户的四个字段（id / 工号 / 姓名 / 角色）落盘。
  ///
  /// 不是凭证：它不能用来访问任何接口，只是"离线时先把界面画出来"。
  /// 服务端一旦可达就会用 `/auth/me` 的真实结果覆盖它。
  Future<void> saveCachedUser(String? json) async {
    if (json == null || json.isEmpty) {
      await _storage.delete(key: _kCachedUser);
      return;
    }
    await _storage.write(key: _kCachedUser, value: json);
  }

  Future<String?> readCachedUser() async {
    final value = await _storage.read(key: _kCachedUser);
    return (value == null || value.isEmpty) ? null : value;
  }

  /// 保存 refresh token。
  ///
  /// **不本地判过期**：服务端登录/刷新响应只返回 `access_token`/`refresh_token`/`user`，
  /// 不含 refresh 的过期时间（它只存在于服务端 `auth_session.expires_at`）。
  /// 本地猜过期时间既多余又可能与服务端不一致——直接让它去问服务端，
  /// 失败（过期/被吊销/被踢下线）由 [AuthService.refresh] 统一处理成"回登录页"。
  Future<void> saveRefreshToken(String? token) async {
    if (token == null || token.isEmpty) {
      await _storage.delete(key: _kRefreshToken);
      return;
    }
    await _storage.write(key: _kRefreshToken, value: token);
  }

  /// 读取 refresh token。
  Future<String?> readRefreshToken() async {
    final token = await _storage.read(key: _kRefreshToken);
    return (token == null || token.isEmpty) ? null : token;
  }

  /// 退出登录：清空内存与安全存储。服务端会话吊销由调用方负责。
  ///
  /// **缓存用户也一并清掉**：那是"我上次登录过"的证据，
  /// 主动退出后不该还能靠它离线进主界面（否则等于退不掉）。
  Future<void> clear() async {
    _accessToken = null;
    await _storage.delete(key: _kRefreshToken);
    await _storage.delete(key: _kCachedUser);
  }
}
