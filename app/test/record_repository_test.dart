import 'dart:convert';

import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rehab_app/core/api_endpoints.dart';
import 'package:rehab_app/core/error.dart';
import 'package:rehab_app/data/local/app_database.dart';
import 'package:rehab_app/data/remote/record_dto.dart';
import 'package:rehab_app/data/repo/record_repository.dart';
import 'package:rehab_app/sync/sync_engine.dart';

import 'support.dart';

/// 一份最小但**形状真实**的表单响应（字段名都来自后端 `RecordFormOut`）。
///
/// 四种字段类型都覆盖到：`single` / `multi` / `number` / `text`，
/// 并带上 `required` / `hint` / `unit` / `auto`。
Map<String, dynamic> formJson({
  String kind = 'daily',
  String discipline = 'PT',
  String? pendingDocument,
  Map<String, dynamic>? existing,
}) =>
    {
      'patient': {
        'inpatient_no': 'ZY001',
        'name': '患者甲',
        'status': 'in_hospital',
      },
      'discipline': discipline,
      'discipline_name': '运动',
      'kind': kind,
      'kind_label': switch (kind) {
        'initial' => '首评',
        'reassessment' => '阶段性复评',
        'discharge' => '出院小结',
        _ => '日常治疗记录',
      },
      'title': '康复治疗记录（PT运动）',
      'next_seq': 3,
      'total_daily': 2,
      'days_until_reassessment': 18,
      'pending_document': pendingDocument,
      'pending_document_label':
          pendingDocument == null ? null : (pendingDocument == 'initial' ? '首评' : '阶段性复评'),
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
            {
              'key': 'complaint',
              'type': 'multi',
              'label': '主诉',
              'options': ['患肢酸胀', '乏力', '无不适'],
            },
            {
              'key': 'vas',
              'type': 'number',
              'label': '疼痛VAS',
              'unit': '分',
            },
          ],
        },
        {
          'key': 'o',
          'label': 'O',
          'heading': '客观资料',
          'fields': [
            {
              'key': 'therapy_items',
              'type': 'multi',
              'label': '本次训练项目',
              'required': true,
              'options': ['偏瘫肢体综合训练', '平衡生物反馈训练', '徒手肌力训练'],
            },
            {
              'key': 'extra_note',
              'type': 'text',
              'label': '备注',
              'hint': '选填。留空则记录里不显示这一项。',
            },
            if (kind == 'discharge')
              {
                'key': 'summary',
                'type': 'text',
                'label': '治疗过程汇总',
                'auto': 'latest_vs_initial',
                'hint': '自动生成，只读',
              },
          ],
        },
      ],
      'prefill': {'mental': '良好', 'therapy_items': ['偏瘫肢体综合训练']},
      'prefill_source': {'mental': 'same_day_first', 'therapy_items': 'last_daily'},
      'footer': ['治疗师签名：__________'],
      'existing': existing,
    };

void main() {
  group('表单 DTO（SOAP 模板驱动，客户端只透传）', () {
    test('解析患者、文书形态、序号与复评倒计时', () {
      final form = RecordFormData.fromJson(formJson());
      expect(form.patientNo, 'ZY001');
      expect(form.patientName, '患者甲');
      expect(form.discipline, 'PT');
      expect(form.disciplineName, '运动');
      expect(form.kind, 'daily');
      expect(form.kindLabel, '日常治疗记录');
      expect(form.title, '康复治疗记录（PT运动）');
      expect(form.nextSeq, 3);
      expect(form.totalDaily, 2);
      expect(form.daysUntilReassessment, 18);
      expect(form.pendingDocument, isNull);
      expect(form.showsSeqNo, isTrue, reason: '日常记录显示"第 N 次"');
      expect(form.isAssessment, isFalse);
    });

    test('★ 四种字段类型都能解析（single / multi / number / text）', () {
      final form = RecordFormData.fromJson(formJson());
      final fields = form.allFields;

      final mental = form.field('mental')!;
      expect(mental.isSingle, isTrue);
      expect(mental.options, ['良好', '一般', '差']);
      expect(mental.required, isFalse);

      final complaint = form.field('complaint')!;
      expect(complaint.isMulti, isTrue);
      expect(complaint.options.length, 3);

      final vas = form.field('vas')!;
      expect(vas.isNumber, isTrue);
      expect(vas.unit, '分');

      final note = form.field('extra_note')!;
      expect(note.isText, isTrue);
      expect(note.hint, isNotNull);

      // 分段与段名（渲染时是「段名：字段；字段」）。
      expect(form.soap.map((s) => s.heading), ['主观资料', '客观资料']);
      expect(form.soap.first.label, 'S');
      expect(fields, hasLength(5));
    });

    test('★ 评估文书不显示序号（kind != daily）', () {
      final initial = RecordFormData.fromJson(formJson(kind: 'initial'));
      expect(initial.showsSeqNo, isFalse);
      expect(initial.isAssessment, isTrue);
      final discharge = RecordFormData.fromJson(formJson(kind: 'discharge'));
      expect(discharge.isDischarge, isTrue);
      expect(discharge.showsSeqNo, isFalse);
    });

    test('★ 缺评估文书时 kind 就是那份文书，pending_document 用来提示', () {
      final form = RecordFormData.fromJson(
        formJson(kind: 'initial', pendingDocument: 'initial'),
      );
      expect(form.pendingDocument, 'initial');
      expect(form.pendingDocumentLabel, '首评');
      expect(form.isAssessment, isTrue, reason: '服务端已把 kind 换成评估文书');
    });

    test('required / hint / unit / auto 原样透传', () {
      final form = RecordFormData.fromJson(formJson(kind: 'discharge'));
      expect(form.field('therapy_items')!.required, isTrue);
      expect(form.field('extra_note')!.hint, contains('选填'));
      expect(form.field('vas')!.unit, '分');
      expect(form.field('summary')!.auto, isTrue);
    });

    test('toJson 能往返（离线缓存靠它）', () {
      final form = RecordFormData.fromJson(formJson());
      final again = RecordFormData.fromJson(
        Map<String, dynamic>.from(jsonDecode(jsonEncode(form.toJson())) as Map),
      );
      expect(again.patientNo, form.patientNo);
      expect(again.kind, form.kind);
      expect(again.totalDaily, 2);
      expect(again.daysUntilReassessment, 18);
      expect(again.prefill['therapy_items'], ['偏瘫肢体综合训练']);
      expect(again.allFields.length, form.allFields.length);
    });

    test('★ 初值 = 服务端预填 + 已存在记录的内容（已存在优先）', () {
      final form = RecordFormData.fromJson(formJson(existing: {
        'id': 88,
        'patient_no': 'ZY001',
        'therapist_id': 2,
        'record_date': '2026-10-06',
        'discipline': 'PT',
        'kind': 'daily',
        'body': {'vas': 3, 'mental': '一般'},
        'rendered_text': '康复治疗记录（PT运动）',
        'status': 'draft',
      }));
      expect(form.existing, isNotNull);
      expect(form.existing!.id, 88);
      final values = form.initialValues();
      expect(values['mental'], '一般', reason: '已存在记录覆盖了预填的"良好"');
      expect(values['vas'], 3);
      expect(values['therapy_items'], ['偏瘫肢体综合训练']);
    });
  });

  group('字段值的归一化（提交体必须与后端同一形状）', () {
    final single = SoapField.fromJson({
      'key': 'mental', 'type': 'single', 'label': '精神状态',
      'options': ['良好', '一般'],
    });
    final multi = SoapField.fromJson({
      'key': 'items', 'type': 'multi', 'label': '项目', 'options': ['A', 'B'],
    });
    final number = SoapField.fromJson({
      'key': 'vas', 'type': 'number', 'label': '疼痛VAS', 'unit': '分',
    });
    final text = SoapField.fromJson({'key': 'note', 'type': 'text', 'label': '备注'});

    test('single：空串归一化成 null（不写进 body）', () {
      expect(single.normalize('良好'), '良好');
      expect(single.normalize(''), isNull);
      expect(single.normalize(null), isNull);
    });

    test('multi：始终是数组（传字符串会被后端当成单值）', () {
      expect(multi.normalize(['A']), ['A']);
      expect(multi.normalize(['A', 'B']), ['A', 'B']);
      expect(multi.normalize('A/B'), ['A', 'B']);
      expect(multi.normalize('A、B'), ['A', 'B']);
      expect(multi.normalize(<String>[]), isNull);
      expect(multi.normalize(''), isNull);
    });

    test('number：存成数字，0 是有效值', () {
      expect(number.normalize('3'), 3);
      expect(number.normalize(2.5), 2.5);
      expect(number.normalize(0), 0);
      expect(number.normalize(''), isNull);
      // 0 必须算"填了"（VAS 0 分是真实数据）。
      expect(SoapField.hasValue(0), isTrue);
      expect(SoapField.hasValue(<String>[]), isFalse);
    });

    test('text：原样，空白串丢掉', () {
      expect(text.normalize('  有点头晕  '), '有点头晕');
      expect(text.normalize('   '), isNull);
    });

    test('display：多选用 / 连接（与后端渲染器一致）', () {
      expect(SoapField.display(['A', 'B']), 'A/B');
      expect(SoapField.display(3), '3');
      expect(SoapField.display(null), '');
    });
  });

  group('记录离线写入（先本地 + 入队）', () {
    late AppDatabase db;
    late RecordRepository repo;

    setUp(() {
      db = AppDatabase.forTesting(NativeDatabase.memory());
      repo = RecordRepository(
        client: buildScriptedClient({}),
        db: db,
        sync: SyncEngine(client: buildScriptedClient({}), db: db),
      );
    });

    tearDown(() async => db.close());

    test('新草稿：负数占位 id、pending、入队 insert、内容存成 body_json', () async {
      final saved = await repo.save(
        existingId: null,
        patientNo: 'ZY001',
        therapistId: 2,
        recordDate: '2026-10-06',
        discipline: 'PT',
        kind: 'daily',
        body: {'mental': '良好', 'therapy_items': ['偏瘫肢体综合训练']},
        status: 'draft',
        renderedText: '康复治疗记录（PT运动）',
      );

      expect(saved.localId, lessThan(0), reason: '本地新建用负数占位，避免与服务端自增 id 撞号');
      expect(saved.clientUuid, isNotEmpty);

      final row = await db.select(db.treatmentRecords).getSingle();
      expect(row.syncStatus, 'pending');
      expect(row.status, 'draft');
      expect(row.discipline, 'PT');
      expect(row.kind, 'daily');
      expect(RecordRepository.decodeBody(row.bodyJson),
          {'mental': '良好', 'therapy_items': ['偏瘫肢体综合训练']});
      expect(row.renderedText, '康复治疗记录（PT运动）');
    });

    test('★ 推送 payload 的形状：`body`（没有 items / session_period / duration_min）', () async {
      await repo.save(
        existingId: null,
        patientNo: 'ZY001',
        therapistId: 2,
        recordDate: '2026-10-06',
        discipline: 'PT',
        kind: 'daily',
        body: {'vas': 2, 'complaint': ['乏力']},
        status: 'submitted',
      );

      final queued = await db.select(db.changeQueue).getSingle();
      expect(queued.op, 'insert');
      expect(queued.baseRevision, isNull, reason: '新建不带基线（协议 §4.4）');

      final payload = jsonDecode(queued.payloadJson) as Map<String, dynamic>;
      expect(payload['patient_no'], 'ZY001');
      expect(payload['record_date'], '2026-10-06');
      expect(payload['discipline'], 'PT');
      expect(payload['kind'], 'daily');
      expect(payload['status'], 'submitted');
      expect(payload['body'], {'vas': 2, 'complaint': ['乏力']});
      // 旧模型的字段一个都不能再出现（服务端已经不认它们）。
      expect(payload.containsKey('items'), isFalse);
      expect(payload.containsKey('session_period'), isFalse);
      expect(payload.containsKey('duration_min'), isFalse);
      expect(payload.containsKey('patient_response'), isFalse);
    });

    /// 用户 2026-10-05 实测：「新建记录时会提示冲突……保留我的按钮无法生效」。
    ///
    /// 这条守**根因**：本地 `revision == 0` 时不能把它当基线带上。
    ///
    /// 乐观锁的语义是"我基于第 N 版改的"。一条**正数 id** 的记录在服务端一定存在，
    /// 所以服务端那版至少是 1；本地却是 0，说明这份基线不可信
    ///（历史遗留：上传后 revision 没回写）。带 0 上去必然对不上，
    /// 服务端只能回一个含糊的 `server_status=submitted` —— 现场就是"一保存就冲突"。
    ///
    /// 不带基线时服务端回 `missing_base_revision` + **真实 `server_revision`**，
    /// "保留我的"正好用那个值一步对齐（`ConflictController.keepMine`）。
    test('★ 本地 revision=0 时不带 base_revision（改成可自愈的明确冲突）', () async {
      // 造一条"服务端已有、但本地 revision 没回写"的记录：正数 id + revision 0。
      await db.into(db.treatmentRecords).insertOnConflictUpdate(
            TreatmentRecordsCompanion.insert(
              id: const Value(77),
              patientNo: 'ZY001',
              therapistId: 2,
              recordDate: '2026-10-06',
              discipline: 'PT',
              kind: 'daily',
              clientUuid: const Value('u-stale'),
              revision: const Value(0),
              syncStatus: const Value('synced'),
            ),
          );

      await repo.save(
        existingId: 77,
        patientNo: 'ZY001',
        therapistId: 2,
        recordDate: '2026-10-06',
        discipline: 'PT',
        kind: 'daily',
        body: {'vas': 3},
        status: 'submitted',
      );

      final queued = await db.select(db.changeQueue).getSingle();
      expect(queued.op, 'update');
      expect(
        queued.baseRevision,
        isNull,
        reason: '基线不可信时必须不带；带 0 会换来一个说不清的冲突',
      );
    });

    test('本地 revision 可信（>0）时带上它（这才是乐观锁该有的样子）', () async {
      await db.into(db.treatmentRecords).insertOnConflictUpdate(
            TreatmentRecordsCompanion.insert(
              id: const Value(78),
              patientNo: 'ZY001',
              therapistId: 2,
              recordDate: '2026-10-06',
              discipline: 'PT',
              kind: 'daily',
              clientUuid: const Value('u-fresh'),
              revision: const Value(5),
              syncStatus: const Value('synced'),
            ),
          );

      await repo.save(
        existingId: 78,
        patientNo: 'ZY001',
        therapistId: 2,
        recordDate: '2026-10-06',
        discipline: 'PT',
        kind: 'daily',
        body: {'vas': 3},
        status: 'submitted',
      );

      final queued = await db.select(db.changeQueue).getSingle();
      expect(queued.baseRevision, 5);
    });

    test('读回本地草稿的 body（继续编辑要靠它）', () async {
      final saved = await repo.save(
        existingId: null,
        patientNo: 'ZY001',
        therapistId: 2,
        recordDate: '2026-10-06',
        discipline: 'ST_SW',
        kind: 'daily',
        body: {'vas': 3, 'mental': '一般'},
        status: 'draft',
      );

      final body = await repo.readLocalBody(saved.localId);
      expect(body['vas'], 3);
      expect(body['mental'], '一般');

      final draft = await repo.findLocalDraft(
        patientNo: 'ZY001',
        recordDate: '2026-10-06',
        discipline: 'ST_SW',
      );
      expect(draft?.id, saved.localId);
      // 别的大类不该被匹配到（表单/草稿都是按大类分的）。
      expect(
        await repo.findLocalDraft(
          patientNo: 'ZY001',
          recordDate: '2026-10-06',
          discipline: 'PT',
        ),
        isNull,
      );
    });

    test('改一条尚未推送的本地草稿：仍是一个队列条目，且不带基线', () async {
      final saved = await repo.save(
        existingId: null,
        patientNo: 'ZY001',
        therapistId: 2,
        recordDate: '2026-10-06',
        discipline: 'PT',
        kind: 'daily',
        body: {'mental': '良好'},
        status: 'draft',
      );

      await repo.save(
        existingId: saved.localId,
        patientNo: 'ZY001',
        therapistId: 2,
        recordDate: '2026-10-06',
        discipline: 'PT',
        kind: 'daily',
        body: {'mental': '差'},
        status: 'draft',
      );

      final queued = await db.select(db.changeQueue).getSingle();
      expect(queued.baseRevision, isNull,
          reason: '服务端还不知道这个 uuid，带基线反而可能被判成冲突');
      expect(queued.payloadJson, contains('差'));

      final rows = await db.select(db.treatmentRecords).get();
      expect(rows, hasLength(1), reason: '更新不该产生第二条本地记录');
    });

    test('按患者查询是响应式的：存一条草稿本地立刻能看到', () async {
      final emissions = <int>[];
      final sub = repo.watchLocal('ZY001').listen((r) => emissions.add(r.length));

      await pumpEventQueue();
      expect(emissions.last, 0);

      await repo.save(
        existingId: null,
        patientNo: 'ZY001',
        therapistId: 2,
        recordDate: '2026-10-06',
        discipline: 'PT',
        kind: 'daily',
        body: const {},
        status: 'draft',
      );
      await pumpEventQueue();
      expect(emissions.last, 1);

      await sub.cancel();
    });

    test('当天计数按**大类**分开（服务端是"同一天同一大类至多 2 条"）', () async {
      await repo.save(
        existingId: null,
        patientNo: 'ZY001',
        therapistId: 2,
        recordDate: '2026-10-06',
        discipline: 'PT',
        kind: 'daily',
        body: const {},
        status: 'submitted',
      );
      expect(
        await repo.countForDay(
          patientNo: 'ZY001',
          recordDate: '2026-10-06',
          discipline: 'PT',
        ),
        1,
      );
      expect(
        await repo.countForDay(
          patientNo: 'ZY001',
          recordDate: '2026-10-06',
          discipline: 'OT',
        ),
        0,
      );
    });
  });

  group('表单缓存（离线优先）', () {
    late AppDatabase db;
    late RecordRepository repo;
    late ScriptedAdapter adapter;

    setUp(() {
      db = AppDatabase.forTesting(NativeDatabase.memory());
      adapter = ScriptedAdapter({kRecordForm: (200, formJson())});
      repo = RecordRepository(
        client: buildScriptedClient({}, adapter: adapter),
        db: db,
        sync: SyncEngine(client: buildScriptedClient({}), db: db),
      );
    });

    tearDown(() async => db.close());

    test('取表单带 patient_no + discipline（kind 只在出院时显式传）', () async {
      await repo.fetchForm('ZY001', 'PT', date: '2026-10-06');
      final q = adapter.seen.single.queryParameters;
      expect(q['patient_no'], 'ZY001');
      expect(q['discipline'], 'PT');
      expect(q['date'], '2026-10-06');
      expect(q.containsKey('kind'), isFalse, reason: '形态由服务端门禁决定');
    });

    test('★ 出院小结必须显式传 kind=discharge（门禁推不出来）', () async {
      await repo.fetchForm('ZY001', 'PT', kind: 'discharge');
      expect(adapter.seen.single.queryParameters['kind'], 'discharge');
    });

    test('联网成功后落缓存；断网时能读回来', () async {
      final online = await repo.fetchForm('ZY001', 'PT');
      expect(online.fromCache, isFalse);

      final cached = await repo.readCachedForm('ZY001', 'PT');
      expect(cached, isNotNull);
      expect(cached!.form.patientName, '患者甲');
      expect(cached.form.allFields.length, 5);

      // 断网：抛 NETWORK_ERROR 时应回落到缓存。
      final offlineRepo = RecordRepository(
        client: buildScriptedClient({kRecordForm: (500, {'code': 'X', 'message': 'boom'})}),
        db: db,
        sync: SyncEngine(client: buildScriptedClient({}), db: db),
      );
      final fallback = await offlineRepo.fetchForm('ZY001', 'PT');
      expect(fallback.fromCache, isTrue);
      expect(fallback.form.patientName, '患者甲');
    });

    test('★ 缓存按大类 + 形态分开存（不能互相覆盖）', () async {
      final adapter2 = ScriptedAdapter({
        kRecordForm: (200, formJson()),
      });
      final repo2 = RecordRepository(
        client: buildScriptedClient({}, adapter: adapter2),
        db: db,
        sync: SyncEngine(client: buildScriptedClient({}), db: db),
      );
      await repo2.fetchForm('ZY001', 'PT');
      await db.into(db.refCache).insertOnConflictUpdate(
            RefCacheCompanion.insert(
              key: RecordRepository.formCacheKey('ZY001', 'PT', kind: 'discharge'),
              payloadJson: jsonEncode(
                RecordFormData.fromJson(formJson(kind: 'discharge')).toJson(),
              ),
              fetchedAt: '2026-10-06T00:00:00Z',
            ),
          );

      final daily = await repo2.readCachedForm('ZY001', 'PT');
      final discharge =
          await repo2.readCachedForm('ZY001', 'PT', kind: 'discharge');
      expect(daily!.form.kind, 'daily');
      expect(discharge!.form.kind, 'discharge');
      // 没缓存过的大类返回 null，而不是错误地回落到别的大类。
      expect(await repo2.readCachedForm('ZY001', 'ST_SP'), isNull);
    });

    test('缓存损坏时返回 null，不炸掉整个页面', () async {
      await db.into(db.refCache).insertOnConflictUpdate(
            RefCacheCompanion.insert(
              key: RecordRepository.formCacheKey('ZY001', 'PT'),
              payloadJson: '这不是 JSON',
              fetchedAt: '2026-10-06T00:00:00Z',
            ),
          );
      expect(await repo.readCachedForm('ZY001', 'PT'), isNull);
    });
  });

  group('多选字段的"最近用过"（58 项选项要靠它才能一点就中）', () {
    late AppDatabase db;
    late RecordRepository repo;

    setUp(() {
      db = AppDatabase.forTesting(NativeDatabase.memory());
      repo = RecordRepository(
        client: buildScriptedClient({}),
        db: db,
        sync: SyncEngine(client: buildScriptedClient({}), db: db),
      );
    });

    tearDown(() async => db.close());

    test('记住之后最近的排最前，且去重、限长', () async {
      await repo.rememberOptions('therapy_items', ['徒手肌力训练']);
      await repo.rememberOptions('therapy_items', ['偏瘫肢体综合训练']);
      expect(
        await repo.recentOptions('therapy_items'),
        ['偏瘫肢体综合训练', '徒手肌力训练'],
      );

      // 重复使用只提前，不重复。
      await repo.rememberOptions('therapy_items', ['徒手肌力训练']);
      expect(
        await repo.recentOptions('therapy_items'),
        ['徒手肌力训练', '偏瘫肢体综合训练'],
      );

      for (var i = 0; i < 20; i++) {
        await repo.rememberOptions('therapy_items', ['项目$i']);
      }
      expect(
        (await repo.recentOptions('therapy_items')).length,
        RecordRepository.recentOptionsLimit,
      );
    });

    test('没记过就返回空表（界面按模板顺序显示）', () async {
      expect(await repo.recentOptions('never_used'), isEmpty);
    });
  });

  /// ★ 2026-10-05：用户要求「患者详情页的治疗记录要可以点进去，**在原始记录上进行修改**」。
  ///
  /// 已提交（`submitted`）的记录本地只镜像了最近同步过的那一份，而"最近同步过"不等于
  /// "内容最新"（别人可能改过、或这条还没同步下来），所以点进去编辑前要按**服务端 id**
  /// 回服务端取一次当前内容。
  group('★ 按服务端 id 取记录（点进去改已有记录）', () {
    late AppDatabase db;
    late RecordRepository repo;
    late ScriptedAdapter adapter;

    setUp(() {
      db = AppDatabase.forTesting(NativeDatabase.memory());
      adapter = ScriptedAdapter({
        kRecord(41): (200, {
          'id': 41,
          'patient_no': 'ZY001',
          'therapist_id': 2,
          'record_date': '2026-10-06',
          'discipline': 'PT',
          'kind': 'daily',
          'status': 'submitted',
          'seq_no': 3,
          'body': {'mental': '一般', 'vas': 3},
          'rendered_text': '康复治疗记录（PT运动）',
        }),
      });
      repo = RecordRepository(
        client: buildScriptedClient({}, adapter: adapter),
        db: db,
        sync: SyncEngine(client: buildScriptedClient({}), db: db),
      );
    });

    tearDown(() async => db.close());

    test('请求 /records/{id} 并解出 body / status（编辑要靠它们预填）', () async {
      final record = await repo.fetchRecord(41);

      expect(adapter.seen.single.path, '/api/v1/records/41');
      expect(record.id, 41);
      expect(record.status, 'submitted');
      expect(record.body, {'mental': '一般', 'vas': 3});
    });

    test('服务端取不到这条记录时抛 AppError（调用方据此退回本地内容）', () async {
      final broken = RecordRepository(
        client: buildScriptedClient({
          kRecord(41): (404, {'code': 'RECORD_NOT_FOUND', 'message': '记录不存在'}),
        }),
        db: db,
        sync: SyncEngine(client: buildScriptedClient({}), db: db),
      );

      await expectLater(broken.fetchRecord(41), throwsA(isA<AppError>()));
    });
  });
}
