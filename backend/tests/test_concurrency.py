"""并发与跨线程访问测试。

## 为什么单独建这个文件

系统里有一类**只在并发下才暴露**的缺陷：FastAPI 会把同步依赖（`get_db`）
与路由处理函数分别丢进 anyio 线程池，二者**不保证落在同一个线程**。
`sqlite3` 默认 `check_same_thread=True`，跨线程使用连接会抛
`ProgrammingError: SQLite objects created in a thread can only be used in that same thread`。

这个缺陷的特点：

- **顺序调用测不出来** —— 依赖与路由往往复用同一工作线程；
- **逐个 curl 也测不出来** —— 一次一个请求，线程池复用同一线程；
- **浏览器一打开就炸** —— 首屏同时发好几个请求。

因此这里必须用**真线程池并发**去打接口，否则不叫覆盖。
"""

from __future__ import annotations

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from tests.api_base import ApiTestCase
from tests.support import DbTestCase


class TestStorageCrossThread(DbTestCase):
    """连接本身必须能被另一个线程使用 —— 这是 FastAPI 线程池能工作的前提。"""

    def setUp(self) -> None:
        super().setUp()
        self.migrate()

    def test_connection_usable_from_another_thread(self) -> None:
        result: dict[str, object] = {}

        def use_from_other_thread() -> None:
            try:
                assert self.conn is not None
                row = self.conn.execute("SELECT 1 AS v").fetchone()
                result["value"] = row["v"]
            except Exception as exc:  # noqa: BLE001 - 测试要拿到原始异常
                result["error"] = exc

        thread = threading.Thread(target=use_from_other_thread)
        thread.start()
        thread.join(timeout=10)

        self.assertNotIn(
            "error",
            result,
            f"连接跨线程使用应被允许（check_same_thread=False），实际报错：{result.get('error')}",
        )
        self.assertEqual(result.get("value"), 1)

    def test_handoff_between_many_threads_over_time(self) -> None:
        """连接在多个线程之间**依次**交接 —— 这正是 FastAPI 的用法。

        刻意不测"同一时刻多个线程同时 execute 同一个连接"：SQLite 连接不是线程安全的，
        Python 会直接返回 `None`（实测：`TypeError: 'NoneType' object is not subscriptable`）。
        生产中每个请求都有自己的连接（`get_db` 每请求新建、`finally` 关闭），
        所以真实约束是"**换个线程用没问题**"，而不是"多线程同时用"。
        用 `join` 保证各线程严格串行，才是在断言我们要保证的那件事。
        """
        values: list[int] = []
        errors: list[str] = []

        def worker(index: int) -> None:
            try:
                assert self.conn is not None
                values.append(int(self.conn.execute("SELECT ?", (index,)).fetchone()[0]))
            except Exception as exc:  # noqa: BLE001 - 测试要拿到原始异常
                errors.append(f"{type(exc).__name__}: {exc}")

        for index in range(12):
            thread = threading.Thread(target=worker, args=(index,))
            thread.start()
            thread.join(timeout=10)  # 串行交接，不并发访问同一连接

        self.assertEqual(errors, [], f"线程间交接连接不应报错：{errors[:3]}")
        self.assertEqual(sorted(values), list(range(12)))

    def test_writes_from_another_thread_are_visible(self) -> None:
        """不只是读 —— 跨线程写也要正常（并发写是我们真实会遇到的场景）。"""

        def writer() -> None:
            assert self.conn is not None
            self.conn.execute(
                "INSERT INTO patient (inpatient_no, name) VALUES (?, ?)",
                ("CROSS001", "跨线程患者"),
            )

        thread = threading.Thread(target=writer)
        thread.start()
        thread.join(timeout=10)

        assert self.conn is not None
        row = self.conn.execute(
            "SELECT inpatient_no FROM patient WHERE inpatient_no = ?", ("CROSS001",)
        ).fetchone()
        self.assertIsNotNone(row, "跨线程写入应当生效并可见")


class TestConcurrentApiRequests(ApiTestCase):
    """并发打真实接口 —— 这是浏览器首屏的真实行为。"""

    def setUp(self) -> None:
        super().setUp()
        self.migrate()
        self.admin = self.make_admin("A001")
        self.headers = self.login_headers("A001")

    # 覆盖各模块的列表接口，与后台首页同时发起的请求基本一致
    # （字典 / 选项集 / 模板接口已随迁移 011/012 删除，模板改由 templates/*.json 承载）
    ENDPOINTS = [
        "/api/v1/patients?page=1&page_size=1",
        "/api/v1/users?page=1&page_size=5",
        "/api/v1/records?page=1&page_size=1",
        "/api/v1/records/enums",
        "/api/v1/audit-logs?page=1&page_size=5",
        "/api/v1/summary/date?date=2027-03-01",
        # 排期 / 请假接口已于 2026-10-05 随功能下线删除
        "/api/v1/timeline?page=1&page_size=1",
    ]

    def test_parallel_list_requests_all_succeed(self) -> None:
        def hit(url: str) -> tuple[str, int, str]:
            resp = self.client.get(url, headers=self.headers)
            return url, resp.status_code, resp.text[:200]

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(hit, self.ENDPOINTS * 3))

        bad = [(url, code, body) for url, code, body in results if code != 200]
        self.assertEqual(
            bad,
            [],
            "并发请求不应失败（跨线程使用 SQLite 连接是常见原因）：\n"
            + "\n".join(f"  {u} -> {c} {b}" for u, c, b in bad[:5]),
        )

    def test_repeated_parallel_bursts(self) -> None:
        """连续多轮并发：单轮可能碰巧同线程，多轮更容易暴露。"""
        urls = [
            "/api/v1/patients?page=1&page_size=1",
            "/api/v1/users?page=1&page_size=5",
            "/api/v1/records/enums",
        ]
        for round_index in range(5):
            with ThreadPoolExecutor(max_workers=6) as pool:
                codes = list(
                    pool.map(
                        lambda u: self.client.get(u, headers=self.headers).status_code,
                        urls * 4,
                    )
                )
            self.assertEqual(
                set(codes),
                {200},
                f"第 {round_index + 1} 轮出现非 200：{sorted(set(codes))}",
            )

    def test_parallel_writes_do_not_corrupt(self) -> None:
        """并发写：每请求一个连接 + WAL + busy_timeout，应全部成功。"""

        def create_patient(index: int) -> int:
            resp = self.client.post(
                "/api/v1/patients",
                json={"inpatient_no": f"PAR{index:03d}", "name": f"并发患者{index}"},
                headers=self.headers,
            )
            return resp.status_code

        with ThreadPoolExecutor(max_workers=6) as pool:
            codes = list(pool.map(create_patient, range(12)))

        self.assertEqual(set(codes), {201}, f"并发建患者应全部成功：{sorted(set(codes))}")
        count = self.conn.execute(
            "SELECT COUNT(*) FROM patient WHERE inpatient_no LIKE 'PAR%'"
        ).fetchone()[0]
        self.assertEqual(int(count), 12, "不应丢写或重复写")


if __name__ == "__main__":
    unittest.main(verbosity=2)
