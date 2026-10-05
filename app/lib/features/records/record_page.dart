import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/core/date_utils.dart';
import 'package:rehab_app/data/remote/record_dto.dart';
import 'package:rehab_app/features/records/record_providers.dart';

/// 治疗记录页（SOAP 模板驱动，2026-10-05 脊柱级改造）。
///
/// ## 这一版为什么长这样
///
/// 用户的原始诉求是「点好多次，不容易使用」——旧版是「字典树 → 主项目 →
/// 子项目 → 参数表」四层展开，记一次治疗要点十几下。新版把它压成**一屏**：
///
/// 1. **按 `soap[]` 分段渲染**，每段就是「段名：若干 chip」——
///    点一下就是选中，不展开、不弹窗、不进二级页；
/// 2. `single` / `multi` 都是 chip（再点一下取消），选项多时（运动 58 项）
///    给搜索框，并把**最近用过的排到最前**（`recent_options` 本地记忆）；
/// 3. 只剩三个数字框与备注是键盘输入；
/// 4. **不自己判断该填哪份文书**：`kind` / `pending_document` / `prefill`
///    全由服务端 `GET /records/form` 算好，客户端照渲染（缺首评/复评时
///    服务端返回的就是那份文书）；
/// 5. 草稿允许残缺，必填校验只在提交时做（本地预检一次 + 服务端 422 兜底，
///    服务端给的 `details.missing` 是中文标签，直接标在字段上）。
class RecordPage extends ConsumerStatefulWidget {
  const RecordPage({super.key, required this.args});

  final RecordEditorArgs args;

  @override
  ConsumerState<RecordPage> createState() => _RecordPageState();
}

class _RecordPageState extends ConsumerState<RecordPage> {
  @override
  void initState() {
    super.initState();
    // build 期间不能改 provider 状态，放到首帧后。
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        ref.read(recordEditorProvider.notifier).start(widget.args);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(recordEditorProvider);
    final controller = ref.read(recordEditorProvider.notifier);

    // 出院办完就回患者页（那边会刷新状态）。
    ref.listen(recordEditorProvider, (previous, next) {
      if (next.discharged && previous?.discharged != true && mounted) {
        // 返回值是**给患者页显示的一句话**（记录页自己的消息条会随页面消失）。
        Navigator.of(context).pop('已提交出院，患者进入「待出院」');
        return;
      }
      // ★ 用户 2026-10-05：「记录完成后，没有返回患者页」。
      //
      // 提交成功后自动 `pop`，并把提示语交给患者页显示。
      // 只认 `submit`（存草稿不返回，见 `savedSubmitted` 的注释）。
      if (next.savedSubmitted &&
          previous?.savedSubmitted != true &&
          !next.discharged &&
          mounted) {
        final label = next.form?.kindLabel;
        Navigator.of(context).pop(
          label == null || label.isEmpty ? '已提交' : '已提交：$label',
        );
      }
    });

    return PopScope(
      // 有未保存改动时先问一句，避免床旁误返回把刚写的丢掉。
      canPop: !state.dirty,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        final leave = await _confirmDiscard(context, controller);
        if (leave && context.mounted) Navigator.of(context).pop();
      },
      child: Scaffold(
        appBar: AppBar(
          title: Text(state.form?.title ?? '治疗记录'),
          actions: [
            if (state.formFromCache)
              const Padding(
                padding: EdgeInsets.only(right: 8),
                child: Tooltip(
                  message: '离线：表单取自本地缓存，预填值可能不是最新',
                  child: Icon(Icons.cloud_off_outlined),
                ),
              ),
          ],
          bottom: state.message == null && state.error == null
              ? null
              : PreferredSize(
                  preferredSize: const Size.fromHeight(34),
                  child: _Bar(
                    text: state.error ?? state.message!,
                    isError: state.error != null,
                    onDismiss: controller.clearMessage,
                  ),
                ),
        ),
        body: state.loading
            ? const Center(child: CircularProgressIndicator())
            : state.form == null
                ? _LoadFailed(
                    message: state.error ?? '表单加载失败',
                    onRetry: controller.retry,
                  )
                : _SoapForm(state: state, controller: controller),
        bottomNavigationBar: state.form == null
            ? null
            : _BottomBar(state: state, controller: controller),
      ),
    );
  }

  Future<bool> _confirmDiscard(
    BuildContext context,
    RecordEditorController controller,
  ) async {
    final ok = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('还没保存'),
        content: const Text('这次改动还没保存，返回会丢掉。'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, 'stay'), child: const Text('继续填写')),
          TextButton(
            onPressed: () async {
              await controller.save(submit: false);
              if (ctx.mounted) Navigator.pop(ctx, 'saved');
            },
            child: const Text('存草稿并返回'),
          ),
          TextButton(onPressed: () => Navigator.pop(ctx, 'discard'), child: const Text('放弃改动')),
        ],
      ),
    );
    // "存草稿并返回"也算可以离开 —— 内容已经落到本地了。
    return ok == 'discard' || ok == 'saved';
  }
}

class _SoapForm extends StatelessWidget {
  const _SoapForm({required this.state, required this.controller});

  final RecordEditorState state;
  final RecordEditorController controller;

  @override
  Widget build(BuildContext context) {
    final form = state.form!;
    final body = controller.buildBody(form);
    final filled = body.length;
    final total = form.allFields.length;

    return ListView(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 24),
      children: [
        _HeaderCard(state: state, controller: controller, form: form),
        if (form.patientPendingDischarge) ...[
          const SizedBox(height: 10),
          const _Notice(
            icon: Icons.logout,
            text: '该患者已提交出院小结（待出院），不能再记新治疗记录。',
            isError: true,
          ),
        ],
        if (form.pendingDocument != null) ...[
          const SizedBox(height: 10),
          _Notice(
            icon: Icons.assignment_late_outlined,
            text: '本次需先完成「${form.pendingDocumentLabel ?? form.pendingDocument}」：'
                '${form.kindLabel}是独立的评估文书，不能跳过。'
                '填完保存后回到患者页再点一次这个大类，就能记当天的日常治疗记录。',
          ),
        ],
        const SizedBox(height: 10),
        _ProgressCard(filled: filled, total: total),
        const SizedBox(height: 10),
        for (final section in form.soap)
          _SectionCard(
            section: section,
            state: state,
            controller: controller,
          ),
        if (form.footer.isNotEmpty) ...[
          const SizedBox(height: 4),
          for (final line in form.footer)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(line,
                  style: TextStyle(
                      fontSize: 12, color: Theme.of(context).colorScheme.outline)),
            ),
        ],
        const SizedBox(height: 12),
        _PreviewCard(text: controller.previewText(form, body)),
        // 出院小结**已经提交过**、但出院还没办：给一个直接办理的入口
        //（离线写完小结后回到线上时的补救路径，不必重填）。
        if (form.isDischarge &&
            form.existing != null &&
            !form.existing!.isDraft) ...[
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: state.saving
                ? null
                : () => controller.requestDischarge(
                      serverRecordId: form.existing!.id,
                    ),
            icon: const Icon(Icons.logout),
            label: const Text('这份出院小结已提交 · 直接办理出院'),
          ),
        ],
      ],
    );
  }
}

/// 抬头：患者、文书形态、序号、复评倒计时、日期。
class _HeaderCard extends StatelessWidget {
  const _HeaderCard({
    required this.state,
    required this.controller,
    required this.form,
  });

  final RecordEditorState state;
  final RecordEditorController controller;
  final RecordFormData form;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    '${form.patientName} · ${form.patientNo}',
                    style: theme.textTheme.titleMedium
                        ?.copyWith(fontWeight: FontWeight.bold),
                  ),
                ),
                Chip(
                  visualDensity: VisualDensity.compact,
                  label: Text(form.kindLabel),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Wrap(
              spacing: 8,
              runSpacing: 4,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                // ★ 评估文书**不显示序号**（评定不占日常次数）。
                if (form.showsSeqNo)
                  _Tag(text: '第 ${form.nextSeq} 次'),
                if (form.showsSeqNo)
                  _Tag(
                    text: form.sessionsUntilReassessment > 0
                        ? '距复评还差 ${form.sessionsUntilReassessment} 次'
                        : '已到复评点',
                  ),
                _Tag(text: form.disciplineName),
                if (form.templateVersion > 1)
                  _Tag(text: '模板 v${form.templateVersion}'),
              ],
            ),
            const Divider(height: 20),
            Row(
              children: [
                Expanded(
                  child: InkWell(
                    onTap: () => _pickDate(context),
                    child: InputDecorator(
                      decoration: const InputDecoration(
                        labelText: '日期',
                        isDense: true,
                        border: OutlineInputBorder(),
                      ),
                      child: Text(shortDateFromIso(state.recordDate)),
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: InputDecorator(
                    decoration: const InputDecoration(
                      labelText: '内容',
                      isDense: true,
                      border: OutlineInputBorder(),
                    ),
                    child: Text(
                      '${form.allFields.length} 个字段（必填 '
                      '${form.allFields.where((f) => f.required).length}）',
                      style: const TextStyle(fontSize: 13),
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _pickDate(BuildContext context) async {
    final current = parseDate(state.recordDate) ?? DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: current,
      firstDate: DateTime(current.year - 2),
      lastDate: DateTime(current.year + 1),
    );
    if (picked != null) controller.setDate(picked);
  }
}

/// 一段（S / O / A / P）：段名 + 该段的字段。
class _SectionCard extends StatelessWidget {
  const _SectionCard({
    required this.section,
    required this.state,
    required this.controller,
  });

  final SoapSection section;
  final RecordEditorState state;
  final RecordEditorController controller;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final filled = section.fields
        .where((f) => SoapField.hasValue(state.values[f.key]))
        .length;
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(
                  '${section.heading}：',
                  style: theme.textTheme.titleSmall
                      ?.copyWith(fontWeight: FontWeight.bold),
                ),
                Text(
                  section.label,
                  style: TextStyle(fontSize: 11, color: theme.colorScheme.outline),
                ),
                const Spacer(),
                Text(
                  '$filled/${section.fields.length}',
                  style: TextStyle(fontSize: 11, color: theme.colorScheme.outline),
                ),
              ],
            ),
            const SizedBox(height: 6),
            for (final field in section.fields)
              _FieldBlock(
                field: field,
                state: state,
                controller: controller,
              ),
          ],
        ),
      ),
    );
  }
}

/// 单个字段：标签 + 控件（chip / 数字 / 文本）。
class _FieldBlock extends StatelessWidget {
  const _FieldBlock({
    required this.field,
    required this.state,
    required this.controller,
  });

  final SoapField field;
  final RecordEditorState state;
  final RecordEditorController controller;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final value = state.values[field.key];
    final isMissing = state.missingLabels.contains(field.label);

    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(field.label, style: const TextStyle(fontSize: 13)),
              if (field.required)
                Text(' *', style: TextStyle(color: theme.colorScheme.error)),
              if (field.unit != null && field.isNumber)
                Text(' (${field.unit})',
                    style: TextStyle(fontSize: 11, color: theme.colorScheme.outline)),
              const Spacer(),
              if (field.auto)
                Text('自动生成',
                    style: TextStyle(fontSize: 10, color: theme.colorScheme.outline)),
            ],
          ),
          const SizedBox(height: 4),
          if (isMissing)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text(
                '服务端说这一项必填，还没填',
                style: TextStyle(fontSize: 11, color: theme.colorScheme.error),
              ),
            ),
          _control(context, value),
        ],
      ),
    );
  }

  Widget _control(BuildContext context, dynamic value) {
    // 自动生成的字段（如出院小结的「治疗过程汇总」）由服务端算好，只读。
    if (field.auto) {
      return Container(
        width: double.infinity,
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.surfaceContainerHighest,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Text(
          SoapField.hasValue(value) ? SoapField.display(value) : '（服务端未给出内容）',
          style: const TextStyle(fontSize: 13),
        ),
      );
    }

    if (field.isSingle) {
      return _ChipRow(
        field: field,
        selected: {SoapField.display(value)},
        isMulti: false,
        controller: controller,
      );
    }

    if (field.isMulti) {
      final selected = <String>{
        if (value is List) ...value.map((e) => '$e'),
      };
      return _ChipRow(
        field: field,
        selected: selected,
        isMulti: true,
        controller: controller,
      );
    }

    if (field.isNumber) {
      return _NumberField(
        key: ValueKey('num:${field.key}'),
        field: field,
        value: value,
        onChanged: (v) => controller.setValue(field, v),
      );
    }

    return _TextField(
      key: ValueKey('text:${field.key}'),
      field: field,
      value: value,
      onChanged: (v) => controller.setValue(field, v),
    );
  }
}

/// 一排可点的 chip（单选 / 多选共用）。
///
/// 选项多时（如运动的 58 个疗法）自动出现**搜索框**，并把**最近用过的排最前**
/// ——用户的痛点就是"点好多次"，每天重复的那几项必须一点就到。
class _ChipRow extends StatefulWidget {
  const _ChipRow({
    required this.field,
    required this.selected,
    required this.isMulti,
    required this.controller,
  });

  final SoapField field;
  final Set<String> selected;
  final bool isMulti;
  final RecordEditorController controller;

  @override
  State<_ChipRow> createState() => _ChipRowState();
}

class _ChipRowState extends State<_ChipRow> {
  final _search = TextEditingController();
  String _query = '';

  /// 超过这个数量就给搜索框（吞咽只有 4 项，搜索框反而是干扰）。
  static const int _searchThreshold = 10;

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final field = widget.field;
    final ordered = widget.controller.orderedOptions(field);
    final query = _query.trim();
    final visible = query.isEmpty
        ? ordered
        : ordered.where((o) => o.toLowerCase().contains(query.toLowerCase())).toList();
    final showSearch = widget.isMulti && ordered.length > _searchThreshold;
    // 单选也可能很多（如"本次训练项目"以外的长清单），一样给搜索。
    final showSingleSearch = !widget.isMulti && ordered.length > _searchThreshold;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (showSearch || showSingleSearch) ...[
          TextField(
            controller: _search,
            decoration: InputDecoration(
              isDense: true,
              border: const OutlineInputBorder(),
              prefixIcon: const Icon(Icons.search, size: 18),
              hintText: '搜索（共 ${ordered.length} 项）',
              suffixIcon: query.isEmpty
                  ? null
                  : IconButton(
                      icon: const Icon(Icons.close, size: 18),
                      onPressed: () {
                        _search.clear();
                        setState(() => _query = '');
                      },
                    ),
            ),
            onChanged: (v) => setState(() => _query = v),
          ),
          const SizedBox(height: 6),
        ],
        if (visible.isEmpty)
          Text('没有匹配的选项',
              style: TextStyle(
                  fontSize: 12, color: Theme.of(context).colorScheme.outline))
        else
          Wrap(
            spacing: 6,
            runSpacing: 4,
            children: [
              for (final option in visible)
                widget.isMulti
                    ? FilterChip(
                        label: Text(option),
                        selected: widget.selected.contains(option),
                        avatar: widget.controller.isRecent(field, option)
                            ? const Icon(Icons.history, size: 14)
                            : null,
                        onSelected: (_) =>
                            widget.controller.toggleMulti(field, option),
                      )
                    : ChoiceChip(
                        label: Text(option),
                        selected: widget.selected.contains(option),
                        avatar: widget.controller.isRecent(field, option)
                            ? const Icon(Icons.history, size: 14)
                            : null,
                        // 再点一下取消选择。
                        onSelected: (_) =>
                            widget.controller.toggleSingle(field, option),
                      ),
            ],
          ),
      ],
    );
  }
}

/// 数字输入（带 `unit` 后缀）。
class _NumberField extends StatefulWidget {
  const _NumberField({
    super.key,
    required this.field,
    required this.value,
    required this.onChanged,
  });

  final SoapField field;
  final dynamic value;
  final ValueChanged<dynamic> onChanged;

  @override
  State<_NumberField> createState() => _NumberFieldState();
}

class _NumberFieldState extends State<_NumberField> {
  late final TextEditingController _text;

  @override
  void initState() {
    super.initState();
    _text = TextEditingController(text: widget.value?.toString() ?? '');
  }

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: _text,
      keyboardType: const TextInputType.numberWithOptions(decimal: true, signed: true),
      decoration: InputDecoration(
        isDense: true,
        border: const OutlineInputBorder(),
        suffixText: widget.field.unit,
        hintText: widget.field.hint,
      ),
      onChanged: (v) {
        // 数字存成数字（服务端按类型解析），空串表示"没填"。
        widget.onChanged(num.tryParse(v) ?? (v.isEmpty ? null : v));
      },
    );
  }
}

/// 多行文本（`hint` 当 placeholder）。
class _TextField extends StatefulWidget {
  const _TextField({
    super.key,
    required this.field,
    required this.value,
    required this.onChanged,
  });

  final SoapField field;
  final dynamic value;
  final ValueChanged<dynamic> onChanged;

  @override
  State<_TextField> createState() => _TextFieldState();
}

class _TextFieldState extends State<_TextField> {
  late final TextEditingController _text;

  @override
  void initState() {
    super.initState();
    _text = TextEditingController(text: widget.value?.toString() ?? '');
  }

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: _text,
      minLines: 2,
      maxLines: 4,
      decoration: InputDecoration(
        isDense: true,
        border: const OutlineInputBorder(),
        hintText: widget.field.hint,
      ),
      onChanged: widget.onChanged,
    );
  }
}

/// 填写进度（"还差几项"一眼可见，减少来回找）。
class _ProgressCard extends StatelessWidget {
  const _ProgressCard({required this.filled, required this.total});

  final int filled;
  final int total;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      children: [
        Icon(Icons.checklist, size: 16, color: theme.colorScheme.outline),
        const SizedBox(width: 6),
        Text('已填 $filled/$total 项',
            style: TextStyle(fontSize: 12, color: theme.colorScheme.outline)),
        const SizedBox(width: 8),
        Text('点一下就是选中，不必展开',
            style: TextStyle(fontSize: 11, color: theme.colorScheme.outline)),
      ],
    );
  }
}

/// 记录预览：与服务端渲染出来的 SOAP 文本同一排版（段名：字段；字段）。
class _PreviewCard extends StatelessWidget {
  const _PreviewCard({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: EdgeInsets.zero,
      child: ExpansionTile(
        title: const Text('记录预览', style: TextStyle(fontSize: 14)),
        subtitle: Text('输出就是这段文本（不是表格）',
            style: TextStyle(fontSize: 11, color: theme.colorScheme.outline)),
        childrenPadding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
        children: [
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: theme.colorScheme.surfaceContainerHighest,
              borderRadius: BorderRadius.circular(8),
            ),
            child: SelectableText(
              text,
              style: const TextStyle(fontSize: 12, height: 1.5),
            ),
          ),
        ],
      ),
    );
  }
}

class _Tag extends StatelessWidget {
  const _Tag({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: theme.colorScheme.secondaryContainer,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Text(text, style: const TextStyle(fontSize: 11)),
    );
  }
}

class _Notice extends StatelessWidget {
  const _Notice({required this.icon, required this.text, this.isError = false});

  final IconData icon;
  final String text;
  final bool isError;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: isError ? scheme.errorContainer : scheme.tertiaryContainer,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon,
              size: 18,
              color: isError ? scheme.onErrorContainer : scheme.onTertiaryContainer),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: TextStyle(
                fontSize: 12,
                color: isError ? scheme.onErrorContainer : scheme.onTertiaryContainer,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _BottomBar extends StatelessWidget {
  const _BottomBar({required this.state, required this.controller});

  final RecordEditorState state;
  final RecordEditorController controller;

  @override
  Widget build(BuildContext context) {
    final isDischarge = state.form?.isDischarge == true;
    final pending = state.form?.patientPendingDischarge == true;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
        child: Row(
          children: [
            Expanded(
              child: OutlinedButton(
                onPressed: state.saving ? null : () => controller.save(submit: false),
                child: const Text('存草稿'),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              flex: 2,
              child: FilledButton(
                onPressed: state.saving || pending
                    ? null
                    : () => controller.save(submit: true),
                child: state.saving
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2))
                    : Text(isDischarge ? '提交并办理出院' : '提交'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Bar extends StatelessWidget {
  const _Bar({required this.text, required this.isError, required this.onDismiss});

  final String text;
  final bool isError;
  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      width: double.infinity,
      color: isError ? scheme.errorContainer : scheme.secondaryContainer,
      padding: const EdgeInsets.only(left: 12, right: 4),
      child: Row(
        children: [
          Icon(isError ? Icons.warning_amber_outlined : Icons.cloud_done_outlined,
              size: 16),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(fontSize: 12),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ),
          IconButton(
            icon: const Icon(Icons.close, size: 16),
            onPressed: onDismiss,
            tooltip: '关闭',
            visualDensity: VisualDensity.compact,
          ),
        ],
      ),
    );
  }
}

class _LoadFailed extends StatelessWidget {
  const _LoadFailed({required this.message, required this.onRetry});

  final String message;
  final Future<void> Function() onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.error_outline, size: 44),
            const SizedBox(height: 10),
            const Text('打不开记录表单',
                style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
            const SizedBox(height: 6),
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 6),
            Text(
              '离线且本地没有缓存过这张表单时会出现这种情况；连一次网即可。',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.outline),
            ),
            const SizedBox(height: 16),
            FilledButton(onPressed: onRetry, child: const Text('重试')),
          ],
        ),
      ),
    );
  }
}
