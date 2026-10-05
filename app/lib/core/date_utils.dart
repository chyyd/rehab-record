/// 日期工具。
///
/// 与服务端约定一致（`README.md` 常用约定）：**日期用本地墙钟 `YYYY-MM-DD`**，
/// 时刻才用 UTC。排期是"工作日历"语义，所以这里一律按本地日期处理，
/// 不做时区换算 —— 否则西半球时区下会出现"前一天/后一天"的偏移。
library;

/// 格式化成服务端要的 `YYYY-MM-DD`。
String formatDate(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-'
    '${d.month.toString().padLeft(2, '0')}-'
    '${d.day.toString().padLeft(2, '0')}';

/// 解析 `YYYY-MM-DD`（失败返回 null，不抛）。
DateTime? parseDate(String s) => DateTime.tryParse(s);

/// 当天 0 点（去掉时分秒，便于比较）。
DateTime startOfDay(DateTime d) => DateTime(d.year, d.month, d.day);

/// 含 [days] 天的日期列表，从 [from] 开始。
List<DateTime> dateRange(DateTime from, int days) {
  final start = startOfDay(from);
  return List<DateTime>.generate(days, (i) => start.add(Duration(days: i)));
}

/// 该日期所在周的**周一**（科室按自然周排班，周一为一周之始）。
DateTime mondayOf(DateTime d) {
  final day = startOfDay(d);
  // DateTime.weekday: 周一=1 … 周日=7
  return day.subtract(Duration(days: day.weekday - 1));
}

/// 一周 7 天（周一起）。
List<DateTime> weekDays(DateTime anyDayInWeek) => dateRange(mondayOf(anyDayInWeek), 7);

/// 形如 `3/2` 的短日期，供格子表头用。
String shortDate(DateTime d) => '${d.month}/${d.day}';

/// 形如 `周一` 的星期标签。
String weekdayLabel(DateTime d) => switch (d.weekday) {
      1 => '周一',
      2 => '周二',
      3 => '周三',
      4 => '周四',
      5 => '周五',
      6 => '周六',
      _ => '周日',
    };

/// `YYYY-MM-DD` → `M/D`（解析失败时原样返回）。
String shortDateFromIso(String iso) {
  final d = parseDate(iso);
  return d == null ? iso : shortDate(d);
}
