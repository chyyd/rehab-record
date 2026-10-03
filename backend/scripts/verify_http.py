"""端到端验证：用**真实 uvicorn 服务器**跑一遍关键接口。

与 `tests/test_api.py` 的区别：测试用 `TestClient`（进程内直连 ASGI），
本脚本真的起 HTTP 服务器再发请求，覆盖网络层与协议层——部署前值得跑一次。

    cd backend
    python scripts/verify_http.py

退出码 0 表示全部通过。
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn  # noqa: E402

HOST = "127.0.0.1"


def _free_port() -> int:
    """向系统要一个空闲端口，避免与残留进程或其它服务撞端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


PORT = _free_port()
BASE = f"http://{HOST}:{PORT}"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def request(path: str, method: str = "GET") -> tuple[int, str, str]:
    req = urllib.request.Request(BASE + path, method=method, data=b"" if method != "GET" else None)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.headers.get("content-type", ""), resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("content-type", ""), exc.read().decode("utf-8")


def main() -> int:
    from app.main import app

    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # 等服务就绪（最多 10 秒）
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.2)
    if not server.started:
        print("服务未能启动", file=sys.stderr)
        return 2
    print(f"uvicorn 已启动：{BASE}\n")

    try:
        # 1) 版本化健康检查
        code, ctype, body = request("/api/v1/health")
        payload = json.loads(body)
        check("GET /api/v1/health → 200", code == 200, str(code))
        check("健康检查 status=ok", payload.get("status") == "ok", str(payload.get("status")))
        check("Content-Type 为 JSON", "application/json" in ctype, ctype)
        check("库为 WAL 且外键开启", payload["database"]["journal_mode"].lower() == "wal"
              and payload["database"]["foreign_keys"] is True)
        check("无未应用迁移", payload["database"]["pending_migrations"] == [],
              str(payload["database"]["pending_migrations"]))
        check("作息为 Q11 定稿值",
              payload["worktime"]["morning"]["start"] == "06:00"
              and payload["worktime"]["morning"]["end"] == "11:30"
              and payload["worktime"]["afternoon"]["start"] == "13:00"
              and payload["worktime"]["afternoon"]["end"] == "17:30")
        check("中文未被转义（ensure_ascii=False）", "康复科" in body)

        # 2) 无前缀健康检查（容器编排探活）
        code, _, body = request("/health")
        check("GET /health → 200", code == 200, str(code))

        # 3) 根路径服务信息
        code, _, body = request("/")
        info = json.loads(body)
        check("GET / → 服务信息", code == 200 and info.get("api_prefix") == "/api/v1")

        # 4) 统一错误体（D08）
        code, _, body = request("/api/v1/nope")
        err = json.loads(body)
        check("未知路径 → 404 且结构化", code == 404 and err.get("code") == "NOT_FOUND")
        check("404 不含 FastAPI 默认 detail 字段", "detail" not in err)

        code, _, body = request("/api/v1/health", method="POST")
        err = json.loads(body)
        check("POST /api/v1/health → 405 且结构化",
              code == 405 and err.get("code") == "METHOD_NOT_ALLOWED")

        # 5) OpenAPI 与文档
        code, _, body = request("/openapi.json")
        schema = json.loads(body)
        check("OpenAPI 可生成且含健康检查", code == 200 and "/api/v1/health" in schema["paths"])
        code, ctype, body = request("/docs")
        check("Swagger UI 可访问", code == 200 and "text/html" in ctype)
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    print()
    if failures:
        print(f"{len(failures)} 项失败：")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("HTTP 端到端验证全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
