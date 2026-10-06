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
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date as _date
from datetime import timedelta
from pathlib import Path
from typing import Any

# 模板根目录。
#
# 默认是**仓库根的 `templates/`**（本地开发的布局：`backend/app/services/x.py`
# 上溯三层 = 仓库根）。但这个推导在**容器**里不成立 —— 镜像里通常把
# `backend/` 放到 `/app`、`templates/` 放到 `/templates`，两者不再同级。
#
# 所以留一个 `KB_TEMPLATES_DIR` 覆盖（2026-10-06 加，为 Docker 部署）。
# 默认值保持不变，本地开发完全不受影响。
TEMPLATES_DIR = Path(
    os.environ.get("KB_TEMPLATES_DIR") or (Path(__file__).resolve().parents[3] / "templates")
)

KINDS = ("initial", "daily", "reassessment", "discharge")

# 形态 → 中文名（界面与输出都用）
KIND_LABELS = {
    "initial": "首评",
    "daily": "日常治疗记录",
    "reassessment": "阶段性复评",
    "discharge": "出院小结",
}

# 复评周期：**30 个自然日**（用户 2026-10-06 改）。
#
# 历史：2026-10-05 原本是「每 20 次日常治疗后复评」，按**次数**算。
# 用户 2026-10-06 改为按**日期**算：
#   「复评的间隔逻辑需要改一下，设定为距离首评或上一次复评 30 个自然日。
#     如果当日没有治疗，顺延到下一次治疗时评估，也就是 1 个月评一次。」
#
# 于是"一次复评"不再是"挂在第 N 次日常序号上"，而是一个**日期周期**：
# 应做日 = 上次评估的 `record_date` + 30 天。`seq_no` 因此完全不参与复评判定
#（它只回答"这是第几次日常治疗"，治疗师要看的是这个）。
REASSESS_INTERVAL_DAYS = 30

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


def discipline_keys() -> list[str]:
    """全部大类 key（`PT` / `OT` / `ST_SW` / `ST_SP`）。

    供接口校验参数用 —— `_therapy_options` 内部那个查找失败时抛的是
    `TemplateError`（500），不适合拿来校验用户输入。
    """
    data = _load_json(TEMPLATES_DIR / "disciplines.json")
    return [str(d["key"]) for d in data.get("disciplines", [])]


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


def _as_date(value: str | _date | None) -> _date | None:
    """把 `'YYYY-MM-DD'`（或带时间的 ISO 串）转成 `date`；转不了返回 `None`。"""
    if value is None:
        return None
    if isinstance(value, _date):
        return value
    try:
        return _date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def next_reassessment_due(
    anchor_date: str | _date | None,
    *,
    done_dates: Iterable[str | _date] | None = None,
    on_date: str | _date | None = None,
) -> _date | None:
    """下一个复评**应做日**：`首评日 + 30 × k`（第一个还没复评的）。

    用户 2026-10-06：「设定为距离首评或上一次复评 30 个自然日。
    如果当日没有治疗，顺延到下一次治疗时评估，也就是 1 个月评一次。」
    并且明确选了周期**从计划应做日起算**（不是实际完成日）。

    ## 为什么锚点是**首评日**而不是"最近一次评估"

    这是本题唯一的坑，我第一版就踩了。两个概念长得像、但不等价：

    - 锚 = 最近一次复评的**实际完成日** → 拖到第 35 天才补做，下一次就变成第 65 天
      （周期漂成 35 天一次），**越拖越漂**，与"1 个月评一次"直接矛盾。
    - 锚 = **首评日**（唯一不动的时间原点）→ 应做日永远是首评后第 30、60、90… 天；
      第 35 天补做也好、第 50 天补做也好，下一个应做日仍是第 60 天。

    用户要的是后者。所以这里把锚换成首评日，再按 30 天逐格推进，
    跳过**已经做过复评**的那些格子 —— "哪一格该做"因此不需要任何额外落库状态。

    [done_dates] 是已存在的复评各自的 `record_date`。某一格只要**任意一份**复评
    落在 `[该格, 下一格)` 区间内，就算做过。
    [on_date] 给出"今天"：函数返回第一个**尚未完成**的格子；
    不传则等价于 `on_date = 首评日`。
    """
    base = _as_date(anchor_date)
    if base is None:
        return None
    done = [d for d in (_as_date(x) for x in (done_dates or ())) if d is not None]
    today = _as_date(on_date) if on_date is not None else base

    step = timedelta(days=REASSESS_INTERVAL_DAYS)
    due = base + step
    # 逐格推进。循环上限只是防御异常数据的死循环（正常几轮就返回）。
    for _ in range(1000):
        if due > today:
            return due  # 这一格还没到 —— 它就是下一个应做日
        # 这一格已经到过：做过复评就跳过；没做说明**逾期未做** → 应做日就是它
        if not any(due <= d < due + step for d in done):
            return due
        due += step
    return due


def days_until_reassessment(
    anchor_date: str | _date | None,
    on_date: str | _date,
    *,
    done_dates: Iterable[str | _date] | None = None,
) -> int | None:
    """距复评应做日还有几天（`<= 0` 表示已到点）。没有首评时返回 `None`。

    界面用它替换原来的「距复评还差 N **次**」—— 现在单位是**天**。
    """
    due = next_reassessment_due(anchor_date, done_dates=done_dates, on_date=on_date)
    if due is None:
        return None
    on = _as_date(on_date)
    if on is None:
        return None
    return (due - on).days


def reassessment_document_for(
    *,
    has_initial: bool,
    initial_date: str | _date | None,
    done_dates: Iterable[str | _date] | None = None,
    on_date: str | _date,
) -> str | None:
    """在 [on_date] 记这条日常之前，**先**必须完成哪份评估文书（None = 可以记）。

    判定完全按日期：

    - 该大类**还没有首评** → `'initial'`（第 1 次日常前的硬阻断，没变）；
    - 首评之后，`首评日 + 30 × k` 的**第一个未复评的格子**已到点 → `'reassessment'`；
    - 否则 → `None`。

    「如果当日没有治疗，顺延到下一次治疗时评估」在这里自然成立：
    判定拿**本次记录的日期**去比应做日，所以应做日那天没治疗也没关系，
    下一次来治疗时照样会被拦下要求复评 —— 不需要任何"补记"或定时任务。

    >>> reassessment_document_for(has_initial=False, initial_date=None, on_date='2026-11-01')
    'initial'
    >>> reassessment_document_for(has_initial=True, initial_date='2026-11-01', on_date='2026-11-20') is None
    True
    >>> reassessment_document_for(has_initial=True, initial_date='2026-11-01', on_date='2026-12-01')
    'reassessment'
    """
    if not has_initial:
        return "initial"
    due = next_reassessment_due(initial_date, done_dates=done_dates, on_date=on_date)
    if due is None:
        # 有首评却拿不到它的日期（数据异常）—— 保守要求复评，而不是放行。
        return "reassessment"
    on = _as_date(on_date)
    if on is None:
        return "reassessment"
    return "reassessment" if on >= due else None


def kind_for_date(
    *,
    has_initial: bool,
    initial_date: str | _date | None,
    done_dates: Iterable[str | _date] | None = None,
    on_date: str | _date,
    has_daily_today: bool = False,
) -> str:
    """今天该填哪种形态（`initial` / `reassessment` / `daily`）。

    与老的 `kind_for_seq` 的区别：**复评看日期，不看次数**。

    [has_daily_today] 只用于一条**边界**判断：复评到点那天如果当天已经记过日常，
    就不该把表单再折成日常（`daily`），否则治疗师会以为"复评不用做了"。
    ⚠ 它**不**影响"是否要求复评"——那只看日期。
    """
    needed = reassessment_document_for(
        has_initial=has_initial,
        initial_date=initial_date,
        done_dates=done_dates,
        on_date=on_date,
    )
    if needed == "initial":
        return "initial"
    if needed == "reassessment":
        return "reassessment"
    return "daily"


def pending_documents_for_date(
    *,
    has_initial: bool,
    initial_date: str | _date | None,
    done_dates: Iterable[str | _date] | None = None,
    on_date: str | _date,
) -> list[str]:
    """今天需要补的**评估文书**列表（不含日常记录本身）。"""
    kind = kind_for_date(
        has_initial=has_initial,
        initial_date=initial_date,
        done_dates=done_dates,
        on_date=on_date,
    )
    return [] if kind == "daily" else [kind]


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

    # 自动生成的整段文字（如出院小结的「治疗过程汇总」）自带句末标点，
    # 再拼 `；` 会得到「…中风险。；出院时…」这种双标点。这里去掉行尾标点，
    # 由渲染器统一负责分隔。**只对 auto 字段做** —— 治疗师手写的 text 保留原样。
    if ftype == "text" and field_def.get("auto"):
        body = body.rstrip("。；;，,、 ")

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
