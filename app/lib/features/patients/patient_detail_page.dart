import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/core/date_utils.dart';
import 'package:rehab_app/core/disciplines.dart';
import 'package:rehab_app/core/route_observer.dart';
import 'package:rehab_app/data/local/app_database.dart' as local;
import 'package:rehab_app/data/repo/record_repository.dart';
import 'package:rehab_app/features/patients/patients_providers.dart';
import 'package:rehab_app/features/records/record_page.dart';
import 'package:rehab_app/features/records/record_providers.dart';
import 'package:rehab_app/features/timeline/patient_summary_page.dart';

/// 患者详情。
///
/// ## "记录治疗"区域为什么是四个大类按钮
///
/// 用户原话：「患者详情中的治疗记录部分的内容，现在太过于繁琐，需要点好多次，
/// 不容易使用，改成类似模板这样」。所以这里**不再有二级选择**：
/// 四个大类**竖排**直接点，点进去就是一屏 chip 表单。
/// 每个按钮上直接写出「已记录 N 次」与「距复评还差 M 次」——
/// 治疗师不用进去才知道该记第几次、该不该复评。
///
/// ## 出院按钮
///
/// 用户原话：「在 app 记录治疗的**左侧对称位置**添加出院按钮，
/// 所有治疗师都可以有出院的权限，点击后就是出院小结」。
/// 所以它就在四个大类按钮**左边**，同一条横带上，任何治疗师都可见可用。
class PatientDetailPage extends ConsumerStatefulWidget {
  const PatientDetailPage({super.key, required this.inpatientNo});

  final String inpatientNo;

  @override
  ConsumerState<PatientDetailPage> createState() => _PatientDetailPageState();
}

class _PatientDetailPageState extends ConsumerState<PatientDetailPage>
    with RouteAware {
  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // 订阅路由变化：从记录页 / 汇总页 pop 回来时收到 `didPopNext()`。
    //
    // 用 `didChangeDependencies` 而不是 `initState`：订阅要拿 `ModalRoute.of`，
    // 而在 `initState` 里 `context` 还不能用。
    final route = ModalRoute.of(context);
    if (route is PageRoute) appRouteObserver.subscribe(this, route);
  }

  @override
  void dispose() {
    appRouteObserver.unsubscribe(this);
    super.dispose();
  }

  /// 又回到本页 → 全量刷一次患者。
  ///
  /// 用户 2026-10-05：「每次返回患者页自动刷新」。这一页最需要它：
  /// 停在详情页时患者可能被置为**待出院**，此时该页仍显示"在院"、
  /// 甚至允许继续点大类（点进去会被服务端 409 拦）。
  @override
  void didPopNext() {
    if (!mounted) return;
    // 走全量刷新（而不是只 invalidate 本地 provider）：状态变了的是**服务端**，
    // 只重读本地库拿到的还是旧状态。
    ref.read(patientSyncControllerProvider.notifier).refresh();
  }

  @override
  Widget build(BuildContext context) {
    final inpatientNo = widget.inpatientNo;
    final patient = ref.watch(patientDetailProvider(inpatientNo));
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('患者详情'),
        actions: [
          // 汇总/打印走服务端聚合，屏幕上看到的与打出来的 PDF 是同一份口径。
          IconButton(
            tooltip: '患者汇总与打印',
            icon: const Icon(Icons.summarize_outlined),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => PatientSummaryPage(inpatientNo: inpatientNo),
              ),
            ),
          ),
        ],
      ),
      body: patient.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('$e')),
        data: (p) {
          if (p == null) {
            return const Center(child: Text('本地没有这名患者，请先同步'));
          }

          final note = p.adminNote?.trim() ?? '';
          final records = ref.watch(localRecordsProvider(inpatientNo));
          final summaries = ref.watch(disciplineSummariesProvider(inpatientNo));

          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
            children: [
              if (note.isNotEmpty)
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: theme.colorScheme.errorContainer,
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(Icons.warning_amber_rounded,
                          color: theme.colorScheme.onErrorContainer),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '注意事项',
                              style: TextStyle(
                                fontWeight: FontWeight.bold,
                                color: theme.colorScheme.onErrorContainer,
                              ),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              note,
                              style: TextStyle(color: theme.colorScheme.onErrorContainer),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              if (note.isNotEmpty) const SizedBox(height: 16),

              Text(p.name, style: theme.textTheme.headlineSmall),
              const SizedBox(height: 4),
              Text(
                p.inpatientNo,
                style: theme.textTheme.titleMedium
                    ?.copyWith(color: theme.colorScheme.outline),
              ),
              const SizedBox(height: 16),

              _InfoRow(label: '诊断', value: p.diagnosis ?? '—'),
              _InfoRow(label: '状态', value: _statusLabel(p.status)),
              _InfoRow(
                label: '归属',
                // 优先显示**姓名**（服务端解析），拿不到才退回 id、再退回"未分配"。
                // 三级兜底写在 `PatientView.ownerLabel` 里，列表页也用同一口径。
                value: p.ownerLabel,
              ),

              const Divider(height: 32),
              Text('记录治疗', style: theme.textTheme.titleMedium),
              const SizedBox(height: 4),
              Text(
                '点大类直接记录；一屏勾选，点一下就是选中',
                style: TextStyle(fontSize: 12, color: theme.colorScheme.outline),
              ),
              const SizedBox(height: 10),
              if (p.status == 'pending_discharge' || p.status == 'discharged')
                _DischargedNotice(status: p.status)
              else
                // ★ 用户："在记录治疗的左侧对称位置添加出院按钮" ——
                // 让左边的出院按钮与右边的四大类按钮**等高**才叫对称。
                //
                // ⚠ 必须包 `IntrinsicHeight`：`Row` 在纵向 `ListView` 里高度**无界**，
                // 直接 `crossAxisAlignment: stretch` 会抛
                // `BoxConstraints forces an infinite height` ——
                // 而且异常发生在布局期，整页会**渲染成空白**（连错误提示都没有），
                // 现场看就是"点进患者详情一片白"。
                // `IntrinsicHeight` 先量出最高子项的固有高度，`stretch` 才有意义。
                IntrinsicHeight(
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      _DischargeButton(
                        patientNo: inpatientNo,
                        summaries: summaries.value ?? const [],
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: _DisciplineButtons(
                          patientNo: inpatientNo,
                          summaries: summaries,
                        ),
                      ),
                    ],
                  ),
                ),

              const Divider(height: 32),
              Text('治疗记录', style: theme.textTheme.titleMedium),
              const SizedBox(height: 4),
              Text(
                '按日期倒序；内容是 SOAP 文本（草稿未上传时标「待上传」）',
                style: TextStyle(fontSize: 12, color: theme.colorScheme.outline),
              ),
              const SizedBox(height: 8),

              records.when(
                loading: () => const Padding(
                  padding: EdgeInsets.all(16),
                  child: Center(child: CircularProgressIndicator()),
                ),
                error: (e, _) => Text('$e'),
                data: (rows) => rows.isEmpty
                    ? const Padding(
                        padding: EdgeInsets.symmetric(vertical: 16),
                        child: Text('还没有治疗记录'),
                      )
                    : Column(
                        children: [
                          for (final r in rows)
                            _RecordTile(
                              record: r,
                              // ★ 2026-10-05：用户要求「治疗记录要可以点进去，
                              // **在原始记录上进行修改**」→ 不再只让草稿可点。
                              // 后端 `EDITABLE_BY_OWNER = (draft, submitted)`，
                              // 已提交记录本来就能改（会走 `edit_count` 留痕）。
                              //
                              // 只有 `locked` 保持不可点：那是管理员锁定的归档记录，
                              // 普通治疗师改会被 403 —— 点了只会得到一个错误弹窗。
                              onTap: r.status == 'locked'
                                  ? null
                                  : () => _openExisting(context, r),
                            ),
                        ],
                      ),
              ),
            ],
          );
        },
      ),
    );
  }

  static String _statusLabel(String status) => switch (status) {
        'in_hospital' => '在院',
        'paused' => '暂停',
        'pending_discharge' => '待出院（已提交出院小结）',
        'discharged' => '已出院',
        _ => status,
      };

  /// 打开一条既有记录继续编辑（用户：「在原始记录上进行修改」）。
  void _openExisting(BuildContext context, local.TreatmentRecord row) {
    pushRecordEditor(
      context,
      RecordEditorArgs(
        patientNo: widget.inpatientNo,
        discipline: row.discipline,
        existingId: row.id,
        recordDate: row.recordDate,
        kind: row.kind == 'daily' ? null : row.kind,
      ),
    );
  }
}

/// 打开记录页并提示它的返回消息（三处入口共用）。
///
/// 做成顶层函数而不是成员：出院按钮与四大类按钮各自是**独立的小 widget**，
/// 它们不该为了弹个提示而把整个患者页的 State 传下来。
Future<void> pushRecordEditor(BuildContext context, RecordEditorArgs args) async {
  final messenger = ScaffoldMessenger.of(context);
  final message = await Navigator.of(context).push<String>(
    MaterialPageRoute<String>(builder: (_) => RecordPage(args: args)),
  );
  if (message == null || message.isEmpty) return;
  messenger
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(message)));
}

/// 出院按钮：与四个大类按钮同一条横带，在**左侧**。
///
/// 点它 → 直接取出院小结表单（`kind=discharge`）。出院小结是**按大类**写的
/// （每个大类有自己的 `discharge.json`，里面的"治疗过程汇总"只汇总该大类），
/// 所以大类多于一个有记录时，先问一句要写哪个大类的；只有一个就直接进，
/// 不再多一次点击。
class _DischargeButton extends ConsumerWidget {
  const _DischargeButton({required this.patientNo, required this.summaries});

  final String patientNo;
  final List<DisciplineSummary> summaries;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    return SizedBox(
      width: 96,
      child: OutlinedButton(
        style: OutlinedButton.styleFrom(
          padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 6),
          foregroundColor: theme.colorScheme.error,
          side: BorderSide(color: theme.colorScheme.error.withValues(alpha: 0.6)),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        ),
        onPressed: () => _start(context, ref),
        child: const Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.logout, size: 22),
            SizedBox(height: 6),
            Text('出院', style: TextStyle(fontWeight: FontWeight.bold)),
            SizedBox(height: 2),
            Text('出院小结', style: TextStyle(fontSize: 10)),
          ],
        ),
      ),
    );
  }

  Future<void> _start(BuildContext context, WidgetRef ref) async {
    // 摘要还没回来（离线且没缓存过）时也要能进：退回四大类的静态名单，
    // 点哪个大类就写哪个大类的出院小结。
    final rows = summaries.isEmpty
        ? [
            for (final d in Discipline.all)
              DisciplineSummary(key: d.key, name: d.name),
          ]
        : summaries;
    final withRecords =
        rows.where((s) => s.totalDaily > 0 || s.needsDocument).toList();
    final only = withRecords.length == 1
        ? withRecords.single
        : (rows.length == 1 ? rows.single : null);

    var picked = only;
    picked ??= await showModalBottomSheet<DisciplineSummary>(
        context: context,
        builder: (ctx) => SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Padding(
                padding: EdgeInsets.fromLTRB(16, 16, 16, 4),
                child: Text('出院小结写在哪个大类下？',
                    style: TextStyle(fontWeight: FontWeight.bold)),
              ),
              const Padding(
                padding: EdgeInsets.fromLTRB(16, 0, 16, 8),
                child: Text(
                  '每个大类有自己的出院小结（"治疗过程汇总"只汇总该大类）。',
                  style: TextStyle(fontSize: 12),
                ),
              ),
              for (final s in rows)
                ListTile(
                  leading: const Icon(Icons.description_outlined),
                  title: Text(s.name),
                  subtitle: Text(
                    s.error != null
                        ? s.error!
                        : '已记录 ${s.totalDaily} 次'
                            '${s.needsDocument ? ' · 待（${s.pendingDocumentLabel}）' : ''}',
                  ),
                  onTap: () => Navigator.pop(ctx, s),
                ),
              const SizedBox(height: 8),
            ],
          ),
        ),
      );
    if (picked == null || !context.mounted) return;

    await pushRecordEditor(
      context,
      RecordEditorArgs(
        patientNo: patientNo,
        // `picked` 在上面已经做过 null 判空并提前 return，这里不需要 `!`
        //（编译器会提示 unnecessary_non_null_assertion）。
        discipline: picked.key,
        kind: 'discharge',
        recordDate: formatDate(DateTime.now()),
      ),
    );
  }
}

/// 竖排四个大类按钮（用户要求"竖排"），每个显示次数与复评倒计时。
class _DisciplineButtons extends ConsumerWidget {
  const _DisciplineButtons({required this.patientNo, required this.summaries});

  final String patientNo;
  final AsyncValue<List<DisciplineSummary>> summaries;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return summaries.when(
      loading: () => const Padding(
        padding: EdgeInsets.symmetric(vertical: 12),
        child: Center(child: SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))),
      ),
      // 摘要取不到（离线且没缓存）时**仍然画出四个按钮**：点进去会自己再取一次。
      error: (e, _) => _buttons(
        context,
        [for (final d in Discipline.all) DisciplineSummary(key: d.key, name: d.name, error: '$e')],
      ),
      data: (rows) => _buttons(context, rows),
    );
  }

  Widget _buttons(BuildContext context, List<DisciplineSummary> rows) {
    return Column(
      children: [
        for (final s in rows)
          _DisciplineButton(patientNo: patientNo, summary: s),
      ],
    );
  }
}

class _DisciplineButton extends ConsumerWidget {
  const _DisciplineButton({required this.patientNo, required this.summary});

  final String patientNo;
  final DisciplineSummary summary;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final subtitle = summary.error != null
        ? summary.error!
        : [
            '已记录 ${summary.totalDaily} 次',
            summary.sessionsUntilReassessment > 0
                ? '距复评还差 ${summary.sessionsUntilReassessment} 次'
                : '已到复评点',
            if (summary.needsDocument) '需先填${summary.pendingDocumentLabel ?? ''}',
          ].join(' · ');

    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Material(
        color: theme.colorScheme.primaryContainer,
        borderRadius: BorderRadius.circular(10),
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: () => _open(context, ref),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        summary.name,
                        style: const TextStyle(
                            fontWeight: FontWeight.bold, fontSize: 15),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        subtitle,
                        style: TextStyle(
                          fontSize: 11,
                          color: theme.colorScheme.onPrimaryContainer
                              .withValues(alpha: 0.75),
                        ),
                      ),
                    ],
                  ),
                ),
                if (summary.needsDocument)
                  Icon(Icons.assignment_late_outlined,
                      size: 18, color: theme.colorScheme.error),
                const SizedBox(width: 4),
                const Icon(Icons.chevron_right, size: 20),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _open(BuildContext context, WidgetRef ref) async {
    await pushRecordEditor(
      context,
      RecordEditorArgs(
        patientNo: patientNo,
        discipline: summary.key,
        recordDate: formatDate(DateTime.now()),
      ),
    );
    // 记完之后次数/复评倒计时会变，重新取一次摘要。
    ref.invalidate(disciplineSummariesProvider(patientNo));
  }
}

class _DischargedNotice extends StatelessWidget {
  const _DischargedNotice({required this.status});

  final String status;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: theme.colorScheme.secondaryContainer,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.info_outline),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              status == 'discharged'
                  ? '该患者已出院，不能继续记录治疗。'
                  : '该患者已提交出院小结，处于「待出院」状态，不能再记新记录。'
                      '（管理员确认或满 7 天后正式出院；期间可取消待出院）',
              style: const TextStyle(fontSize: 13),
            ),
          ),
        ],
      ),
    );
  }
}

/// 一条本地记录：展示 SOAP 文本摘要（不再是"N 项"表格）。
class _RecordTile extends StatelessWidget {
  const _RecordTile({required this.record, this.onTap});

  final local.TreatmentRecord record;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final body = RecordRepository.decodeBody(record.bodyJson);
    final kindLabel = _kindLabel(record.kind);
    final summary = record.renderedText.trim().isNotEmpty
        ? _firstContentLine(record.renderedText)
        : _bodyLine(body);

    // 记录状态要一眼看到 —— 尤其"已锁定"和"已提交"的区别：
    // 前者点不动（管理员才能改），后者**可以点进去改**（用户 2026-10-05 要求）。
    final statusTag = switch (record.status) {
      'draft' => ' · 草稿',
      'locked' => ' · 已锁定',
      _ => '',
    };
    final locked = onTap == null;

    return ListTile(
      contentPadding: EdgeInsets.zero,
      enabled: !locked,
      leading: CircleAvatar(
        radius: 18,
        child: Text(
          record.seqNo?.toString() ?? _shortKind(record.kind),
          style: const TextStyle(fontSize: 11),
        ),
      ),
      title: Text(
        '${shortDateFromIso(record.recordDate)} · $kindLabel$statusTag',
      ),
      subtitle: Text(
        [
          if (record.seqNo != null) '第 ${record.seqNo} 次',
          if (summary.isNotEmpty) summary,
          if (record.syncStatus == 'pending') '待上传',
        ].join(' · '),
        maxLines: 3,
        overflow: TextOverflow.ellipsis,
      ),
      trailing: record.syncStatus == 'pending'
          ? Icon(Icons.cloud_upload_outlined,
              size: 18, color: theme.colorScheme.outline)
          : Icon(
              locked ? Icons.lock_outline : Icons.edit_outlined,
              size: 18,
              color: theme.colorScheme.outline,
            ),
      onTap: onTap,
    );
  }

  /// 本地草稿还没有服务端渲染文本时的**退化摘要**：`键=值` 连接。
  ///
  /// 只用键名（`complaint` 这类 key 没有中文标签可用）—— 它出现在"草稿还没
  /// 上传"的行里，治疗师点进去能看到完整表单，这里只求"这条记的是啥"有迹可循。
  static String _bodyLine(Map<String, dynamic> body) {
    if (body.isEmpty) return '';
    return body.entries.map((e) => '${e.key}=${e.value}').join('；');
  }

  /// 跳过标题行，取第一段正文（与服务端 `rendered_excerpt` 同口径）。
  static String _firstContentLine(String text) {
    for (final line in text.split('\n')) {
      final trimmed = line.trim();
      if (trimmed.isEmpty) continue;
      if (trimmed.startsWith('治疗日期')) continue;
      if (trimmed.contains('：')) return trimmed;
    }
    return text.split('\n').first;
  }

  static String _kindLabel(String kind) => switch (kind) {
        'initial' => '首评',
        'reassessment' => '复评',
        'discharge' => '出院小结',
        _ => '日常记录',
      };

  static String _shortKind(String kind) => switch (kind) {
        'initial' => '首',
        'reassessment' => '复',
        'discharge' => '出',
        _ => '日',
      };
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 96,
            child: Text(label,
                style: TextStyle(color: theme.colorScheme.outline)),
          ),
          Expanded(child: Text(value)),
        ],
      ),
    );
  }
}
