import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:rehab_app/core/providers.dart';
import 'package:rehab_app/data/repo/patient_repository.dart';
import 'package:rehab_app/features/patients/patients_providers.dart';

/// 患者表单：**新建**与**编辑**共用（2026-10-06）。
///
/// 字段与 Web 后台的「新建患者」一致（用户要求「字段同web后台的新建患者」）：
/// 住院编号 / 姓名 / 诊断 / 注意事项 / 状态。
///
/// 为什么做成一个 Sheet 而不是两个页面：
/// - 它只出现在患者列表与患者详情上，是**就地**动作，跳页会让治疗师丢失上下文；
/// - 新建与编辑字段几乎相同，共用一处就不会出现"后台加了字段、App 忘了加"。
///
/// ⚠ 两个字段的**可编辑性**不同，这是刻意的：
/// - **住院编号只在新建时可填**（它是主键，改它等于换一个患者）；
/// - **状态在编辑时才出现**（新建时后端只接受在院/暂停，且"新建一个已出院的患者"
///   会被后端以 `PATIENT_DISCHARGED_IMMUTABLE` 拒绝）。
class PatientFormSheet extends ConsumerStatefulWidget {
  const PatientFormSheet({super.key, this.existing});

  /// 非空 = 编辑该患者；为空 = 新建。
  final PatientView? existing;

  /// 弹出表单。返回 true 表示"确实保存了"（调用方据此刷新/提示）。
  static Future<bool> show(BuildContext context, {PatientView? existing}) async {
    final saved = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (_) => PatientFormSheet(existing: existing),
    );
    return saved == true;
  }

  @override
  ConsumerState<PatientFormSheet> createState() => _PatientFormSheetState();
}

class _PatientFormSheetState extends ConsumerState<PatientFormSheet> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _no;
  late final TextEditingController _name;
  late final TextEditingController _diagnosis;
  late final TextEditingController _note;
  late String _status;

  bool _saving = false;
  String? _error;

  bool get _isEdit => widget.existing != null;

  /// 状态选项。**不放"已出院"**：出院要走出院流程（小结 + 留痕），
  /// 从表单里直接选"已出院"会绕过它 —— 后端也会拒绝新建已出院的患者。
  static const _statuses = <String, String>{
    'in_hospital': '在院',
    'paused': '暂停',
  };

  /// 状态码 → 中文（界面一律显示中文，不给用户看 `pending_discharge` 这种原始值）。
  static String _statusLabel(String code) => const {
        'in_hospital': '在院',
        'paused': '暂停',
        'pending_discharge': '待出院',
        'discharged': '已出院',
      }[code] ??
      code;

  @override
  void initState() {
    super.initState();
    final p = widget.existing;
    _no = TextEditingController(text: p?.inpatientNo ?? '');
    _name = TextEditingController(text: p?.name ?? '');
    _diagnosis = TextEditingController(text: p?.diagnosis ?? '');
    _note = TextEditingController(text: p?.adminNote ?? '');
    // 已出院的患者进来编辑时，状态不在选项里 —— 退化成"在院"会让一次无辜的保存
    // 把它恢复成在院。所以保留原值，并在下面显式提示不能在这里改。
    _status = _statuses.containsKey(p?.status) ? p!.status : 'in_hospital';
  }

  @override
  void dispose() {
    _no.dispose();
    _name.dispose();
    _diagnosis.dispose();
    _note.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    final repo = ref.read(appServicesProvider).requireValue.patients;
    try {
      if (_isEdit) {
        await repo.update(
          widget.existing!.inpatientNo,
          name: _name.text.trim(),
          // 传空串是**清空**（`null` 才是"不改"）—— 治疗师把诊断删掉应当生效。
          diagnosis: _diagnosis.text.trim(),
          adminNote: _note.text.trim(),
          // 已出院的患者不在选项里，此时**不动状态**（改回在院要走恢复流程）。
          status: _statuses.containsKey(widget.existing!.status) ? _status : null,
        );
      } else {
        await repo.create(
          inpatientNo: _no.text.trim(),
          name: _name.text.trim(),
          diagnosis: _diagnosis.text.trim(),
          adminNote: _note.text.trim(),
          status: _status,
        );
      }
      // 新建/改名后列表要立刻反映（本地库已写入，这里让 provider 重读）。
      ref.invalidate(patientListProvider);
      if (mounted) Navigator.pop(context, true);
    } on Object catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _error = _describe(e);
      });
    }
  }

  /// 把后端的错误码翻成治疗师看得懂的一句话。
  String _describe(Object e) {
    final text = '$e';
    if (text.contains('NETWORK_ERROR')) {
      return '连不上服务器。建档需要联网（离线时可以照常记录治疗）。';
    }
    if (text.contains('PATIENT_EXISTS') || text.contains('已存在')) {
      return '这个住院编号已经建过档了，换一个编号，或去列表里找到那位患者。';
    }
    if (text.contains('PATIENT_DISCHARGED_IMMUTABLE')) {
      return '不能新建"已出院"的患者。请先建在院患者，再走出院流程。';
    }
    if (text.contains('PATIENT_NOT_VISIBLE')) {
      return '这位患者当前不在你的白板上（可能已出院），改不了。';
    }
    return text;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      // 键盘弹起时把表单顶上去，否则下面的字段被挡住。
      padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
      child: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 20),
          child: Form(
            key: _formKey,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        _isEdit ? '编辑患者' : '新建患者',
                        style: theme.textTheme.titleLarge
                            ?.copyWith(fontWeight: FontWeight.bold),
                      ),
                    ),
                    IconButton(
                      tooltip: '关闭',
                      onPressed:
                          _saving ? null : () => Navigator.pop(context, false),
                      icon: const Icon(Icons.close),
                    ),
                  ],
                ),
                const SizedBox(height: 8),

                if (_isEdit)
                  // 编号是主键，编辑时只读展示（改它等于换一个患者）。
                  Text('住院编号：${widget.existing!.inpatientNo}',
                      style: theme.textTheme.bodyMedium?.copyWith(
                        color: theme.colorScheme.outline,
                      ))
                else
                  TextFormField(
                    controller: _no,
                    autofocus: true,
                    textInputAction: TextInputAction.next,
                    decoration: const InputDecoration(
                      labelText: '住院编号 *',
                      hintText: '如 ZY2026001',
                      border: OutlineInputBorder(),
                    ),
                    validator: (v) =>
                        (v == null || v.trim().isEmpty) ? '请填住院编号' : null,
                  ),
                const SizedBox(height: 12),

                TextFormField(
                  controller: _name,
                  textInputAction: TextInputAction.next,
                  decoration: const InputDecoration(
                    labelText: '姓名 *',
                    border: OutlineInputBorder(),
                  ),
                  validator: (v) =>
                      (v == null || v.trim().isEmpty) ? '请填姓名' : null,
                ),
                const SizedBox(height: 12),

                TextFormField(
                  controller: _diagnosis,
                  maxLines: 2,
                  decoration: const InputDecoration(
                    labelText: '诊断',
                    hintText: '如 脑卒中恢复期',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 12),

                TextFormField(
                  controller: _note,
                  maxLines: 3,
                  decoration: const InputDecoration(
                    labelText: '注意事项',
                    hintText: '如 过敏、防跌倒、体位限制',
                    // 这里原来写了一句 helper「治疗师可以修改（2026-10-06 起不再是只读）」。
                    // 用户 2026-10-06：「那一行都去掉，标出来干什么？多余」——
                    // 确实多余：能改就是能改，把"现在已经不是只读"写在界面上是废话。
                    // 权限本身由后端门禁保证（见 api/v1/patients.py），不靠在界面上声明。
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 12),

                if (_isEdit && !_statuses.containsKey(widget.existing!.status))
                  // 已出院 / 待出院：状态不在选项里，也不能在这里改。
                  // 这一条**不是**废话，必须留：没有它，状态框会凭空消失，
                  // 用户不知道去哪改。只把原始状态码换成中文（原来会显示 discharged）。
                  Text(
                    '当前状态「${_statusLabel(widget.existing!.status)}」，'
                    '不在这里改 —— 请用患者页的出院/恢复操作。',
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: theme.colorScheme.outline),
                  )
                else
                  DropdownButtonFormField<String>(
                    initialValue: _status,
                    decoration: const InputDecoration(
                      labelText: '状态',
                      border: OutlineInputBorder(),
                    ),
                    items: [
                      for (final e in _statuses.entries)
                        DropdownMenuItem(value: e.key, child: Text(e.value)),
                    ],
                    onChanged: _saving
                        ? null
                        : (v) => setState(() => _status = v ?? _status),
                  ),

                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: theme.colorScheme.errorContainer,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      _error!,
                      style:
                          TextStyle(color: theme.colorScheme.onErrorContainer),
                    ),
                  ),
                ],

                const SizedBox(height: 18),
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton(
                        onPressed:
                            _saving ? null : () => Navigator.pop(context, false),
                        child: const Text('取消'),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: FilledButton(
                        onPressed: _saving ? null : _save,
                        child: _saving
                            ? const SizedBox(
                                width: 18,
                                height: 18,
                                child: CircularProgressIndicator(strokeWidth: 2),
                              )
                            : Text(_isEdit ? '保存' : '建档'),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
