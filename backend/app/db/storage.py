"""数据库访问层（标准库 sqlite3）。

设计要点
--------
1. **不引入 ORM 作为真源**：迁移用纯 SQL 文件，服务端模型可以后接 SQLAlchemy，
   但表结构的唯一真源是 ``backend/app/db/migrations/*.sql``。
2. **迁移有账本**：已应用的迁移记在 ``schema_migrations`` 表里，重复执行安全（幂等）。
3. **健壮性原则**（Design for Failure）：连接创建时显式设置 WAL、外键、busy_timeout，
   并在开启外键后**立即校验它真的生效**——外键失效会静默产生脏数据，必须早失败。
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings, get_settings

_MIGRATION_NAME_RE = re.compile(r"^(?P<version>\d{3,})_(?P<name>[A-Za-z0-9_]+)\.sql$")


class StorageError(RuntimeError):
    """数据库层的通用错误。"""


class MigrationError(StorageError):
    """迁移执行失败。"""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path

    @property
    def label(self) -> str:
        return f"{self.version:03d}_{self.name}"


@dataclass(frozen=True)
class MigrationResult:
    applied: list[str]
    skipped: list[str]

    @property
    def applied_count(self) -> int:
        return len(self.applied)


# --------------------------------------------------------------------------- #
# 连接
# --------------------------------------------------------------------------- #
def connect(
    settings: Settings | None = None, *, ensure_parent: bool = True, read_only: bool = False
) -> sqlite3.Connection:
    """打开一个配置正确的 SQLite 连接。

    ``read_only=True`` 时以只读模式打开（URI ``mode=ro``）：
    健康检查这类"探针"必须能报告"库不存在"，而不是顺手把文件创建出来。
    只读连接同样会开启外键，但不会尝试切 WAL。

    调用方负责关闭（或用 ``with closing(...)``）。
    """
    cfg = settings or get_settings()
    if ensure_parent and not read_only:
        cfg.db_path.parent.mkdir(parents=True, exist_ok=True)

    # `check_same_thread=False` 是**必须**的，不是图方便：
    # FastAPI 会把同步依赖（`get_db` 是 `def`）和路由处理函数分别丢进 anyio 线程池，
    # 二者**不保证落在同一个线程**。线程池在并发下会轮转，于是"依赖里建的连接、
    # 路由里用"经常跨线程 → sqlite3 默认的 check_same_thread=True 会抛
    # `ProgrammingError: SQLite objects created in a thread can only be used in that same thread`。
    # 这个缺陷只在**并发**下出现：单请求顺序调用时依赖与路由往往复用同一线程，
    # 所以单元测试与逐个 curl 都测不出来，是浏览器里同时发多个请求才暴露的。
    #
    # 关掉这项检查是安全的，因为：
    #   1. 连接是**每请求一个**（`get_db` 的 finally 里关闭），不在线程间共享；
    #   2. 我们不开显式事务（`isolation_level=None`），没有跨线程的事务状态；
    #   3. 真正的并发保护交给 SQLite 自身的 WAL + `busy_timeout`。
    if read_only:
        uri = cfg.db_path.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(
            uri, uri=True, isolation_level=None, check_same_thread=False,
            timeout=cfg.sqlite_busy_timeout_ms / 1000,
        )
    else:
        conn = sqlite3.connect(
            str(cfg.db_path), isolation_level=None, check_same_thread=False,
            timeout=cfg.sqlite_busy_timeout_ms / 1000,
        )

    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {int(cfg.sqlite_busy_timeout_ms)}")
    conn.execute("PRAGMA foreign_keys = ON")
    if cfg.sqlite_wal and not read_only:
        conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")

    # 外键是我们数据完整性的重要一环，开启后必须验证真的生效
    if not conn.execute("PRAGMA foreign_keys").fetchone()[0]:
        conn.close()
        raise StorageError("PRAGMA foreign_keys 无法开启：SQLite 构建可能不支持外键，拒绝在无外键保护下运行")
    return conn


def json1_available(conn: sqlite3.Connection) -> bool:
    """检测 JSON1 扩展（4.2 节要求）。Python 3.9+ 自带 SQLite 通常已编译进来。"""
    try:
        row = conn.execute("SELECT json_extract(?, '$.a')", ('{"a":1}',)).fetchone()
        return bool(row) and row[0] == 1
    except sqlite3.OperationalError:
        return False


# --------------------------------------------------------------------------- #
# 迁移
# --------------------------------------------------------------------------- #
def discover_migrations(migrations_dir: Path | None = None, settings: Settings | None = None) -> list[Migration]:
    """按版本号升序读取迁移文件；命名不合规或版本号重复直接报错。"""
    cfg = settings or get_settings()
    directory = migrations_dir or cfg.migrations_dir
    if not directory.is_dir():
        raise MigrationError(f"迁移目录不存在：{directory}")

    found: dict[int, Migration] = {}
    for path in sorted(directory.glob("*.sql")):
        match = _MIGRATION_NAME_RE.match(path.name)
        if not match:
            raise MigrationError(f"迁移文件名不合规（应为 NNN_name.sql）：{path.name}")
        version = int(match.group("version"))
        if version in found:
            raise MigrationError(f"迁移版本号重复：{version:03d}（{found[version].path.name} 与 {path.name}）")
        found[version] = Migration(version=version, name=match.group("name"), path=path)
    return [found[v] for v in sorted(found)]


def _ensure_ledger(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            name       TEXT    NOT NULL,
            applied_at TEXT    NOT NULL,
            checksum   TEXT    NOT NULL
        )
        """
    )


def _ledger_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    return row is not None


def applied_migrations(conn: sqlite3.Connection, *, create_if_missing: bool = True) -> dict[int, sqlite3.Row]:
    """读取迁移账本。

    ``create_if_missing=False``（只读连接，如健康检查）时不建表：
    账本不存在就视为"没有任何已应用迁移"，而不是抛
    ``attempt to write a readonly database``。
    """
    if not _ledger_exists(conn):
        if not create_if_missing:
            return {}
        _ensure_ledger(conn)
    rows = conn.execute("SELECT version, name, applied_at, checksum FROM schema_migrations").fetchall()
    return {int(row["version"]): row for row in rows}


def pending_migrations(
    conn: sqlite3.Connection, migrations: list[Migration], *, create_if_missing: bool = True
) -> list[Migration]:
    done = applied_migrations(conn, create_if_missing=create_if_missing)
    return [m for m in migrations if m.version not in done]


def schema_version(conn: sqlite3.Connection, *, create_if_missing: bool = True) -> int:
    done = applied_migrations(conn, create_if_missing=create_if_missing)
    return max(done) if done else 0


def migrate(conn: sqlite3.Connection, migrations: list[Migration] | None = None) -> MigrationResult:
    """应用所有未执行的迁移。

    事务语义：``sqlite3.executescript`` 会先提交当前事务，因此**不能**外包一层显式
    BEGIN/COMMIT（那会导致 "cannot commit - no transaction is active"）。
    这里的做法是脚本内自带 ``BEGIN`` / ``COMMIT``（见迁移文件抬头），
    失败时由 SQLite 自动回滚未提交的部分，我们再补一次幂等的 ROLLBACK 兜底。
    """
    import hashlib
    from datetime import datetime

    items = migrations if migrations is not None else discover_migrations()
    done = applied_migrations(conn)
    applied: list[str] = []
    skipped: list[str] = []

    for migration in items:
        sql = migration.path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()

        if migration.version in done:
            # 已执行的迁移被改动过 → 迁移历史与代码不一致，必须报错而不是忽略
            if done[migration.version]["checksum"] != checksum:
                raise MigrationError(
                    f"迁移 {migration.label} 的已应用内容与当前文件不一致（校验和不匹配）。"
                    "已应用的迁移不得修改，请新增一个迁移文件。"
                )
            skipped.append(migration.label)
            continue

        try:
            conn.executescript(sql)
            applied_at = datetime.now().astimezone().isoformat(timespec="seconds")
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at, checksum) VALUES (?, ?, ?, ?)",
                (migration.version, migration.name, applied_at, checksum),
            )
        except Exception as exc:  # noqa: BLE001 - 需要把所有失败统一转成迁移错误
            if conn.in_transaction:  # 兜底：脚本中途失败时可能留下未提交事务
                conn.execute("ROLLBACK")
            raise MigrationError(f"迁移 {migration.label} 执行失败：{exc}") from exc

        # 让 SQLite 自己的 user_version 与服务端账本保持一致，便于外部工具判断
        conn.execute(f"PRAGMA user_version = {migration.version}")
        applied.append(migration.label)

    return MigrationResult(applied=applied, skipped=skipped)


def initialize(settings: Settings | None = None) -> MigrationResult:
    """建库 + 迁移到最新。可重复调用。"""
    conn = connect(settings)
    try:
        return migrate(conn)
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #
def inspect(settings: Settings | None = None) -> dict[str, object]:
    """收集数据库健康信息，供 /api/v1/health 与 CLI 使用。

    以**只读**方式打开，因此不会因为一次健康检查就把空库创建出来。
    """
    cfg = settings or get_settings()
    info: dict[str, object] = {
        "db_path": str(cfg.db_path),
        "db_exists": cfg.db_path.exists(),
    }
    if not info["db_exists"]:
        info.update({"reachable": False, "status": "down", "reason": "数据库文件不存在，请先执行 init"})
        return info

    try:
        conn = connect(cfg, read_only=True)
    except (sqlite3.OperationalError, StorageError) as exc:
        info.update(
            {
                "reachable": False,
                "status": "down",
                "reason": f"数据库文件存在但无法打开：{exc}",
                "problems": ["数据库无法打开（文件损坏或权限不足）"],
            }
        )
        return info

    try:
        info["reachable"] = True
        info["sqlite_version"] = conn.execute("SELECT sqlite_version()").fetchone()[0]
        info["json1"] = json1_available(conn)
        info["foreign_keys"] = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
        info["journal_mode"] = conn.execute("PRAGMA journal_mode").fetchone()[0]
        info["foreign_key_violations"] = len(conn.execute("PRAGMA foreign_key_check").fetchall())

        version = schema_version(conn, create_if_missing=False)
        info["schema_version"] = version
        info["migrations_error"] = None
        try:
            pending = [
                m.label
                for m in pending_migrations(conn, discover_migrations(settings=cfg), create_if_missing=False)
            ]
            info["pending_migrations"] = pending
        except MigrationError as exc:
            info["pending_migrations"] = None
            info["migrations_error"] = str(exc)
            pending = None

        table_count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        info["table_count"] = table_count

        problems: list[str] = []
        if not info["json1"]:
            problems.append("JSON1 扩展不可用")
        if not info["foreign_keys"]:
            problems.append("外键未开启")
        if info["journal_mode"].lower() != "wal":
            problems.append(f"journal_mode 为 {info['journal_mode']}，期望 wal")
        if info["foreign_key_violations"]:
            problems.append(f"存在 {info['foreign_key_violations']} 条外键违规")
        if pending:
            problems.append(f"有 {len(pending)} 个未应用迁移")
        if version == 0 and not pending:
            problems.append("尚未应用任何迁移，请执行 init")
        if info["migrations_error"]:
            problems.append(f"迁移文件异常：{info['migrations_error']}")

        info["problems"] = problems
        # down 只留给"继续跑会静默产生坏数据"的情况：JSON1 或外键不可用
        info["status"] = "down" if not info["json1"] or not info["foreign_keys"] else ("degraded" if problems else "ok")
        return info
    finally:
        conn.close()


__all__ = [
    "Migration",
    "MigrationError",
    "MigrationResult",
    "StorageError",
    "applied_migrations",
    "connect",
    "discover_migrations",
    "initialize",
    "inspect",
    "json1_available",
    "migrate",
    "pending_migrations",
    "schema_version",
]
