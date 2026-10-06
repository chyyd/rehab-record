import 'package:rehab_app/core/config.dart';
import 'package:rehab_app/core/error.dart';
import 'package:rehab_app/data/local/app_database.dart';
import 'package:rehab_app/data/local/backend_settings.dart';
import 'package:rehab_app/data/remote/api_client.dart';

/// 探测结果：目标地址上到底有没有本系统的后端。
class BackendProbeResult {
  const BackendProbeResult({
    required this.baseUrl,
    required this.ok,
    this.serviceName,
    this.version,
    this.message,
  });

  final String baseUrl;
  final bool ok;

  /// 健康检查返回的 `service` 字段（用于确认"是**本系统**的后端"而不是别的服务）。
  final String? serviceName;
  final String? version;

  /// 失败原因，直接可展示给用户。
  final String? message;
}

/// 服务器（后端地址）设置。
///
/// 解决的是**部署**问题而不是**使用**问题：同一份 APK 要装到多套互不相通的
/// 内网里，装完才发现连不上时，现场必须有办法把地址改对 ——
/// 而不是"回去重新打包"（现场没有构建环境）。
///
/// 三个动作：
///  1. [probe]：**先探测再保存**，避免存下一个打不通的地址把用户锁在门外；
///  2. [save]：记住地址，并按指纹切换到对应的本地库；
///  3. [resetToDefault]：回到编译期注入的地址。
class SettingsRepository {
  SettingsRepository({BackendSettings? settings})
      : _settings = settings ?? BackendSettings();

  final BackendSettings _settings;

  /// 探测某个地址上是否有本系统的后端。
  ///
  /// 打的是 **`/health`**（不带 `/api/v1` 前缀、无需认证）——
  /// 登录都还没成功的时候就能用，这正是"地址填错了"要诊断的那一刻。
  ///
  /// **不复用 [ApiClient]**：那个实例的 baseUrl 是构造时定死的，
  /// 而且带着令牌与 401 刷新逻辑。探测一个"还没被采纳"的地址，
  /// 用一个临时的裸客户端更干净（也不会把当前会话的令牌发过去）。
  Future<BackendProbeResult> probe(String rawBaseUrl) async {
    final baseUrl = AppConfig.normalizeBaseUrl(rawBaseUrl);
    final invalid = AppConfig.validateBaseUrl(baseUrl);
    if (invalid != null) {
      return BackendProbeResult(baseUrl: baseUrl, ok: false, message: invalid);
    }

    final config = AppConfig.fromEnvironment().copyWith(baseUrl: baseUrl);
    final client = ApiClient(config: config, readAccessToken: () => null);
    try {
      await client.loadTrustedCa();
      final body = await client.request('/health');
      final map = body is Map ? body : const {};
      final service = map['service']?.toString();
      return BackendProbeResult(
        baseUrl: baseUrl,
        ok: true,
        serviceName: service,
        version: map['version']?.toString(),
        // 认得出服务名就报出来，让用户确认自己连的是"哪一套"
        message: service == null ? null : '$service ${map['version'] ?? ''}'.trim(),
      );
    } on AppError catch (e) {
      return BackendProbeResult(
        baseUrl: baseUrl,
        ok: false,
        message: e.code == 'NETWORK_ERROR'
            ? '连不上这个地址（检查 IP、端口，以及手机是否在同一网络）'
            : e.message,
      );
    } catch (e) {
      return BackendProbeResult(baseUrl: baseUrl, ok: false, message: '$e');
    } finally {
      await client.close();
    }
  }

  /// 保存地址（**应当先 [probe] 成功**）。
  ///
  /// 同时更新"当前本地库属于哪台后端"的指纹 —— 指纹一变，
  /// [AppDatabase] 会打开**另一个库文件**，从而不会把两台后端的数据混在一起。
  Future<void> save(String rawBaseUrl) async {
    final baseUrl = AppConfig.normalizeBaseUrl(rawBaseUrl);
    await _settings.save(baseUrl, backendFingerprint(baseUrl));
  }

  /// 当前的本地库该用哪个文件。
  Future<DatabaseNaming> databaseNaming(String effectiveBaseUrl) async {
    final environment = AppConfig.environmentBaseUrl();
    final fingerprint = backendFingerprint(effectiveBaseUrl);
    return DatabaseNaming(
      backendFingerprint: fingerprint,
      // 与"编译期默认那台"一致 → 沿用老库文件名 `rehab_app.sqlite`，
      // 老用户升级后数据不丢（见 databaseFileName 的说明）。
      isEnvironmentDefault: fingerprint == backendFingerprint(environment),
    );
  }

  /// 恢复成编译期默认地址。
  Future<void> resetToDefault() async {
    final environment = AppConfig.environmentBaseUrl();
    // 指纹也一起对齐，否则会去开一个"默认地址 + 旧指纹"的莫名库文件。
    await _settings.save(environment, backendFingerprint(environment));
    await _settings.clearBaseUrl();
  }

  /// 当前保存的地址（没设过时为 null）。
  Future<String?> savedBaseUrl() => _settings.readBaseUrl();
}
