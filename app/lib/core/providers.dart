import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/core/config.dart';
import 'package:rehab_app/data/local/app_database.dart';
import 'package:rehab_app/data/local/token_store.dart';
import 'package:rehab_app/data/remote/api_client.dart';
import 'package:rehab_app/data/remote/auth_service.dart';
import 'package:rehab_app/data/repo/patient_repository.dart';
import 'package:rehab_app/data/repo/record_repository.dart';
import 'package:rehab_app/data/repo/timeline_repository.dart';
import 'package:rehab_app/sync/sync_engine.dart';

/// App 启动时构造好的一组长期存活对象。
///
/// 集中在一个对象里而不是各自一个 provider：它们之间有真实的构造依赖
/// （`ApiClient` 需要 `TokenStore` 作为令牌读取器，`AuthService` 需要两者，
/// `PatientRepository`/`SyncEngine` 需要 `ApiClient` + `AppDatabase`），
/// 分散写会出现"某个 provider 先于它的依赖被读取"的时序问题。
class AppServices {
  AppServices({
    required this.config,
    required this.tokens,
    required this.client,
    required this.auth,
    required this.db,
    required this.patients,
    required this.records,
    required this.timeline,
    required this.sync,
  });

  final AppConfig config;
  final TokenStore tokens;
  final ApiClient client;
  final AuthService auth;
  final AppDatabase db;
  final PatientRepository patients;
  final RecordRepository records;
  final TimelineRepository timeline;
  final SyncEngine sync;

  Future<void> dispose() async {
    await client.close();
    await db.close();
  }
}

/// 启动依赖图。
///
/// `FutureProvider` 保证只跑一次：Flutter 首帧前先把 CA 证书读进内存，
/// 否则第一次 HTTPS 请求会因为 `SecurityContext` 里没有信任根而失败。
///
/// 打开本地库与读证书都是**本地**操作，正常不会失败；但设备刚启动、存储还在挂载、
/// 或上次进程被杀留下 WAL 锁时，可能出现一次性失败。这里对瞬时失败
/// **自动重试两次**（退避 200/400ms），免得用户被一个"重试"按钮挡在门外；
/// 真正的持久故障（如证书文件损坏）重试后仍会落到失败页。
final appServicesProvider = FutureProvider<AppServices>((ref) async {
  Object? lastError;
  for (var attempt = 0; attempt < 3; attempt++) {
    try {
      return await _buildServices(ref);
    } catch (e) {
      lastError = e;
      if (attempt < 2) {
        await Future<void>.delayed(Duration(milliseconds: 200 * (attempt + 1)));
      }
    }
  }
  throw StateError('启动失败（已重试 3 次）：$lastError');
});

Future<AppServices> _buildServices(Ref ref) async {
  final config = AppConfig.fromEnvironment();
  final db = AppDatabase();
  final tokens = TokenStore();

  // 令牌读取器指向内存中的 access token；刷新交给 AuthService。
  late final ApiClient client;
  late final AuthService auth;

  client = ApiClient(
    config: config,
    readAccessToken: () => tokens.accessToken,
    refreshToken: () => auth.refresh(),
  );
  auth = AuthService(client: client, tokens: tokens);
  final sync = SyncEngine(client: client, db: db);

  // 自签 CA 必须在第一个请求之前装好。
  await client.loadTrustedCa();

  ref.onDispose(() {
    // 由 Flutter 决定生命周期，这里只做兜底，避免热重载时泄漏连接。
    client.close();
  });

  return AppServices(
    config: config,
    tokens: tokens,
    client: client,
    auth: auth,
    db: db,
    patients: PatientRepository(client: client, db: db),
    records: RecordRepository(client: client, db: db, sync: sync),
    timeline: TimelineRepository(client: client),
    sync: sync,
  );
}

/// 便利读取器：拿不到（仍在启动）时抛错，调用方应用 `appServicesProvider` 的
/// loading 分支包住 UI，而不是在业务代码里到处判空。
extension AppServicesRef on Ref {
  AppServices get services {
    final value = watch(appServicesProvider).value;
    if (value == null) {
      throw StateError('AppServices 尚未就绪：请在 UI 上处理 appServicesProvider 的 loading 状态');
    }
    return value;
  }
}
