import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:rehab_app/core/api_endpoints.dart';
import 'package:rehab_app/core/config.dart';
import 'package:rehab_app/core/error.dart';

import 'support.dart';

void main() {
  group('AppError 解析（与后端统一错误体对齐）', () {
    test('解析标准错误体', () {
      final err = AppError.fromBody(
        {'code': 'RECORD_LOCKED', 'message': '该记录已锁定', 'details': {'record_id': 7}},
        httpStatus: 403,
      );
      expect(err.code, 'RECORD_LOCKED');
      expect(err.message, '该记录已锁定');
      expect(err.details?['record_id'], 7);
      expect(err.httpStatus, 403);
      expect(err.isAuthError, isFalse);
      expect(err.isConflict, isFalse);
    });

    test('401 视为需要重新登录', () {
      final err = AppError.fromBody({'code': 'AUTH_REQUIRED', 'message': '未认证'}, httpStatus: 401);
      expect(err.isAuthError, isTrue);
    });

    test('409 视为业务冲突（可提示具体原因）', () {
      final err = AppError.fromBody(
        {'code': 'CONFLICT', 'message': '该半日无法排期', 'details': {'conflicts': []}},
        httpStatus: 409,
      );
      expect(err.isConflict, isTrue);
      expect(err.details?['conflicts'], isEmpty);
    });

    test('非 JSON 响应也能降级成可读错误', () {
      final err = AppError.fromRawBody('<html>502 Bad Gateway</html>', httpStatus: 502);
      expect(err.code, 'UNKNOWN');
      expect(err.message, contains('502'));
    });

    test('空响应体不抛异常', () {
      final err = AppError.fromRawBody('', httpStatus: 500);
      expect(err.message, contains('空响应'));
    });

    test('details 不是对象时忽略，不崩', () {
      final err = AppError.fromBody({'code': 'INVALID', 'message': 'x', 'details': 'oops'});
      expect(err.details, isNull);
    });

    test('网络错误有独立 code，便于走离线模式', () {
      final err = AppError.network('无法连接服务器');
      expect(err.code, 'NETWORK_ERROR');
      expect(err.httpStatus, isNull);
    });
  });

  group('ApiClient 请求行为', () {
    test('已登录时带 Bearer 头', () async {
      final adapter = ScriptedAdapter({kAuthMe: (200, {'id': 1})});
      final client = buildScriptedClient({}, adapter: adapter, readAccessToken: () => 'tok-123');
      await client.request(kAuthMe);

      expect(adapter.seen.single.headers['Authorization'], 'Bearer tok-123');
    });

    test('未登录时不带 Authorization 头', () async {
      final adapter = ScriptedAdapter({kAuthMe: (200, {'id': 1})});
      final client = buildScriptedClient({}, adapter: adapter);
      await client.request(kAuthMe);

      expect(adapter.seen.single.headers.containsKey('Authorization'), isFalse);
    });

    test('非 2xx 抛结构化 AppError（不是 Dio 原始异常）', () async {
      final client = buildScriptedClient(
        {
          kPatients: (403, {'code': 'PATIENT_NOT_VISIBLE', 'message': '无权访问该患者'}),
        },
        readAccessToken: () => 't',
      );

      await expectLater(
        client.request(kPatients),
        throwsA(isA<AppError>().having((e) => e.code, 'code', 'PATIENT_NOT_VISIBLE')),
      );
    });

    test('401 时用 refresh 换令牌并重放原请求', () async {
      final adapter = ScriptedAdapter({kPatients: (401, {'code': 'AUTH_REQUIRED'})})
        ..succeedAfterRefresh = true;
      var refreshCalls = 0;
      final client = buildScriptedClient(
        {},
        adapter: adapter,
        readAccessToken: () => 'stale',
        refreshToken: () async {
          refreshCalls++;
          return 'fresh';
        },
      );

      final result = await client.request(kPatients);
      expect(result, {'ok': true});
      expect(refreshCalls, 1, reason: '应恰好刷新一次');
      expect(adapter.seen.length, 2, reason: '原请求应被重放');
    });

    test('refresh 返回 null 时不无限重试，直接抛 401', () async {
      final adapter = ScriptedAdapter({kPatients: (401, {'code': 'AUTH_REQUIRED'})});
      var refreshCalls = 0;
      final client = buildScriptedClient(
        {},
        adapter: adapter,
        readAccessToken: () => 'stale',
        refreshToken: () async {
          refreshCalls++;
          return null;
        },
      );

      await expectLater(client.request(kPatients), throwsA(isA<AppError>()));
      expect(refreshCalls, 1);
      expect(adapter.seen.length, 1, reason: '没有新令牌就不该重放');
    });

    test('并发 401 只刷新一次（refresh 是轮换的，重复刷新会互相作废）', () async {
      final adapter = ScriptedAdapter({kPatients: (401, {'code': 'AUTH_REQUIRED'})})
        ..succeedAfterRefresh = true;
      var refreshCalls = 0;
      final client = buildScriptedClient(
        {},
        adapter: adapter,
        readAccessToken: () => 'stale',
        refreshToken: () async {
          refreshCalls++;
          await Future<void>.delayed(const Duration(milliseconds: 30));
          return 'fresh';
        },
      );

      await Future.wait([
        client.request(kPatients),
        client.request(kPatients),
        client.request(kPatients),
      ]);

      expect(refreshCalls, 1, reason: '三个并发 401 必须共用一个刷新动作');
    });
  });

  group('接口路径常量', () {
    test('统一前缀且带出参的路径拼接正确', () {
      expect(kApiPrefix, '/api/v1');
      expect(kAuthLogin, '/api/v1/auth/login');
      expect(kPatient('ZY001'), '/api/v1/patients/ZY001');
      expect(kRecordSubmit(42), '/api/v1/records/42/submit');
      expect(kPrintSummaryPatient('ZY001'), '/api/v1/print/summary/patient/ZY001');
    });

    test('AppConfig 默认地址在安卓上走 10.0.2.2（模拟器访问宿主机的地址）', () {
      final cfg = AppConfig.fromEnvironment();
      expect(cfg.baseUrl, isNotEmpty);
      // 安卓模拟器里 127.0.0.1 指向模拟器自身，宿主机是 10.0.2.2。
      if (Platform.isAndroid) {
        expect(cfg.baseUrl, contains('10.0.2.2'));
      }
    });
  });
}
