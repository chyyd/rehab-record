import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/core/error.dart';
import 'package:rehab_app/core/providers.dart';
import 'package:rehab_app/data/local/app_database.dart';
import 'package:rehab_app/features/patients/patients_providers.dart';

/// 冲突队列里的条目（UI 视图）。
///
/// 直接从 `change_queue` 行派生，并把 `payload_json` 解析出来供展示 ——
/// 治疗师需要看到**自己到底改了什么**才能判断该保留谁。
class ConflictItem {
  const ConflictItem({
    required this.clientUuid,
    required this.entity,
    required this.op,
    required this.baseRevision,
    required this.retryCount,
    required this.createdAt,
    required this.payload,
    this.lastError,
  });

  final String clientUuid;

  /// `treatment_record`（2026-10-05 排期下线后，它是唯一可离线写的实体）。
  final String entity;

  /// `insert` / `update`。
  final String op;

  /// 入队时的基线版本（**服务端当前版本见 [serverRevision]**）。
  final int? baseRevision;

  final int retryCount;
  final String createdAt;
  final String? lastError;
  final Map<String, dynamic> payload;

  factory ConflictItem.fromRow(ChangeQueueData row) {
    Map<String, dynamic> payload = const {};
    try {
      final decoded = jsonDecode(row.payloadJson);
      if (decoded is Map) payload = Map<String, dynamic>.from(decoded);
    } on FormatException {
      // 载荷坏了不该让整个冲突页面打不开；下面用空 map 展示"内容无法解析"。
    }
    return ConflictItem(
      clientUuid: row.clientUuid,
      entity: row.entity,
      op: row.op,
      baseRevision: row.baseRevision,
      retryCount: row.retryCount,
      createdAt: row.createdAt,
      lastError: row.lastError,
      payload: payload,
    );
  }

  String get entityLabel => switch (entity) {
        'treatment_record' => '治疗记录',
        // 排期已于 2026-10-05 下线；保留这条只为让**历史队列数据**仍显示得出来。
        'appointment' => '排期（已下线）',
        _ => entity,
      };

  String get opLabel => switch (op) {
        'insert' => '新建',
        'update' => '修改',
        'delete' => '删除',
        _ => op,
      };

  /// 患者住院号（两种实体的 payload 里都有 `patient_no`）。
  String? get patientNo => payload['patient_no'] as String?;

  String? get recordDate => payload['record_date'] as String?;

  String get dateLabel => recordDate ?? '—';

  /// 记录形态（`initial` / `daily` / `reassessment` / `discharge`）。
  String? get kind => payload['kind'] as String?;

  String get kindLabel => switch (kind) {
        'initial' => '首评',
        'reassessment' => '复评',
        'discharge' => '出院小结',
        'daily' => '日常记录',
        _ => kind ?? '—',
      };

  /// 大类（`PT` / `OT` / `ST_SW` / `ST_SP`）。
  String? get discipline => payload['discipline'] as String?;

  /// 这份改动填了几个字段（`body` 的键数）。
  ///
  /// 旧模型这里数的是 `items`（明细项）；SOAP 模型下内容就是一整个 `body`，
  /// 所以数它的键 —— 界面上的"填了几项"含义不变。
  int get itemCount {
    final body = payload['body'];
    return body is Map ? body.length : 0;
  }

  /// 冲突原因的人话解释。
  ///
  /// 服务端返回的原因分两类（协议 §4.4）：
  ///  - `missing_base_revision` / `entity_prefers_server`：
  ///    这条东西在服务端**已经不是我改之前的版本了**（别人改过，或我本地这份是没有基线的旧副本）；
  ///  - `server_status=xxx`：服务端已经**提交/锁定**了，草稿的"客户端优先"不再适用。
  ///
  /// 因此"保留我的"是**有代价**的：会覆盖掉服务端当前的版本。
  /// 文案必须把这一点讲清楚，不能让治疗师以为可以随便点。
  String get reasonLabel {
    final reason = lastError ?? '';
    if (reason == 'missing_base_revision') {
      return '本地这份改动没有版本基线（可能来自旧副本），服务端已有另一个版本';
    }
    if (reason == 'entity_prefers_server') {
      return '服务端已有另一个版本，这类数据默认以服务端为准';
    }
    if (reason.startsWith('server_status=')) {
      final status = reason.substring('server_status='.length);
      final label = switch (status) {
        'submitted' => '已提交',
        'locked' => '已锁定',
        'draft' => '草稿',
        _ => status,
      };
      return '服务端这条记录已经是「$label」状态，不再是可被草稿覆盖的草稿';
    }
    if (reason.isEmpty) return '服务端已有另一个版本';
    return reason;
  }
}

/// 冲突页面状态。
class ConflictState {
  const ConflictState({
    this.items = const [],
    this.busy = false,
    this.message,
    this.isError = false,
  });

  final List<ConflictItem> items;
  final bool busy;
  final String? message;
  final bool isError;

  bool get isEmpty => items.isEmpty;
}

/// 冲突处理控制器。
class ConflictController extends Notifier<ConflictState> {
  @override
  ConflictState build() => const ConflictState();

  /// 重新读取冲突队列（进入页面 / 裁决后调用）。
  Future<void> reload() async {
    final services = ref.read(appServicesProvider).requireValue;
    final rows = await services.sync.conflicts();
    state = ConflictState(
      items: rows.map(ConflictItem.fromRow).toList(),
      busy: state.busy,
      message: state.message,
      isError: state.isError,
    );
  }

  /// 推一次，看冲突有没有变化（用于"服务端那边后来又变了"的情形）。
  ///
  /// 冲突条目本来不会被 `pushPending` 重推（它只挑 `pending`），
  /// 所以这里先把它们退回 `pending`？**不** —— 那会把治疗师还没裁决的东西
  /// 擅自推上去。这里只做一次"重新确认"：查库刷新即可。
  Future<void> refresh() async {
    state = ConflictState(items: state.items, busy: true);
    await reload();
    state = ConflictState(items: state.items, busy: false);
  }

  /// **保留我的版本**：以服务端当前版本为基线重推。
  ///
  /// 服务端要的 `server_revision` 不在这条队列行里（它只出现在**冲突响应**中，
  /// 而那次响应早已过去，服务端此后可能又被别人改过）。所以分两步：
  ///
  ///  1. `requeueWithoutBase` 清空基线 → 服务端必然再判一次冲突，
  ///     这次响应里带回**当前的** `server_revision`；
  ///  2. 用它作为基线再推一次 → `base_revision == server_revision` → 直接应用。
  ///
  /// 第 1 步**必须清空基线而不是沿用旧基线**：留着旧基线时若恰好与服务端一致，
  /// 服务端会直接应用 —— 那就成了"推着推着悄悄覆盖"，而不是治疗师确认后的覆盖。
  Future<bool> keepMine(ConflictItem item) async {
    final services = ref.read(appServicesProvider).requireValue;
    state = ConflictState(items: state.items, busy: true);

    // 1) 清空基线退回 pending 并推，捕获服务端当前 revision。
    //
    // ★ 先确认队列行真的还在：不在了（多半是这条冲突已被"采用服务端"丢弃）
    //   就必须直接报错 —— 否则后面推不出冲突，会被误判成"已覆盖成功"。
    final stillQueued = await services.sync.requeueWithoutBase(item.clientUuid);
    if (!stillQueued) {
      await _afterDecision(
        '这条冲突已经不在待推送队列里了（可能刚被"采用服务端"处理过），请下拉刷新后重看',
        isError: true,
      );
      return false;
    }
    final first = await services.sync.pushPending();
    final conflict = first.conflicts
        .where((c) => c.clientUuid == item.clientUuid)
        .firstOrNull;
    final serverRevision = conflict?.serverRevision;

    if (serverRevision == null) {
      // 这次没冲突 → 说明已经应用成功（例如服务端那条已被别人改回可覆盖状态）。
      await _afterDecision('已用我的版本覆盖服务端');
      return true;
    }

    // 2) 用最新基线再推一次。
    await services.sync.keepMine(item.clientUuid, serverRevision);
    final second = await services.sync.pushPending();
    final applied = second.applied.any((a) => a.clientUuid == item.clientUuid);
    final stillConflict = second.conflicts.any((c) => c.clientUuid == item.clientUuid);

    if (applied) {
      await _afterDecision('已用我的版本覆盖服务端');
      return true;
    }
    if (stillConflict) {
      await _afterDecision(
        '服务端仍拒绝（该记录可能已锁定）；请联系管理员处理',
        isError: true,
      );
      return false;
    }
    await _afterDecision('已提交');
    return true;
  }

  /// **采用服务端版本**：丢掉本地这条变更，然后拉取一次让服务端版本落到本地。
  Future<bool> useServer(ConflictItem item) async {
    final services = ref.read(appServicesProvider).requireValue;
    state = ConflictState(items: state.items, busy: true);
    try {
      await services.sync.discardMine(item.clientUuid);
      // 必须拉一次：否则本地还留着"没推上去的改动"，与服务端不一致。
      await services.sync.pullIncremental();
      await _afterDecision('已采用服务端版本');
      return true;
    } on AppError catch (e) {
      await _afterDecision(
        e.code == 'NETWORK_ERROR' ? '离线中：已丢弃本地改动，但还没能同步服务端版本' : e.message,
        isError: e.code != 'NETWORK_ERROR',
      );
      return false;
    }
  }

  /// **全部采用服务端版本**（批量裁决）。
  Future<void> useServerForAll() async {
    final services = ref.read(appServicesProvider).requireValue;
    final uuids = state.items.map((i) => i.clientUuid).toList();
    if (uuids.isEmpty) return;
    state = ConflictState(items: state.items, busy: true);
    try {
      await services.sync.discardMany(uuids);
      await services.sync.pullIncremental();
      await _afterDecision('已全部采用服务端版本（${uuids.length} 条）');
    } on AppError catch (e) {
      await _afterDecision(
        e.code == 'NETWORK_ERROR' ? '离线中：已丢弃本地改动，联网后再同步' : e.message,
        isError: e.code != 'NETWORK_ERROR',
      );
    }
  }

  Future<void> _afterDecision(String message, {bool isError = false}) async {
    // 裁决会影响待同步计数与患者列表，统一失效。
    ref.invalidate(pendingCountProvider);
    final services = ref.read(appServicesProvider).requireValue;
    final rows = await services.sync.conflicts();
    state = ConflictState(
      items: rows.map(ConflictItem.fromRow).toList(),
      message: message,
      isError: isError,
    );
  }

  void clearMessage() => state = ConflictState(items: state.items);
}

final conflictControllerProvider =
    NotifierProvider<ConflictController, ConflictState>(ConflictController.new);

/// 冲突条数（响应式，用于「我的」页与同步提示上的角标）。
final conflictCountProvider = StreamProvider<int>((ref) {
  final services = ref.watch(appServicesProvider).requireValue;
  return services.sync.watchConflicts().map((rows) => rows.length);
});
