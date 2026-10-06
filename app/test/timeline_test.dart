import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rehab_app/core/api_endpoints.dart';
import 'package:rehab_app/core/date_utils.dart';
import 'package:rehab_app/data/remote/timeline_dto.dart';
import 'package:rehab_app/data/repo/timeline_repository.dart';
import 'package:rehab_app/features/timeline/timeline_providers.dart';

import 'support.dart';

/// 时间轴与汇总的响应（**SOAP 纯文本口径**）。
///
/// 记录内容不再是"主项目 / 子项目 / 参数 / 患者反应"表格，而是服务端冻结的
/// `rendered_text`；汇总的 `item_count` / `total_duration_min` /
/// `main_item_counts` 也换成了 `record_count` / `patient_count` /
/// `therapist_counts` / `discipline_counts`。
Map<String, dynamic> timelineJson() => {
      'items': [
        {
          'id': 132,
          'patient_no': 'S5A',
          'patient_name': '阶段五患者甲',
          'therapist_id': 3,
          'therapist_name': '张三',
          'record_date': '2026-10-06',
          'discipline': 'PT',
          'discipline_name': '运动',
          'kind': 'daily',
          'kind_label': '日常治疗记录',
          'seq_no': 4,
          'status': 'submitted',
          'edit_count': 1,
          'rendered_text': '康复治疗记录（PT运动）\n治疗日期：2026-10-06   第 4 次\n\n'
              '主观资料：精神状态：良好；主诉：乏力\n\n客观资料：本次训练项目：偏瘫肢体综合训练',
          'rendered_excerpt': '主观资料：精神状态：良好；主诉：乏力',
        },
        {
          'id': 131,
          'patient_no': 'S5A',
          'patient_name': '阶段五患者甲',
          'therapist_id': 3,
          'therapist_name': '张三',
          'record_date': '2026-10-05',
          'discipline': 'PT',
          'discipline_name': '运动',
          'kind': 'initial',
          'kind_label': '首评',
          'seq_no': null,
          'status': 'draft',
          'rendered_text': '康复初始评定（PT运动）\n治疗日期：2026-10-05\n\n主观资料：自觉症状：肢体无力',
        },
      ],
      'total': 17,
      'page': 1,
      'page_size': 2,
    };

Map<String, dynamic> dateSummaryJson() => {
      'date': '2026-10-06',
      'group_by': 'therapist',
      'totals': {
        'record_count': 5,
        'patient_count': 4,
        'therapist_counts': {'张三': 3, '李四': 2},
        'discipline_counts': {'运动': 4, '吞咽': 1},
      },
      'groups': [
        {
          'key': '张三',
          'totals': {
            'record_count': 3,
            'patient_count': 2,
            'discipline_counts': {'运动': 3},
          },
          'rows': [
            {
              'record_id': 132,
              'record_date': '2026-10-06',
              'patient_no': 'S5A',
              'patient_name': '阶段五患者甲',
              'therapist_name': '张三',
              'discipline': 'PT',
              'discipline_name': '运动',
              'kind': 'daily',
              'kind_label': '日常治疗记录',
              'seq_no': 4,
              'status': 'submitted',
              'rendered_text': '康复治疗记录（PT运动）\n\n主观资料：精神状态：良好',
            },
          ],
        },
      ],
    };

Map<String, dynamic> patientDailyJson() => {
      'patient': {
        'inpatient_no': 'S2B',
        'name': '阶段二患者乙',
        'diagnosis': '脑卒中恢复期',
        'status': 'in_hospital',
      },
      'date_from': '2026-10-01',
      'date_to': '2026-10-06',
      'totals': {
        'record_count': 2,
        'patient_count': 1,
        'discipline_counts': {'运动': 2},
      },
      'days': [
        {
          'record_date': '2026-10-06',
          'record_count': 1,
          'therapists': ['张三'],
          'disciplines': ['运动', '言语'],
          'temporary': true,
          'records': [
            {
              'record_id': 132,
              'record_date': '2026-10-06',
              'discipline': 'PT',
              'discipline_name': '运动',
              'kind': 'initial',
              'kind_label': '首评',
              'status': 'submitted',
              'therapist_name': '张三',
              'is_temporary': 1,
              'rendered_text': '康复初始评定（PT运动）\n\n主观资料：自觉症状：肢体无力',
            },
          ],
          'texts': ['康复初始评定（PT运动）\n\n主观资料：自觉症状：肢体无力'],
        },
      ],
    };

void main() {
  group('时间轴 DTO', () {
    test('解析条目与分页信息（含大类与形态）', () {
      final page = TimelinePageData.fromJson(timelineJson());
      expect(page.total, 17);
      expect(page.items, hasLength(2));
      expect(page.items.first.displayName, '阶段五患者甲');
      expect(page.items.first.disciplineName, '运动');
      expect(page.items.first.kindLabel, '日常治疗记录');
      expect(page.items.first.statusLabel, '已提交');
      // ★ 内容是 SOAP 文本，不再是"N 项"。
      expect(page.items.first.renderedExcerpt, contains('主观资料'));
      expect(page.items.first.line, contains('精神状态'));
      // 17 条、每页 2 条 → 还有更多。
      expect(page.hasMore, isTrue);
    });

    test('评估文书没有序号时不造数据', () {
      final initial = TimelinePageData.fromJson(timelineJson()).items[1];
      expect(initial.seqNo, isNull);
      expect(initial.kind, 'initial');
      expect(initial.statusLabel, '草稿');
      // 没有 rendered_excerpt 时从 rendered_text 里截第一段正文。
      expect(initial.line, contains('自觉症状'));
    });

    test('最后一页 hasMore 为 false', () {
      final page = TimelinePageData.fromJson({
        ...timelineJson(),
        'total': 2,
      });
      expect(page.hasMore, isFalse);
    });

    test('患者名为空时回落到住院号', () {
      final item = TimelineItem.fromJson({
        'id': 1, 'patient_no': 'X1', 'therapist_id': 1,
        'record_date': '2026-10-06', 'status': 'draft',
      });
      expect(item.displayName, 'X1');
      expect(item.line, isEmpty);
    });
  });

  group('汇总 DTO（SOAP 文本口径）', () {
    test('按日期汇总：总计、分组、逐条文书', () {
      final s = DateSummary.fromJson(dateSummaryJson());
      expect(s.date, '2026-10-06');
      expect(s.groupBy, 'therapist');
      expect(s.totals.recordCount, 5);
      expect(s.totals.patientCount, 4);
      // ★ 口径换成大类分布（主项目/子项目计数已随字典树删除）。
      expect(s.totals.disciplineCounts['运动'], 4);
      expect(s.totals.therapistCounts['李四'], 2);
      expect(s.groups.single.label, '张三');
      expect(s.groups.single.rows.single.renderedText, contains('主观资料'));
    });

    test('缺失的计数对象不崩（服务端可能省略）', () {
      final t = SummaryTotals.fromJson({'record_count': 1});
      expect(t.disciplineCounts, isEmpty);
      expect(t.therapistCounts, isEmpty);
      expect(t.patientCount, 0);
    });

    test('患者每日汇总：天、大类、临时治疗标记、SOAP 文本', () {
      final s = PatientDailySummary.fromJson(patientDailyJson());
      expect(s.patient.inpatientNo, 'S2B');
      expect(s.patient.status, 'in_hospital');
      expect(s.days.single.disciplines, ['运动', '言语']);
      expect(s.days.single.recordCount, 1);
      expect(s.days.single.temporary, isTrue,
          reason: '临时治疗要能识别出来（记录人 ≠ 患者归属人）');
      expect(s.days.single.records.single.isTemporary, isTrue);
      expect(s.days.single.texts.single, contains('康复初始评定'));
    });
  });

  group('时间轴仓库', () {
    test('查询参数按契约拼装（scope / 分页 / 日期 / 大类 / 形态）', () async {
      final adapter = ScriptedAdapter({kTimeline: (200, timelineJson())});
      final repo = TimelineRepository(
        client: buildScriptedClient({}, adapter: adapter),
      );

      await repo.fetchTimeline(
        page: 2,
        pageSize: 20,
        scope: 'mine',
        dateFrom: '2026-10-01',
        dateTo: '2026-10-06',
        discipline: 'PT',
        kind: 'daily',
      );

      final q = adapter.seen.single.queryParameters;
      expect(q['page'], 2);
      expect(q['page_size'], 20);
      // 注意：`scope=temp` 已按用户决定删除；现在只有 visible / mine。
      expect(q['scope'], 'mine');
      expect(q['from'], '2026-10-01');
      expect(q['to'], '2026-10-06');
      expect(q['discipline'], 'PT');
      expect(q['kind'], 'daily');
      // 旧的主项目筛选参数已随字典树删除，不该再出现。
      expect(q.containsKey('main_item_id'), isFalse);
    });

    test('没传大类/形态就不带这两个参数（服务端按存在与否判断）', () async {
      final adapter = ScriptedAdapter({kTimeline: (200, timelineJson())});
      final repo = TimelineRepository(
        client: buildScriptedClient({}, adapter: adapter),
      );
      await repo.fetchTimeline();
      final q = adapter.seen.single.queryParameters;
      expect(q.containsKey('discipline'), isFalse);
      expect(q.containsKey('kind'), isFalse);
    });

    test('汇总请求带 date 与 group_by', () async {
      final adapter = ScriptedAdapter({kSummaryDate: (200, dateSummaryJson())});
      final repo = TimelineRepository(
        client: buildScriptedClient({}, adapter: adapter),
      );
      await repo.fetchDateSummary(date: '2026-10-06', groupBy: 'patient');
      final q = adapter.seen.single.queryParameters;
      expect(q['date'], '2026-10-06');
      expect(q['group_by'], 'patient');
    });

    test('患者每日汇总走 /summary/patient/{no}', () async {
      final adapter = ScriptedAdapter({
        kSummaryPatient('S2B'): (200, patientDailyJson()),
      });
      final repo = TimelineRepository(
        client: buildScriptedClient({}, adapter: adapter),
      );
      final s = await repo.fetchPatientDaily('S2B');
      expect(s.patient.name, '阶段二患者乙');
      expect(adapter.seen.single.path, '/api/v1/summary/patient/S2B');
    });

    test('★ PDF 必须按字节取回（走 JSON 解析会把字节变成 "[37,80,68,70]"）', () async {
      // 真实 PDF 头：%PDF
      final pdf = utf8.encode('%PDF-1.4 fake').toList();
      final adapter = ScriptedAdapter(
        {},
        binaryResponses: {kPrintSummaryDate: (200, pdf)},
      );
      final client = buildScriptedClient({}, adapter: adapter);
      final bytes = await client.requestBytes(kPrintSummaryDate, query: {'date': '2026-10-06'});
      expect(bytes, pdf);
      expect(String.fromCharCodes(bytes.take(4)), '%PDF');
      // 日期要带上，否则打出来的是别的日子。
      expect(adapter.seen.single.queryParameters['date'], '2026-10-06');
    });

    test('打印地址拼装（供排查：能直接看到打的是哪一天）', () {
      final repo = TimelineRepository(client: buildScriptedClient({}));
      final url = repo.pdfUrl(kPrintSummaryDate, query: {'date': '2026-10-06'});
      expect(url, 'http://test.local/api/v1/print/summary/date?date=2026-10-06');
    });
  });

  group('时间轴默认筛选（2026-10-06 用户要求只显示今日）', () {
    /// 用户原话：「时间轴页面现在显示全部记录，太多了，仅显示今日的就行」。
    ///
    /// 所以默认必须是 `from == to == 今天`，而不是"全部"（两个都为 null）。
    /// 这条测试同时守住"默认不是全部"和"区间=单独一天"两件事。
    test('★ 默认筛选是今天（不是全部）', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);

      final filter = container.read(timelineFilterProvider);
      final today = formatDate(DateTime.now());

      expect(filter.dateFrom, today, reason: '默认应从今天开始');
      expect(filter.dateTo, today, reason: '默认应到今天为止');
      expect(
        filter.hasDateRange,
        isTrue,
        reason: '默认必须带日期区间 —— 不带就是"显示全部"，正是用户要去掉的',
      );
    });

    test('「重置全部」回到默认（今天），不是清成全部', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);

      final controller = container.read(timelineFilterProvider.notifier);
      controller.setDateRange(DateTime(2026, 1, 1), DateTime(2026, 1, 7));
      controller.setDiscipline('PT');
      expect(container.read(timelineFilterProvider).dateFrom, '2026-01-01');

      controller.reset();

      final after = container.read(timelineFilterProvider);
      final today = formatDate(DateTime.now());
      expect(after.dateFrom, today, reason: '重置后应与刚打开时一致');
      expect(after.dateTo, today);
      expect(after.discipline, isNull, reason: '其它筛选维度仍要清空');
    });

    test('用户仍可清掉区间看全部（只改默认值，没拿掉能力）', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);

      container.read(timelineFilterProvider.notifier).clearDateRange();
      final filter = container.read(timelineFilterProvider);
      expect(filter.hasDateRange, isFalse);
      expect(filter.dateFrom, isNull);
      expect(filter.dateTo, isNull);
    });
  });
}
