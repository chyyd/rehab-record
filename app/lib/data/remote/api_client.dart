// 构造器刻意用「公开参数名 + 私有字段」（`required ApiClient client` → `_client`）：
// 调用方看到的是简洁的参数名，内部仍保持私有。prefer_initializing_formals 对
// 这种写法无解（`this._client` 不能作具名参数），故在此文件关闭该规则。
// ignore_for_file: prefer_initializing_formals

import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:dio/io.dart';
import 'package:flutter/services.dart' show rootBundle;

import 'package:rehab_app/core/config.dart';
import 'package:rehab_app/core/error.dart';

/// 令牌读取/刷新回调。由认证层实现，网络层不直接依赖认证层（避免循环依赖）。
typedef AccessTokenReader = String? Function();

/// 用 refresh token 换新的 access token；失败返回 null（触发跳登录）。
typedef TokenRefresher = Future<String?> Function();

/// HTTP 客户端。
///
/// 三件事必须由它统一负责，不能散到各个调用点：
///
/// 1. **自签 CA 注入**（设计 D06 / T2.8）：把内网 CA 交给 Dart 的 [SecurityContext]。
///    **绝不允许 `badCertificateCallback` 一律放行** —— 那等于把 JWT 与密码
///    裸露在内网（`设计.md` 5.5 明确要求"客户端必须内建 CA，不得关闭校验"）。
/// 2. **401 静默刷新**：access token 只放内存，过期就用 refresh token 换一次，
///    然后**重放原请求**；并发的 401 共用同一个刷新动作，否则 refresh 轮换会让
///    先到的请求作废（令牌是一次性的）。
/// 3. **统一错误体**：后端所有错误都是 `{code, message, details}`，
///    在这里翻译成 [AppError]，上层不必再解析 HTTP 状态码。
class ApiClient {
  ApiClient({
    required AppConfig config,
    required AccessTokenReader readAccessToken,
    TokenRefresher? refreshToken,
  })  : _config = config,
        _readAccessToken = readAccessToken,
        _refreshToken = refreshToken {
    _dio = Dio(
      BaseOptions(
        baseUrl: config.baseUrl,
        connectTimeout: config.connectTimeout,
        receiveTimeout: config.receiveTimeout,
        // 自己判断状态码，不用 Dio 的抛异常规则，便于统一错误体处理。
        validateStatus: (_) => true,
        headers: {'Accept': 'application/json'},
      ),
    )..interceptors.add(
        InterceptorsWrapper(
          onRequest: (options, handler) {
            final token = _readAccessToken();
            if (token != null && token.isNotEmpty) {
              options.headers['Authorization'] = 'Bearer $token';
            }
            handler.next(options);
          },
        ),
      );

    _configureTls();
  }

  final AppConfig _config;
  final AccessTokenReader _readAccessToken;
  final TokenRefresher? _refreshToken;
  late final Dio _dio;

  /// 进行中的刷新动作；并发的 401 共用它。
  Future<String?>? _refreshing;

  AppConfig get config => _config;
  Dio get raw => _dio;

  /// 把内置 CA 装进 [SecurityContext]。
  ///
  /// 未配置 CA 时保持系统信任链——生产环境应换成受信任证书，而不是关校验。
  void _configureTls() {
    final caAsset = _config.trustedCaAsset;
    if (caAsset == null) return;

    _dio.httpClientAdapter = IOHttpClientAdapter(
      createHttpClient: () {
        final context = SecurityContext(withTrustedRoots: true);
        // 证书是构建期固定的静态资源，同步加载即可（只在创建 client 时读一次）。
        final bytes = _loadedCa ?? (throw StateError('CA 证书尚未加载'));
        context.setTrustedCertificatesBytes(bytes);
        return HttpClient(context: context);
      },
    );
  }

  List<int>? _loadedCa;

  /// 预加载 CA 证书。必须在发起请求前调用一次（在 `main()` 里 await）。
  Future<void> loadTrustedCa() async {
    final caAsset = _config.trustedCaAsset;
    if (caAsset == null) return;
    final data = await rootBundle.load(caAsset);
    _loadedCa = data.buffer.asUint8List();
  }

  /// 发起请求并返回解析后的 JSON。
  ///
  /// 失败一律抛 [AppError]（含网络不可用），调用方不需要 try/catch Dio 的异常类型。
  Future<dynamic> request(
    String path, {
    String method = 'GET',
    Map<String, dynamic>? query,
    Object? body,
    bool isRetry = false,
  }) async {
    late Response<dynamic> response;
    try {
      response = await _dio.request<dynamic>(
        path,
        queryParameters: query,
        data: body == null ? null : jsonEncode(body),
        options: Options(method: method, contentType: 'application/json'),
      );
    } on DioException catch (e) {
      throw AppError.network(_describeDioError(e));
    }

    final status = response.statusCode ?? 0;
    if (status >= 200 && status < 300) return response.data;

    // 401：尝试刷新一次并重放原请求。
    if (status == 401 && !isRetry && _refreshToken != null) {
      final fresh = await _refreshOnce();
      if (fresh != null) {
        return request(path,
            method: method, query: query, body: body, isRetry: true);
      }
    }

    throw AppError.fromBody(response.data, httpStatus: status);
  }

  /// 取**二进制**响应（打印用的 PDF）。
  ///
  /// 单独一个方法而不是给 [request] 加参数：PDF 的失败体仍是 JSON 错误体，
  /// 而 [request] 会把 2xx 的 `response.data` 当解析后的 JSON 返回 ——
  /// 走 `ResponseType.bytes` 时它是 `List<int>`，两者不能混在一起。
  ///
  /// 401 的静默刷新逻辑与 [request] 保持一致（并发的刷新仍共用一个 future）。
  Future<List<int>> requestBytes(
    String path, {
    Map<String, dynamic>? query,
    bool isRetry = false,
  }) async {
    late Response<dynamic> response;
    try {
      response = await _dio.request<dynamic>(
        path,
        queryParameters: query,
        options: Options(method: 'GET', responseType: ResponseType.bytes),
      );
    } on DioException catch (e) {
      throw AppError.network(_describeDioError(e));
    }

    final status = response.statusCode ?? 0;
    if (status >= 200 && status < 300) {
      final data = response.data;
      if (data is List<int>) return data;
      if (data is List) return data.cast<int>();
      throw AppError.network('服务端返回的不是二进制内容');
    }

    if (status == 401 && !isRetry && _refreshToken != null) {
      final fresh = await _refreshOnce();
      if (fresh != null) return requestBytes(path, query: query, isRetry: true);
    }

    // 失败体是 JSON（服务端统一错误体），但这里拿到的可能是字节，统一转回文本再解析。
    final raw = response.data;
    final decoded = raw is List<int> ? utf8.decode(raw, allowMalformed: true) : raw;
    throw AppError.fromBody(decoded, httpStatus: status);
  }

  /// 并发的 401 共用一个刷新动作。
  Future<String?> _refreshOnce() {
    return _refreshing ??= () async {
      try {
        return await _refreshToken!();
      } finally {
        _refreshing = null;
      }
    }();
  }

  /// 把 Dio 的异常翻译成人能读的原因。
  ///
  /// **离线优先**：网络不通不是错误状态，是正常工作模式，所以文案要中性。
  ///
  /// 注意 `DioExceptionType` 是**可扩展的枚举**，dio 升级可能加成员；
  /// 这里显式覆盖当前 9 个取值（dio 5.11.1），不放 `default` 分支，
  /// 这样将来新增成员时**编译期就会报出来**，逼着补文案而不是静默落到兜底。
  String _describeDioError(DioException e) {
    switch (e.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
      case DioExceptionType.transformTimeout:
        return '连接超时';
      case DioExceptionType.connectionError:
        return '无法连接服务器';
      case DioExceptionType.badCertificate:
        return '证书校验失败（内网 CA 可能未内置或已更换）';
      case DioExceptionType.cancel:
        return '请求已取消';
      case DioExceptionType.badResponse:
        return '响应异常';
      case DioExceptionType.unknown:
        return e.message ?? '未知网络错误';
    }
  }

  Future<void> close() async => _dio.close(force: true);
}
