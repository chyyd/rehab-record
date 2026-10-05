import 'dart:convert';

import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rehab_app/data/local/app_database.dart';
import 'package:rehab_app/data/remote/record_dto.dart';
import 'package:rehab_app/data/repo/record_repository.dart';
import 'package:rehab_app/sync/sync_engine.dart';

import 'support.dart';

/// 一份最小但**形状真实**的表单响应（字段名都来自后端 `RecordFormOut`）。
Map<String, dynamic> formJson() => {
      'patient': {
        'inpatient_no': 'ZY001',
        'name': '张三',
        'diagnosis': '脑卒中恢复期',
        'admin_note': '注意防跌倒',
        'status': 'in_health',
      },
      'main_items': [
        {
          'id': 1,
          'name': '运动治疗',
          'alias': 'PT',
          'sort': 1,
          'sub_items': [
            {
              'id': 11,
              'main_item_id': 1,
              'name': '关节松动术',
              'sort': 1,
              'params': [
                {
                  'id': 111,
                  'sub_item_id': 11,
                  'param_key': 'side',
                  'param_name': '部位',
                  'input_type': 'select',
                  'options': ['左', '右'],
                  'required': 1,
                  'sort': 1,
                  // 服务端已按 5 级带入算好 —— 客户端**不该**再算一遍。
                  'current_value': '左',
                  'value_source': 'last_value',
                },
                {
                  'id': 112,
                  'sub_item_id': 11,
                  'param_key': 'grade',
                  'param_name': '分级',
                  'input_type': 'number',
                  'required': 0,
                  'unit': '级',
                  'sort': 2,
                  'current_value': null,
                  'value_source': null,
                },
              ],
            },
          ],
        },
      ],
      'response_defs': [
        {
          'id': 1,
          'code': 'pain',
          'label': '疼痛',
          'value_type': 'number',
          'value_unit': '分',
          'value_min': 0,
          'value_max': 10,
        },
        {
          'id': 2,
          'code': 'discomfort',
          'label': '不适',
          'value_type': 'tag',
          'options': ['无不适', '头晕', '乏力'],
        },
      ],
      'last_completed_seq_no': 3,
      'reference_date': '2027-03-01',
    };

void main() {
  group('表单 DTO（服务端算好带入值，客户端只透传）', () {
    test('解析患者、主项目、子项目、参数', () {
      final form = RecordFormData.fromJson(formJson());
      expect(form.patientNo, 'ZY001');
      expect(form.patientName, '张三');
      expect(form.adminNote, '注意防跌倒');
      expect(form.mainItems.single.display, 'PT', reason: '有别名时用别名');
      expect(form.mainItems.single.subItems.single.name, '关节松动术');
      // 已完成 3 次 → 本次是第 4 次。
      expect(form.nextSeqNo, 4);
    });

    test('参数的带入值原样保留，并带出"值来源"标注', () {
      final p = RecordFormData.fromJson(formJson())
          .mainItems
          .single
          .subItems
          .single
          .params;
      final side = p.firstWhere((e) => e.paramKey == 'side');
      expect(side.currentValue, '左');
      expect(side.valueSourceLabel, '上次值');
      expect(side.required, isTrue);
      expect(side.isSelect, isTrue);
      expect(side.candidates.map((c) => c.value), ['左', '右']);
    });

    test('选项集解析结果优先于字典静态选项', () {
      final json = formJson();
      final param = ((json['main_items'] as List).first['sub_items'] as List)
          .first['params'][0] as Map<String, dynamic>;
      param['options_resolved'] = {
        'code': 'side',
        'source': 'personal',
        'options': [
          {'value': 'L', 'label': '左侧'},
        ],
        'defaults': ['L'],
      };
      final parsed = FormParam.fromJson(param);
      expect(parsed.candidates.single.label, '左侧');
      expect(parsed.optionsSourceLabel, '个人选项集');
    });

    test('toJson 能往返（离线缓存靠它）', () {
      final form = RecordFormData.fromJson(formJson());
      final again = RecordFormData.fromJson(
        Map<String, dynamic>.from(jsonDecode(jsonEncode(form.toJson())) as Map),
      );
      expect(again.patientNo, form.patientNo);
      expect(again.mainItems.single.subItems.single.params.length, 2);
      expect(again.lastCompletedSeqNo, 3);
      expect(again.responseDefs.length, 2);
    });

    test('患者反应三种控件的解析', () {
      final defs = RecordFormData.fromJson(formJson()).responseDefs;
      final pain = defs.firstWhere((d) => d.code == 'pain');
      expect(pain.valueType, 'number');
      expect(pain.valueUnit, '分');
      expect(pain.valueMax, 10);
      final tag = defs.firstWhere((d) => d.code == 'discomfort');
      expect(tag.valueType, 'tag');
      expect(tag.options, ['无不适', '头晕', '乏力']);
    });

    test('★ multi_select 的带入值必须归一化成数组（否则提交会被服务端拒掉）', () {
      // 实测：`items` 这个 multi_select 参数从 last_value 读回来是 "洗脸 刷牙"。
      // 后端 _validate_value 对 multi_select 明确要求数组，
      // 直接把字符串塞进 params 提交会 400（"多选参数取值必须是数组"）。
      final param = FormParam.fromJson({
        'id': 1, 'sub_item_id': 1, 'param_key': 'items', 'param_name': '项目',
        'input_type': 'multi_select', 'required': 0,
        'current_value': '洗脸 刷牙', 'value_source': 'last_value',
      });
      expect(param.normalizeValue(param.currentValue), ['洗脸', '刷牙']);

      // 顿号分隔（存快照时的形式）也要能拆开。
      final dot = FormParam.fromJson({
        'id': 2, 'sub_item_id': 1, 'param_key': 'x', 'param_name': 'x',
        'input_type': 'multi_select', 'required': 0, 'current_value': '舌、唇',
      });
      expect(dot.normalizeValue(dot.currentValue), ['舌', '唇']);

      // 已经是数组的原样返回。
      expect(param.normalizeValue(['左']), ['左']);
      // 空值不该变成 ['']。
      expect(param.normalizeValue(''), isNull);
      expect(param.normalizeValue(null), isNull);
    });

    test('number 带入值归一化成数字', () {
      final p = FormParam.fromJson({
        'id': 1, 'sub_item_id': 1, 'param_key': 'reps', 'param_name': '次数',
        'input_type': 'number', 'required': 0, 'current_value': '10',
      });
      expect(p.normalizeValue('10'), 10);
      expect(p.normalizeValue(3), 3);
      expect(p.normalizeValue(''), isNull);
    });

    test('select 的空串归一化成 null（不提交空值）', () {
      final p = FormParam.fromJson({
        'id': 1, 'sub_item_id': 1, 'param_key': 'side', 'param_name': '侧',
        'input_type': 'select', 'required': 0, 'current_value': '',
      });
      expect(p.normalizeValue(''), isNull);
      expect(p.normalizeValue('左'), '左');
    });

    test('★ 带入值不在选项集内时必须丢掉（否则"表单给的值，提交却被拒"）', () {
      // 实测的原始数据：assistance_level 的 dict_default 是「部分辅助」，
      // 但同一响应里 options_resolved 的合法值是「完全辅助/最大辅助/中等辅助/
      // 最小辅助/监护/独立」—— 照表单预填直接提交必被 422。
      final p = FormParam.fromJson({
        'id': 1, 'sub_item_id': 8, 'param_key': 'assistance_level',
        'param_name': '辅助程度', 'input_type': 'select', 'required': 0,
        'default_value': '部分辅助',
        'current_value': '部分辅助', 'value_source': 'dict_default',
        'options_resolved': {
          'code': 'assistance_level', 'source': 'global',
          'options': [
            {'value': '完全辅助', 'label': '完全辅助'},
            {'value': '中等辅助', 'label': '中等辅助'},
            {'value': '独立', 'label': '独立'},
          ],
          'defaults': <String>[],
        },
      });

      expect(p.isValueSubmittable('部分辅助'), isFalse);
      expect(p.normalizeValue(p.currentValue), isNull,
          reason: '不合法的带入值必须丢掉，不能预填进提交体');
      expect(p.normalizeValue(p.defaultValue), isNull);
      // 合法值照常通过。
      expect(p.normalizeValue('独立'), '独立');
    });

    test('多选里只要有一个值不合法就整体丢掉', () {
      final p = FormParam.fromJson({
        'id': 1, 'sub_item_id': 1, 'param_key': 'body_part', 'param_name': '部位',
        'input_type': 'multi_select', 'required': 0,
        'options_resolved': {
          'code': 'body_part', 'source': 'global',
          'options': [
            {'value': '舌', 'label': '舌'},
            {'value': '腭', 'label': '腭'},
          ],
          'defaults': <String>[],
        },
      });
      expect(p.normalizeValue(['舌']), ['舌']);
      expect(p.normalizeValue(['舌', '肩']), isNull);
    });

    test('没有候选项时不做判断（交给服务端），避免误杀自由文本', () {
      final p = FormParam.fromJson({
        'id': 1, 'sub_item_id': 1, 'param_key': 'x', 'param_name': 'x',
        'input_type': 'select', 'required': 0, 'current_value': '任意值',
        'options': <String>[],
      });
      expect(p.isValueSubmittable('任意值'), isTrue);
      expect(p.normalizeValue('任意值'), '任意值');
    });

    test('未绑主项目的反应定义适用于所有项目', () {
      final def = ResponseDef.fromJson({
        'id': 1, 'code': 'x', 'label': 'x', 'value_type': 'tag',
      });
      expect(def.appliesTo(1), isTrue);
      expect(def.appliesTo(null), isTrue);

      final bound = ResponseDef.fromJson({
        'id': 2, 'code': 'y', 'label': 'y', 'value_type': 'tag', 'main_item_id': 5,
      });
      expect(bound.appliesTo(5), isTrue);
      expect(bound.appliesTo(6), isFalse);
    });
  });

  group('患者反应草稿的形状（必须与后端一致）', () {
    test('序列化成 {tags: [...], items: [{code, value}]}', () {
      final r = PatientResponseDraft(
        tags: {'无不适'},
        items: {'pain': 3},
      );
      final json = r.toJson();
      expect((json['tags'] as List).cast<String>(), ['无不适']);
      expect((json['items'] as List).single, {'code': 'pain', 'value': 3});
    });

    test('能往返解析', () {
      final back = PatientResponseDraft.fromJson({
        'tags': ['头晕'],
        'items': [
          {'code': 'pain', 'value': 5},
          {'code': 'rom', 'value': '120'},
        ],
      });
      expect(back.tags, {'头晕'});
      expect(back.items['pain'], 5);
      expect(back.items['rom'], '120');
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

    test('新草稿：负数占位 id、pending、入队 insert、明细存成 JSON', () async {
      final id = await repo.saveDraft(
        existingId: null,
        patientNo: 'ZY001',
        therapistId: 2,
        recordDate: '2027-03-01',
        sessionPeriod: 'am',
        appointmentId: null,
        durationMin: 30,
        note: '首次',
        response: PatientResponseDraft(tags: {'无不适'}, items: {'pain': 2}),
        items: [
          RecordItemDraft(
            mainItemId: 1,
            subItemId: 11,
            subItemName: '关节松动术',
            params: {'side': '左'},
          ),
        ],
        status: 'draft',
      );

      expect(id, lessThan(0), reason: '本地新建用负数占位，避免与服务端自增 id 撞号');

      final row = await db.select(db.treatmentRecords).getSingle();
      expect(row.syncStatus, 'pending');
      expect(row.status, 'draft');
      expect(row.durationMin, 30);
      expect(row.clientUuid, isNotNull);

      // 未推送的明细只能存 JSON 列 —— 它没有服务端 id，走不了 record_items 表。
      final queued = await db.select(db.changeQueue).getSingle();
      expect(queued.op, 'insert');
      expect(queued.baseRevision, isNull, reason: '新建不带基线（协议 §4.4）');
      expect(queued.payloadJson, contains('"side":"左"'));
      expect(queued.payloadJson, contains('"patient_response"'));
      expect(queued.payloadJson, contains('"items"'));
    });

    test('读回未推送的明细（继续编辑要靠它）', () async {
      final id = await repo.saveDraft(
        existingId: null,
        patientNo: 'ZY001',
        therapistId: 2,
        recordDate: '2027-03-01',
        sessionPeriod: null,
        appointmentId: null,
        durationMin: null,
        note: null,
        response: PatientResponseDraft(),
        items: [
          RecordItemDraft(
            mainItemId: 1, subItemId: 11, subItemName: '关节松动术',
            params: {'side': '左', 'grade': 3},
          ),
        ],
        status: 'draft',
      );

      final items = await repo.readPendingItems(id);
      expect(items, hasLength(1));
      expect(items.single.subItemId, 11);
      expect(items.single.params['side'], '左');
      expect(items.single.params['grade'], 3);
    });

    test('空患者反应不写进 payload（服务端按"未评估"处理）', () async {
      await repo.saveDraft(
        existingId: null,
        patientNo: 'ZY001',
        therapistId: 2,
        recordDate: '2027-03-01',
        sessionPeriod: null,
        appointmentId: null,
        durationMin: null,
        note: null,
        response: PatientResponseDraft(),
        items: const [],
        status: 'draft',
      );

      final queued = await db.select(db.changeQueue).getSingle();
      expect(queued.payloadJson.contains('patient_response'), isFalse);
      final row = await db.select(db.treatmentRecords).getSingle();
      expect(row.patientResponseJson, isNull);
    });

    test('改一条尚未推送的本地草稿：仍是一个队列条目，且不带基线', () async {
      final id = await repo.saveDraft(
        existingId: null,
        patientNo: 'ZY001', therapistId: 2, recordDate: '2027-03-01',
        sessionPeriod: null, appointmentId: null, durationMin: null, note: 'v1',
        response: PatientResponseDraft(), items: const [], status: 'draft',
      );

      await repo.saveDraft(
        existingId: id,
        patientNo: 'ZY001', therapistId: 2, recordDate: '2027-03-01',
        sessionPeriod: null, appointmentId: null, durationMin: 45, note: 'v2',
        response: PatientResponseDraft(), items: const [], status: 'draft',
      );

      // 同一个 client_uuid 只留一条（队列以它为幂等键）。
      final queued = await db.select(db.changeQueue).getSingle();
      expect(queued.baseRevision, isNull,
          reason: '服务端还不知道这个 uuid，带基线反而可能被判成冲突');
      expect(queued.payloadJson, contains('v2'));

      final rows = await db.select(db.treatmentRecords).get();
      expect(rows, hasLength(1), reason: '更新不该产生第二条本地记录');
      expect(rows.single.durationMin, 45);
    });

    test('按患者查询是响应式的：存一条草稿本地立刻能看到', () async {
      final emissions = <int>[];
      final sub = repo.watchLocal('ZY001').listen((r) => emissions.add(r.length));

      await pumpEventQueue();
      expect(emissions.last, 0);

      await repo.saveDraft(
        existingId: null,
        patientNo: 'ZY001', therapistId: 2, recordDate: '2027-03-01',
        sessionPeriod: null, appointmentId: null, durationMin: null, note: null,
        response: PatientResponseDraft(), items: const [], status: 'draft',
      );
      await pumpEventQueue();
      expect(emissions.last, 1);

      await sub.cancel();
    });

    test('表单离线缓存往返', () async {
      // 预置一份缓存，再断网读它。
      await db.into(db.refCache).insertOnConflictUpdate(
            RefCacheCompanion.insert(
              key: 'record_form:ZY001:all',
              payloadJson: jsonEncode(RecordFormData.fromJson(formJson()).toJson()),
              fetchedAt: '2027-03-01T00:00:00Z',
            ),
          );

      final cached = await repo.readCachedForm('ZY001');
      expect(cached, isNotNull);
      expect(cached!.patientName, '张三');
      expect(cached.mainItems.single.subItems.single.params.length, 2);
    });

    test('★ 表单缓存按"反应作用域"分开存（不能互相覆盖）', () async {
      // patient 反应定义是按主项目分组的。不带 main_item_id 与带 1 是**两份不同
      // 内容**的表单，缓存 key 必须区分，否则先取全量再取分组就会互相覆盖，
      // 离线时可能拿到错误作用域的定义 → 提交 422。
      final all = RecordFormData.fromJson(formJson());
      final scoped = RecordFormData.fromJson({
        ...formJson(),
        'response_defs': [
          {'id': 2, 'code': 'pain', 'label': '疼痛', 'value_type': 'number'},
        ],
      });

      await db.into(db.refCache).insertOnConflictUpdate(
            RefCacheCompanion.insert(
              key: 'record_form:ZY001:all',
              payloadJson: jsonEncode(all.toJson()),
              fetchedAt: '2027-03-01T00:00:00Z',
            ),
          );
      await db.into(db.refCache).insertOnConflictUpdate(
            RefCacheCompanion.insert(
              key: 'record_form:ZY001:1',
              payloadJson: jsonEncode(scoped.toJson()),
              fetchedAt: '2027-03-01T00:00:00Z',
            ),
          );

      expect((await repo.readCachedForm('ZY001'))!.responseDefs.length, 2);
      expect(
        (await repo.readCachedForm('ZY001', mainItemId: 1))!.responseDefs.length,
        1,
      );
      // 没缓存过的作用域返回 null，而不是错误地回落到别的 key。
      expect(await repo.readCachedForm('ZY001', mainItemId: 2), isNull);
    });

    test('缓存损坏时返回 null，不炸掉整个页面', () async {
      await db.into(db.refCache).insertOnConflictUpdate(
            RefCacheCompanion.insert(
              key: 'record_form:ZY001',
              payloadJson: '这不是 JSON',
              fetchedAt: '2027-03-01T00:00:00Z',
            ),
          );
      expect(await repo.readCachedForm('ZY001'), isNull);
    });

    test('当天计数（含未推送草稿）', () async {
      await repo.saveDraft(
        existingId: null,
        patientNo: 'ZY001', therapistId: 2, recordDate: '2027-03-01',
        sessionPeriod: 'am', appointmentId: null, durationMin: null, note: null,
        response: PatientResponseDraft(), items: const [], status: 'draft',
      );
      expect(await repo.countForDay(patientNo: 'ZY001', recordDate: '2027-03-01'), 1);
      expect(
        await repo.countForDay(
            patientNo: 'ZY001', recordDate: '2027-03-01', sessionPeriod: 'am'),
        1,
      );
      expect(
        await repo.countForDay(
            patientNo: 'ZY001', recordDate: '2027-03-01', sessionPeriod: 'pm'),
        0,
      );
    });
  });
}
