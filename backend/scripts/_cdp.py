"""极简 Chrome DevTools Protocol 客户端（只用标准库）。

## 为什么自己写

项目里没有 Playwright / Selenium，也不该为了"在浏览器里点几下"引入一整套
浏览器驱动依赖（还要下载几百 MB 的内核）。而本机已有 Edge，
用它的 `--remote-debugging-port` 就能通过 CDP 驱动 —— 只需要一个最小的
WebSocket 客户端：握手 + 发文本帧 + 收文本帧。协议本身不复杂，
标准库的 `socket` / `base64` / `struct` 足够。

## 限制（如实说明）

只实现验收需要的子集：文本帧、不分片、客户端掩码（RFC 6455 要求）。
二进制帧与超长分片不处理 —— CDP 的响应都是文本 JSON，
`Runtime.evaluate` 的结果也走 JSON，够用。
"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import urllib.request
from typing import Any
from urllib.parse import urlparse


class CdpError(RuntimeError):
    pass


class WebSocket:
    """最小的同步 WebSocket 客户端（仅文本帧）。"""

    def __init__(self, url: str, timeout: float = 30.0) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "ws":
            raise CdpError(f"只支持 ws:// ，收到 {url}")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")

        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self._sock.sendall(handshake.encode())
        # 读握手响应直到空行
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise CdpError("WebSocket 握手时连接被关闭")
            buffer += chunk
        status_line = buffer.split(b"\r\n", 1)[0].decode(errors="replace")
        if "101" not in status_line:
            raise CdpError(f"WebSocket 握手失败：{status_line}")
        self._rest = buffer.split(b"\r\n\r\n", 1)[1]

    def send_text(self, text: str) -> None:
        payload = text.encode("utf-8")
        header = bytearray([0x81])  # FIN + text
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < (1 << 16):
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        mask = os.urandom(4)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(bytes(header) + masked)

    def _recv_exact(self, count: int) -> bytes:
        data = self._rest[:count]
        self._rest = self._rest[count:]
        while len(data) < count:
            chunk = self._sock.recv(count - len(data))
            if not chunk:
                raise CdpError("连接在读帧时被关闭")
            data += chunk
        return data

    def recv_text(self) -> str:
        while True:
            first, second = self._recv_exact(2)
            opcode = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._recv_exact(8))[0]
            payload = self._recv_exact(length) if length else b""
            if opcode == 0x1:
                return payload.decode("utf-8", errors="replace")
            if opcode == 0x8:
                raise CdpError("对端发送了关闭帧")
            # ping / pong / 其它帧忽略，继续读

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


class Cdp:
    """与一个页面会话（target）交互。"""

    def __init__(self, ws_url: str) -> None:
        self._ws = WebSocket(ws_url)
        self._next_id = 0
        self.console_errors: list[str] = []
        self.page_errors: list[str] = []
        self.requests: list[dict[str, Any]] = []
        self._buffer: list[dict[str, Any]] = []

    # -- 命令 ------------------------------------------------------------- #
    def call(self, method: str, params: dict[str, Any] | None = None, timeout_events: int = 400) -> dict[str, Any]:
        """发一条 CDP 命令并等它的响应。

        **必须把等待期间收到的事件先存起来**，而不是直接丢弃：
        页面在导航/首屏渲染时会涌出成百上千个事件（每个模块的
        `Network.responseReceived`、每次渲染的 `Runtime.consoleAPICalled`），
        如果这些事件里夹着"属于下一个命令的响应"，丢了就再也要不回来了 ——
        表现为下一条命令永远等不到响应（实测踩到过。
        `Network.enable` 之后单次页面加载就能产生数千个事件）。
        """
        self._next_id += 1
        message_id = self._next_id
        self._ws.send_text(json.dumps({"id": message_id, "method": method, "params": params or {}}))

        for _ in range(timeout_events):
            raw = self._ws.recv_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if message.get("id") == message_id:
                # 先把这轮缓冲的事件按序处理掉，保证错误收集不丢
                pending, self._buffer = self._buffer, []
                for item in pending:
                    self._handle_event(item)
                if "error" in message:
                    raise CdpError(f"{method} 失败：{message['error']}")
                return message.get("result", {})

            if "id" in message:
                # 属于其它命令的响应（我们没用并发命令），先存着
                self._buffer.append(message)
            else:
                self._handle_event(message)

        raise CdpError(f"{method} 在 {timeout_events} 个事件内没有响应")

    def _handle_event(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        params = message.get("params", {})
        if method == "Runtime.consoleAPICalled" and params.get("type") == "error":
            text = " ".join(
                str(a.get("value", a.get("description", ""))) for a in params.get("args", [])
            )
            self.console_errors.append(text[:500])
        elif method == "Runtime.exceptionThrown":
            detail = params.get("exceptionDetails", {})
            exc = detail.get("exception", {}) or {}
            # ★ 2026-10-06：原来只取 `exception.description`，取不到就退成 `detail.text`，
            # 而 `text` 是个**普通字符串**（如 "Uncaught"）—— 于是报错内容常常只有
            # `Object` 或 `未知异常`，**根本没法定位**。这里把类型、消息、值、位置
            # 与调用栈的头部都拼进去，让"没有未捕获的页面异常"这条检查真的可用。
            parts: list[str] = []
            if exc.get("className"):
                parts.append(str(exc["className"]))
            if exc.get("description"):
                parts.append(str(exc["description"]))
            elif exc.get("value") is not None:
                parts.append(str(exc["value"]))
            if detail.get("text"):
                parts.append(str(detail["text"]))
            loc = detail.get("url") or ""
            if loc:
                parts.append(
                    f"@ {loc}:{detail.get('lineNumber', '?')}:{detail.get('columnNumber', '?')}"
                )
            frames = (detail.get("stackTrace", {}) or {}).get("callFrames", []) or []
            for f in frames[:4]:
                fn = f.get("functionName") or "(anonymous)"
                parts.append(
                    f"    at {fn} ({f.get('url', '')}:{f.get('lineNumber', '?')}:"
                    f"{f.get('columnNumber', '?')})"
                )
            desc = "\n".join(parts) or "未知异常"
            self.page_errors.append(str(desc)[:2000])
        elif method == "Log.entryAdded":
            entry = params.get("entry", {})
            if entry.get("level") == "error":
                self.console_errors.append(str(entry.get("text", ""))[:500])
        elif method == "Network.responseReceived":
            response = params.get("response", {})
            self.requests.append({"url": response.get("url", ""), "status": response.get("status", 0)})

    def drain(self, seconds_events: int = 300) -> None:
        """把挂起的事件读掉（不阻塞太久）。"""
        self._ws._sock.settimeout(0.35)
        try:
            for _ in range(seconds_events):
                try:
                    self._handle_event(json.loads(self._ws.recv_text()))
                except TimeoutError:
                    break
                except (CdpError, json.JSONDecodeError):
                    break
        finally:
            self._ws._sock.settimeout(30.0)

    # -- 便捷方法 --------------------------------------------------------- #
    def enable(self, *, network: bool = True) -> None:
        self.call("Runtime.enable")
        self.call("Page.enable")
        self.call("Log.enable")
        if network:
            # `Network` 域会为**每个**子资源产生事件，页面首屏动辄数千个。
            # 只关心"有没有 4xx/5xx"时不必开它 —— `Log.entryAdded` 已经会报告
            # 资源加载失败，而且事件量小得多。
            self.call("Network.enable")

    def eval(self, expression: str, await_promise: bool = True) -> Any:
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": True,
                "userGesture": True,
            },
        )
        if result.get("exceptionDetails"):
            detail = result["exceptionDetails"]
            desc = detail.get("exception", {}).get("description") or detail.get("text")
            raise CdpError(f"页面内 JS 抛错：{desc}")
        return result.get("result", {}).get("value")

    def goto(self, url: str, settle: float = 1.6) -> None:
        import time

        self.call("Page.navigate", {"url": url})
        time.sleep(settle)

    def close(self) -> None:
        self._ws.close()


def new_target(port: int = 9222, url: str = "about:blank") -> str:
    """新建一个标签页，返回它的 WebSocket 调试地址。"""
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/json/new?{urllib.parse.quote(url, safe=':/?=&')}",
        method="PUT",
    )
    with urllib.request.urlopen(request, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return str(payload["webSocketDebuggerUrl"])


__all__ = ["Cdp", "CdpError", "WebSocket", "new_target"]
