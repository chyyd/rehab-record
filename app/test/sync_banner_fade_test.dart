import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rehab_app/features/home/home_shell.dart';

/// 顶部提示条的**自动渐隐**（2026-10-06）。
///
/// 用户原话：「显示"已更新X名患者"后，2 秒后渐隐」。
///
/// 抽成独立 widget 就是为了能这样测：渐隐靠定时器 + 动画，
/// 混在业务页面里只能靠肉眼看。
void main() {
  group('FadeOutAfter', () {
    testWidgets('★ 停留 2 秒后渐隐，并在淡出结束后回调', (tester) async {
      var faded = false;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: FadeOutAfter(
              duration: const Duration(seconds: 2),
              onFaded: () => faded = true,
              child: const Text('已更新 6 名患者'),
            ),
          ),
        ),
      );

      // 立刻可见、且还没回调
      expect(find.text('已更新 6 名患者'), findsOneWidget);
      expect(faded, isFalse, reason: '2 秒内不该消失');

      // 1.9 秒：仍在
      await tester.pump(const Duration(milliseconds: 1900));
      expect(faded, isFalse);

      // 过 2 秒：开始渐隐（透明度开始降），但回调要等动画跑完
      await tester.pump(const Duration(milliseconds: 200));
      final opacity = tester.widget<AnimatedOpacity>(find.byType(AnimatedOpacity));
      expect(opacity.opacity, 0, reason: '2 秒后应开始渐隐（目标透明度 0）');

      // 等淡出动画 + 回调
      await tester.pump(const Duration(milliseconds: 400));
      await tester.pumpAndSettle();
      expect(faded, isTrue, reason: '淡出结束后要回调，让上层把横幅真正移除');
    });

    testWidgets('duration 为零时**常驻**，不渐隐也不回调', (tester) async {
      var faded = false;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: FadeOutAfter(
              duration: Duration.zero,
              onFaded: () => faded = true,
              child: const Text('有 2 条改动冲突待处理'),
            ),
          ),
        ),
      );

      expect(find.byType(AnimatedOpacity), findsNothing,
          reason: '常驻模式下不该包动画（白包一层还可能有额外重建）');

      // 等一段时间，确认它不会自己消失 —— 冲突要留到人处理
      await tester.pump(const Duration(seconds: 5));
      expect(find.text('有 2 条改动冲突待处理'), findsOneWidget);
      expect(faded, isFalse);
    });

    testWidgets('dispose 时取消定时器（不能对已卸载的 widget 回调）', (tester) async {
      var faded = false;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: FadeOutAfter(
              duration: const Duration(seconds: 2),
              onFaded: () => faded = true,
              child: const Text('临时横幅'),
            ),
          ),
        ),
      );

      // 在计时器触发前把整棵树换掉
      await tester.pumpWidget(const MaterialApp(home: Scaffold(body: SizedBox())));
      await tester.pump(const Duration(seconds: 5));

      expect(faded, isFalse,
          reason: 'widget 已销毁就不该再回调 —— 否则上层会对着空状态做操作');
    });

    testWidgets('连续两条新提示：各自重新计时（靠 key 换新实例）', (tester) async {
      var firstFaded = false;
      var secondFaded = false;

      Widget build(int seq) => MaterialApp(
            home: Scaffold(
              body: seq == 1
                  ? FadeOutAfter(
                      key: const ValueKey(1),
                      duration: const Duration(seconds: 2),
                      onFaded: () => firstFaded = true,
                      child: const Text('已更新 4 名患者'),
                    )
                  : FadeOutAfter(
                      key: const ValueKey(2),
                      duration: const Duration(seconds: 2),
                      onFaded: () => secondFaded = true,
                      child: const Text('已更新 6 名患者'),
                    ),
            ),
          );

      await tester.pumpWidget(build(1));
      await tester.pump(const Duration(milliseconds: 1500));

      // 第一条还没淡完，就来了第二条（文案可能相同，靠 seq 区分）
      await tester.pumpWidget(build(2));
      await tester.pump(const Duration(milliseconds: 1000));
      expect(secondFaded, isFalse,
          reason: '★ 新提示要从头计时 2 秒，不能沿用上一条的剩余时间');
      // 被换掉的那条不该再回调：它的 State 已经销毁了。
      expect(firstFaded, isFalse,
          reason: '第一条已被替换，不该再回调（否则上层会清掉新提示）');

      await tester.pump(const Duration(milliseconds: 1400));
      await tester.pumpAndSettle();
      expect(secondFaded, isTrue);
    });
  });
}
