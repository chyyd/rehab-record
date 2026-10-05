"""静态复核各验收脚本（`verify_*.py`）的**验收项数**。

`docs/setup.md` 与 `README.md` 里写着每个验收脚本的项数（14 / 25 / 31 / 56 / 35 / 67，合计 228），
`scripts/check_docs_consistency.py` 会拿本模块的结果去核对那些数字 ——
否则"验收项数"只能靠人工数 `check()` 调用，改一次脚本就再也对不上了。

## 计数口径

数的是**运行时会真正执行的 `check()` 次数**（不是源码里出现几次）：

- `for x in ("a", "b", "c")` / `for i in range(n)` 这类**字面量循环会被展开**，
  因为它每次都真的跑 `len(...)` 遍（如 `verify_stage2.py` 用 6 个路径验证"两批已下线接口"、
  `verify_stage5.py` 用 7 个关键词验证"PDF 真的印出了中文"）；
- 其余无法静态确定的循环（如遍历运行期才拿到的页面清单）按 1 次计，
  并打到 stderr —— 那种脚本的项数用它自己运行时的 `checks` 计数器更准。

**口径已用运行时输出复核过**（2026-10-05）：把 6 个脚本各跑一遍、数 `  OK  ` / `  FAIL` 行，
得到 14 / 25 / 31 / 56 / 35 / 67，与本模块的静态结果**逐个吻合**（合计 228 项）。

    cd backend
    python scripts/count_verify_checks.py            # 默认 6 个脚本
    python scripts/count_verify_checks.py verify_stage2.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent

DEFAULT_SCRIPTS = (
    "verify_http.py",
    "verify_stage1.py",
    "verify_stage2.py",
    "verify_stage3.py",
    "verify_stage4.py",
    "verify_stage5.py",
)


def _literal_iterations(node: ast.AST) -> int | None:
    """字面量可数的循环次数；数不出来返回 None。"""
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return len(node.elts)
    is_range_call = (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "range"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Constant)
    )
    if is_range_call:
        return int(node.args[0].value)  # type: ignore[attr-defined]
    return None


class _CheckCounter(ast.NodeVisitor):
    """遍历 AST，按"循环展开"的倍数累计 `check(...)` 调用。"""

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.total = 0
        self.multiplier = 1
        self.warnings: list[str] = []

    def visit_For(self, node: ast.For) -> None:
        iterations = _literal_iterations(node.iter)
        if iterations is None:
            lineno = getattr(node, "lineno", 0)
            self.warnings.append(f"{self.filename}:{lineno} 无法静态展开的循环，按 1 次计")
            self.generic_visit(node)
            return
        previous = self.multiplier
        self.multiplier *= iterations
        for child in node.body:
            self.visit(child)
        self.multiplier = previous

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id == "check":
            self.total += self.multiplier
        self.generic_visit(node)


def count_checks(path: Path, *, warn: bool = False) -> int:
    """返回该验收脚本的项数（运行时 `check()` 次数）。"""
    counter = _CheckCounter(path.name)
    counter.visit(ast.parse(path.read_text(encoding="utf-8")))
    if warn:
        for line in counter.warnings:
            print(f"  [警告] {line}", file=sys.stderr)
    return counter.total


def count_all(names: tuple[str, ...] | list[str] = DEFAULT_SCRIPTS, *, warn: bool = False) -> dict[str, int]:
    return {name: count_checks(SCRIPTS_DIR / name, warn=warn) for name in names}


def main(argv: list[str]) -> int:
    names = tuple(argv[1:]) or DEFAULT_SCRIPTS
    counts = count_all(names, warn=True)
    for name, count in counts.items():
        print(f"{name}: {count}")
    print(f"合计: {sum(counts.values())}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
