import 'package:flutter_test/flutter_test.dart';
import 'package:rehab_app/core/config.dart';
import 'package:rehab_app/data/local/app_database.dart';

/// 运行期"服务器地址"相关的纯函数（2026-10-06）。
///
/// 这一组是整个功能里**最容易出错、又最难在真机上发现**的部分：
/// 指纹算错会让两台后端共用一个本地库 —— 而本地库把服务端主键当自己的主键
///（`treatment_records.id` 就是服务端记录 id、`patients.inpatient_no` 是住院号），
/// 混库的表现是"数据看起来对，但其实是另一家医院的记录"，
/// 现场极难判断，所以在这里逐条钉住。
void main() {
  group('地址规范化', () {
    test('去掉首尾空白与所有尾部斜杠', () {
      expect(AppConfig.normalizeBaseUrl('  http://10.0.0.8:8000/  '),
          'http://10.0.0.8:8000');
      expect(AppConfig.normalizeBaseUrl('http://a//'), 'http://a');
    });

    test('漏了 http:// 会自动补上（现场手填太常见了）', () {
      expect(AppConfig.normalizeBaseUrl('10.0.0.8:8000'), 'http://10.0.0.8:8000');
      expect(AppConfig.normalizeBaseUrl('rehab.local'), 'http://rehab.local');
    });

    test('scheme 大小写归一（Dart 的 Uri 不认大写 scheme）', () {
      // 不归一化的话 `Uri.tryParse('HTTP://h:8000')` 会把 `http` 当 host、
      // 端口按默认 80 算 —— 指纹会变成 `http_80`，两台后端撞库。
      expect(AppConfig.normalizeBaseUrl('HTTP://10.0.0.8:8000'),
          'http://10.0.0.8:8000');
      expect(AppConfig.normalizeBaseUrl('HTTPS://Rehab.Local'),
          'https://Rehab.Local');
    });

    test('尾部斜杠必须去掉（否则拼出 //api/v1）', () {
      // 路径常量以 `/api/v1` 开头；反代对 `//api/v1` 常常直接 404。
      final base = AppConfig.normalizeBaseUrl('https://gw.hosp.local/rehab/');
      expect('$base/api/v1/health', 'https://gw.hosp.local/rehab/api/v1/health');
    });
  });

  group('地址校验', () {
    test('合法：http/https + host，允许 IP、端口、基路径', () {
      for (final ok in [
        'http://10.0.0.8:8000',
        'https://rehab.local',
        'https://gw.hosp.local/rehab',
        'http://192.168.1.5',
        // 缺 scheme 的会被 normalize 补成 http:// 之后视为合法
        '10.0.0.8:8000',
      ]) {
        expect(AppConfig.validateBaseUrl(ok), isNull, reason: '$ok 应该合法');
      }
    });

    test('不合法：空、非 http(s) scheme', () {
      expect(AppConfig.validateBaseUrl(''), isNotNull);
      expect(AppConfig.validateBaseUrl('   '), isNotNull);
      expect(AppConfig.validateBaseUrl('ftp://10.0.0.8'), isNotNull,
          reason: '只支持 http/https');
      expect(AppConfig.validateBaseUrl('http://'), isNotNull,
          reason: '没有 host 不算合法');
    });
  });

  group('后端指纹（本地库分文件靠它）', () {
    test('同地址必同值 —— 含 scheme/路径/大小写/尾斜杠差异', () {
      final a = backendFingerprint('http://10.0.0.8:8000');
      expect(backendFingerprint('http://10.0.0.8:8000/'), a);
      expect(backendFingerprint('  http://10.0.0.8:8000  '), a);
      expect(backendFingerprint('https://10.0.0.8:8000'), a,
          reason: '同一台后端的 https 入口不该被算成两台');
      expect(backendFingerprint('http://10.0.0.8:8000/rehab'), a);
      expect(backendFingerprint('HTTP://10.0.0.8:8000'), a);
    });

    test('★ 不同后端必不同值 —— 不然两台后端会共用一个本地库', () {
      final a = backendFingerprint('http://10.0.0.8:8000');
      expect(backendFingerprint('http://10.0.0.9:8000'), isNot(a));
      expect(backendFingerprint('http://10.0.0.8:8001'), isNot(a),
          reason: '端口不同就是不同服务，必须分开');
      expect(backendFingerprint('http://rehab.local:8000'), isNot(a));
    });

    test('缺 scheme 也能算对（用户很可能就填 10.0.0.8:8000）', () {
      // Uri.tryParse('10.0.0.8:8000') 会把 `10.0.0.8` 当 scheme、host 为空 ——
      // 不补 scheme 的话指纹会退化成 'default'，两台后端就撞库了。
      expect(backendFingerprint('10.0.0.8:8000'),
          backendFingerprint('http://10.0.0.8:8000'));
      expect(backendFingerprint('10.0.0.8:8000'), isNot('default'));
    });

    test('只含文件名安全字符', () {
      for (final url in [
        'http://10.0.0.8:8000',
        'https://gw.hosp.local/rehab',
        'http://[fe80::1]:8000',
        '10.0.0.8:8000',
      ]) {
        final fp = backendFingerprint(url);
        expect(RegExp(r'^[a-z0-9_]+$').hasMatch(fp), isTrue,
            reason: '$url → $fp 含不适合做文件名的字符');
      }
    });

    test('解析不出 host 时退回 default（保证永远有可用的文件名）', () {
      expect(backendFingerprint(''), 'default');
      expect(backendFingerprint('   '), 'default');
    });
  });

  group('本地库文件名', () {
    test('编译期默认那台沿用老文件名 —— 老用户升级后数据不丢', () {
      expect(
        databaseFileName(const DatabaseNaming(
          backendFingerprint: '10_0_2_2_8000',
          isEnvironmentDefault: true,
        )),
        'rehab_app.sqlite',
      );
    });

    test('其它后端带指纹后缀 —— 结构上不可能与默认库串', () {
      final name = databaseFileName(const DatabaseNaming(
        backendFingerprint: '10_0_0_8_8000',
        isEnvironmentDefault: false,
      ));
      expect(name, 'rehab_app_10_0_0_8_8000.sqlite');
      expect(name, isNot('rehab_app.sqlite'));
    });

    test('★ 不是靠"指纹 == default"来判断 —— 真实地址的指纹永远不是 default', () {
      // 我第一版就是这么写错的：以为默认地址会得到 'default' 指纹，
      // 于是兼容逻辑永远不成立、老库被悄悄弃用。
      expect(backendFingerprint('http://10.0.2.2:8000'), isNot('default'));
      expect(
        databaseFileName(DatabaseNaming(
          backendFingerprint: backendFingerprint('http://10.0.2.2:8000'),
          isEnvironmentDefault: true,
        )),
        'rehab_app.sqlite',
      );
    });

    test('不同后端的库文件名互不相同', () {
      final names = [
        'http://10.0.0.8:8000',
        'http://10.0.0.9:8000',
        'http://10.0.0.8:8001',
      ].map((u) => databaseFileName(DatabaseNaming(
            backendFingerprint: backendFingerprint(u),
            isEnvironmentDefault: false,
          )));
      expect(names.toSet().length, 3, reason: '三台后端必须三个不同的库文件');
    });
  });
}
