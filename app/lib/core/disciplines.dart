/// 康复四大类（与服务端 `templates/disciplines.json` 对齐）。
///
/// ★ **唯一真源在服务端模板文件**（用户要求「模板不进数据库，方便手改」），
/// App 这里只放一份**离线兜底**：详情页要能在完全没有网络、也没缓存过表单时
/// 仍然把四个大类按钮画出来。真正的名称与次数来自
/// `GET /records/form`（返回 `discipline_name` / `total_daily` /
/// `days_until_reassessment`），显示时以服务端为准。
library;

/// 一个大类：`key` 是接口参数，`name` 是中文显示名。
class Discipline {
  const Discipline(this.key, this.name);

  final String key;
  final String name;

  /// 顺序与服务端 `order` 一致：运动 / 生活技能 / 吞咽 / 言语。
  static const List<Discipline> all = [
    Discipline('PT', '运动'),
    Discipline('OT', '生活技能'),
    Discipline('ST_SW', '吞咽'),
    Discipline('ST_SP', '言语'),
  ];

  /// 按 key 取中文名（未知 key 原样返回，不编造）。
  static String nameOf(String key) =>
      all.firstWhere((d) => d.key == key, orElse: () => Discipline(key, key)).name;
}
