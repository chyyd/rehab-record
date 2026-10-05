import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import 'package:rehab_app/core/api_endpoints.dart';
import 'package:rehab_app/data/remote/api_client.dart';
import 'package:rehab_app/data/remote/timeline_dto.dart';

/// 时间轴与汇总（**只读，直接走服务端**，不做本地镜像）。
///
/// 为什么不像患者/排期那样先落本地：这是"全科协作视图"，需要看到**别人**写的记录，
/// 而本地库只镜像了自己同步过的部分。只读数据也没有离线写入的需要，
/// 所以直接查服务端最省事也最不容易出现"本地与线上不一致"。
// 构造器刻意用「公开参数名 + 私有字段」（与 api_client.dart 同一约定）；
// 条件键是构造可选查询参数最清楚的写法。
// ignore_for_file: prefer_initializing_formals, use_null_aware_elements
class TimelineRepository {
  TimelineRepository({required ApiClient client}) : _client = client;

  final ApiClient _client;

  /// 时间轴（按日期倒序，分页）。
  ///
  /// `scope` 只有 `visible`（我能看到的患者）与 `mine`（我写的）——
  /// 曾经的 `temp` 已随临时指派下线（2026-10-05）。
  /// 筛选维度是 `discipline`（四大类）与 `kind`（形态），
  /// **不再有** `main_item_id`：字典树与主项目已随迁移 011 删除。
  Future<TimelinePageData> fetchTimeline({
    int page = 1,
    int pageSize = 20,
    String? dateFrom,
    String? dateTo,
    String scope = 'visible',
    String? discipline,
    String? kind,
  }) async {
    final data = await _client.request(kTimeline, query: {
      'page': page,
      'page_size': pageSize,
      'scope': scope,
      if (dateFrom != null) 'from': dateFrom,
      if (dateTo != null) 'to': dateTo,
      if (discipline != null) 'discipline': discipline,
      if (kind != null) 'kind': kind,
    });
    return TimelinePageData.fromJson(Map<String, dynamic>.from(data as Map));
  }

  /// 按日期汇总（`group_by` = therapist / patient）。
  Future<DateSummary> fetchDateSummary({
    required String date,
    String groupBy = 'therapist',
  }) async {
    final data = await _client.request(kSummaryDate, query: {
      'date': date,
      'group_by': groupBy,
    });
    return DateSummary.fromJson(Map<String, dynamic>.from(data as Map));
  }

  /// 患者每日汇总。
  Future<PatientDailySummary> fetchPatientDaily(
    String inpatientNo, {
    String? dateFrom,
    String? dateTo,
  }) async {
    final data = await _client.request(
      kSummaryPatient(inpatientNo),
      query: {
        if (dateFrom != null) 'from': dateFrom,
        if (dateTo != null) 'to': dateTo,
      },
    );
    return PatientDailySummary.fromJson(Map<String, dynamic>.from(data as Map));
  }

  /// 下载打印用 PDF 到应用缓存目录，返回本地文件路径。
  ///
  /// **必须自己带 Bearer 下载**，不能把 URL 直接丢给系统浏览器/阅读器：
  /// 那些组件不会带我们的 Authorization 头，打开只会看到 401。
  Future<File> downloadPdf({
    required String path,
    required String filename,
    Map<String, dynamic>? query,
  }) async {
    final bytes = await _client.requestBytes(path, query: query);
    final dir = await getApplicationDocumentsDirectory();
    final printed = Directory('${dir.path}/prints');
    if (!await printed.exists()) {
      await printed.create(recursive: true);
    }
    final file = File('${printed.path}/$filename');
    await file.writeAsBytes(bytes, flush: true);
    return file;
  }

  /// 打印 PDF 的下载地址（供界面显示/复制排查）。
  String pdfUrl(String path, {Map<String, dynamic>? query}) {
    final uri = Uri.parse('${_client.config.baseUrl}$path')
        .replace(queryParameters: query?.map((k, v) => MapEntry(k, '$v')));
    return uri.toString();
  }
}

/// 供调试：把字节数格式化成可读文本。
String humanBytes(int bytes) {
  if (bytes < 1024) return '$bytes B';
  if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
  return '${(bytes / 1024 / 1024).toStringAsFixed(1)} MB';
}

/// 把 JSON 失败体转成可读文本（打印失败时用）。
String describeFailure(Object raw) {
  if (raw is String) return raw;
  try {
    return jsonEncode(raw);
  } on JsonUnsupportedObjectError {
    return '$raw';
  }
}
