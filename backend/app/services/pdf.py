"""PDF 生成（阶段 5 / `设计.md` 3.9、Q10 定稿）。

**中文渲染用 reportlab 内置的 CID 字体 `STSong-Light`**（`UnicodeCIDFont`）：
它自带字形数据，**不依赖任何系统字体文件**，因此不必在容器里打包 CJK 字体，
也不必引入 WeasyPrint（后者依赖 GTK/Pango 原生库）。这是 V1.3 实测后对 V1.2 的修订。

版式约定（Q10 定稿）：

| 位置 | 内容 |
|---|---|
| 抬头 | 科室名 + 住院编号 + 姓名（按模板不同） |
| 页脚 | 页码 + 打印时间 |
| 签名栏 | **无**（对齐 1.4 不做患者签字） |

三套模板：单患者汇总、按日期汇总、按患者每日汇总。
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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
        "cell": ParagraphStyle("cell", fontName=font, fontSize=8, leading=11),
        "cell_small": ParagraphStyle("cell_small", fontName=font, fontSize=7, leading=10),
        "meta": ParagraphStyle("meta", fontName=font, fontSize=9, leading=14),
    }


def _print_time() -> str:
    """打印时间。用本地时区展示，但**存储与比较一律用 UTC**（见 `core/clock.py`）。"""
    now = datetime.now(UTC).astimezone()
    return now.strftime("%Y-%m-%d %H:%M")


def _table(rows: list[list[Any]], col_widths: list[float], style: dict[str, ParagraphStyle]) -> Table:
    """统一的表格样式：表头灰底、细网格、单元格内容按 Paragraph 换行。

    单元格一律包成 `Paragraph`，否则长文本（如参数摘要）不会自动换行，
    会直接溢出到页边外。
    """
    wrapped = []
    for r_index, row in enumerate(rows):
        paragraph = style["cell"] if r_index else style["cell"]
        wrapped.append(
            [cell if hasattr(cell, "wrap") else Paragraph(str(cell), paragraph) for cell in row]
        )
    table = Table(wrapped, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return table


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
    main_items = "、".join(f"{k}×{v}" for k, v in (totals.get("main_item_counts") or {}).items())
    sub_items = "、".join(f"{k}×{v}" for k, v in (totals.get("sub_item_counts") or {}).items())
    parts = [
        f"治疗次数：<b>{totals.get('record_count', 0)}</b> 次",
        f"总时长：<b>{totals.get('total_duration_min', 0)}</b> 分钟",
        f"子项目条目：{totals.get('item_count', 0)} 条",
    ]
    if totals.get("patient_count"):
        parts.append(f"涉及患者：{totals['patient_count']} 人")
    text = "　".join(parts)
    if main_items:
        text += f"<br/>主项目频次：{main_items}"
    if sub_items:
        text += f"<br/>子项目频次：{sub_items}"
    return Paragraph(text, style["meta"])


# --------------------------------------------------------------------------- #
# 1. 单患者汇总 PDF
# --------------------------------------------------------------------------- #
def patient_summary_pdf(
    overview: dict[str, Any], *, dept_name: str = DEFAULT_DEPT_NAME
) -> bytes:
    """单患者汇总（`设计.md` 3.9）：基本信息 + 归属 + 记录列表 + 统计。"""
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
    story.append(Paragraph("汇总统计", style["heading"]))
    story.append(_totals_paragraph(overview["totals"], style))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("治疗记录", style["heading"]))

    rows: list[list[Any]] = [["#", "日期", "半日", "实际治疗师", "主项目", "子项目", "参数", "患者反应", "时长"]]
    for record in overview["records"]:
        items = record["items"] or [{}]
        for index, item in enumerate(items):
            rows.append(
                [
                    record["record_no"] if index == 0 else "",
                    record["record_date"] if index == 0 else "",
                    {"am": "上午", "pm": "下午"}.get(str(record.get("session_period")), "")
                    if index == 0
                    else "",
                    (
                        str(record.get("therapist_name") or "")
                        + ("（临时）" if record.get("is_temporary") else "")
                    )
                    if index == 0
                    else "",
                    item.get("main_item_name") or "",
                    item.get("sub_item_name") or "",
                    item.get("params_digest") or "",
                    (record.get("response_digest") or "") if index == 0 else "",
                    f"{record.get('duration_min') or 0} 分钟" if index == 0 else "",
                ]
            )
    if len(rows) == 1:
        rows.append(["", "", "", "", "（无已提交的治疗记录）", "", "", "", ""])

    story.append(
        _table(
            rows,
            [8 * mm, 20 * mm, 11 * mm, 20 * mm, 30 * mm, 34 * mm, 42 * mm, 22 * mm, 15 * mm],
            style,
        )
    )
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
    """按日期汇总（`设计.md` 3.8）：当天全部记录，按治疗师或患者分组。"""
    style = _styles()
    story: list[Any] = []
    group_label = "治疗师" if summary.get("group_by") == "therapist" else "患者"

    story.append(Paragraph("当日总计", style["heading"]))
    story.append(_totals_paragraph(summary["totals"], style))
    story.append(Spacer(1, 3 * mm))

    for group in summary["groups"]:
        story.append(Paragraph(f"按{group_label}：{group['key']}", style["heading"]))
        story.append(
            Paragraph(
                f"共 {group['totals']['record_count']} 次、{group['totals']['total_duration_min']} 分钟",
                style["body"],
            )
        )
        rows: list[list[Any]] = [["患者", "半日", "主项目", "子项目", "参数", "患者反应", "时长"]]
        for row in group["rows"]:
            rows.append(
                [
                    f"{row.get('patient_name') or ''}（{row.get('patient_no') or ''}）",
                    {"am": "上午", "pm": "下午"}.get(str(row.get("session_period")), ""),
                    row.get("main_item_name") or "",
                    row.get("sub_item_name_snapshot") or "",
                    row.get("params_digest") or "",
                    row.get("response_digest") or "",
                    f"{row.get('duration_min') or 0} 分",
                ]
            )
        story.append(
            _table(rows, [34 * mm, 11 * mm, 30 * mm, 32 * mm, 42 * mm, 22 * mm, 13 * mm], style)
        )
        story.append(Spacer(1, 3 * mm))

    if not summary["groups"]:
        story.append(Paragraph("当日没有已提交的治疗记录。", style["body"]))

    return _build(
        story,
        title="康复治疗按日期汇总",
        subtitle=f"{summary.get('date')}　共 {summary['totals']['record_count']} 次",
        paper=landscape(A4),
        dept_name=dept_name,
    )


# --------------------------------------------------------------------------- #
# 3. 按患者每日汇总 PDF
# --------------------------------------------------------------------------- #
def patient_daily_pdf(daily: dict[str, Any], *, dept_name: str = DEFAULT_DEPT_NAME) -> bytes:
    """按患者每日汇总（`设计.md` 3.8）：每天一行。"""
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
                ("汇总", f"{daily['totals']['record_count']} 次 / {daily['totals']['total_duration_min']} 分钟"),
            ],
            style,
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("每日汇总", style["heading"]))

    rows: list[list[Any]] = [["日期", "半日", "治疗师", "主项目", "子项目", "参数", "患者反应", "时长"]]
    for day in daily["days"]:
        rows.append(
            [
                day["record_date"],
                "、".join({"am": "上午", "pm": "下午"}.get(p, p) for p in day["session_periods"]),
                "、".join(day["therapists"]) + ("（临时）" if day.get("temporary") else ""),
                "、".join(day["main_items"]),
                "、".join(day["sub_items"]),
                "<br/>".join(day["params"]),
                "；".join(day["responses"]),
                f"{day['duration_min']} 分",
            ]
        )
    if len(rows) == 1:
        rows.append(["（区间内无已提交记录）", "", "", "", "", "", "", ""])

    story.append(
        _table(
            rows,
            [20 * mm, 14 * mm, 22 * mm, 30 * mm, 30 * mm, 42 * mm, 22 * mm, 13 * mm],
            style,
        )
    )
    return _build(
        story,
        title="康复治疗按患者每日汇总",
        subtitle=f"{patient.get('name')}　{patient.get('inpatient_no')}",
        paper=landscape(A4),
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
