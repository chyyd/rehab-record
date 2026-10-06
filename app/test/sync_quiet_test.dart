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

/// 连续离线后**安静下来**（2026-10-06）。
///
/// 用户原话：「连续多次离线后安静下来、不再提示」。
///
/// 场景：治疗师回家后 App 仍在跑定时同步，每 30 秒失败一次。
/// 如果每次都把「离线中，显示本地数据」推上顶部横幅，会一直闪，
/// 而这条信息他早就知道了（离线优先本来就是设计目标）。
///
/// 规则：
///  - 连续失败 **超过** `quietAfterFailures` 次 → 不再更新提示（同步照跑）；
///  - 成功一次即归零并**立刻可以再提示**；
///  - **冲突永远要报**（那需要人做决定，不能被"安静"策略吞掉）；
///  - 用户**主动**触发的同步一律给反馈（他正等着）。
void main() {
  Future<({ProviderContainer container, ScriptedAdapter adapter})> build() async {
    final adapter = ScriptedAdapter({
      kSyncPull: (
        200,
        {'cursor': 0, 'latest_cursor': 0, 'changes': <Object?>[], 'has_more': false}
      ),
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

  /// 让后续请求都连不上（状态码 0 = 模拟离线，见 support.dart）。
  void goOffline(ScriptedAdapter adapter) {
    adapter.responses[kPatients] = (0, <String, Object?>{});
    adapter.responses[kSyncPull] = (0, <String, Object?>{});
  }

  void goOnline(ScriptedAdapter adapter) {
    adapter.responses[kPatients] = (200, {'items': <Object?>[], 'total': 0});
    adapter.responses[kSyncPull] = (
      200,
      {'cursor': 0, 'latest_cursor': 0, 'changes': <Object?>[], 'has_more': false}
    );
  }

  test('★ 连续离线到第 4 次后不再提示（前 3 次仍提示）', () async {
    final (:container, :adapter) = await build();
    final controller = container.read(patientSyncControllerProvider.notifier);
    goOffline(adapter);

    final limit = PatientSyncController.quietAfterFailures;
    for (var i = 1; i <= limit; i++) {
      await controller.refreshQuietly();
      expect(
        container.read(patientSyncControllerProvider).message,
        isNotNull,
        reason: '第 $i 次失败还在阈值内，应该提示',
      );
    }

    await controller.refreshQuietly();
    final state = container.read(patientSyncControllerProvider);
    expect(
      state.message,
      isNull,
      reason: '★ 连续失败超过 $limit 次后要安静下来（同步照跑，只是不吵）',
    );
    // "安静"不等于"状态错了"：仍要如实标记失败，供调度器退避。
    expect(state.lastFailed, isTrue, reason: '安静下来也必须继续退避');
    expect(state.syncing, isFalse);
  });

  test('★ 安静之后成功一次，就恢复提示', () async {
    final (:container, :adapter) = await build();
    final controller = container.read(patientSyncControllerProvider.notifier);

    goOffline(adapter);
    for (var i = 0; i <= PatientSyncController.quietAfterFailures; i++) {
      await controller.refreshQuietly();
    }
    expect(container.read(patientSyncControllerProvider).message, isNull,
        reason: '前提：此时确实已经安静');

    goOnline(adapter);
    // 用户主动同步（默认 announce: true）——他正等着，必须给反馈。
    await controller.refresh();

    final state = container.read(patientSyncControllerProvider);
    expect(state.message, isNotNull, reason: '恢复后主动同步要有反馈');
    expect(state.lastFailed, isFalse);
    expect(state.syncing, isFalse);
  });

  test('★ 定时同步（announce: false）成功时**不提示**（不每 30 秒刷横幅）', () async {
    final (:container, :adapter) = await build();
    final controller = container.read(patientSyncControllerProvider.notifier);
    goOnline(adapter);

    for (var i = 0; i < 5; i++) {
      await controller.refreshQuietly();
      final state = container.read(patientSyncControllerProvider);
      expect(
        state.message,
        isNull,
        reason: '★ 自动同步不该刷「已更新 N 名患者」—— 上次同步时间在「我的」页看得到',
      );
      expect(state.lastFailed, isFalse, reason: '它确实同步成功了，只是不说');
      expect(state.syncing, isFalse);
    }
  });

  test('用户主动同步（默认 announce）始终给反馈，不受"安静"影响', () async {
    final (:container, :adapter) = await build();
    final controller = container.read(patientSyncControllerProvider.notifier);
    goOnline(adapter);

    // 连续多次主动同步，每次都要有反馈
    for (var i = 0; i < 5; i++) {
      await controller.refresh();
      expect(container.read(patientSyncControllerProvider).message, isNotNull,
          reason: '主动同步第 ${i + 1} 次也该有反馈 —— 用户正等着');
    }
  });
}
