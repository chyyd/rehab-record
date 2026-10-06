import 'dart:io';

import 'package:rehab_app/core/api_endpoints.dart';
import 'package:rehab_app/data/local/backend_settings.dart';

/// App 运行期配置。
///
/// ## 后端地址的来源与优先级（2026-10-06 起运行期可改）
///
/// 1. **用户在登录页手填的地址**（存 `flutter_secure_storage`，`BackendSettings`）
/// 2. `--dart-define=KB_BASE_URL=...` 注入的地址（构建期，仍是推荐做法）
/// 3. 平台默认值（Android 模拟器 `10.0.2.2:8000`，其它 `127.0.0.1:8000`）
///
/// 之所以要第 1 条：本系统会部署到**多套互不相通的内网**（医院 A / 医院 B / 演示），
/// 而装在手机上的 APK 只有一份。没有运行期设置的话，"换了环境就连不上、
/// 且没有任何补救入口" —— 现场只能重新打包，而现场没有构建环境。
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

  /// 从 `--dart-define` 构造（**不含**运行期覆盖）。
  ///
  /// 默认值指向本机后端，方便开发时直接在模拟器里跑：
  /// Android 模拟器访问宿主机要用 `10.0.2.2`，所以默认值按平台区分。
  factory AppConfig.fromEnvironment() {
    const injected = String.fromEnvironment('KB_BASE_URL');
    const caAsset = String.fromEnvironment('KB_TRUSTED_CA');
    return AppConfig(
      baseUrl: injected.isNotEmpty ? injected : defaultBaseUrl(),
      trustedCaAsset: caAsset.isNotEmpty ? caAsset : null,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 20),
    );
  }

  /// 解析出**实际生效**的配置：运行期覆盖 > 构建期注入 > 平台默认。
  ///
  /// 读安全存储可能失败（设备异常、Keystore 不可用）。那种情况下**退回
  /// 构建期默认值**而不是让启动失败 —— 地址读不出来是"设置丢了"，
  /// 不该表现成"App 打不开"；而且退回去的那个默认值在开发环境通常正好是对的。
  static Future<AppConfig> load({BackendSettings? settings}) async {
    final base = AppConfig.fromEnvironment();
    try {
      final stored = await (settings ?? BackendSettings()).readBaseUrl();
      if (stored != null && stored.isNotEmpty) {
        return base.copyWith(baseUrl: stored);
      }
    } catch (_) {
      // 忽略：用构建期默认值（见上面的说明）
    }
    return base;
  }

  /// 平台默认地址。
  static String defaultBaseUrl() {
    // Android 模拟器里 127.0.0.1 指向模拟器自身，宿主机是 10.0.2.2。
    if (Platform.isAndroid) return 'http://10.0.2.2:8000';
    return kDefaultBaseUrl;
  }

  /// `--dart-define` / 平台默认给出的地址（即"没被运行期改过"的那个）。
  ///
  /// 「恢复默认地址」与"本地库该用哪个文件名"都要用它。
  static String environmentBaseUrl() => AppConfig.fromEnvironment().baseUrl;

  /// 规范化用户填的地址：去空白、补 scheme、scheme 小写、去尾部斜杠。
  ///
  /// **补 scheme**：`10.0.0.8:8000` 补成 `http://10.0.0.8:8000`。
  /// 现场手填时漏掉 `http://` 太常见了，直接拒绝不如替用户补上
  ///（Dio 需要一个完整 URL 才能请求，见 `ApiClient`）。
  ///
  /// **尾部斜杠必须去**：路径常量以 `/api/v1/...` 开头，`baseUrl + path` 拼接时
  /// `http://host/` + `/api/v1` 会变成 `//api/v1`（多数服务器能容忍，
  /// 但反向代理常常不能）。
  static String normalizeBaseUrl(String raw) {
    var value = raw.trim();
    if (value.isEmpty) return value;
    // scheme 归一化成小写（RFC 3986：scheme 大小写不敏感）。
    // Dart 的 Uri 不认大写 scheme，不归一化会把 `HTTP://host` 的 host 解析成 `http`。
    final scheme = RegExp(r'^([A-Za-z][A-Za-z0-9+.\-]*)://').firstMatch(value);
    if (scheme != null) {
      value = '${scheme.group(1)!.toLowerCase()}://${value.substring(scheme.end)}';
    } else {
      value = 'http://$value';
    }
    while (value.endsWith('/')) {
      value = value.substring(0, value.length - 1);
    }
    return value;
  }

  /// 校验用户填的地址；返回错误文案，合法时返回 null。
  ///
  /// 刻意**只要求 http/https + 有 host**：现场可能是 IP、可能是主机名、
  /// 可能带基路径（如 `https://gw.hosp.local/rehab`），不该过度约束。
  static String? validateBaseUrl(String raw) {
    final value = normalizeBaseUrl(raw);
    if (value.isEmpty) return '请填写服务器地址';
    final uri = Uri.tryParse(value);
    if (uri == null || !uri.hasScheme || uri.host.isEmpty) {
      return '地址要形如 http://10.0.0.8:8000';
    }
    if (uri.scheme != 'http' && uri.scheme != 'https') {
      return '只支持 http:// 或 https://';
    }
    return null;
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

/// 后端**指纹**：给地址算一个稳定、可读、文件名安全的短标识。
///
/// 用途是给"属于哪台后端"的本地库文件命名（`rehab_app_<fingerprint>.sqlite`）。
/// 因此它必须：
///
/// - **同地址必同值**、不同地址（含端口不同）必不同值 —— 否则会串库；
/// - **只含 `[a-z0-9_]`** —— 否则在 Windows/Android 上做文件名不安全；
/// - 用 host + port 而不是整个 URL —— 一是可读（排障时一眼看出是哪个库），
///   二是**忽略 scheme 与路径差异**：`http://10.0.0.8:8000` 与
///   `http://10.0.0.8:8000/` 是同一台后端，不该被算成两台。
///
/// 解析失败时退回 `default`，保证永远有一个可用的文件名。
String backendFingerprint(String baseUrl) {
  final uri = Uri.tryParse(normalizeForFingerprint(baseUrl));
  final host = uri?.host ?? '';
  if (host.isEmpty) return 'default';
  final port = (uri != null && uri.hasPort)
      ? uri.port
      : (uri?.scheme == 'https' ? 443 : 80);
  final raw = '${host}_$port'.toLowerCase();
  // 只留安全字符；IPv6 的 `:` 与域名里的 `.`/`-` 都在这里被归一化。
  final safe = raw.replaceAll(RegExp(r'[^a-z0-9]+'), '_');
  return safe.replaceAll(RegExp(r'^_+|_+$'), '');
}

/// `Uri.tryParse` 里的两个坑，都必须在算指纹前抹平。
///
/// **坑 1：缺 scheme。** `10.0.0.8:8000` 会被解析成 **scheme=`10.0.0.8`**、
/// host 为空（`:` 被当成 scheme 分隔符）。用户很可能就这么填，
/// 不补 scheme 的话指纹会退化成 `default`，两台后端就撞库了。
///
/// **坑 2：scheme 大小写。** Dart 的 `Uri` **不认** `HTTP://`（scheme 必须小写），
/// 于是 `Uri.tryParse('HTTP://10.0.0.8:8000')` 会把 `http` 当 host、
/// 端口按默认 80 算 → 指纹变成 `http_80`。
/// 而 RFC 3986 明确 scheme 大小写不敏感，用户从浏览器复制地址时
/// 拿到大写是很常见的。所以这里先把 scheme 统一成小写。
String normalizeForFingerprint(String baseUrl) =>
    AppConfig.normalizeBaseUrl(baseUrl);
