import 'package:drift/native.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rehab_app/core/api_endpoints.dart';
import 'package:rehab_app/core/config.dart';
import 'package:rehab_app/core/providers.dart';
import 'package:rehab_app/data/local/app_database.dart';
import 'package:rehab_app/data/local/token_store.dart';
import 'package:rehab_app/data/remote/auth_service.dart';
import 'package:rehab_app/data/repo/patient_repository.dart';
import 'package:rehab_app/data/repo/record_repository.dart';
import 'package:rehab_app/data/repo/settings_repository.dart';
import 'package:rehab_app/data/repo/timeline_repository.dart';
import 'package:rehab_app/features/patients/patients_providers.dart';
import 'package:rehab_app/sync/sync_engine.dart';

import 'support.dart';

/// 并发 refresh 的防重入（2026-10-06）。
///
/// 加了 30 秒定时同步之后，并发调用从「可能」变成「必然」：
/// 定时器到点时用户可能正好点了同步按钮、或刚从详情页返回触发 didPopNext。
///
/// 不防重入的后果不只是浪费流量：pushPending 会重推整个离线队列；
/// 更麻烦的是两条 pullIncremental 会互相覆盖游标，并把 UI 刷成「已更新」。
///
/// 断言「服务端被打了几次」而不是内部字段 —— 前者才是用户能感知的。
void main() {
  Future<({ProviderContainer container, ScriptedAdapter adapter})> build() async {
    final adapter = ScriptedAdapter({
      kSyncPull: (200, {'cursor': 0, 'latest_cursor': 0, 'changes': <Object?>[], 'has_more': false}),
      kSyncPush: (200, {'results': <Object?>[], 'server_cursor': 0}),
      kPatients: (200, {'items': <Object?>[], 'total': 0}),
    });
    final client = buildScriptedClient({}, adapter: adapter);
    final db = AppDatabase.forTesting(NativeDatabase.memory());
    final tokens = TokenStore();
    final sync = SyncEngine(client: client, db: db);
    const config = AppConfig(
      baseUrl: 'http://test.local',
      trustedCaAsset: null,
      connectTimeout: Duration(seconds: 5),
      receiveTimeout: Duration(seconds: 5),
    );
    final container = ProviderContainer.test(
      overrides: [
        appServicesProvider.overrideWithValue(
          AsyncValue.data(AppServices(
            config: config,
            tokens: tokens,
            client: client,
            auth: AuthService(client: client, tokens: tokens),
            db: db,
            patients: PatientRepository(client: client, db: db),
            records: RecordRepository(client: client, db: db, sync: sync),
            timeline: TimelineRepository(client: client),
            sync: sync,
            settings: SettingsRepository(),
          )),
        ),
      ],
    );
    return (container: container, adapter: adapter);
  }

  test('两次并发 refresh 只跑一轮（不重复拉、不互相覆盖游标）', () async {
    final (:container, :adapter) = await build();
    final controller = container.read(patientSyncControllerProvider.notifier);

    // 真正并发：不 await 第一个就发第二个。
    final first = controller.refresh();
    final second = controller.refresh();
    await Future.wait([first, second]);

    final pulls = adapter.seen.where((r) => r.path == kSyncPull).length;
    expect(pulls, 1, reason: '两轮并发只该拉一次；拉两次会互相覆盖游标');
    // 空队列时 pushPending 本来就不发请求，所以这里是「至多一次」。
    final pushes = adapter.seen.where((r) => r.path == kSyncPush).length;
    expect(pushes, lessThanOrEqualTo(1), reason: '离线队列不该被推两遍');
    expect(container.read(patientSyncControllerProvider).syncing, isFalse);
  });

  test('上一轮结束后，新的 refresh 能正常再跑一轮（锁要释放）', () async {
    final (:container, :adapter) = await build();
    final controller = container.read(patientSyncControllerProvider.notifier);

    await controller.refresh();
    await controller.refresh();

    final pulls = adapter.seen.where((r) => r.path == kSyncPull).length;
    expect(pulls, 2, reason: '串行两次就该拉两次 —— 防重入不能把后续同步也吞掉');
  });

  test('离线失败时：不抛异常，且标记 lastFailed 供定时器退避', () async {
    final (:container, :adapter) = await build();
    // 状态码 0 = 模拟连不上（见 support.dart）。
    adapter.responses[kSyncPull] = (0, <String, Object?>{});
    final controller = container.read(patientSyncControllerProvider.notifier);

    // 不抛 —— 调用方（initState 的 post-frame、didPopNext、按钮 onPressed）
    // 全都没有 catch，抛出会变成未处理异常（红屏日志）。
    final ok = await controller.refreshQuietly();

    expect(ok, isFalse, reason: '连不上就不该报成功，否则定时器不会退避');
    final state = container.read(patientSyncControllerProvider);
    expect(state.lastFailed, isTrue, reason: '要能区分故障失败与有冲突');
    expect(state.syncing, isFalse);
    expect(state.message, contains('离线'));
  });
}

