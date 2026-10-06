import 'package:drift/native.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rehab_app/core/config.dart';
import 'package:rehab_app/core/providers.dart';
import 'package:rehab_app/data/local/app_database.dart';
import 'package:rehab_app/data/local/token_store.dart';
import 'package:rehab_app/data/remote/api_client.dart';
import 'package:rehab_app/data/remote/auth_service.dart';
import 'package:rehab_app/data/repo/patient_repository.dart';
import 'package:rehab_app/data/repo/record_repository.dart';
import 'package:rehab_app/data/repo/settings_repository.dart';
import 'package:rehab_app/data/repo/timeline_repository.dart';
import 'package:rehab_app/features/auth/login_page.dart';
import 'package:rehab_app/sync/sync_engine.dart';

import 'support.dart';

/// 登录页的「服务器设置」入口（2026-10-06）。
///
/// 用户原话：「我要在其他环境部署时，如果app找不到后端，那么登录时应该有
/// 后端地址的手动设置」。
///
/// 为什么这条必须用 widget 测试而不是真机点：
/// 入口和面板都在**未登录**状态下才可见，而模拟器的 `adb input tap`
/// 在这个项目里一直不可靠（键盘会改变坐标、TAB 不循环字段）——
/// 用 widget 测试能把"入口存在 + 面板能打开 + 当前地址显示正确"钉死。
void main() {
  /// 造一个可用的 AppServices（与 `record_page_navigation_test.dart` 同法）。
  (ProviderContainer, ScriptedAdapter) buildContainer({
    required SettingsRepository settings,
    String baseUrl = 'http://10.0.2.2:8000',
  }) {
    final adapter = ScriptedAdapter({});
    final client = ApiClient(
      config: AppConfig(
        baseUrl: baseUrl,
        trustedCaAsset: null,
        connectTimeout: const Duration(seconds: 5),
        receiveTimeout: const Duration(seconds: 5),
      ),
      readAccessToken: () => null,
    );
    final db = AppDatabase.forTesting(NativeDatabase.memory());
    final tokens = TokenStore();
    final sync = SyncEngine(client: client, db: db);
    final container = ProviderContainer(
      overrides: [
        appServicesProvider.overrideWithValue(
          AsyncValue.data(AppServices(
            config: AppConfig(
              baseUrl: baseUrl,
              trustedCaAsset: null,
              connectTimeout: const Duration(seconds: 5),
              receiveTimeout: const Duration(seconds: 5),
            ),
            tokens: tokens,
            client: client,
            auth: AuthService(client: client, tokens: tokens),
            db: db,
            patients: PatientRepository(client: client, db: db),
            records: RecordRepository(client: client, db: db, sync: sync),
            timeline: TimelineRepository(client: client),
            sync: sync,
            settings: settings,
          )),
        ),
      ],
    );
    return (container, adapter);
  }

  testWidgets('★ 登录页底部有「服务器设置」入口，并显示当前地址', (tester) async {
    // 注入一个"已有地址"的假设置，避免真去读写 Keystore。
    final settings = _FakeSettings(saveCalls: []);
    final (container, _) = buildContainer(settings: settings);
    addTearDown(container.dispose);

    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(home: LoginPage()),
      ),
    );
    await tester.pumpAndSettle();

    // 入口存在 —— 这是整个需求的核心：地址不对时人得进得来这一页。
    expect(find.text('服务器设置'), findsOneWidget);
    // 当前地址要显示出来，否则用户不知道该改成什么。
    expect(find.text('http://10.0.2.2:8000'), findsWidgets);
    // 登录本身的功能不能被这个入口挤掉。
    expect(find.text('工号'), findsOneWidget);
    expect(find.text('密码'), findsOneWidget);
  });

  testWidgets('★ 点入口能打开面板，面板里有输入框与「测试连接并保存」', (tester) async {
    final settings = _FakeSettings(saveCalls: []);
    final (container, _) = buildContainer(settings: settings);
    addTearDown(container.dispose);

    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(home: LoginPage()),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('服务器设置'));
    await tester.pumpAndSettle();

    expect(find.text('服务器地址'), findsOneWidget, reason: '应有地址输入框');
    // 「先探测再保存」是本功能的关键设计：连不上就不让存，
    // 免得把用户锁在一个打不通的地址上。
    expect(find.text('测试连接并保存'), findsOneWidget);
    expect(find.text('恢复默认地址'), findsOneWidget);
    // 换服务器会换本地库，界面上必须讲清楚。
    expect(find.textContaining('本地数据副本'), findsOneWidget);
  });

  testWidgets('地址非法时不发起探测，直接给出可读提示', (tester) async {
    final settings = _FakeSettings(saveCalls: []);
    final (container, _) = buildContainer(settings: settings);
    addTearDown(container.dispose);

    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(home: LoginPage()),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('服务器设置'));
    await tester.pumpAndSettle();

    // ⚠ 不能用 `find.byType(TextField)`：`TextFormField` 内部也是 TextField，
    //    所以工号、密码、地址三个会一起被匹配到（我第一版就踩了 "Too many elements"）。
    await tester.enterText(
      find.widgetWithText(TextField, '服务器地址'),
      'ftp://10.0.0.8',
    );
    await tester.tap(find.text('测试连接并保存'));
    await tester.pumpAndSettle();

    expect(find.textContaining('只支持 http'), findsOneWidget);
    expect(settings.saveCalls, isEmpty,
        reason: '非法地址绝不能保存 —— 保存了就把用户锁在门外了');
  });
}

/// 假的设置仓储：**不碰真 Keystore**（`flutter_secure_storage` 在测试环境没有实现）。
///
/// 只覆盖测试用到的部分：`probe` 由真实实现改成可控结果，`save` 只记账。
class _FakeSettings implements SettingsRepository {
  _FakeSettings({required this.saveCalls});

  final List<String> saveCalls;

  @override
  Future<void> save(String rawBaseUrl) async => saveCalls.add(rawBaseUrl);

  @override
  Future<void> resetToDefault() async {}

  @override
  Future<String?> savedBaseUrl() async => null;

  @override
  Future<DatabaseNaming> databaseNaming(String effectiveBaseUrl) async =>
      const DatabaseNaming(
        backendFingerprint: 'test',
        isEnvironmentDefault: true,
      );

  @override
  Future<BackendProbeResult> probe(String rawBaseUrl) async {
    final normalized = AppConfig.normalizeBaseUrl(rawBaseUrl);
    final invalid = AppConfig.validateBaseUrl(normalized);
    if (invalid != null) {
      return BackendProbeResult(baseUrl: normalized, ok: false, message: invalid);
    }
    return BackendProbeResult(
      baseUrl: normalized,
      ok: true,
      serviceName: '测试后端',
      version: '0.1.0',
      message: '测试后端 0.1.0',
    );
  }
}
