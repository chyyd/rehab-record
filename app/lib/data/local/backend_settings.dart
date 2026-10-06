import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// **后端地址**的持久化存储（运行期可改）。
///
/// 与 [TokenStore]（`data/local/token_store.dart`）同样的存储后端
/// （`flutter_secure_storage` → Android Keystore），但**关心点完全不同**：
///
/// - 令牌是**凭证**，泄露等于被盗号，所以必须加密；
/// - 后端地址不是凭证，但它有一个和令牌一样的要求：**冷启动时必须最早可读**。
///   地址决定"连哪台服务器"，而数据库文件名、首帧要发的请求都依赖它。
///   放在 `SharedPreferences` 也能读，但那个文件在"清除数据"里更容易被一起抹掉，
///   而地址被抹掉的后果是 App 又指回编译期默认值 —— 现场表现为
///   "昨天还好好的，今天连不上了"，很难排查。
///
/// 所以两者放同一处，**忘记地址与忘记令牌是同一类故障**，一起被清、也一起保留。
///
/// ## 为什么记住「指纹」而不是只记地址
///
/// 本地库把服务端主键当自己的主键用（`treatment_records.id` 就是服务端记录 id、
/// `patients.inpatient_no` 就是服务端住院号、`sync_state.last_cursor` 是服务端
/// 变更日志游标）。**换一台服务器，这些标识全部对不上**：
/// 同一个住院号在两边是不同的患者，同一个记录 id 在两边是不同的记录 ——
/// 继续用同一个本地库会两边数据混在一起，离线队列里的改动还会被推到错误的服务器。
///
/// 所以这里额外记住"当前本地库属于哪台后端"[readFingerprint]，
/// 地址一变就换一个**独立的库文件**（见 `AppDatabase` 的库文件名），
/// 从根上避免混库。
class BackendSettings {
  BackendSettings({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;

  static const String _kBaseUrl = 'kb_base_url';
  static const String _kFingerprint = 'kb_backend_fingerprint';

  /// 用户手填的后端地址；没设过时为 null（此时用编译期默认值）。
  Future<String?> readBaseUrl() async {
    final value = await _storage.read(key: _kBaseUrl);
    return (value == null || value.isEmpty) ? null : value;
  }

  /// 当前本地库对应的后端指纹；没设过时为 null。
  Future<String?> readFingerprint() async {
    final value = await _storage.read(key: _kFingerprint);
    return (value == null || value.isEmpty) ? null : value;
  }

  /// 记住用户选的地址与其指纹（两者一起写，避免只写成功一半）。
  Future<void> save(String baseUrl, String fingerprint) async {
    await _storage.write(key: _kBaseUrl, value: baseUrl);
    await _storage.write(key: _kFingerprint, value: fingerprint);
  }

  /// 恢复成"编译期默认地址"（用户点了「恢复默认」）。
  ///
  /// 指纹**保留**：默认地址对应的库文件要继续用，不能因为清掉设置就换库。
  Future<void> clearBaseUrl() async => _storage.delete(key: _kBaseUrl);
}
