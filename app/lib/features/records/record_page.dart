import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/core/date_utils.dart';
import 'package:rehab_app/core/worktime.dart';
import 'package:rehab_app/data/remote/record_dto.dart';
import 'package:rehab_app/features/records/record_providers.dart';

/// 治疗记录页（阶段 3 核心）。
///
/// ## 三个刻意的设计决定
///
/// 1. **不自己算"上次值/默认值"**：服务端 `GET /records/form` 已按 5 级带入
///    （上次值 → 个人选项集 → 科室 → 全局 → 字典默认）填好 `current_value`。
///    客户端重算一遍只会与服务端产生分歧。
/// 2. **草稿允许残缺**：必填校验**只在"提交"时做**。床旁先记一半（甚至只记
///    "做了关节松动"就被人叫走）是常态，强行挡住会让人放弃记录。
/// 3. **先本地 + 入队，再尽力推送**：床旁弱网/无网必须能存下来。
///
/// 编辑器是**单例** provider（不是 family），所以进入时要在 `initState` 里
/// `start(args)`；见 `RecordEditorController` 上的说明。
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
    final theme = Theme.of(context);

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
          title: Text(state.form?.patientName ?? '治疗记录'),
          actions: [
            if (state.formFromCache)
              const Padding(
                padding: EdgeInsets.only(right: 8),
                child: Tooltip(
                  message: '离线：表单取自本地缓存，带入值可能不是最新',
                  child: Icon(Icons.cloud_off_outlined),
                ),
              ),
          ],
          bottom: state.message == null && state.error == null
              ? null
              : PreferredSize(
                  preferredSize: const Size.fromHeight(30),
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
                : _Body(state: state, controller: controller, theme: theme),
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

class _Body extends StatelessWidget {
  const _Body({required this.state, required this.controller, required this.theme});

  final RecordEditorState state;
  final RecordEditorController controller;
  final ThemeData theme;

  @override
  Widget build(BuildContext context) {
    final form = state.form!;
    return ListView(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 24),
      children: [
        _PatientCard(state: state, controller: controller, form: form),
        const SizedBox(height: 12),

        _SectionTitle('可做的治疗项目', subtitle: '点参数直接加一项；同一项目可以加多次'),
        for (final main in form.mainItems)
          _MainItemCard(main: main, controller: controller),
        const SizedBox(height: 12),

        _SectionTitle(
          '本次治疗内容',
          subtitle: state.items.isEmpty ? '还没有加任何项目' : '共 ${state.items.length} 项',
        ),
        if (state.items.isEmpty)
          _Hint('在上面选一个项目的参数加进来；也可以只写患者反应。')
        else
          for (var i = 0; i < state.items.length; i++)
            _ItemEditor(
              index: i,
              item: state.items[i],
              form: form,
              controller: controller,
            ),
        const SizedBox(height: 12),

        _SectionTitle('患者反应', subtitle: '按反应定义填写；不填表示未评估'),
        _ResponseEditor(state: state, controller: controller),
        const SizedBox(height: 12),

        _SectionTitle('备注与时长'),
        TextField(
          controller: TextEditingController(text: state.note),
          minLines: 2,
          maxLines: 4,
          decoration: const InputDecoration(
            hintText: '本次治疗的补充说明（可留空）',
            border: OutlineInputBorder(),
          ),
          onChanged: controller.setNote,
        ),
        const SizedBox(height: 10),
        _DurationPicker(
          value: state.durationMin,
          onChanged: controller.setDuration,
        ),
      ],
    );
  }
}

class _PatientCard extends StatelessWidget {
  const _PatientCard({required this.state, required this.controller, required this.form});

  final RecordEditorState state;
  final RecordEditorController controller;
  final RecordFormData form;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final note = form.adminNote?.trim() ?? '';

    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (note.isNotEmpty) ...[
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: theme.colorScheme.errorContainer,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Row(
                  children: [
                    Icon(Icons.warning_amber_rounded,
                        size: 18, color: theme.colorScheme.onErrorContainer),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(note,
                          style: TextStyle(color: theme.colorScheme.onErrorContainer)),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 10),
            ],
            Row(
              children: [
                Expanded(
                  child: Text(
                    '${form.patientName} · ${form.patientNo}',
                    style: theme.textTheme.titleMedium
                        ?.copyWith(fontWeight: FontWeight.bold),
                  ),
                ),
                // 服务端按已完成次数给序号，这里只做提示。
                Chip(
                  visualDensity: VisualDensity.compact,
                  label: Text('第 ${form.nextSeqNo} 次'),
                ),
              ],
            ),
            if (form.diagnosis != null) ...[
              const SizedBox(height: 2),
              Text(form.diagnosis!,
                  style: TextStyle(color: theme.colorScheme.outline, fontSize: 13)),
            ],
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
                  child: DropdownButtonFormField<String?>(
                    initialValue: state.sessionPeriod,
                    decoration: const InputDecoration(
                      labelText: '半日',
                      isDense: true,
                      border: OutlineInputBorder(),
                    ),
                    items: [
                      const DropdownMenuItem(value: null, child: Text('未指定')),
                      for (final p in kPeriods)
                        DropdownMenuItem(value: p, child: Text(periodLabel(p))),
                    ],
                    onChanged: controller.setPeriod,
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

class _MainItemCard extends StatelessWidget {
  const _MainItemCard({required this.main, required this.controller});

  final FormMainItem main;
  final RecordEditorController controller;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ExpansionTile(
        title: Text(main.display, style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Text('${main.subItems.length} 个子项目',
            style: TextStyle(fontSize: 12, color: theme.colorScheme.outline)),
        childrenPadding: const EdgeInsets.fromLTRB(8, 0, 8, 10),
        children: [
          for (final sub in main.subItems)
            _SubItemRow(main: main, sub: sub, controller: controller),
        ],
      ),
    );
  }
}

class _SubItemRow extends StatelessWidget {
  const _SubItemRow({required this.main, required this.sub, required this.controller});

  final FormMainItem main;
  final FormSubItem sub;
  final RecordEditorController controller;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(sub.name),
                if (sub.params.isNotEmpty)
                  Text(
                    // 把带入值显示出来：治疗师一眼能确认"上次就是这么做的"。
                    sub.params
                        .map((p) => '${p.paramName}=${_displayValue(p.currentValue) ?? '—'}')
                        .join('  '),
                    style: TextStyle(fontSize: 11, color: theme.colorScheme.outline),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  )
                else
                  Text('无参数', style: TextStyle(fontSize: 11, color: theme.colorScheme.outline)),
              ],
            ),
          ),
          IconButton(
            tooltip: '加一项「${sub.name}」',
            icon: const Icon(Icons.add_circle_outline),
            onPressed: () => controller.addSubItem(main, sub),
          ),
        ],
      ),
    );
  }

  static String? _displayValue(dynamic v) {
    if (v == null) return null;
    if (v is List) return v.join('、');
    return '$v';
  }
}

/// 一条已加入的明细：可改参数、可删。
class _ItemEditor extends ConsumerWidget {
  const _ItemEditor({
    required this.index,
    required this.item,
    required this.form,
    required this.controller,
  });

  final int index;
  final RecordItemDraft item;
  final RecordFormData form;
  final RecordEditorController controller;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final main = form.mainItems.where((m) => m.id == item.mainItemId).firstOrNull;
    final sub = main?.subItems.where((s) => s.id == item.subItemId).firstOrNull;
    final theme = Theme.of(context);

    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 4, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    sub?.name ?? item.subItemName,
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                ),
                if (main != null)
                  Text(main.display,
                      style: TextStyle(fontSize: 11, color: theme.colorScheme.outline)),
                IconButton(
                  tooltip: '移除这一项',
                  icon: const Icon(Icons.delete_outline, size: 20),
                  onPressed: () => controller.removeItemAt(index),
                ),
              ],
            ),
            if (sub == null)
              Text('字典里已找不到这个子项目（可能被停用），参数无法编辑',
                  style: TextStyle(fontSize: 12, color: theme.colorScheme.error))
            else
              for (final p in sub.params)
                _ParamField(
                  param: p,
                  value: item.params[p.paramKey],
                  onChanged: (v) => controller.setItemParam(index, p.paramKey, v),
                ),
          ],
        ),
      ),
    );
  }
}

/// 单个参数控件：按 `input_type` 渲染。
class _ParamField extends StatefulWidget {
  const _ParamField({required this.param, required this.value, required this.onChanged});

  final FormParam param;
  final dynamic value;
  final ValueChanged<dynamic> onChanged;

  @override
  State<_ParamField> createState() => _ParamFieldState();
}

class _ParamFieldState extends State<_ParamField> {
  late final TextEditingController _text;

  @override
  void initState() {
    super.initState();
    _text = TextEditingController(text: widget.value?.toString() ?? '');
  }

  @override
  void didUpdateWidget(covariant _ParamField old) {
    super.didUpdateWidget(old);
    // 外部值变了（如"继续编辑"读回草稿）要同步到输入框，否则显示的是旧值。
    final incoming = widget.value?.toString() ?? '';
    if (incoming != _text.text && !_text.selection.isValid) {
      _text.text = incoming;
    }
  }

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = widget.param;
    final theme = Theme.of(context);
    final sourceLabel = p.valueSourceLabel ?? p.optionsSourceLabel;

    return Padding(
      padding: const EdgeInsets.only(right: 8, bottom: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(p.paramName, style: const TextStyle(fontSize: 13)),
              if (p.required) Text(' *', style: TextStyle(color: theme.colorScheme.error)),
              if (p.unit != null)
                Text(' (${p.unit})',
                    style: TextStyle(fontSize: 11, color: theme.colorScheme.outline)),
              const Spacer(),
              // 标注这个值是怎么来的 —— 治疗师需要知道"这是上次的值"还是"默认值"。
              if (sourceLabel != null)
                Text(sourceLabel,
                    style: TextStyle(fontSize: 10, color: theme.colorScheme.outline)),
            ],
          ),
          const SizedBox(height: 4),
          _control(p),
        ],
      ),
    );
  }

  Widget _control(FormParam p) {
    final candidates = p.candidates;

    if (p.isSelect && candidates.isNotEmpty) {
      if (p.isMulti) {
        // 初始值可能是数组，也可能是"空格/顿号分隔的字符串"（last_value 走库时）
        // —— 统一按 normalizeValue 解析，否则初始选中态显示不出来。
        final normalized = p.normalizeValue(widget.value);
        final selected = normalized is List
            ? normalized.map((e) => '$e').toSet()
            : <String>{};
        return Wrap(
          spacing: 6,
          runSpacing: 4,
          children: [
            for (final o in candidates)
              FilterChip(
                label: Text(o.label),
                selected: selected.contains(o.value),
                onSelected: (on) {
                  final next = {...selected};
                  on ? next.add(o.value) : next.remove(o.value);
                  // 多选**始终提交数组**：服务端对 multi_select 要求数组。
                  widget.onChanged(next.toList());
                  setState(() {});
                },
              ),
          ],
        );
      }
      return Wrap(
        spacing: 6,
        runSpacing: 4,
        children: [
          for (final o in candidates)
            ChoiceChip(
              label: Text(o.label),
              selected: '${widget.value}' == o.value,
              onSelected: (on) => widget.onChanged(on ? o.value : null),
            ),
        ],
      );
    }

    if (p.isBool) {
      return SwitchListTile(
        contentPadding: EdgeInsets.zero,
        dense: true,
        title: const Text('是', style: TextStyle(fontSize: 13)),
        value: widget.value == true || widget.value == 'true' || widget.value == 1,
        onChanged: (v) => widget.onChanged(v),
      );
    }

    // number / text / 没有候选值的 select 都退化成一个输入框。
    return TextField(
      controller: _text,
      keyboardType: p.isNumber
          ? const TextInputType.numberWithOptions(decimal: true, signed: true)
          : TextInputType.text,
      decoration: const InputDecoration(isDense: true, border: OutlineInputBorder()),
      onChanged: (v) {
        if (p.isNumber) {
          final parsed = num.tryParse(v);
          // 数字字段存成数字，别把 "3" 当字符串存进去（服务端按类型解析）。
          widget.onChanged(parsed ?? (v.isEmpty ? null : v));
        } else {
          widget.onChanged(v);
        }
      },
    );
  }
}

class _ResponseEditor extends StatefulWidget {
  const _ResponseEditor({required this.state, required this.controller});

  final RecordEditorState state;
  final RecordEditorController controller;

  @override
  State<_ResponseEditor> createState() => _ResponseEditorState();
}

class _ResponseEditorState extends State<_ResponseEditor> {
  final _texts = <String, TextEditingController>{};

  @override
  void dispose() {
    for (final c in _texts.values) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final defs = widget.state.form!.responseDefs;
    if (defs.isEmpty) {
      return const _Hint('字典里还没有配置患者反应定义');
    }
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (final d in defs) ...[
              Text(d.label, style: const TextStyle(fontSize: 13)),
              const SizedBox(height: 4),
              _control(d),
              const SizedBox(height: 10),
            ],
          ],
        ),
      ),
    );
  }

  Widget _control(ResponseDef d) {
    switch (d.valueType) {
      case 'tag':
        // tag 型：多选标签。选项来自定义本身，也可能为空（退化成输入框）。
        if (d.options.isEmpty) {
          return const _Hint('该反应未配置选项');
        }
        return Wrap(
          spacing: 6,
          runSpacing: 4,
          children: [
            for (final o in d.options)
              FilterChip(
                label: Text(o),
                selected: widget.state.responseTags.contains(o),
                onSelected: (_) {
                  widget.controller.toggleResponseTag(o);
                  setState(() {});
                },
              ),
          ],
        );

      case 'select':
        return DropdownButtonFormField<String?>(
          initialValue:
              widget.state.responseItems[d.code]?.toString(),
          decoration: const InputDecoration(isDense: true, border: OutlineInputBorder()),
          items: [
            const DropdownMenuItem(value: null, child: Text('未选择')),
            for (final o in d.options) DropdownMenuItem(value: o, child: Text(o)),
          ],
          onChanged: (v) {
            widget.controller.setResponseItem(d.code, v);
            setState(() {});
          },
        );

      case 'number':
        final ctrl = _texts.putIfAbsent(d.code, () => TextEditingController());
        return TextField(
          controller: ctrl,
          keyboardType: const TextInputType.numberWithOptions(decimal: true, signed: true),
          decoration: InputDecoration(
            isDense: true,
            border: const OutlineInputBorder(),
            suffixText: d.valueUnit,
            helperText: (d.valueMin != null || d.valueMax != null)
                ? '范围 ${d.valueMin ?? '-∞'} ~ ${d.valueMax ?? '+∞'}'
                : null,
          ),
          onChanged: (v) => widget.controller
              .setResponseItem(d.code, num.tryParse(v) ?? (v.isEmpty ? null : v)),
        );

      default:
        final ctrl = _texts.putIfAbsent(d.code, () => TextEditingController());
        return TextField(
          controller: ctrl,
          decoration: const InputDecoration(isDense: true, border: OutlineInputBorder()),
          onChanged: (v) => widget.controller.setResponseItem(d.code, v),
        );
    }
  }
}

class _DurationPicker extends StatelessWidget {
  const _DurationPicker({required this.value, required this.onChanged});

  final int? value;
  final ValueChanged<int?> onChanged;

  static const _presets = [15, 20, 30, 45, 60];

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 6,
      runSpacing: 4,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        const Text('治疗时长', style: TextStyle(fontSize: 13)),
        for (final m in _presets)
          ChoiceChip(
            label: Text('$m 分钟'),
            selected: value == m,
            onSelected: (on) => onChanged(on ? m : null),
          ),
      ],
    );
  }
}

class _BottomBar extends StatelessWidget {
  const _BottomBar({required this.state, required this.controller});

  final RecordEditorState state;
  final RecordEditorController controller;

  @override
  Widget build(BuildContext context) {
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
                onPressed: state.saving ? null : () => controller.save(submit: true),
                child: state.saving
                    ? const SizedBox(
                        width: 20, height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2))
                    : const Text('提交'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.title, {this.subtitle});

  final String title;
  final String? subtitle;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 6, top: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Text(title,
              style: theme.textTheme.titleSmall
                  ?.copyWith(fontWeight: FontWeight.bold)),
          if (subtitle != null) ...[
            const SizedBox(width: 8),
            Expanded(
              child: Text(subtitle!,
                  style: TextStyle(fontSize: 11, color: theme.colorScheme.outline)),
            ),
          ],
        ],
      ),
    );
  }
}

class _Hint extends StatelessWidget {
  const _Hint(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Text(text,
          style: TextStyle(
              fontSize: 12, color: Theme.of(context).colorScheme.outline)),
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
          Icon(isError ? Icons.warning_amber_outlined : Icons.cloud_done_outlined, size: 16),
          const SizedBox(width: 8),
          Expanded(child: Text(text, style: const TextStyle(fontSize: 13))),
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
