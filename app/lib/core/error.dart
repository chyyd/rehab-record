import 'dart:convert';

/// 统一的错误模型。
///
/// 后端所有错误都收敛成同一种结构（`backend/app/core/errors.py`，设计 D08）：
/// ```json
/// {"code": "PATIENT_NOT_VISIBLE", "message": "无权访问该患者", "details": {...}}
/// ```
/// 因此客户端只需要一个类型，就能对任何失败做出一致处理。
class AppError implements Exception {
  const AppError({
    required this.code,
    required this.message,
    this.details,
    this.httpStatus,
  });

  /// 机器可读的错误码，如 `AUTH_REQUIRED`、`RECORD_LOCKED`、`CONFLICT`。
  final String code;

  /// 给用户看的中文说明（后端已经写好，直接展示）。
  final String message;

  /// 结构化补充信息，如冲突条目 `{"conflicts": [...]}`。
  final Map<String, dynamic>? details;

  /// HTTP 状态码（网络层失败时为 null）。
  final int? httpStatus;

  /// 是否为"需要重新登录"的错误。
  bool get isAuthError => code == 'AUTH_REQUIRED' || code == 'TOKEN_WRONG_TYPE' || httpStatus == 401;

  /// 是否为业务冲突（可提示治疗师具体原因，而不是"出错了"）。
  bool get isConflict => code == 'CONFLICT' || httpStatus == 409;

  /// 是否为参数/用法错误（通常是客户端 bug）。
  bool get isInvalid => code == 'INVALID' || httpStatus == 422;

  /// 从后端错误体构造；`details` 不是对象时忽略。
  factory AppError.fromBody(Object? body, {int? httpStatus}) {
    if (body is Map) {
      final map = Map<String, dynamic>.from(body);
      final details = map['details'];
      return AppError(
        code: (map['code'] as String?) ?? 'UNKNOWN',
        message: (map['message'] as String?) ?? '请求失败',
        details: details is Map ? Map<String, dynamic>.from(details) : null,
        httpStatus: httpStatus,
      );
    }
    return AppError(
      code: 'UNKNOWN',
      message: body?.toString().isNotEmpty == true ? body.toString() : '请求失败',
      httpStatus: httpStatus,
    );
  }

  /// 从原始响应字符串尽力解析出结构化错误。
  factory AppError.fromRawBody(String raw, {int? httpStatus}) {
    if (raw.trim().isEmpty) {
      return AppError(code: 'UNKNOWN', message: '请求失败（空响应）', httpStatus: httpStatus);
    }
    try {
      return AppError.fromBody(jsonDecode(raw), httpStatus: httpStatus);
    } catch (_) {
      return AppError(
        code: 'UNKNOWN',
        message: raw.length > 200 ? '${raw.substring(0, 200)}…' : raw,
        httpStatus: httpStatus,
      );
    }
  }

  /// 网络层失败（连不上、超时、TLS 失败等）。
  ///
  /// 离线优先的 App 里这不是异常情况，调用方应据此走"离线模式"而不是报错弹窗。
  factory AppError.network(String reason) =>
      AppError(code: 'NETWORK_ERROR', message: '网络不可用：$reason');

  @override
  String toString() => 'AppError($code, $message)';
}
