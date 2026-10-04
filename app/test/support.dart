import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:rehab_app/core/config.dart';
import 'package:rehab_app/data/remote/api_client.dart';

/// 记录每次请求并返回预置响应的适配器。
///
/// 为什么自定义而不用 mock 库：这里只需要"给什么请求返回什么"，
/// 一个 [HttpClientAdapter] 足够，省一个依赖；而且**完全不需要真实网络**，
/// 测试可以离线跑（本项目所在环境对 github 不通，这一点很重要）。
class ScriptedAdapter implements HttpClientAdapter {
  ScriptedAdapter(this.responses);

  /// 路径 → (状态码, 响应体)。
  final Map<String, (int, Object?)> responses;

  /// 按顺序记录请求，便于断言"带没带 Authorization"、"重放了几次"。
  final List<RequestOptions> seen = [];

  /// 为真时，**第一次之后的**请求把 401 改成 200，用来测静默刷新 + 重放。
  bool succeedAfterRefresh = false;

  static const Map<String, List<String>> jsonHeaders = {
    Headers.contentTypeHeader: ['application/json'],
  };

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    seen.add(options);
    final entry = responses[options.path];
    if (entry == null) {
      return ResponseBody.fromString('{}', 404, headers: jsonHeaders);
    }
    var (status, body) = entry;
    if (status == 401 && succeedAfterRefresh && seen.length > 1) {
      status = 200;
      body = const {'ok': true};
    }
    return ResponseBody.fromString(jsonEncode(body), status, headers: jsonHeaders);
  }

  @override
  void close({bool force = false}) {}
}

/// 造一个挂了 [ScriptedAdapter] 的 [ApiClient]（测试专用，不发真实请求）。
ApiClient buildScriptedClient(
  Map<String, (int, Object?)> responses, {
  String? Function()? readAccessToken,
  Future<String?> Function()? refreshToken,
  ScriptedAdapter? adapter,
}) {
  final client = ApiClient(
    config: const AppConfig(
      baseUrl: 'http://test.local',
      trustedCaAsset: null,
      connectTimeout: Duration(seconds: 5),
      receiveTimeout: Duration(seconds: 5),
    ),
    readAccessToken: readAccessToken ?? () => null,
    refreshToken: refreshToken,
  );
  client.raw.httpClientAdapter = adapter ?? ScriptedAdapter(responses);
  return client;
}
