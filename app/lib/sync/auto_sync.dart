// 构造器刻意用「公开参数名 + 私有字段」（`tick` → `_tick`）：调用方看到的是
// 简洁的参数名，内部保持私有。`prefer_initializing_formals` 对这种写法无解
//（`this._tick` 不能作具名参数），故在此文件关闭该规则。
// ignore_for_file: prefer_initializing_formals
import 'dart:async';

import 'package:flutter/widgets.dart';

/// 主动定时同步（2026-10-06）。
///
/// ## 为什么需要它
///
/// 原来的增量同步是**事件驱动**的：登录后、页面返回、下拉刷新、点同步按钮。
/// 缺少"什么都没发生"时的那条路径 —— 而全科共享视图恰恰需要它：
/// 张三给患者 A 记了一条，李四的手机停在患者列表上不动，
/// **他看不到这条新记录**（列表是本地 Drift 流，没人 pull 就不会变）。
///
/// ## 节奏（故意简单，且不引人依赖）
///
/// - 前台每 **30 秒**一次；
/// - 失败后**退避** 30 → 60 → 120 秒（上限 120），成功立刻回到 30 秒。
///   退避是必须的：离线时 30 秒硬打会导致整场治疗都在重试，
///   而治疗师在床旁本来就常常没有信号；
/// - 只在前台跑：一进后台就停表（后台网络在国产 ROM 上会被杀，
///   与其留着一条"看起来在同步"的死表，不如明确停掉）。
///
/// 刻意**不引入 `connectivity_plus` / `workmanager`**：
///  - 前者只告诉你"有网"，不告诉你"服务器可达"（医院内网里常见有 WiFi 但连不上后端）；
/// 真正可用性的判据是"请求成功"，而那正是退避逻辑在做的事；
///  - 后者的后台执行在国产 ROM 上不可靠，还要处理权限与白名单。
///
/// 界面上每次成功/失败都会更新顶部的同步条（由 `PatientSyncController` 负责），
/// 所以这不是"偷偷跑的网络请求"。
class AutoSync with WidgetsBindingObserver {
  AutoSync({
    required Future<bool> Function() tick,
    Duration interval = const Duration(seconds: 30),
    Duration maxBackoff = const Duration(seconds: 120),
  })  : _tick = tick,
        _interval = interval,
        _maxBackoff = maxBackoff;

  /// 执行一次同步，返回是否成功（决定要不要退避）。
  final Future<bool> Function() _tick;

  final Duration _interval;
  final Duration _maxBackoff;

  Timer? _timer;
  bool _started = false;
  bool _paused = false;

  /// 连续失败次数（成功后归零）。
  int _failures = 0;

  /// 当前间隔（按连续失败次数退避）。
  Duration get currentInterval =>
      backoffInterval(_interval, _failures, maxBackoff: _maxBackoff);

  /// 开始调度。**幂等**（重复调用不会叠出多条定时器）。
  void start() {
    if (_started) return;
    _started = true;
    WidgetsBinding.instance.addObserver(this);
    _schedule();
  }

  void stop() {
    _started = false;
    _timer?.cancel();
    _timer = null;
    WidgetsBinding.instance.removeObserver(this);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (!_started) return;
    if (state == AppLifecycleState.resumed) {
      _paused = false;
      // 回到前台**立刻**同步一次，而不是等下一个 30 秒 ——
      // "切出去看了一眼微信再回来"是最常见的场景，此时数据很可能已经旧了。
      _fire();
    } else if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.inactive ||
        state == AppLifecycleState.detached) {
      _paused = true;
      _timer?.cancel();
      _timer = null;
    }
  }

  void _schedule() {
    _timer?.cancel();
    if (!_started || _paused) return;
    _timer = Timer(currentInterval, _fire);
  }

  Future<void> _fire() async {
    if (!_started) return;
    final ok = await _tick();
    _failures = ok ? 0 : _failures + 1;
    _schedule(); // 下一轮（间隔按成败重算）
  }
}

/// 退避间隔：`base × 2^failures`，上限 [maxBackoff]；`failures == 0` 时就是 [base]。
///
/// 抽成纯函数是为了**能测**：`AutoSync` 内部靠真定时器，
/// 在单测里等 30 秒不现实。退避策略本身是这个功能里最该被钉住的部分
///（算错会变成"离线时疯狂重试"或"再也不重试"）。
Duration backoffInterval(
  Duration base,
  int failures, {
  Duration maxBackoff = const Duration(seconds: 120),
}) {
  if (failures <= 0) return base;
  // 左移位数封顶，避免 failures 很大时把整数撑爆（<< 31 以上在 Dart 里会溢出到负）。
  final shift = failures > 3 ? 3 : failures;
  final seconds = base.inSeconds * (1 << shift);
  return seconds > maxBackoff.inSeconds
      ? maxBackoff
      : Duration(seconds: seconds);
}
