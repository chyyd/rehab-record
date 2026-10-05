"""测试公共设施：临时库 + 干净的配置单例。

只用标准库 unittest，保证在**没有任何第三方依赖**的环境下也能跑。
依赖恢复后可直接被 pytest 收集，无需改写。

运行方式（在 backend/ 目录下）：
    python -m unittest discover -s tests -t . -v
    python -m unittest tests.test_worktime -v
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import unittest
from pathlib import Path

from app.core.config import Settings, WorkTimeConfig, get_settings
from app.db import storage

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# 临时库放在工作区内的 data/ 下，且**直接放文件、不建子目录**。
# 原因（本机实测）：tempfile.mkdtemp() 建出来的子目录在当前用户下是"拒绝访问"的，
# 往里写文件会 PermissionError / SQLite 报 unable to open database file；
# 而直接在 data/ 下建文件是正常可写的。系统 %TEMP% 则会在解释器退出时删不掉（WinError 5）。
# 两者都绕开：唯一文件名 + 显式清理。
TMP_DIR = BACKEND_ROOT / "data"


class _ScratchDir:
    """一个"写得进、退出时自动删"的旁路文件目录。

    行为上等价于 ``pathlib.Path`` 的常用子集（``/`` 运算符与 ``write_text``），
    但通过 ``__truediv__`` 记录每个被引用的文件，交给 ``tearDown`` 统一清理。

    为什么不用 ``tempfile.TemporaryDirectory``：本机实测 ``mkdtemp`` 建出的子目录
    在当前用户下是"拒绝访问"的，写文件会 PermissionError。所以仍然把文件直接建在
    ``data/`` 下，只是**名字带上前缀并记账**，从而既能写、也能清。
    """

    def __init__(self, registry: list[Path], directory: Path) -> None:
        self._registry = registry
        self._dir = directory

    def __truediv__(self, name: str) -> Path:
        path = self._dir / name
        if path not in self._registry:
            self._registry.append(path)
        return path

    def __fspath__(self) -> str:
        return str(self._dir)

    def __str__(self) -> str:
        return str(self._dir)

    def mkdir(self, *args: object, **kwargs: object) -> None:
        self._dir.mkdir(*args, **kwargs)  # type: ignore[arg-type]


class DbTestCase(unittest.TestCase):
    """每个测试一个独立的临时 SQLite 文件，互不干扰。

    同时把 ``KB_DB_PATH`` 指向该临时库：应用代码里任何 ``get_settings()``
    （包括 FastAPI 依赖注入）都会拿到临时库，而不是真实的 ``data/kf.db``。
    没有这一步，测试里 ``get_settings.cache_clear()`` 反而会让应用回落到真实库。
    """

    conn: object | None = None

    def setUp(self) -> None:
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(prefix="kf-test-", suffix=".db", dir=TMP_DIR)
        os.close(fd)
        self.db_file = Path(path)
        # tmp_path 指向**本用例专属的清理清单**目录，而不是共享的 data/：
        # 早先直接返回 data/，导致测试写出的 probe.pdf / bad_seed.json 等旁路文件
        # 永远留在工作区里（既污染仓库，也让并发用例互相看到对方的残留）。
        self._scratch: list[Path] = []
        self.tmp_path = _ScratchDir(self._scratch, TMP_DIR)
        self.settings = Settings(db_path=self.db_file)

        # 让应用侧解析配置时也指向这个临时库（测试结束在 tearDown 还原）
        self._prev_db_path = os.environ.get("KB_DB_PATH")
        os.environ["KB_DB_PATH"] = str(self.db_file)
        get_settings.cache_clear()
        self.conn = storage.connect(self.settings)

    def tearDown(self) -> None:
        # 先删测试自己写出的旁路文件，再删库文件
        for scratch in self._scratch:
            with contextlib.suppress(OSError):
                scratch.unlink(missing_ok=True)
        try:
            if self.conn is not None:
                self.conn.close()
        finally:
            # WAL 模式下会伴随 -wal / -shm 文件，一并清掉。
            # 清理失败不影响测试结论（例如文件已被测试自身关闭/移动）。
            for suffix in ("", "-wal", "-shm", "-journal"):
                candidate = Path(str(self.db_file) + suffix)
                with contextlib.suppress(OSError):
                    candidate.unlink(missing_ok=True)
            if self._prev_db_path is None:
                os.environ.pop("KB_DB_PATH", None)
            else:
                os.environ["KB_DB_PATH"] = self._prev_db_path
            get_settings.cache_clear()

    # -- 便捷方法 ---------------------------------------------------------- #
    def migrate(self) -> storage.MigrationResult:
        return storage.migrate(self.conn, storage.discover_migrations(settings=self.settings))

    def add_user(self, employee_no: str = "T001", name: str = "张三", role: str = "therapist") -> int:
        cur = self.conn.execute(
            "INSERT INTO user (employee_no, name, role, password_hash) VALUES (?, ?, ?, ?)",
            (employee_no, name, role, "x"),
        )
        return int(cur.lastrowid)

    def add_patient(self, inpatient_no: str = "ZY001", name: str = "李四", therapist_id: int | None = None) -> str:
        self.conn.execute(
            "INSERT INTO patient (inpatient_no, name, assigned_therapist_id) VALUES (?, ?, ?)",
            (inpatient_no, name, therapist_id),
        )
        return inpatient_no


__all__ = ["BACKEND_ROOT", "DbTestCase", "Settings", "WorkTimeConfig", "storage"]
