import 'package:drift/native.dart';
import 'package:flutter/material.dart';
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
import 'package:rehab_app/features/settings/settings_page.dart';
import 'package:rehab_app/sync/sync_engine.dart';

import 'support.dart';

/// 「我的」→ 后端地址 的**修改入口**（2026-10-06）。
///
/// 用户原话：「我的-后段地址，设个入口可以改」。
///
/// 原来那一行只是**显示**地址（排障用），没有入口 ——
/// 想换环境只能先退出登录、再从登录页底部改，绕。
///
/// 这里断言：那一行可点、点了能打开与登录页**同一个**面板。
/// 换地址后的重建/重登流程在 `settings_page` 里，由 `_openServerSheet` 负责 ——
/// 那条链路要真的重建服务图，widget 测试里不适合端到端跑，故只守入口。
void main() {
  Future<ProviderContainer> build() async {
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
      baseUrl: 'http://10.0.2.2:8000',
      trustedCaAsset: null,
      connectTimeout: Duration(seconds: 5),
      receiveTimeout: Duration(seconds: 5),
    );
    return ProviderContainer.test(
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
  }

  Future<void> pumpSettings(WidgetTester tester, ProviderContainer container) async {
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(home: Scaffold(body: SettingsPage())),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('★ 「后端地址」那一行可点（有 chevron 入口）', (tester) async {
    final container = await build();
    addTearDown(container.dispose);
    await pumpSettings(tester, container);

    expect(find.text('后端地址'), findsOneWidget);
    // 显示当前地址（排障要看的就是它）
    expect(find.text('http://10.0.2.2:8000'), findsWidgets);
    // 入口：出现 chevron 才说明"可点"，否则用户不会去点它
    expect(
      find.descendant(
        of: find.ancestor(
          of: find.text('后端地址'),
          matching: find.byType(ListTile),
        ),
        matching: find.byIcon(Icons.chevron_right),
      ),
      findsOneWidget,
      reason: '可点的行要有 chevron，否则看不出能进',
    );
  });

  testWidgets('★ 点进去打开的是与登录页同一个「服务器设置」面板', (tester) async {
    final container = await build();
    addTearDown(container.dispose);
    await pumpSettings(tester, container);

    await tester.tap(find.text('后端地址'));
    await tester.pumpAndSettle();

    // 与登录页共用同一个 widget，所以文案、探测逻辑、提示都一致 ——
    // 不会出现"两个地方行为不一样"的经典问题。
    expect(find.text('服务器设置'), findsOneWidget);
    expect(find.text('服务器地址'), findsOneWidget);
    expect(find.text('测试连接并保存'), findsOneWidget);
    expect(find.text('恢复默认地址'), findsOneWidget);
    // 界面上必须讲清楚"换服务器会换本地数据副本"
    expect(find.textContaining('本地数据副本'), findsOneWidget);
  });
}
