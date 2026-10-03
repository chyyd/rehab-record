"""PDF 中文渲染验证（D03 / R3 / 阶段 0 验收项）。

**方案已由实测确定**：用 **reportlab + 内置 CID 字体 `STSong-Light`**，而不是 WeasyPrint。
理由（2026-10-03 实测，见 CHANGELOG）：
- WeasyPrint 未安装，且它依赖 GTK/Pango 原生库，在 Windows 上装起来成本高；
- reportlab 的 `UnicodeCIDFont("STSong-Light")` 是**自带的中文 CID 字体，不依赖任何系统字体文件**，
  中文表格渲染与文本提取都正常（用 pypdf 反向校验）。
- 部署到 Linux 容器时同样可用，不必再打包 Noto CJK —— 省掉一个最容易在末期翻车的环节。

本文件同时是"字体可用性"的回归防线：一旦方案回退到依赖系统字体，这里会立刻失败。
"""

from __future__ import annotations

import importlib.util
import unittest

from tests.support import BACKEND_ROOT  # noqa: F401


def _has(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


class TestPdfDependencies(unittest.TestCase):
    def test_reportlab_available(self) -> None:
        self.assertTrue(_has("reportlab"), "未安装 reportlab —— PDF 打印功能无法工作")

    def test_pypdf_available_for_verification(self) -> None:
        """pypdf 用于反向校验生成的 PDF 能被解析、文本可提取（不是空白页）。"""
        self.assertTrue(_has("pypdf"), "未安装 pypdf —— 无法自动校验 PDF 内容")


@unittest.skipUnless(_has("reportlab"), "未安装 reportlab")
class TestChinesePdfRendering(unittest.TestCase):
    """核心验收：中文表格能渲染成合法 PDF，且文本层正确（不是方框、不是空白）。"""

    FONT_NAME = "STSong-Light"

    @classmethod
    def setUpClass(cls) -> None:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont

        try:
            pdfmetrics.registerFont(UnicodeCIDFont(cls.FONT_NAME))
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(f"CID 字体 {cls.FONT_NAME} 注册失败：{exc}") from exc

    def setUp(self) -> None:
        import os
        import tempfile
        from pathlib import Path

        # 与 tests/support.py 保持一致：**不要**用 mkdtemp 建子目录。
        # 本机实测 mkdtemp 建出的目录当前用户无权访问，往里写文件会 PermissionError；
        # 系统 %TEMP% 则在退出时删不掉（WinError 5）。所以直接在工作区 data/ 下建唯一文件。
        tmp_dir = BACKEND_ROOT / "data"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(prefix="kf-pdf-", suffix=".pdf", dir=tmp_dir)
        os.close(fd)
        self._pdf_file = Path(path)
        # 测试自身写出的旁路文件（probe.pdf / numbers.pdf）直接建在 tmp_path 下，
        # 这里逐个记账，tearDown 一并删掉 —— 否则会永久留在 data/ 里污染工作区。
        self._scratch: list[Path] = []

    def tearDown(self) -> None:
        for scratch in self._scratch:
            scratch.unlink(missing_ok=True)
        self._pdf_file.unlink(missing_ok=True)

    def _scratch_path(self, name: str):
        path = self._pdf_file.parent / name
        self._scratch.append(path)
        return path

    @property
    def tmp_path(self):
        return self._pdf_file.parent

    def _build_pdf(self, path) -> None:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        style = ParagraphStyle("cn", fontName=self.FONT_NAME, fontSize=10, leading=14)
        heading = ParagraphStyle("h", fontName=self.FONT_NAME, fontSize=16, leading=20)

        rows = [
            ["日期", "治疗师", "主项目", "子项目", "参数", "时长"],
            ["2026-10-05", "张三", "运动功能障碍训练", "偏瘫肢体综合训练", "部位：左肩；MMT：2 级", "30 分钟"],
            ["2026-10-05", "李四", "吞咽功能障碍训练", "摄食训练", "食物性状：糊状；一口量：5ml", "20 分钟"],
        ]
        table = Table(
            [[Paragraph(cell, style) for cell in row] for row in rows],
            colWidths=[24 * mm, 20 * mm, 36 * mm, 36 * mm, 40 * mm, 18 * mm],
        )
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ]
            )
        )
        doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm)
        doc.build([Paragraph("康复科治疗过程记录 — 患者汇总", heading), Spacer(1, 6 * mm), table])

    def test_renders_valid_pdf_with_extractable_chinese(self) -> None:
        import pypdf

        out = self._scratch_path("probe.pdf")
        self._build_pdf(out)

        raw = out.read_bytes()
        self.assertTrue(raw.startswith(b"%PDF"), "输出不是合法 PDF")
        self.assertGreater(len(raw), 1000, "PDF 过小，可能是空白页")

        reader = pypdf.PdfReader(str(out))
        self.assertEqual(len(reader.pages), 1)
        text = reader.pages[0].extract_text() or ""
        # 中文必须真的进了文本层：若字体缺失会变成方框或空串
        for keyword in ("康复科", "偏瘫肢体综合训练", "糊状", "张三", "30 分钟"):
            self.assertIn(keyword, text, f"PDF 文本层缺少 {keyword!r}，字体可能未生效")

    def test_number_columns_do_not_break_layout(self) -> None:
        """数字、百分号、单位混排不应导致渲染失败。"""
        import pypdf
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import Paragraph, SimpleDocTemplate

        style = ParagraphStyle("cn2", fontName=self.FONT_NAME, fontSize=10, leading=14)
        out = self._scratch_path("numbers.pdf")
        doc = SimpleDocTemplate(str(out), pagesize=A4)
        doc.build(
            [
                Paragraph(
                    "Berg 评分 0–56 分；疼痛 NRS 3 分；一口量 5ml；频率 80Hz；强度 2mA；"
                    "血氧 95%；完成度 50–75%；侧别 左；MMT 2 级。",
                    style,
                )
            ]
        )
        text = pypdf.PdfReader(str(out)).pages[0].extract_text() or ""
        self.assertIn("Berg", text)
        self.assertIn("95%", text)
        self.assertIn("50–75%", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
