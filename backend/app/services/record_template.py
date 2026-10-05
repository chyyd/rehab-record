"""康复记录模板：加载与渲染（纯函数，无副作用）。

## 为什么要有这一层

模板是 **JSON 文件**（`templates/*.json`），不是数据库表 —— 用户要求
「使用 json 格式保存模板，不进数据库，以便以后我手动修改」。

★ 核心设计：**同一份模板同时驱动「填」和「印」**。
  表单从 `soap[].fields` 渲染，SOAP 文本也从同样的 `soap[].fields` 渲染。
  这样不可能出现「界面改了、打印没跟上」的漂移 —— 那是旧表格方案最大的隐患。

## 历史病历不随模板变

记录落库时把渲染结果**冻结**存进 `rendered_text`，而不是每次从 JSON 重算。
理由：用户以后手改模板时，**旧病历的措辞不应该跟着变** —— 病历是法律文书。

## 输出形态

    康复治疗记录（PT运动）
    治疗日期：2026-10-06   第 2 次

    主观资料：精神状态：良好；主诉：乏力；疼痛VAS：2分；训练配合度：良好

    客观资料：本次训练项目：偏瘫肢体综合训练/平衡功能训练；维持站立时间：45s

    评估分析：本次训练功能表现：较前改善；当前训练方案：有效

    康复计划：后续安排：继续维持原方案；安全与宣教：继续落实防跌倒宣教

    治疗师签名：__________

**所有形态统一**这一段一行的排版（用户 2026-10-05：「A 形式是正确的，其他的记录也要这样」）。
段首是中文段名 + 冒号，段内字段用 `；` 连接，字段值内部用 `/` 连接多选。
没填的字段**整条不出现**（模板第 3 条规则：「删除不需要的选项，保留选中项」）。

**多日记录**按时间顺序往下排（用户：「多日的情况下，是按时间顺序往下排就行，
不用一天一张」），所以渲染器只负责单条；多条由调用方按日期拼接，不插分页符。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 模板根目录：仓库根的 `templates/`
TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "templates"

KINDS = ("initial", "daily", "reassessment", "discharge")

# 形态 → 中文名（界面与输出都用）
KIND_LABELS = {
    "initial": "首评",
    "daily": "日常治疗记录",
    "reassessment": "阶段性复评",
    "discharge": "出院小结",
}

# 复评触发周期（用户 2026-10-05 定：每 20 次治疗后复评）
REASSESS_EVERY = 20

SEP_INLINE = "；"
SEP_MULTI = "/"


class TemplateError(Exception):
    """模板文件有问题（缺文件、JSON 语法错、字段不合法）。"""


@dataclass(frozen=True)
class Template:
    discipline: str
    kind: str
    title: str
    soap: list[dict[str, Any]]
    footer: list[str] = field(default_factory=list)
    version: int = 1
    subtitle: str | None = None
    trigger: dict[str, Any] = field(default_factory=dict)
    source: Path | None = None

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)

    @property
    def mandatory(self) -> bool:
        return bool(self.trigger.get("mandatory"))

    def all_fields(self) -> list[dict[str, Any]]:
        return [f for sec in self.soap for f in sec.get("fields", [])]

    def field(self, key: str) -> dict[str, Any] | None:
        for f in self.all_fields():
            if f["key"] == key:
                return f
        return None


# --------------------------------------------------------------------------- #
# 加载
# --------------------------------------------------------------------------- #
def _therapy_options(discipline: str) -> list[str]:
    data = _load_json(TEMPLATES_DIR / "disciplines.json")
    for d in data.get("disciplines", []):
        if d["key"] == discipline:
            return list(d.get("therapy_options", []))
    raise TemplateError(f"disciplines.json 里没有大类 {discipline!r}")


_JSON_CACHE: dict[Path, Any] = {}


def _load_json(path: Path) -> Any:
    """读 JSON（带缓存）。注意缓存的是**文件内容**，改文件后要重开进程或调 clear_cache()。"""
    if path in _JSON_CACHE:
        return _JSON_CACHE[path]
    if not path.exists():
        raise TemplateError(f"模板文件不存在：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TemplateError(f"{path.name} 不是合法 JSON：{exc}") from None
    _JSON_CACHE[path] = data
    return data


def clear_cache() -> None:
    """清缓存（测试与「改完模板想立刻生效」时用）。"""
    _JSON_CACHE.clear()


def template_path(discipline: str, kind: str) -> Path:
    return TEMPLATES_DIR / discipline / f"{kind}.json"


def load(discipline: str, kind: str) -> Template:
    """加载一份模板，并把 `options_source` 占位符展开成真实选项。"""
    if kind not in KINDS:
        raise TemplateError(f"未知形态 {kind!r}，只支持 {KINDS}")
    raw = _load_json(template_path(discipline, kind))

    soap: list[dict[str, Any]] = []
    for section in raw.get("soap", []):
        fields: list[dict[str, Any]] = []
        for f in section.get("fields", []):
            f = dict(f)
            if f.get("options_source") == "therapy_options":
                # 占位符 → 该大类的疗法清单（只改 disciplines.json 一处即可）
                f["options"] = _therapy_options(discipline)
                f.pop("options_source", None)
            if f["type"] in ("single", "multi") and not f.get("options") and not f.get("allow_other"):
                raise TemplateError(
                    f"{discipline}/{kind}.json 的字段 {f['key']!r} 是 {f['type']} 但没有 options"
                )
            fields.append(f)
        soap.append({**section, "fields": fields})

    return Template(
        discipline=raw["discipline"],
        kind=raw["kind"],
        title=raw["title"],
        soap=soap,
        footer=list(raw.get("footer", [])),
        version=int(raw.get("version", 1)),
        subtitle=raw.get("subtitle"),
        trigger=dict(raw.get("trigger", {})),
        source=template_path(discipline, kind),
    )


def load_disciplines() -> list[dict[str, Any]]:
    """四个大类定义（按 order 排序）。"""
    data = _load_json(TEMPLATES_DIR / "disciplines.json")
    return sorted(data.get("disciplines", []), key=lambda d: d.get("order", 99))


def load_all() -> dict[str, dict[str, Template]]:
    """{大类: {形态: 模板}} —— 缺哪个形态一目了然。"""
    out: dict[str, dict[str, Template]] = {}
    for d in load_disciplines():
        out[d["key"]] = {}
        for kind in KINDS:
            try:
                out[d["key"]][kind] = load(d["key"], kind)
            except TemplateError:
                pass
    return out


# --------------------------------------------------------------------------- #
# 触发：该用哪种形态
# --------------------------------------------------------------------------- #
def counts_as_session(kind: str) -> bool:
    """这种形态是否计入「该大类第几次治疗」。

    ★ **只有日常记录计数**（用户 2026-10-05 纠正）：
      「评定并不占用日常训练的次数，比如第一次首评后，当天还是要有一个日常记录
        用来记录当天的训练。复评和出院小结也是。」

    所以首评/复评/出院小结是**独立文书**，与当天的日常记录**并存**：
    第 1 天会有两条（首评 + 日常记录，后者算第 1 次）；
    第 21 天也有两条（复评 + 日常记录，后者算第 21 次）。

    >>> [counts_as_session(k) for k in ("initial", "daily", "reassessment", "discharge")]
    [False, True, False, False]
    """
    return kind == "daily"


def kind_for_seq(seq_no: int) -> str:
    """按「该大类已有多少次**日常记录**」决定今天该填哪种形态。

    注意 `seq_no` 是**日常记录**的序号（不含首评/复评/出院小结）。

    - 第 1 次日常 → 同时需要首评（首评是独立文书，不占次数）
    - 每满 20 次日常后（即第 21、41、61… 次日常）→ 同时需要复评

    >>> [kind_for_seq(n) for n in (1, 2, 20, 21, 40, 41, 61)]
    ['initial', 'daily', 'daily', 'reassessment', 'daily', 'reassessment', 'reassessment']

    ⚠ 返回值表示「除了日常记录之外，还需要哪份文书」；`daily` 表示不需要额外文书。
    日常记录本身**每次都填**。
    """
    if seq_no <= 1:
        return "initial"
    if (seq_no - 1) % REASSESS_EVERY == 0:
        return "reassessment"
    return "daily"


def pending_documents(seq_no: int) -> list[str]:
    """今天需要补的**评估文书**列表（不含日常记录本身）。

    >>> pending_documents(1)
    ['initial']
    >>> pending_documents(2)
    []
    >>> pending_documents(21)
    ['reassessment']
    """
    kind = kind_for_seq(seq_no)
    return [] if kind == "daily" else [kind]


def required_document_for_next(seq_no: int) -> str | None:
    """要记「第 `seq_no` 次日常记录」，**先**必须完成哪份评估文书。

    用户 2026-10-05（三条都选「不能跳过」）：
      「1A。2不能。3不能。」
    即点击大类后**先弹评估文书**，填完再填当天的日常记录；三者都是硬阻断。

    评估文书与它对应的日常记录**绑定在同一个序号**上，所以「是否已完成」的判定是
    「存在区间标识 = 本序号的该形态记录吗」，由调用方查库后把集合传进来。

    - 第 1 次日常 → 必须先有 `initial`（区间标识 1）
    - 第 21、41、61… 次日常 → 必须先有 `reassessment`（区间标识 21/41/61…）
    - 其余 → None（直接记日常）

    >>> required_document_for_next(1)
    'initial'
    >>> required_document_for_next(2) is None
    True
    >>> required_document_for_next(21)
    'reassessment'
    """
    if seq_no <= 1:
        return "initial"
    if (seq_no - 1) % REASSESS_EVERY == 0:
        return "reassessment"
    return None


def assessment_span_seq(seq_no: int) -> int:
    """评估文书要挂在哪个日常序号上（= 它对应的那一次日常）。

    - 首评 → 1
    - 复评 → 21 / 41 / 61…（就是触发它的那个日常序号）

    这样「该序号下有没有这份文书」就是一个简单查询，不需要额外状态。
    """
    if seq_no <= 1:
        return 1
    if (seq_no - 1) % REASSESS_EVERY == 0:
        return seq_no
    # 落在两次复评之间：归属到最近一次复评点（唯一的复评点为 21、41、61…）
    return ((seq_no - 1) // REASSESS_EVERY) * REASSESS_EVERY + 1


def next_session_gate(
    next_seq: int,
    *,
    has_initial: bool,
    reassessment_spans: set[int] | None = None,
) -> str | None:
    """记「第 `next_seq` 次日常」之前还缺哪份文书（None = 可以记）。

    `reassessment_spans` 是**已存在的复评**所挂的序号集合
    （即 `[r.span_seq for r in 该大类的复评记录]`）。

    >>> next_session_gate(1, has_initial=False)
    'initial'
    >>> next_session_gate(1, has_initial=True) is None
    True
    >>> next_session_gate(21, has_initial=True, reassessment_spans=set())
    'reassessment'
    >>> next_session_gate(21, has_initial=True, reassessment_spans={21}) is None
    True
    """
    missing = required_document_for_next(next_seq)
    if missing is None:
        return None
    if missing == "initial":
        return None if has_initial else "initial"
    spans = reassessment_spans or set()
    return None if assessment_span_seq(next_seq) in spans else "reassessment"


def sessions_until_reassessment(seq_no: int) -> int:
    """还差几次**日常记录**到下一次复评（已到点则为 0）。界面用来显示「12/20」。"""
    if seq_no < 1:
        return REASSESS_EVERY
    done = seq_no - 1
    remainder = done % REASSESS_EVERY
    return 0 if remainder == 0 and seq_no > 1 else REASSESS_EVERY - remainder


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #
def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple)):
        return any(_has_value(v) for v in value)
    return True


def render_value(field_def: dict[str, Any], value: Any, label: str | None = None) -> str | None:
    """把一个字段渲染成 `标签：值`；没填返回 None。

    - single  → 取到的那个选项
    - multi   → 选项用 `/` 连接（模板规则：「选项用/分隔」）
    - number  → 数字 + 单位（`3分`）
    - text    → 原样
    """
    if not _has_value(value):
        return None
    name = label if label is not None else field_def["label"]
    ftype = field_def["type"]

    if ftype == "multi":
        values = [value] if isinstance(value, str) else [str(v) for v in value if _has_value(v)]
        if not values:
            return None
        body = SEP_MULTI.join(values)
    elif ftype == "number":
        body = str(value).strip()
        unit = field_def.get("unit")
        if unit:
            body = f"{body}{unit}"
    else:
        body = str(value).strip()

    return f"{name}：{body}"


def render(
    template: Template,
    answers: dict[str, Any],
    *,
    record_date: str | None = None,
    seq_no: int | None = None,
    total_sessions: int | None = None,
    extra_header: list[str] | None = None,
) -> str:
    """渲染成 SOAP 纯文本（模板风格，**不是表格**）。

    `answers` 的键是字段 key；`auto` 字段由调用方预先算好放进 answers
    （渲染器不做数据查询，保持纯函数）。

    ★ `seq_no` 是**日常记录**的序号。评估文书（首评/复评/出院小结）不占次数
      （用户 2026-10-05 纠正），所以它们**不显示序号** —— 否则「出院小结 第 21 次」
      会让人以为这是第 21 次治疗记录。出院小结改显示「共治疗 N 次」。
    """
    lines: list[str] = [template.title]
    if template.subtitle:
        lines.append(template.subtitle)

    header: list[str] = []
    if record_date:
        header.append(f"治疗日期：{record_date}")
    if seq_no is not None and counts_as_session(template.kind):
        header.append(f"第 {seq_no} 次")
    if total_sessions is not None and template.kind == "discharge":
        header.append(f"共治疗 {total_sessions} 次")
    header.extend(extra_header or [])
    if header:
        lines.append("   ".join(header))

    for section in template.soap:
        rendered: list[tuple[dict[str, Any], str]] = []
        for f in section["fields"]:
            # visible_in 限定：字段只在指定形态出现
            only = f.get("visible_in")
            if only and template.kind not in only:
                continue
            text = render_value(f, answers.get(f["key"]))
            if text:
                rendered.append((f, text))
        if not rendered:
            # 整段都没填就整段不出现 —— 空标题比空内容更让人困惑
            continue

        lines.append("")
        # 排版固定为「段名：字段；字段；字段」—— 用户 2026-10-05 指定：
        # 「主观资料：后面接各个字段。换行。客观资料：各个字段。以此类推。」
        # 并且「A 形式是正确的，其他的记录也要这样」——**所有形态统一**，
        # 所以模板里不再需要（也不再允许）逐段配置 inline。
        lines.append(section["heading"] + "：" + SEP_INLINE.join(t for _, t in rendered))

    if template.footer:
        lines.append("")
        lines.extend(template.footer)

    return "\n".join(lines)


def blank_answers(template: Template) -> dict[str, Any]:
    """空答案（多选给空列表，其余 None）—— App 新建记录时的初值。"""
    out: dict[str, Any] = {}
    for f in template.all_fields():
        out[f["key"]] = [] if f["type"] == "multi" else None
    return out


def apply_prefill(
    template: Template,
    answers: dict[str, Any],
    *,
    last_assessment: dict[str, Any] | None = None,
    last_daily: dict[str, Any] | None = None,
    same_day_first: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按模板的 `prefill` 声明套用预填值（用户 2026-10-05 定的策略）。

    - `last_assessment`  复评/出院：带出该大类上一次评估的值，治疗师只改变化的项
    - `last_daily`       日常记录：**只**带出上次的「本次训练项目」
    - `same_day_first`   同一天同大类第 2 条：带出第 1 条的**全部**内容

    优先级：same_day_first > 字段自己的 prefill 声明。
    """
    out = dict(answers)
    for f in template.all_fields():
        key = f["key"]
        if same_day_first and key in same_day_first:
            out[key] = same_day_first[key]
            continue
        strategy = f.get("prefill")
        if strategy == "last_assessment" and last_assessment and key in last_assessment:
            out[key] = last_assessment[key]
        elif strategy == "last_daily" and last_daily and key in last_daily:
            out[key] = last_daily[key]
    return out


def validate_answers(template: Template, answers: dict[str, Any]) -> list[str]:
    """返回缺失的必填字段名（空列表 = 通过）。

    ★ 只校验 `required: true` 的字段。模板作者要克制：必填项加太多会拖慢床旁录入。
    """
    missing: list[str] = []
    for f in template.all_fields():
        if not f.get("required"):
            continue
        only = f.get("visible_in")
        if only and template.kind not in only:
            continue
        if not _has_value(answers.get(f["key"])):
            missing.append(f["label"])
    return missing
