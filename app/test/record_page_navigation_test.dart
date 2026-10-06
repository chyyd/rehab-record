import 'dart:convert';

import 'package:drift/native.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rehab_app/core/config.dart';
import 'package:rehab_app/core/date_utils.dart';
import 'package:rehab_app/core/providers.dart';
import 'package:rehab_app/data/local/app_database.dart';
import 'package:rehab_app/data/local/token_store.dart';
import 'package:rehab_app/data/remote/auth_service.dart';
import 'package:rehab_app/data/repo/patient_repository.dart';
import 'package:rehab_app/data/repo/record_repository.dart';
import 'package:rehab_app/data/repo/settings_repository.dart';
import 'package:rehab_app/data/repo/timeline_repository.dart';
import 'package:rehab_app/features/auth/auth_controller.dart';
import 'package:rehab_app/features/records/record_page.dart';
import 'package:rehab_app/features/records/record_providers.dart';
import 'package:rehab_app/sync/sync_engine.dart';

import 'support.dart';

/// 一个"已登录"的假认证控制器。
///
/// 生产里 `currentUserProvider` 从 `authControllerProvider` 派生，而后者由
/// `_BootstrapGate` 在真实启动流程里设置。测试不跑那个流程，所以必须自己顶上 ——
/// 否则 `RecordEditorController.save` 第一句就是 `if (user == null)` 直接返回
///（我第一版测试就这样静默失败了：`error=未登录`，页面当然不返回）。
class _FakeSignedInAuth extends AuthController {
  @override
  AuthState build() => const AuthSignedIn(
        user: AuthUser(id: 2, employeeNo: 'T001', name: '张三', role: 'therapist'),
        syncing: false,
      );
}

/// 记录页的**返回行为**（2026-10-05）。
///
/// 用户原话：「记录完成后，没有返回患者页」。缺陷的本质是：提交成功后页面
/// 只是显示一句"已提交"就停在那里，治疗师得自己按返回 —— 而返回键在床旁
/// 是"会丢东西"的动作（有未保存改动时还会弹确认框），所以他不知道该不该按。
///
/// 修复后：**提交成功 → 自动 pop，并把提示语交给患者页显示**。
/// 这一页自己的消息条会随页面一起消失，留在记录页等于没提示。
///
/// 为什么值得专门测：这条行为**已经无声地坏过一次**（原来只在"出院"分支 pop），
/// 而它是纯导航、没有返回值可供上层断言 —— 只有 widget 测试能守住。
///
/// 用 `Navigator` 的真实 push/pop 与真实 `RecordPage`，只在网络边界上挂脚本适配器，
/// 所以跑的是生产代码路径（`RecordEditorController.save` → `_syncAndReport` → 页面监听）。
void main() {
  late AppDatabase db;

  setUp(() => db = AppDatabase.forTesting(NativeDatabase.memory()));
  tearDown(() async => db.close());

  /// 最小但形状真实的表单：**一个必填的单选**，且预填已给值，
  /// 这样"点提交"不需要先输入任何东西就能走通（省掉模拟点击 chip）。
  Map<String, dynamic> formJson() => {
        'patient': {
          'inpatient_no': 'ZY001',
          'name': '患者甲',
          'status': 'in_hospital',
        },
        'discipline': 'PT',
        'discipline_name': '运动',
        'kind': 'daily',
        'kind_label': '日常治疗记录',
        'title': '康复治疗记录（PT运动）',
        'next_seq': 3,
        'total_daily': 2,
        'days_until_reassessment': 18,
        'template_version': 1,
        'soap': [
          {
            'key': 's',
            'label': 'S',
            'heading': '主观资料',
            'fields': [
              {
                'key': 'mental',
                'type': 'single',
                'label': '精神状态',
                'required': true,
                'options': ['良好', '一般', '差'],
              },
            ],
          },
        ],
        'prefill': {'mental': '良好'},
        'prefill_source': {'mental': 'last_daily'},
        'footer': <String>[],
        'existing': null,
      };

  /// 一次成功的推送响应：`applied` 非空 → `hasConflicts == false` → 走成功分支。
  Map<String, dynamic> pushOk() => {
        'applied': [
          {
            'outcome': 'applied',
            'client_uuid': 'uuid-test-0001',
            'entity': 'treatment_record',
            'entity_id': 7,
            'op': 'insert',
            'revision': 1,
          },
        ],
        'skipped': <Map<String, dynamic>>[],
        'conflicts': <Map<String, dynamic>>[],
        'cursor': 1,
      };

  ({ProviderContainer container, ScriptedAdapter adapter}) buildEnv(
    Map<String, (int, Object?)> responses,
  ) {
    final adapter = ScriptedAdapter(responses);
    final client = buildScriptedClient({}, adapter: adapter);
    final sync = SyncEngine(client: client, db: db);
    final tokens = TokenStore();
    final container = ProviderContainer.test(
      overrides: [
        // 必须有登录态：`save()` 拿不到用户会直接返回（见 `_FakeSignedInAuth`）。
        authControllerProvider.overrideWith(_FakeSignedInAuth.new),
        appServicesProvider.overrideWithValue(
          AsyncValue.data(AppServices(
            config: const AppConfig(
              baseUrl: 'http://test.local',
              trustedCaAsset: null,
              connectTimeout: Duration(seconds: 5),
              receiveTimeout: Duration(seconds: 5),
            ),
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

  /// 把记录页 push 到一个真实的 Navigator 上，并记录它 pop 回来的值。
  ///
  /// 关键在于**真的走一次 push**：只有被 push 的路由，`Navigator.pop` 才有意义，
  /// 也才能拿到返回值 —— 这正是患者页 `pushRecordEditor` 看到的那个值。
  Future<Object?> pushAndInteract(
    WidgetTester tester,
    ProviderContainer container, {
    required Future<void> Function(WidgetTester tester) interact,
    String? openDate,
  }) async {
    Object? popped;
    bool poppedCalled = false;

    final host = UncontrolledProviderScope(
      container: container,
      child: MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: Center(
              child: ElevatedButton(
                onPressed: () async {
                  popped = await Navigator.of(context).push<String>(
                    MaterialPageRoute<String>(
                      builder: (_) => RecordPage(
                        args: RecordEditorArgs(
                          patientNo: 'ZY001',
                          discipline: 'PT',
                          recordDate: openDate,
                        ),
                      ),
                    ),
                  );
                  poppedCalled = true;
                },
                child: const Text('打开记录页'),
              ),
            ),
          ),
        ),
      ),
    );

    await tester.pumpWidget(host);
    await tester.tap(find.text('打开记录页'));
    await tester.pumpAndSettle();

    await interact(tester);

    // 等 pop 真正发生（save 是异步的：本地落库 → 推送 → 置信号 → 页面监听）。
    for (var i = 0; i < 40 && !poppedCalled; i++) {
      await tester.pump(const Duration(milliseconds: 50));
    }
    await tester.pumpAndSettle();
    return popped;
  }

  testWidgets('★ 提交成功 → 自动返回，并把提示语带回给上层', (tester) async {
    final env = buildEnv({
      '/api/v1/records/form': (200, formJson()),
      '/api/v1/sync/push': (200, pushOk()),
    });
    addTearDown(env.container.dispose);

    final popped = await pushAndInteract(
      tester,
      env.container,
      interact: (tester) async {
        // 提交（不是存草稿）。
        await tester.tap(find.text('提交'));
        await tester.pump();
      },
    );

    expect(
      popped,
      '已提交：日常治疗记录',
      reason: '返回值应该是给患者页显示的提示语；null 表示页面没返回',
    );
  });

  testWidgets('存草稿**不**返回：那是"先记一半、还要接着写"', (tester) async {
    final env = buildEnv({
      '/api/v1/records/form': (200, formJson()),
      '/api/v1/sync/push': (200, pushOk()),
    });
    addTearDown(env.container.dispose);

    final popped = await pushAndInteract(
      tester,
      env.container,
      interact: (tester) async {
        await tester.tap(find.text('存草稿'));
        await tester.pump();
      },
    );

    expect(popped, isNull, reason: '存草稿把页面弹走会打断治疗师');
    // 页面还在（还能看到表单标题）。
    expect(find.text('康复治疗记录（PT运动）'), findsOneWidget);
  });

  testWidgets('★ 日期没被选过时提交：发出去的是**今天**，不是打开表单那天', (tester) async {
    // 用户 2026-10-06：「新建吞咽治疗记录……时间还是 10-5，
    // 似乎带入参数的时候，把日期也带入了，应该自动改成今日的日期」。
    //
    // `args.recordDate` 是**打开表单那一刻**算的，提交时一直沿用它 ——
    // 于是"23:50 打开、00:10 提交"就把记录记到昨天。这里把打开时的日期
    // 故意设成一个**过去的日期**，断言真正发出去的 payload 是今天。
    final env = buildEnv({
      '/api/v1/records/form': (200, formJson()),
      '/api/v1/sync/push': (200, pushOk()),
    });
    addTearDown(env.container.dispose);

    await pushAndInteract(
      tester,
      env.container,
      // 打开表单时"以为今天是 2020-01-01"。
      openDate: '2020-01-01',
      interact: (tester) async {
        await tester.tap(find.text('提交'));
        await tester.pump();
      },
    );

    final pushed = env.adapter.seen
        .where((r) => r.path.contains('/sync/push'))
        .toList();
    expect(pushed, isNotEmpty, reason: '提交后应该有一次推送');
    // Dio 还没把 body 编码成字节时 `data` 可能是**字符串**（也见过直接给 Map 的
    // 情况），两种都要能读 —— 这里只关心 payload 里的日期。
    final raw = pushed.last.data;
    final body = raw is String
        ? jsonDecode(raw) as Map<String, dynamic>
        : raw as Map<String, dynamic>;
    final change = (body['changes'] as List).first as Map<String, dynamic>;
    final sent = (change['payload'] as Map<String, dynamic>)['record_date'];
    expect(
      sent,
      formatDate(DateTime.now()),
      reason: '没选过日期时必须用提交那一刻的当天，而不是打开表单时的日期',
    );
  });

  testWidgets('推送冲突时不返回：先让人看到有问题', (tester) async {
    final env = buildEnv({
      '/api/v1/records/form': (200, formJson()),
      '/api/v1/sync/push': (
        200,
        {
          'applied': <Map<String, dynamic>>[],
          'skipped': <Map<String, dynamic>>[],
          'conflicts': [
            {
              'outcome': 'conflict',
              'client_uuid': 'uuid-test-0001',
              'entity': 'treatment_record',
              'reason': 'MISSING_ASSESSMENT',
              'message': '第 3 次日常记录前必须先完成复评',
              'details': {'missing_document': 'reassessment'},
            },
          ],
          'cursor': 1,
        }
      ),
    });
    addTearDown(env.container.dispose);

    final popped = await pushAndInteract(
      tester,
      env.container,
      interact: (tester) async {
        await tester.tap(find.text('提交'));
        await tester.pump();
      },
    );

    expect(popped, isNull, reason: '有冲突时应留在页面，把冲突提示给治疗师看');
  });
}
