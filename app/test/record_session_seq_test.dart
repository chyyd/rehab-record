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
import 'package:rehab_app/features/records/record_providers.dart';
import 'package:rehab_app/sync/sync_engine.dart';

import 'support.dart';

/// ★ **第二次打开同一个大类必须重新取表单**（2026-10-06）。
///
/// 用户原话：「E2E001 建立今日的运动记录是总第 21 次，但是，我再点运动按钮时，
/// 提示还是第 21 次，这样就产生了冲突」。
///
/// 根因：`RecordEditorController.start()` 原来靠 `args.sameTarget()` 判"重复调用"
/// 来保持幂等（本意是热重载不清空已填内容）。但**新打开一次**与**热重载重建**
/// 的参数**完全一样**（都是 patientNo + discipline，没有 existingId / kind），
/// 于是第二次打开被当成重复调用直接返回，用的是上一次那份
/// `next_seq=21` / `existing=null` 的表单 —— 提交时撞
/// `ux_record_daily_seq`（唯一索引）。
///
/// 修法：按**会话号**判断。调用方（记录页）每次真正打开就 +1；
/// 同会话内重复调用仍幂等。
///
/// 这一组测试断言的是**服务端被打了几次表单请求**，而不是内部字段 ——
/// "有没有真的重新问服务端"才是这个缺陷的本质。
void main() {
  /// 造一个能改变表单响应的假后端。
  Future<
      ({
        ProviderContainer container,
        ScriptedAdapter adapter,
      })> build() async {
    // 第一次返回 next_seq=21，第二次返回 22（模拟"建完第 21 次之后再取"）。
    final adapter = ScriptedAdapter({
      kRecordForm: (200, _form(nextSeq: 21)),
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

  const args = RecordEditorArgs(patientNo: 'E2E001', discipline: 'PT');

  test('★ 新会话（sessionSeq 变了）即使 args 相同也必须重新取表单', () async {
    final (:container, :adapter) = await build();
    final controller = container.read(recordEditorProvider.notifier);

    // 第一次打开
    await controller.start(args, sessionSeq: 1);
    expect(container.read(recordEditorProvider).form!.nextSeq, 21);

    // 后端现在会给出 22（模拟"第 21 次已保存"）
    adapter.responses[kRecordForm] = (200, _form(nextSeq: 22));

    // 第二次打开：args **完全相同**，只有会话号变了 —— 这正是用户的操作序列
    await controller.start(args, sessionSeq: 2);

    final plays = adapter.seen.where((r) => r.path == kRecordForm).length;
    expect(plays, 2, reason: '★ 新会话必须重新问服务端，否则会复用旧的 next_seq');
    expect(
      container.read(recordEditorProvider).form!.nextSeq,
      22,
      reason: '★ 必须显示 22（用户报的缺陷就是这里还显示 21）',
    );
  });

  test('同一会话内重复调用仍幂等（热重载不会白取一次、也不会清空已填内容）', () async {
    final (:container, :adapter) = await build();
    final controller = container.read(recordEditorProvider.notifier);

    await controller.start(args, sessionSeq: 7);
    final field = container.read(recordEditorProvider).form!.field('therapy_items')!;
    controller.toggleMulti(field, '徒手肌力训练');
    await controller.start(args, sessionSeq: 7); // 同一会话重复调用

    final plays = adapter.seen.where((r) => r.path == kRecordForm).length;
    expect(plays, 1, reason: '同会话内不该重复取表单');
    expect(
      container.read(recordEditorProvider).values['therapy_items'],
      ['徒手肌力训练'],
      reason: '已填内容不能被清掉 —— 这是"幂等"原本要保护的场景',
    );
  });

  test('不传 sessionSeq 时按新会话处理（默认值取不可能相等的 -1）', () async {
    final (:container, :adapter) = await build();
    final controller = container.read(recordEditorProvider.notifier);

    // 模拟"忘了传会话号"：宁可多取一次表单，也不能复用旧的 next_seq。
    await controller.start(args);
    adapter.responses[kRecordForm] = (200, _form(nextSeq: 22));
    await controller.start(args);

    expect(adapter.seen.where((r) => r.path == kRecordForm).length, 2);
    expect(container.read(recordEditorProvider).form!.nextSeq, 22);
  });
}

Map<String, dynamic> _form({required int nextSeq}) => {
      'patient': {'inpatient_no': 'E2E001', 'name': '患者甲', 'status': 'in_hospital'},
      'discipline': 'PT',
      'discipline_name': '运动',
      'kind': 'daily',
      'kind_label': '日常治疗记录',
      'title': '康复治疗记录（PT运动）',
      'next_seq': nextSeq,
      'total_daily': nextSeq - 1,
      'soap': [
        {
          'key': 'o',
          'label': '客观资料',
          'heading': '客观资料',
          'fields': [
            {
              'key': 'therapy_items',
              'type': 'multi',
              'label': '本次训练项目',
              'options': ['徒手肌力训练', '平衡功能训练'],
            },
          ],
        },
      ],
    };
