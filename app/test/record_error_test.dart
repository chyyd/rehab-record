import 'package:flutter_test/flutter_test.dart';
import 'package:rehab_app/core/error.dart';
// 错误文案的规则表在 `record_failure.dart`（纯函数，不依赖 Flutter/Riverpod），
// `record_providers.dart` 把它转出来，所以这里 import 一个就够。
import 'package:rehab_app/features/records/record_providers.dart';
import 'package:rehab_app/sync/sync_engine.dart';

/// 保存失败的四类原因**必须分别说清楚**（治疗师要能照着提示做下一步）。
///
/// 服务端的错误体（`backend/app/core/errors.py`）：
/// ```json
/// {"code": "...", "message": "...", "details": {...}}
/// ```
/// 所以这里测的是"details 怎么变成界面上的话"，纯函数，不需要网络与数据库。
void main() {
  group('422 必填缺失（details.missing 是中文标签）', () {
    test('标签原样标回字段，并说清"已存在本地"', () {
      final failure = explainRecordError(const AppError(
        code: 'INVALID',
        message: '必填项缺失',
        httpStatus: 422,
        details: {
          'missing': ['本次训练项目'],
          'discipline': 'PT',
          'kind': 'daily',
        },
      ));

      expect(failure.missingLabels, {'本次训练项目'});
      expect(failure.message, contains('本次训练项目'));
      expect(failure.message, contains('已存在本地'));
      expect(failure.reloadForm, isFalse);
    });

    test('多個缺失项都标出来', () {
      final failure = explainRecordError(const AppError(
        code: 'INVALID',
        message: '必填项缺失',
        httpStatus: 422,
        details: {
          'missing': ['本次训练项目', '精神状态'],
        },
      ));
      expect(failure.missingLabels, {'本次训练项目', '精神状态'});
      expect(failure.message, contains('本次训练项目、精神状态'));
    });
  });

  group('409 缺评估文书（评估文书不能跳过）', () {
    test('缺首评 → 说明原因，并要求重新取表单（服务端会把 kind 换成首评）', () {
      final failure = explainRecordError(const AppError(
        code: 'MISSING_ASSESSMENT',
        message: '第 1 次日常记录前必须先完成首评',
        httpStatus: 409,
        details: {
          'missing_document': 'initial',
          'missing_document_label': '首评',
          'next_seq': 1,
        },
      ));
      expect(failure.reloadForm, isTrue, reason: '切到那份文书只差一次重新取表单');
      expect(failure.message, contains('首评'));
      expect(failure.message, contains('不能跳过'));
      expect(failure.missingLabels, isEmpty);
    });

    test('缺复评 → 同样要求切过去', () {
      final failure = explainRecordError(const AppError(
        code: 'MISSING_ASSESSMENT',
        message: '第 21 次日常记录前必须先完成阶段性复评',
        httpStatus: 409,
        details: {'missing_document': 'reassessment'},
      ));
      expect(failure.reloadForm, isTrue);
      expect(failure.message, contains('reassessment'),
          reason: '服务端没给 label 时退回 kind 原文，不编造中文');
    });
  });

  group('409 其它业务规则', () {
    test('同一天同一大类超过 2 条 → details.limit', () {
      final failure = explainRecordError(const AppError(
        code: 'CONFLICT',
        message: '同一天同一大类至多 2 条记录',
        httpStatus: 409,
        details: {'limit': 2, 'date': '2026-10-06', 'discipline': 'PT'},
      ));
      expect(failure.message, contains('至多 2 条'));
      expect(failure.message, contains('已存在本地'));
      expect(failure.reloadForm, isFalse);
    });

    test('患者待出院 → 明确说不能再记', () {
      final failure = explainRecordError(const AppError(
        code: 'PATIENT_PENDING_DISCHARGE',
        message: '该患者已提交出院小结，处于待出院状态，不能再记新记录',
        httpStatus: 409,
        details: {'inpatient_no': 'ZY001', 'status': 'pending_discharge'},
      ));
      expect(failure.message, contains('待出院'));
      expect(failure.message, contains('不能再记'));
    });

    test('该区间已有评估文书 → 刷新表单，不重复填', () {
      final failure = explainRecordError(const AppError(
        code: 'ASSESSMENT_ALREADY_EXISTS',
        message: '该区间（第 1 次日常）已有首评',
        httpStatus: 409,
        details: {'kind': 'initial', 'span_seq': 1, 'record_id': 9},
      ));
      expect(failure.reloadForm, isTrue);
      expect(failure.message, contains('无需重复'));
    });
  });

  group('离线不是错误', () {
    test('NETWORK_ERROR → 已存本地，联网自动上传', () {
      final failure = explainRecordError(
        AppError.network('无法连接服务器'),
      );
      expect(failure.message, contains('已存入本地'));
      expect(failure.missingLabels, isEmpty);
      expect(failure.reloadForm, isFalse);
    });

    test('其它未知错误原样显示服务端文案（不吞掉信息）', () {
      final failure = explainRecordError(const AppError(
        code: 'SOMETHING_NEW',
        message: '服务端新加的原因',
        httpStatus: 500,
      ));
      expect(failure.message, '服务端新加的原因');
    });
  });

  group('出院流程：从推送结果里取"这份小结的服务端 id"', () {
    test('applied 里按 client_uuid 找到 entity_id', () {
      final report = PushReport(
        applied: [
          const PushResultItem(
            outcome: PushOutcome.applied,
            clientUuid: 'uuid-a',
            entity: 'treatment_record',
            entityId: 41,
            revision: 2,
          ),
        ],
        skipped: const [],
        conflicts: const [],
        cursor: 7,
      );
      expect(serverIdFor(report, 'uuid-a'), 41);
      expect(serverIdFor(report, 'uuid-b'), isNull,
          reason: '没推上去就没有服务端 id —— 出院接口要等联网后再调');
    });

    test('entity_id 是字符串时也能解析（服务端 JSON 可能给字符串）', () {
      final report = PushReport(
        applied: [
          const PushResultItem(
            outcome: PushOutcome.applied,
            clientUuid: 'uuid-c',
            entity: 'treatment_record',
            entityId: '42',
          ),
        ],
        skipped: const [],
        conflicts: const [],
        cursor: 7,
      );
      expect(serverIdFor(report, 'uuid-c'), 42);
    });
  });
}
