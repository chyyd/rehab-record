import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:rehab_app/core/api_endpoints.dart';
import 'package:rehab_app/data/remote/timeline_dto.dart';
import 'package:rehab_app/data/repo/timeline_repository.dart';

import 'support.dart';

Map<String, dynamic> timelineJson() => {
      'items': [
        {
          'id': 132,
          'patient_no': 'S5A',
          'patient_name': '阶段五患者甲',
          'therapist_id': 3,
          'therapist_name': '张三',
          'record_date': '2027-07-08',
          'session_period': 'pm',
          'seq_no': 4,
          'status': 'submitted',
          'edit_count': 1,
          'item_count': 2,
          'main_item_names': ['运动功能障碍训练'],
        },
        {
          'id': 131,
          'patient_no': 'S5A',
          'patient_name': '阶段五患者甲',
          'therapist_id': 3,
          'therapist_name': '张三',
          'record_date': '2027-07-05',
          'session_period': 'am',
          'seq_no': null,
          'status': 'draft',
          'item_count': 1,
          'main_item_names': <String>[],
        },
      ],
      'total': 17,
      'page': 1,
      'page_size': 2,
    };

Map<String, dynamic> dateSummaryJson() => {
      'date': '2027-07-08',
      'group_by': 'therapist',
      'totals': {
        'record_count': 5,
        'item_count': 9,
        'total_duration_min': 140,
        'patient_count': 4,
        'main_item_counts': {'运动功能障碍训练': 5, '言语功能障碍训练': 4},
        'sub_item_counts': {'偏瘫肢体综合训练': 3},
        'therapist_counts': {'张三': 3, '李四': 2},
      },
      'groups': [
        {
          'key': '张三',
          'label': '张三',
          'totals': {
            'record_count': 3,
            'item_count': 5,
            'total_duration_min': 80,
            'patient_count': 2,
            'sub_item_counts': {'偏瘫肢体综合训练': 3},
          },
          'patient_nos': ['S5A', 'S2B'],
        },
      ],
    };

Map<String, dynamic> patientDailyJson() => {
      'patient': {
        'inpatient_no': 'S2B',
        'name': '阶段二患者乙',
        'diagnosis': '脑卒中恢复期',
      },
      'date_from': '2027-07-01',
      'date_to': '2027-07-08',
      'totals': {
        'record_count': 2,
        'item_count': 3,
        'total_duration_min': 60,
        'patient_count': 1,
      },
      'days': [
        {
          'record_date': '2027-07-08',
          'session_periods': ['am', 'pm'],
          'therapists': ['张三'],
          'main_items': ['运动功能障碍训练'],
          'sub_items': ['偏瘫肢体综合训练'],
          'params': ['side=左'],
          'responses': ['疼痛=2 分'],
          'notes': ['首次'],
          'duration_min': 45,
          'temporary': true,
        },
      ],
    };

void main() {
  group('时间轴 DTO', () {
    test('解析条目与分页信息', () {
      final page = TimelinePage.fromJson(timelineJson());
      expect(page.total, 17);
      expect(page.items, hasLength(2));
      expect(page.items.first.displayName, '阶段五患者甲');
      expect(page.items.first.mainItemNames, ['运动功能障碍训练']);
      expect(page.items.first.statusLabel, '已提交');
      // 17 条、每页 2 条 → 还有更多。
      expect(page.hasMore, isTrue);
    });

    test('草稿没有序号时不造数据', () {
      final draft = TimelinePage.fromJson(timelineJson()).items[1];
      expect(draft.seqNo, isNull);
      expect(draft.statusLabel, '草稿');
      expect(draft.mainItemNames, isEmpty);
    });

    test('最后一页 hasMore 为 false', () {
      final page = TimelinePage.fromJson({
        ...timelineJson(),
        'total': 2,
      });
      expect(page.hasMore, isFalse);
    });

    test('患者名为空时回落到住院号', () {
      final item = TimelineItem.fromJson({
        'id': 1, 'patient_no': 'X1', 'therapist_id': 1,
        'record_date': '2027-07-08', 'status': 'draft',
      });
      expect(item.displayName, 'X1');
    });
  });

  group('汇总 DTO', () {
    test('按日期汇总：总计与分组', () {
      final s = DateSummary.fromJson(dateSummaryJson());
      expect(s.date, '2027-07-08');
      expect(s.groupBy, 'therapist');
      expect(s.totals.recordCount, 5);
      expect(s.totals.patientCount, 4);
      expect(s.totals.mainItemCounts['运动功能障碍训练'], 5);
      expect(s.groups.single.label, '张三');
      expect(s.groups.single.patientNos, ['S5A', 'S2B']);
    });

    test('时长格式化：分钟/小时/小时+分/零', () {
      SummaryTotals t(int m) =>
          SummaryTotals.fromJson({'total_duration_min': m});
      expect(t(0).durationLabel, '0 分钟');
      expect(t(45).durationLabel, '45 分钟');
      expect(t(60).durationLabel, '1 小时');
      expect(t(140).durationLabel, '2 小时 20 分');
    });

    test('缺失的计数对象不崩（服务端可能省略）', () {
      final t = SummaryTotals.fromJson({'record_count': 1});
      expect(t.mainItemCounts, isEmpty);
      expect(t.therapistCounts, isEmpty);
      expect(t.itemCount, 0);
    });

    test('患者每日汇总：天、半日、临时治疗标记', () {
      final s = PatientDailySummary.fromJson(patientDailyJson());
      expect(s.patient.inpatientNo, 'S2B');
      expect(s.days.single.sessionPeriods, ['am', 'pm']);
      expect(s.days.single.durationMin, 45);
      expect(s.days.single.temporary, isTrue,
          reason: '临时治疗要能识别出来（记录人 ≠ 患者归属人）');
    });
  });

  group('时间轴仓库', () {
    test('查询参数按契约拼装（scope / 分页 / 日期区间）', () async {
      final adapter = ScriptedAdapter({kTimeline: (200, timelineJson())});
      final repo = TimelineRepository(
        client: buildScriptedClient({}, adapter: adapter),
      );

      await repo.fetchTimeline(
        page: 2,
        pageSize: 20,
        scope: 'mine',
        dateFrom: '2027-07-01',
        dateTo: '2027-07-08',
      );

      final q = adapter.seen.single.queryParameters;
      expect(q['page'], 2);
      expect(q['page_size'], 20);
      // 注意：`scope=temp` 已按用户决定删除；现在只有 visible / mine。
      expect(q['scope'], 'mine');
      expect(q['from'], '2027-07-01');
      expect(q['to'], '2027-07-08');
      // 没传主项目就不该带这个参数（服务端按存在与否判断）。
      expect(q.containsKey('main_item_id'), isFalse);
    });

    test('主项目筛选传了就带 main_item_id', () async {
      final adapter = ScriptedAdapter({kTimeline: (200, timelineJson())});
      final repo = TimelineRepository(
        client: buildScriptedClient({}, adapter: adapter),
      );
      await repo.fetchTimeline(mainItemId: 2);
      expect(adapter.seen.single.queryParameters['main_item_id'], 2);
    });

    test('汇总请求带 date 与 group_by', () async {
      final adapter = ScriptedAdapter({kSummaryDate: (200, dateSummaryJson())});
      final repo = TimelineRepository(
        client: buildScriptedClient({}, adapter: adapter),
      );
      await repo.fetchDateSummary(date: '2027-07-08', groupBy: 'patient');
      final q = adapter.seen.single.queryParameters;
      expect(q['date'], '2027-07-08');
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
      final bytes = await client.requestBytes(kPrintSummaryDate, query: {'date': '2027-07-08'});
      expect(bytes, pdf);
      expect(String.fromCharCodes(bytes.take(4)), '%PDF');
      // 日期要带上，否则打出来的是别的日子。
      expect(adapter.seen.single.queryParameters['date'], '2027-07-08');
    });

    test('打印地址拼装（供排查：能直接看到打的是哪一天）', () {
      final repo = TimelineRepository(client: buildScriptedClient({}));
      final url = repo.pdfUrl(kPrintSummaryDate, query: {'date': '2027-07-08'});
      expect(url, 'http://test.local/api/v1/print/summary/date?date=2027-07-08');
    });
  });
}
