import 'package:flutter_test/flutter_test.dart';
import 'package:rehab_app/data/remote/record_dto.dart';

/// 长选项列表的**前置与折叠**（2026-10-06）。
///
/// 用户原话：「康复治疗记录的pt运动记录，客观资料中的本次训练项目，
/// 58项太多了，能不能将所有人最常用的10个放在前面，后面的可以折叠」。
///
/// 这一组只测**纯逻辑**（DTO 解析 + 排序），不测 widget：
/// 折叠的展开/收起由 `_ChipRow` 的 `_expanded` 控制，
/// 而它依赖表单能真的加载出来 —— 那部分交给集成/手工验证，
/// 这里先把"顺序对不对、折叠点从哪来"钉住。
void main() {
  Map<String, dynamic> formJson({Map<String, dynamic>? frequent, int? after}) => {
        'patient': {'inpatient_no': 'ZY001', 'name': '患者甲', 'status': 'in_hospital'},
        'discipline': 'PT',
        'discipline_name': '运动',
        'kind': 'daily',
        'kind_label': '日常治疗记录',
        'title': '康复治疗记录（PT运动）',
        'next_seq': 1,
        'total_daily': 0,
        'soap': [
          {
            'key': 'o',
            'label': '客观资料',
            'heading': '客观资料',
            'fields': [
              {
                'key': 'therapy_items',
                'type': 'multi',
                'label': '本次训练项目',
                'required': true,
                'options': ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L'],
                'collapsible_after': ?after,
              },
            ],
          },
        ],
        'frequent_options': ?frequent,
      };
  group('DTO', () {
    test('解析 frequent_options 与 collapsible_after', () {
      final form = RecordFormData.fromJson(
        formJson(frequent: {'therapy_items': ['K', 'A']}, after: 10),
      );
      expect(form.frequentOptions['therapy_items'], ['K', 'A']);
      final field = form.field('therapy_items')!;
      expect(field.collapsibleAfter, 10);
      expect(field.options.length, 12);
    });

    test('没有这两个字段时安全降级（老服务端 / 其它字段）', () {
      final form = RecordFormData.fromJson(formJson());
      expect(form.frequentOptions, isEmpty);
      expect(form.field('therapy_items')!.collapsibleAfter, isNull);
    });

    test('frequent_options 里不是列表的值不会崩', () {
      final form = RecordFormData.fromJson({
        ...formJson(),
        'frequent_options': {'therapy_items': null, 'other': 42},
      });
      expect(form.frequentOptions['therapy_items'], isEmpty);
      expect(form.frequentOptions['other'], isEmpty);
    });
  });

  group('折叠判定（模板决定阈值）', () {
    test('选项数 > collapsible_after 才该折叠', () {
      final many = RecordFormData.fromJson(formJson(after: 10));
      final field = many.field('therapy_items')!;
      expect(field.options.length > field.collapsibleAfter!, isTrue);

      // 阈值比选项还多 → 不折叠
      final few = RecordFormData.fromJson(formJson(after: 99));
      final f2 = few.field('therapy_items')!;
      expect(f2.options.length > f2.collapsibleAfter!, isFalse);
    });

    test('★ 折叠只影响"显示多少"，不改变 DTO 里的选项全集', () {
      // 折叠是**渲染层**的事：数据层必须保留全部选项，
      // 否则已选中的项如果恰好落在折叠区，回显就会丢。
      final form = RecordFormData.fromJson(formJson(after: 10));
      final field = form.field('therapy_items')!;
      expect(field.options, ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L']);
      expect(field.options.length, 12, reason: '12 项都要在，前 10 只是默认显示的部分');
    });
  });
}
