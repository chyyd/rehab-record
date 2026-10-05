/// 保存失败 → 界面提示的**纯函数**映射。
///
/// 单独一个文件（不 import Flutter / Riverpod）有两个好处：
///  1. 它可以脱离 Flutter 引擎在 Dart VM 里直接跑测试；
///  2. "服务端错误怎么变成人话"是一份**规则表**，和状态管理混在一起会越写越乱。
///
/// 四类原因必须分别说清楚（否则治疗师只知道"保存失败"）：
///  - **422 必填缺失**：`details.missing` 是**中文标签** → 标回对应字段；
///  - **409 缺评估文书**：`details.missing_document`（首评/复评）→ 说明原因并切过去；
///  - **409 当天条数超限**：`details.limit`；
///  - **409 患者待出院**：`PATIENT_PENDING_DISCHARGE`。
///
/// 离线（`NETWORK_ERROR`）**不算失败**：内容已落在本地队列，联网会自动上传。
library;

import 'package:rehab_app/core/error.dart';

/// 一次保存失败的**呈现方式**。
class RecordSaveFailure {
  const RecordSaveFailure({
    required this.message,
    this.missingLabels = const <String>{},
    this.reloadForm = false,
  });

  /// 给治疗师看的话。
  final String message;

  /// 要标在字段上的中文标签（服务端 422 的 `details.missing`）。
  final Set<String> missingLabels;

  /// 是否要立刻重新取表单：缺评估文书时服务端会把 `kind` 直接换成那份文书，
  /// 重新取一次界面就切过去了（省掉"退出去再点进来"）。
  final bool reloadForm;
}

/// 把服务端的失败翻成可操作的提示。
RecordSaveFailure explainRecordError(AppError e) {
  final details = e.details ?? const <String, dynamic>{};
  final missing = (details['missing'] as List?)?.map((m) => '$m').toList();
  final missingDocument = details['missing_document'];
  final limit = details['limit'];

  if (missing != null && missing.isNotEmpty) {
    return RecordSaveFailure(
      message: '还有必填项没填：${missing.join('、')}（已存在本地，改完再提交）',
      missingLabels: missing.toSet(),
    );
  }
  if (missingDocument != null) {
    final label = '${details['missing_document_label'] ?? missingDocument}';
    return RecordSaveFailure(
      message: '本次需先完成「$label」：评估文书不能跳过。'
          '已为你切到那份文书，填完保存后再回来记当天的日常治疗。',
      reloadForm: true,
    );
  }
  if (limit != null) {
    return RecordSaveFailure(
      message: '同一天同一大类至多 $limit 条记录（这条已存在本地，可以删掉或改天再记）',
    );
  }
  if (e.code == 'PATIENT_PENDING_DISCHARGE') {
    return const RecordSaveFailure(
      message: '该患者已提交出院小结（待出院），不能再记新记录',
    );
  }
  if (e.code == 'ASSESSMENT_ALREADY_EXISTS') {
    return const RecordSaveFailure(
      message: '该区间已经有这份评估文书了，无需重复填写（表单已刷新）',
      reloadForm: true,
    );
  }
  if (e.code == 'NETWORK_ERROR') {
    // 离线不是错误：本地已存下，联网后自动上传。
    return RecordSaveFailure(message: '已存入本地，联网后自动上传');
  }
  return RecordSaveFailure(message: e.message);
}
