import 'package:flutter_test/flutter_test.dart';
import 'package:rehab_app/sync/auto_sync.dart';

/// 主动定时同步的**退避策略**（2026-10-06）。
///
/// 抽出来单测的原因：`AutoSync` 内部靠真定时器，单测里等 30 秒不现实，
/// 而退避算错的两个方向都很糟 ——
///   · 算小了：离线时每 30 秒硬打一次，整场治疗都在重试（费电、费流量）；
///   · 算大了/不收敛：恢复联网后迟迟不同步，用户以为数据是最新的。
void main() {
  // `AutoSync.start()` 会 `WidgetsBinding.instance.addObserver` ——
  // 纯 `test()` 里没有 Flutter 绑定，不初始化会抛
  // "Binding has not yet been initialized"。
  TestWidgetsFlutterBinding.ensureInitialized();

  const base = Duration(seconds: 30);

  group('退避间隔', () {
    test('没失败时就是基础间隔（30 秒）', () {
      expect(backoffInterval(base, 0), const Duration(seconds: 30));
      expect(backoffInterval(base, -1), const Duration(seconds: 30),
          reason: '负数按"没失败"处理，不该算出奇怪的间隔');
    });

    test('失败后逐次翻倍', () {
      expect(backoffInterval(base, 1), const Duration(seconds: 60));
      expect(backoffInterval(base, 2), const Duration(seconds: 120));
    });

    test('封顶在 maxBackoff，不会无限增长', () {
      expect(backoffInterval(base, 3), const Duration(seconds: 120),
          reason: '30x8=240 已超上限 120，应被截到 120');
      expect(backoffInterval(base, 99), const Duration(seconds: 120));
    });

    test('失败次数很大时不会整数溢出成负间隔', () {
      // `1 << 40` 在 Dart 里会溢出；不封顶移位就会得到负数或 0，
      // 表现为"定时器立刻连续触发"——比不退避还糟。
      final result = backoffInterval(base, 1000);
      expect(result.inSeconds, greaterThan(0));
      expect(result, const Duration(seconds: 120));
    });

    test('自定义上限生效', () {
      expect(
        backoffInterval(base, 2, maxBackoff: const Duration(seconds: 45)),
        const Duration(seconds: 45),
      );
    });
  });

  group('调度器本身', () {
    test('start 幂等：重复 start 不会叠出多余请求', () async {
      var calls = 0;
      final autoSync = AutoSync(
        // 间隔给很大，确保测试期间不会真的触发定时器。
        interval: const Duration(hours: 1),
        tick: () async {
          calls += 1;
          return true;
        },
      );
      addTearDown(autoSync.stop);

      autoSync.start();
      autoSync.start();
      autoSync.start();
      await Future<void>.delayed(const Duration(milliseconds: 50));

      expect(calls, 0, reason: '启动本身不该立刻同步，也不该因为多次 start 而叠加');
      expect(autoSync.currentInterval, const Duration(hours: 1));
    });

    test('stop 之后可以重复调用（不该抛）', () {
      final autoSync = AutoSync(
        interval: const Duration(hours: 1),
        tick: () async => true,
      );
      autoSync.start();
      autoSync.stop();
      autoSync.stop();
      expect(autoSync.currentInterval, const Duration(hours: 1));
    });
  });
}
