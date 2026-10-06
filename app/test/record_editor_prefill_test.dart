import 'package:drift/drift.dart' show Value;
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

/// 记录编辑器**打开已有记录时**的预填规则（2026-10-05）。
///
/// 用户要求「患者详情页的治疗记录要可以点进去，**在原始记录上进行修改**」，
/// 于是 `submitted` 的记录也可点了。随之而来的问题是"预填谁的内容"：
///
/// - 本地草稿（`existingId < 0`）：只在本机，读本地 `body_json` 即可；
/// - 服务端记录（`existingId > 0`）：本地只有一份镜像，"最近同步过"**不等于**
///   "内容最新"（别人可能改过），所以**回服务端取一次**；取不到（离线/被删）
///   再退回本地内容 —— 床旁断网时至少还能改，而不是打不开页面。
///
/// 这里测的是后两种分支。它们只在"打开一条已有记录"时才走到，所以必须有
/// 一条 `existingId > 0` 的编辑目标。
///
/// 做法：`appServicesProvider` 被换成一个**挂了脚本适配器的真实 AppServices**，
/// 于是跑的是生产代码路径（`RecordEditorController._load` 与 `RecordRepository`），
/// 却一个真实请求都不会发出去。
void main() {
  late AppDatabase db;

  setUp(() => db = AppDatabase.forTesting(NativeDatabase.memory()));
  tearDown(() async => db.close());

  /// 一份最小但形状真实的表单响应（字段名来自后端 `RecordFormOut`）。
  ///
  /// 关键点是 `prefill.mental = 良好`：它是"服务端按上次日常带出来的值"，
  /// 用来验证已有记录的内容**确实覆盖**了它。
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

  /// 造一个完全离线的编辑器环境（适配器按 path 给出预置响应）。
  Future<({ProviderContainer container, ScriptedAdapter adapter})> buildEditor(
    Map<String, (int, Object?)> responses,
  ) async {
    final adapter = ScriptedAdapter(responses);
    final client = buildScriptedClient({}, adapter: adapter);
    final sync = SyncEngine(client: client, db: db);
    final tokens = TokenStore();
    final container = ProviderContainer.test(
      overrides: [
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

  /// 打开一条**服务端**记录（id 41）的编辑器。
  Future<RecordEditorState> openExisting(ProviderContainer container) async {
    await container.read(recordEditorProvider.notifier).start(
          const RecordEditorArgs(
            patientNo: 'ZY001',
            discipline: 'PT',
            recordDate: '2026-10-06',
            existingId: 41,
          ),
        );
    return container.read(recordEditorProvider);
  }

  group('★ 打开已有记录时的预填', () {
    test('服务端记录：用服务端返回的 body 覆盖表单预填', () async {
      final env = await buildEditor({
        kRecordForm: (200, formJson()),
        kRecord(41): (200, {
          'id': 41,
          'patient_no': 'ZY001',
          'therapist_id': 2,
          'record_date': '2026-10-06',
          'discipline': 'PT',
          'kind': 'daily',
          'status': 'submitted',
          'body': {'mental': '差'},
        }),
      });

      final state = await openExisting(env.container);

      expect(state.form, isNotNull);
      expect(state.values['mental'], '差',
          reason: '改的是线上那一份：服务端当前内容优先于预填的「良好」');
      expect(state.existingLocalId, 41, reason: '保存时要按这个 id 更新，而不是新建一条');
      // 表单与这条记录都取了（缺一个都说明走错了分支）。
      expect(
        env.adapter.seen.map((r) => r.path),
        containsAll([kRecordForm, kRecord(41)]),
      );
    });

    test('取不到服务端记录时退回本地 body（断网也能在床上改）', () async {
      // 本地镜像：内容和预填不同，用来区分"到底用的是哪一份"。
      await db.into(db.treatmentRecords).insertOnConflictUpdate(
            TreatmentRecordsCompanion.insert(
              id: const Value(41),
              patientNo: 'ZY001',
              therapistId: 2,
              recordDate: '2026-10-06',
              discipline: 'PT',
              kind: 'daily',
              bodyJson: const Value('{"mental":"一般"}'),
              status: const Value('submitted'),
              clientUuid: const Value('uuid-41'),
              syncStatus: const Value('synced'),
            ),
          );

      final env = await buildEditor({
        kRecordForm: (200, formJson()),
        // 服务端这条取不到（被删 / 离线）：必须降级而不是把页面卡在加载中。
        kRecord(41): (500, {'code': 'INTERNAL', 'message': 'boom'}),
      });

      final state = await openExisting(env.container);

      expect(state.loading, isFalse, reason: '降级路径不能让编辑器一直转圈');
      expect(state.values['mental'], '一般',
          reason: '拿服务端内容失败 → 退回本地镜像，而不是退回预填的「良好」');
    });

    test('本地草稿（id < 0）不请求服务端，直接读本地 body', () async {
      await db.into(db.treatmentRecords).insertOnConflictUpdate(
            TreatmentRecordsCompanion.insert(
              id: const Value(-1),
              patientNo: 'ZY001',
              therapistId: 2,
              recordDate: '2026-10-06',
              discipline: 'PT',
              kind: 'daily',
              bodyJson: const Value('{"mental":"差"}'),
              status: const Value('draft'),
              clientUuid: const Value('uuid-draft'),
              syncStatus: const Value('pending'),
            ),
          );

      final env = await buildEditor({kRecordForm: (200, formJson())});
      await env.container.read(recordEditorProvider.notifier).start(
            const RecordEditorArgs(
              patientNo: 'ZY001',
              discipline: 'PT',
              recordDate: '2026-10-06',
              existingId: -1,
            ),
          );
      final state = env.container.read(recordEditorProvider);

      expect(state.values['mental'], '差');
      expect(env.adapter.seen.single.path, kRecordForm,
          reason: '草稿只在本机，服务端还不知道它 —— 发请求只会拿到 404');
    });
  });
}
