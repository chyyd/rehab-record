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

  /// 内存中的 access token。**不落盘。**
  String? _accessToken;

  String? get accessToken => _accessToken;
  bool get hasAccessToken => _accessToken != null && _accessToken!.isNotEmpty;

  /// 记录登录响应里的 access token（仅内存）。
  void setAccessToken(String? token) => _accessToken = token;

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
  Future<void> clear() async {
    _accessToken = null;
    await _storage.delete(key: _kRefreshToken);
  }
}
