import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/app.dart';

void main() {
  // 依赖图在 `app.dart` 的启动门里按需构建（`appServicesProvider`），
  // 这里只负责把 Riverpod 的容器装上。
  runApp(const ProviderScope(child: RehabApp()));
}
