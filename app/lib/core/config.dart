import 'dart:io';

/// App 运行期配置。
///
/// 后端地址与内网 CA 都**不进代码**，由构建期 `--dart-define` 注入，
/// 这样同一份代码可以打到测试/生产两套内网环境，不用改源码。
///
/// ```powershell
/// flutter run --dart-define=KB_BASE_URL=https://10.0.0.8
/// flutter build apk --dart-define=KB_BASE_URL=https://rehab.local
/// ```
class AppConfig {
  const AppConfig({
    required this.baseUrl,
    required this.trustedCaAsset,
    required this.connectTimeout,
    required this.receiveTimeout,
  });

  /// 后端根地址，**不带** `/api/v1`（路径常量里已含前缀）。
  final String baseUrl;

  /// 内置的内网 CA 证书在 assets 中的路径。
  ///
  /// 设计 D06/T2.8 要求：自签场景下客户端**必须内建 CA，不得关闭证书校验**
  /// （关闭校验等于把 JWT 与密码裸露在内网）。为 null 时表示使用系统信任链
  /// （仅适用于已换成受信任证书的环境）。
  final String? trustedCaAsset;

  final Duration connectTimeout;
  final Duration receiveTimeout;

  /// 从 `--dart-define` 构造。
  ///
  /// 默认值指向本机后端，方便开发时直接在模拟器里跑：
  /// Android 模拟器访问宿主机要用 `10.0.2.2`，所以默认值按平台区分。
  factory AppConfig.fromEnvironment() {
    const injected = String.fromEnvironment('KB_BASE_URL');
    const caAsset = String.fromEnvironment('KB_TRUSTED_CA');
    return AppConfig(
      baseUrl: injected.isNotEmpty ? injected : _defaultBaseUrl(),
      trustedCaAsset: caAsset.isNotEmpty ? caAsset : null,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 20),
    );
  }

  static String _defaultBaseUrl() {
    // Android 模拟器里 127.0.0.1 指向模拟器自身，宿主机是 10.0.2.2。
    if (Platform.isAndroid) return 'http://10.0.2.2:8000';
    return 'http://127.0.0.1:8000';
  }

  AppConfig copyWith({String? baseUrl, String? trustedCaAsset}) => AppConfig(
        baseUrl: baseUrl ?? this.baseUrl,
        trustedCaAsset: trustedCaAsset ?? this.trustedCaAsset,
        connectTimeout: connectTimeout,
        receiveTimeout: receiveTimeout,
      );

  @override
  String toString() => 'AppConfig(baseUrl: $baseUrl, ca: $trustedCaAsset)';
}
