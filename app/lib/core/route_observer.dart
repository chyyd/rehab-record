import 'package:flutter/widgets.dart';

/// 全局路由观察者：让页面知道"我又回到前台了"。
///
/// ## 为什么需要它
///
/// 用户 2026-10-05：「每次返回患者页自动刷新」。
///
/// 患者列表与患者详情的内容**本来是本地库里的镜像**，靠 `refreshFromServer()`
/// 全量拉取更新。而 App 只在两个时机刷新：进列表页（`initState`）与下拉刷新。
/// 于是从记录页 / 出院流程返回时，页面上显示的还是**进入子页面之前**的快照 ——
/// 最典型的是刚把患者置为「待出院」，退回列表却还看到他在院。
///
/// `RouteObserver` + `RouteAware.didPopNext()` 是 Flutter 里做这件事的标准做法：
/// 子路由被 pop、本页重新可见时回调，我们就在那里刷一次。
///
/// ## 为什么不用 `initState` 里的刷新
///
/// `initState` 只在**第一次**创建时跑；`Navigator.push` 到子页再 pop 回来时，
/// 本页的 `State` 一直在树上（没被销毁），所以不会重跑。这正是原来漏掉的那一环。
///
/// 注册方式：`MaterialApp.navigatorObservers: [appRouteObserver]`；
/// 页面里 `with RouteAware` 并在 `initState`/`didChangeDependencies` 订阅
/// （订阅要拿到 `ModalRoute`，所以放在 `didChangeDependencies` 更稳）。
final RouteObserver<ModalRoute<void>> appRouteObserver =
    RouteObserver<ModalRoute<void>>();
