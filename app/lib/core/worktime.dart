/// 半日制作息的客户端常量（Q11 定稿）。
///
/// **唯一真源在服务端** `backend/app/core/worktime.py`；App 侧只作展示兜底，
/// 启动后应以 `GET /api/v1/schedule/periods` 或健康检查返回的 `worktime` 覆盖，
/// 不要在业务逻辑里硬编码这几个数字来判断"能不能排"。
library;

/// 上午区间（含边界）。
const String kMorningStart = '06:00';
const String kMorningEnd = '11:30';

/// 下午区间（含边界）。
const String kAfternoonStart = '13:00';
const String kAfternoonEnd = '17:30';

/// 半日代码 → 中文显示名。
const Map<String, String> kPeriodLabels = <String, String>{
  'am': '上午',
  'pm': '下午',
};

/// 半日代码（排期只能取这两个；`full` 是请假专用）。
const List<String> kPeriods = <String>['am', 'pm'];

/// 把半日代码翻译成中文；未知值原样返回。
String periodLabel(String period) => kPeriodLabels[period] ?? period;
