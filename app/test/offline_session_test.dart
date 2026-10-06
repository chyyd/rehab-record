import 'package:flutter_test/flutter_test.dart';
import 'package:rehab_app/core/api_endpoints.dart';
import 'package:rehab_app/data/local/token_store.dart';
import 'package:rehab_app/data/remote/auth_service.dart';

import 'support.dart';

/// **离线冷启动不能把人登出**（2026-10-06）。
///
/// 用户提问的原场景：「治疗师下班回家，脱离了内网环境，不小心点开了 app
/// 或 app 在后台运行，不会造成触发登出并要求输入服务器地址吧」
///
/// 复查代码时发现**前半句确实会**：`AuthService.refresh()` 原来是
/// `on AppError` 一律 `_tokens.clear()` —— 把"离线"当成了"会话失效"。
/// 于是回家点开 App → refresh 连不上 → 本地凭证被清 → 停在登录页，
/// 第二天上班必须重新登录；睡前连离线记录都用不了。
///
/// 这个 App 是离线优先的（本地库能独立工作），所以只有服务端**明确拒绝**
/// 才该清凭证。这一组测试把这条规则钉住。
///
/// > 后半句（"要求输入服务器地址"）**不会**发生：地址存在 `BackendSettings`
/// > 的独立键里，只由用户在登录页改，任何登出/失败路径都不碰它。
/// > 见 `server_settings_test.dart` 与 `BackendSettings` 的实现。
void main() {
  group('离线时的会话恢复', () {
    test('★ refresh 遇网络错误时**保留** refresh token（不清凭证）', () async {
      final store = _MemoryTokenStore();
      await store.saveRefreshToken('refresh-abc');
      await store.saveCachedUser(
        '{"id":2,"employee_no":"T001","name":"张三","role":"therapist"}',
      );

      // 状态码 0 = 模拟连不上（见 support.dart）。
      final adapter = ScriptedAdapter({kAuthRefresh: (0, <String, Object?>{})});
      final client = buildScriptedClient({}, adapter: adapter);
      final auth = AuthService(client: client, tokens: store);

      final token = await auth.refresh();

      expect(token, isNull, reason: '离线时换不到 access 是正常的');
      expect(
        await store.readRefreshToken(),
        'refresh-abc',
        reason: '★ 网络不通只是"现在问不到"，不是"会话失效" —— 凭证必须留着',
      );
    });

    test('★ 离线冷启动用缓存用户进入离线模式（不是回登录页）', () async {
      final store = _MemoryTokenStore();
      await store.saveRefreshToken('refresh-abc');
      await store.saveCachedUser(
        '{"id":2,"employee_no":"T001","name":"张三","role":"therapist"}',
      );
      final adapter = ScriptedAdapter({
        kAuthRefresh: (0, <String, Object?>{}),
        kAuthMe: (0, <String, Object?>{}),
      });
      final client = buildScriptedClient({}, adapter: adapter);
      final auth = AuthService(client: client, tokens: store);

      final user = await auth.restoreSession();

      expect(user, isNotNull, reason: '本地有凭证与身份缓存，就该让人进去用本地数据');
      expect(user!.name, '张三');
      expect(user.employeeNo, 'T001');
      expect(await store.readRefreshToken(), 'refresh-abc', reason: '凭证仍要保留');
    });

    test('服务端**明确拒绝**（401）时才清凭证 → 回登录页', () async {
      final store = _MemoryTokenStore();
      await store.saveRefreshToken('refresh-abc');
      await store.saveCachedUser(
        '{"id":2,"employee_no":"T001","name":"张三","role":"therapist"}',
      );
      final adapter = ScriptedAdapter({
        kAuthRefresh: (
          401,
          {'code': 'INVALID_REFRESH_TOKEN', 'message': '会话已失效'}
        ),
      });
      final client = buildScriptedClient({}, adapter: adapter);
      final auth = AuthService(client: client, tokens: store);

      final user = await auth.restoreSession();

      expect(user, isNull, reason: '被踢下线就该回登录页');
      expect(
        await store.readRefreshToken(),
        isNull,
        reason: '明确失效时必须清凭证，否则每次冷启动都会白白试一次',
      );
      expect(await store.readCachedUser(), isNull, reason: '缓存身份也要一起清');
    });

    test('没有缓存用户时（老版本升级上来）仍回登录页，不会卡住', () async {
      final store = _MemoryTokenStore();
      await store.saveRefreshToken('refresh-abc');
      // 故意不写缓存用户：模拟"从没有这个缓存的旧版本升上来"。
      final adapter = ScriptedAdapter({kAuthRefresh: (0, <String, Object?>{})});
      final client = buildScriptedClient({}, adapter: adapter);
      final auth = AuthService(client: client, tokens: store);

      final user = await auth.restoreSession();

      expect(user, isNull, reason: '没有身份可用，只能回登录页');
      expect(await store.readRefreshToken(), 'refresh-abc',
          reason: '但仍然不该清凭证 —— 联网后还能自动恢复');
    });

    test('在线恢复成功时刷新缓存（下次离线才拿得到最新身份）', () async {
      final store = _MemoryTokenStore();
      await store.saveRefreshToken('refresh-abc');
      final adapter = ScriptedAdapter({
        kAuthRefresh: (
          200,
          {
            'access_token': 'access-new',
            'refresh_token': 'refresh-new',
            'user': {
              'id': 2,
              'employee_no': 'T001',
              'name': '张三',
              'role': 'therapist',
            },
          }
        ),
        kAuthMe: (
          200,
          {'id': 2, 'employee_no': 'T001', 'name': '张三改名', 'role': 'therapist'}
        ),
      });
      final client = buildScriptedClient({}, adapter: adapter);
      final auth = AuthService(client: client, tokens: store);

      final user = await auth.restoreSession();

      expect(user!.name, '张三改名');
      expect(await store.readRefreshToken(), 'refresh-new', reason: 'refresh 是轮换的');
      expect(
        await store.readCachedUser(),
        contains('张三改名'),
        reason: '缓存要跟着更新，否则下次离线显示的是旧姓名',
      );
    });

    test('缓存损坏时删掉它并回登录页（不一直读到坏数据）', () async {
      final store = _MemoryTokenStore();
      await store.saveRefreshToken('refresh-abc');
      await store.saveCachedUser('这不是 JSON');
      final adapter = ScriptedAdapter({kAuthRefresh: (0, <String, Object?>{})});
      final client = buildScriptedClient({}, adapter: adapter);
      final auth = AuthService(client: client, tokens: store);

      final user = await auth.restoreSession();

      expect(user, isNull);
      expect(await store.readCachedUser(), isNull, reason: '坏缓存要清掉');
    });
  });
}

/// 内存版令牌存储：真 `TokenStore` 走 Keystore，测试环境没有实现。
class _MemoryTokenStore implements TokenStore {
  String? _refresh;
  String? _cached;
  String? _access;

  @override
  String? get accessToken => _access;

  @override
  bool get hasAccessToken => _access != null;

  @override
  void setAccessToken(String? token) => _access = token;

  @override
  Future<String?> readRefreshToken() async => _refresh;

  @override
  Future<void> saveRefreshToken(String? token) async => _refresh = token;

  @override
  Future<String?> readCachedUser() async => _cached;

  @override
  Future<void> saveCachedUser(String? json) async => _cached = json;

  @override
  Future<void> clear() async {
    _access = null;
    _refresh = null;
    _cached = null;
  }
}
