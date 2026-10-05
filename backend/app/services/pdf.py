"""PDF 生成（阶段 5 / `设计.md` 3.9、Q10 定稿；2026-10-05 改为 SOAP 纯文本输出）。

**中文渲染用 reportlab 内置的 CID 字体 `STSong-Light`**（`UnicodeCIDFont`）：
它自带字形数据，**不依赖任何系统字体文件**，因此不必在容器里打包 CJK 字体，
也不必引入 WeasyPrint（后者依赖 GTK/Pango 原生库）。这是 V1.3 实测后对 V1.2 的修订。

## 版式（用户 2026-10-05 明确要求）

> 「输出时也用类似格式，避免现有的表格方式」+「多日的情况下，是按时间顺序往下排就行，
> 不用一天一张」

所以：

- 正文是**记录落库时冻结的 `rendered_text`**（SOAP 纯文本），不是表格；
- **多日记录按时间顺序（由早到晚）往下排**，不分页、不一天一张；
- 只有「基本信息 / 统计」这类**元信息**仍用小表格（那是抬头，不是病历内容）；
- 保留既有做法：抬头科室名、页脚页码与打印时间（Q10：**不做签名栏**）。

三套模板：单患者汇总、按日期汇总、按患者每日汇总。
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# 科室名：抬头固定展示。真实部署时可由配置覆盖。
DEFAULT_DEPT_NAME = "康复医学科"

FONT_NAME = "STSong-Light"
FONT_REGISTERED = False


def ensure_font() -> str:
    """注册中文字体（幂等）。返回可用的字体名。

    注册失败时**抛出而不是静默回退到 Helvetica** —— 用 Helvetica 渲染中文会得到
    一页方框，而调用方（以及看 PDF 的人）很难立刻发现"内容其实没印出来"。
    """
    global FONT_REGISTERED
    if not FONT_REGISTERED:
        pdfmetrics.registerFont(UnicodeCIDFont(FONT_NAME))
        FONT_REGISTERED = True
    return FONT_NAME


# --------------------------------------------------------------------------- #
# 基础构件
# --------------------------------------------------------------------------- #
def _styles() -> dict[str, ParagraphStyle]:
    font = ensure_font()
    return {
        "title": ParagraphStyle("title", fontName=font, fontSize=16, leading=22, alignment=1),
        "subtitle": ParagraphStyle("subtitle", fontName=font, fontSize=11, leading=16, alignment=1),
        "heading": ParagraphStyle("heading", fontName=font, fontSize=12, leading=18, spaceBefore=6),
        "body": ParagraphStyle("body", fontName=font, fontSize=9, leading=13),
        # SOAP 正文：段与段之间靠空行区分，行距留足便于阅读与批注
        "soap": ParagraphStyle("soap", fontName=font, fontSize=9.5, leading=15, spaceAfter=6),
        "cell": ParagraphStyle("cell", fontName=font, fontSize=8, leading=11),
        "meta": ParagraphStyle("meta", fontName=font, fontSize=9, leading=14),
    }


def _print_time() -> str:
    """打印时间。用本地时区展示，但**存储与比较一律用 UTC**（见 `core/clock.py`）。"""
    now = datetime.now(UTC).astimezone()
    return now.strftime("%Y-%m-%d %H:%M")


def _escape(text: str) -> str:
    """reportlab 的 Paragraph 是迷你 XML：`&`/`<`/`>` 必须转义，换行要写成 `<br/>`。"""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
    )


def _soap_paragraph(text: str, style: dict[str, ParagraphStyle]) -> Paragraph:
    """把一条记录的 `rendered_text` 变成段落（**保留原样换行**，不重排、不加表格）。"""
    return Paragraph(_escape(text.strip()), style["soap"])


def _soap_block(text: str, style: dict[str, ParagraphStyle]) -> list[Any]:
    """一条记录 = 一段 SOAP 文本 + 一条细分隔线（视觉上区分两份文书，但不强制分页）。"""
    content = text.strip()
    if not content:
        return []
    rule = Table([[""]], colWidths=["100%"], rowHeights=[0.5])
    rule.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#cccccc"))]))
    return [KeepTogether([_soap_paragraph(content, style), Spacer(1, 1 * mm), rule, Spacer(1, 3 * mm)])]


def _build(
    story: list[Any],
    *,
    title: str,
    subtitle: str,
    paper: tuple[float, float] | None = None,
    dept_name: str = DEFAULT_DEPT_NAME,
) -> bytes:
    """把 story 渲染成 PDF 字节，并统一加上抬头与页脚。"""
    style = _styles()
    buffer = io.BytesIO()
    size = paper or A4
    doc = SimpleDocTemplate(
        buffer,
        pagesize=size,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=title,
        author=dept_name,
    )

    printed_at = _print_time()
    header: list[Any] = [
        Paragraph(dept_name, style["title"]),
        Paragraph(title, style["subtitle"]),
    ]
    if subtitle:
        header.append(Paragraph(subtitle, style["subtitle"]))
    header.append(Spacer(1, 5 * mm))

    def on_page(canvas, _doc) -> None:  # noqa: ANN001 - reportlab 回调签名
        canvas.saveState()
        ensure_font()
        canvas.setFont(FONT_NAME, 8)
        canvas.setFillColor(colors.HexColor("#666666"))
        # 页脚：页码 + 打印时间（Q10）；签名栏刻意不做（1.4：不采集患者签字）
        canvas.drawCentredString(size[0] / 2, 10 * mm, f"第 {canvas.getPageNumber()} 页")
        canvas.drawRightString(size[0] - 14 * mm, 10 * mm, f"打印时间：{printed_at}")
        canvas.restoreState()

    doc.build(header + story, onFirstPage=on_page, onLaterPages=on_page)
    return buffer.getvalue()


def _kv_table(pairs: list[tuple[str, Any]], style: dict[str, ParagraphStyle], *, columns: int = 2) -> Table:
    """键值信息表：按 columns 列排布，奇数项补空。"""
    cells: list[list[Any]] = []
    row: list[Any] = []
    for key, value in pairs:
        row.append(Paragraph(f"<b>{key}</b>", style["cell"]))
        row.append(Paragraph("—" if value in (None, "") else str(value), style["cell"]))
        if len(row) >= columns * 2:
            cells.append(row)
            row = []
    if row:
        while len(row) < columns * 2:
            row.append(Paragraph("", style["cell"]))
        cells.append(row)

    widths = []
    for _ in range(columns):
        widths.extend([22 * mm, 60 * mm])
    table = Table(cells, colWidths=widths)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bbbbbb")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f5f5f5")),
                ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f5f5f5")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return table


def _totals_paragraph(totals: dict[str, Any], style: dict[str, ParagraphStyle]) -> Paragraph:
    """统计行（元信息，用一行文字而不是表格）。计数只含日常记录，见 `services/summary.py`。"""
    parts = [
        f"治疗次数：<b>{totals.get('record_count', 0)}</b> 次",
    ]
    if totals.get("patient_count"):
        parts.append(f"涉及患者：{totals['patient_count']} 人")
    text = "　".join(parts)
    by_discipline = "、".join(f"{k}×{v}" for k, v in (totals.get("discipline_counts") or {}).items())
    if by_discipline:
        text += f"<br/>按大类：{by_discipline}"
    by_therapist = "、".join(f"{k}×{v}" for k, v in (totals.get("therapist_counts") or {}).items())
    if by_therapist:
        text += f"<br/>按治疗师：{by_therapist}"
    return Paragraph(text, style["meta"])


def _record_meta(
    record: dict[str, Any], style: dict[str, ParagraphStyle], *, with_patient: bool = False
) -> Paragraph | None:
    """文书抬头（患者/大类/形态/治疗师/是否临时）。

    正文是 SOAP 纯文本，这里只标"这是谁的哪份文书"。按日期汇总必须带患者姓名 ——
    那份汇总按治疗师分组，不写患者名就分不清这一条是谁的。
    """
    bits: list[str] = []
    if with_patient:
        name = str(record.get("patient_name") or "")
        no = str(record.get("patient_no") or "")
        bits.append(f"{name}（{no}）" if name else no)
    bits.append(str(record.get("discipline_name") or record.get("discipline") or ""))
    if record.get("kind_label"):
        bits.append(str(record["kind_label"]))
    if record.get("seq_no"):
        bits.append(f"第 {record['seq_no']} 次")
    who = str(record.get("therapist_name") or "")
    if who:
        bits.append(who + ("（临时）" if record.get("is_temporary") else ""))
    text = "　".join(b for b in bits if b)
    return Paragraph(f"<b>{_escape(text)}</b>", style["body"]) if text else None


# --------------------------------------------------------------------------- #
# 1. 单患者汇总 PDF
# --------------------------------------------------------------------------- #
def patient_summary_pdf(
    overview: dict[str, Any], *, dept_name: str = DEFAULT_DEPT_NAME
) -> bytes:
    """单患者汇总（`设计.md` 3.9）：基本信息 + 统计 + 全部文书的 SOAP 文本（时间升序）。"""
    style = _styles()
    patient = overview["patient"]
    story: list[Any] = []

    story.append(
        _kv_table(
            [
                ("住院编号", patient.get("inpatient_no")),
                ("姓名", patient.get("name")),
                ("诊断", patient.get("diagnosis")),
                ("状态", patient.get("status")),
                ("归属治疗师", patient.get("assigned_therapist_name") or "（未分配）"),
                ("注意事项", patient.get("admin_note")),
            ],
            style,
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(_totals_paragraph(overview["totals"], style))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("治疗记录", style["heading"]))

    records = overview["records"]
    if not records:
        story.append(Paragraph("（无已提交的治疗记录）", style["body"]))
    for record in records:
        meta = _record_meta(record, style)
        if meta is not None:
            story.append(meta)
        story.extend(_soap_block(str(record.get("rendered_text") or ""), style))

    return _build(
        story,
        title="康复治疗记录汇总",
        subtitle=f"{patient.get('name')}　{patient.get('inpatient_no')}",
        dept_name=dept_name,
    )


# --------------------------------------------------------------------------- #
# 2. 按日期汇总 PDF
# --------------------------------------------------------------------------- #
def date_summary_pdf(summary: dict[str, Any], *, dept_name: str = DEFAULT_DEPT_NAME) -> bytes:
    """按日期汇总（`设计.md` 3.8）：当天**日常**记录的 SOAP 文本，按治疗师或患者分组。"""
    style = _styles()
    story: list[Any] = []
    group_label = "治疗师" if summary.get("group_by") == "therapist" else "患者"

    story.append(Paragraph("当日总计", style["heading"]))
    story.append(_totals_paragraph(summary["totals"], style))
    story.append(Spacer(1, 3 * mm))

    for group in summary["groups"]:
        story.append(Paragraph(f"按{group_label}：{group['key']}", style["heading"]))
        story.append(
            Paragraph(f"共 {group['totals']['record_count']} 次", style["body"])
        )
        rows = group["rows"]
        if not rows:
            story.append(Paragraph("（无）", style["body"]))
        for row in rows:
            meta = _record_meta(row, style, with_patient=True)
            if meta is not None:
                story.append(meta)
            story.extend(_soap_block(str(row.get("rendered_text") or ""), style))
        story.append(Spacer(1, 3 * mm))

    if not summary["groups"]:
        story.append(Paragraph("当日没有已提交的治疗记录。", style["body"]))

    # 正文是纯文本长文，横向纸张反而难读，故仍用 A4 纵向
    return _build(
        story,
        title="康复治疗按日期汇总",
        subtitle=f"{summary.get('date')}　共 {summary['totals']['record_count']} 次",
        dept_name=dept_name,
    )


# --------------------------------------------------------------------------- #
# 3. 按患者每日汇总 PDF
# --------------------------------------------------------------------------- #
def patient_daily_pdf(daily: dict[str, Any], *, dept_name: str = DEFAULT_DEPT_NAME) -> bytes:
    """按患者每日汇总（`设计.md` 3.8）：每天的全部文书 SOAP 文本，**由早到晚往下排**。"""
    style = _styles()
    patient = daily["patient"]
    story: list[Any] = []

    story.append(
        _kv_table(
            [
                ("住院编号", patient.get("inpatient_no")),
                ("姓名", patient.get("name")),
                ("诊断", patient.get("diagnosis")),
                ("注意事项", patient.get("admin_note")),
                ("统计区间", f"{daily.get('date_from') or '不限'} ~ {daily.get('date_to') or '不限'}"),
                ("汇总", f"{daily['totals']['record_count']} 次"),
            ],
            style,
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("每日汇总", style["heading"]))

    # ★ 多日记录**按时间顺序往下排**（由早到晚），不分页、不一天一张
    days = sorted(daily["days"], key=lambda d: str(d["record_date"]))
    if not days:
        story.append(Paragraph("（区间内无已提交记录）", style["body"]))
    for day in days:
        therapists = "、".join(day.get("therapists") or [])
        if any(rec.get("is_temporary") for rec in day.get("records") or []):
            therapists += "（临时）"
        head = f"{day['record_date']}"
        if therapists:
            head += f"　{therapists}"
        story.append(Paragraph(f"<b>{_escape(head)}</b>", style["heading"]))
        texts = [str(t) for t in (day.get("texts") or []) if str(t).strip()]
        if not texts:
            story.append(Paragraph("（当天无已提交记录）", style["body"]))
        for text in texts:
            story.extend(_soap_block(text, style))

    return _build(
        story,
        title="康复治疗按患者每日汇总",
        subtitle=f"{patient.get('name')}　{patient.get('inpatient_no')}",
        dept_name=dept_name,
    )


__all__ = [
    "DEFAULT_DEPT_NAME",
    "FONT_NAME",
    "date_summary_pdf",
    "ensure_font",
    "patient_daily_pdf",
    "patient_summary_pdf",
]
