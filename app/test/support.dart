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
  ScriptedAdapter(this.responses, {this.binaryResponses = const {}});

  /// 路径 → (状态码, 响应体)。
  final Map<String, (int, Object?)> responses;

  /// 路径 → (状态码, 原始字节)。用于 PDF 这类**二进制**响应 ——
  /// JSON 那套 `jsonEncode` 会把字节数组变成 `"[1,2,3]"`，拿回来不是 PDF。
  final Map<String, (int, List<int>)> binaryResponses;

  /// 按顺序记录请求，便于断言"带没带 Authorization"、"重放了几次"。
  final List<RequestOptions> seen = [];

  /// **有序脚本**：第 n 次命中该路径的请求返回第 n 个响应。
  ///
  /// 与 [responses]（按路径给固定响应）互补 —— 有些行为只在"同一个接口先返回 A、
  /// 再返回 B"时才验证得了。典型例子是 `/sync/pull`：服务端先说"你的游标作废了"
  ///（`stale_cursor: true`），客户端丢掉游标**再拉一次**，第二次才是真正的快照。
  /// 固定响应表达不了这种两段式。
  ///
  /// 用完之后继续复用最后一个响应（不越界、不报错），
  /// 免得测试因为"多拉了一次"而莫名其妙地 404。
  final Map<String, List<(int, Object?)>> sequences = {};

  /// 每条路径各自消耗到第几个（与 [sequences] 配合）。
  final Map<String, int> _sequenceCursor = {};

  /// 为真时，**第一次之后的**请求把 401 改成 200，用来测静默刷新 + 重放。
  bool succeedAfterRefresh = false;

  static const Map<String, List<String>> jsonHeaders = {
    Headers.contentTypeHeader: ['application/json'],
  };

  static const Map<String, List<String>> binaryHeaders = {
    Headers.contentTypeHeader: ['application/pdf'],
  };

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    seen.add(options);

    final binary = binaryResponses[options.path];
    if (binary != null) {
      final (status, bytes) = binary;
      return ResponseBody.fromBytes(bytes, status, headers: binaryHeaders);
    }

    // 有序脚本优先：同一个路径要"先 A 后 B"时用它。
    final script = sequences[options.path];
    if (script != null && script.isNotEmpty) {
      final idx = (_sequenceCursor[options.path] ?? 0).clamp(0, script.length - 1);
      _sequenceCursor[options.path] = idx + 1;
      final (status, body) = script[idx];
      return ResponseBody.fromString(jsonEncode(body), status, headers: jsonHeaders);
    }

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
  Map<String, (int, List<int>)> binaryResponses = const {},
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
  client.raw.httpClientAdapter =
      adapter ?? ScriptedAdapter(responses, binaryResponses: binaryResponses);
  return client;
}
