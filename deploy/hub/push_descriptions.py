"""把 `deploy/hub/*.md` 推进 Docker Hub 的仓库介绍（Overview）。

Docker Hub 允许通过 API 改仓库描述（网页端手点也行，但那样没有版本管理）。
**介绍文本本身是有价值的产出**，所以正文存在 `deploy/hub/<仓库名>.md`，
这个脚本只负责"把仓库里的那份同步上去"。

## 用法

    # 先拿一个 JWT（用户名密码用你自己的；也可以设 KB_HUB_TOKEN 直接给 token）
    $py = 'C:\\Users\\youda\\AppData\\Local\\Programs\\Python\\Python313\\python.exe'
    & $py deploy/hub/push_descriptions.py --user chyyd

    # 只看会不会成功，不真写
    & $py deploy/hub/push_descriptions.py --user chyyd --dry-run

## ⚠ 两个硬限制（都实测踩过）

1. **`description`（副标题）上限 100 字节** —— 中文一个字 3 字节，
   所以最多约 33 个汉字。超了返回 400，而 PowerShell 的
   `Invoke-RestMethod` **不打印响应体**，只看得到 "400 Bad Request"，
   很容易误判成"内容里的 Markdown 有问题"（我就在这上面绕了几轮）。
2. **`full_description` 上限 25000 字节**（当前正文 ~5 KB，离得很远）。

脚本会在发送前先校验字节数，把这类错误挡在本地。
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

HUB = "https://hub.docker.com/v2"

# 短描述（副标题）**必须** ≤ 100 字节。见模块文档。
SHORT_DESCRIPTIONS = {
    "kf-record-backend": "康复科治疗过程记录系统 — 后端 API（FastAPI + SQLite）",
    "kf-record-admin": "康复科治疗记录系统 — 管理后台（Nginx + React）",
}

MAX_SHORT_BYTES = 100
MAX_FULL_BYTES = 25000


def api(path: str, *, method: str = "GET", body: dict | None = None, token: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(HUB + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "JWT " + token)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:400]
        # ★ 一定要把响应体打出来：Docker Hub 的校验错误只在 body 里说清楚是哪个字段、
        #   实际多少字节、上限多少。只打印状态码会让人去猜。
        raise SystemExit(f"HTTP {exc.code} {path}\n  {detail}") from None


def login(user: str, password: str) -> str:
    got = api("/users/login/", method="POST", body={"username": user, "password": password})
    token = (got or {}).get("token")
    if not token:
        raise SystemExit("登录成功但响应里没有 token")
    return token


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="把 deploy/hub/*.md 同步到 Docker Hub 仓库介绍")
    parser.add_argument("--user", help="Docker Hub 用户名（用于换 JWT）")
    parser.add_argument("--password", help="不推荐：会进 shell 历史。留空则交互输入或用 KB_HUB_TOKEN")
    parser.add_argument("--dry-run", action="store_true", help="只校验与打印，不真写")
    parser.add_argument("--only", help="只处理某个仓库（如 kf-record-backend）")
    args = parser.parse_args(argv)

    token = os.environ.get("KB_HUB_TOKEN")
    if not token and not args.dry_run:
        if not args.user:
            raise SystemExit("需要 --user（或设 KB_HUB_TOKEN）")
        password = args.password or os.environ.get("KB_HUB_PASSWORD") or getpass.getpass(
            f"{args.user} 的 Docker Hub 密码/Token："
        )
        token = login(args.user, password)
        print("已登录，拿到 JWT")

    user = args.user or os.environ.get("KB_HUB_USER")
    if not user:
        raise SystemExit("需要 --user 或 KB_HUB_USER 才能拼出仓库路径")

    failures = 0
    for repo, short in SHORT_DESCRIPTIONS.items():
        if args.only and args.only != repo:
            continue
        md_file = here / f"{repo}.md"
        if not md_file.exists():
            print(f"✗ 找不到 {md_file}")
            failures += 1
            continue

        full = md_file.read_text(encoding="utf-8")
        short_bytes = len(short.encode())
        full_bytes = len(full.encode())
        print(f"\n{user}/{repo}")
        print(f"  description      {short_bytes:>6} 字节 / {MAX_SHORT_BYTES}  {'OK' if short_bytes <= MAX_SHORT_BYTES else '✗ 超限'}")
        print(f"  full_description {full_bytes:>6} 字节 / {MAX_FULL_BYTES}  {'OK' if full_bytes <= MAX_FULL_BYTES else '✗ 超限'}")

        # 先在本地拦住超限 —— 别浪费一次网络往返，也别让报错看起来像"内容有问题"
        if short_bytes > MAX_SHORT_BYTES:
            print("  ✗ 短描述超长，先改 SHORT_DESCRIPTIONS 再跑")
            failures += 1
            continue
        if full_bytes > MAX_FULL_BYTES:
            print("  ✗ 正文超长，请精简")
            failures += 1
            continue

        if args.dry_run:
            print("  （dry-run，未写入）")
            continue

        got = api(
            f"/repositories/{user}/{repo}/",
            method="PATCH",
            body={"description": short, "full_description": full},
            token=token,
        )
        written = len((got or {}).get("full_description") or "")
        print(f"  ✅ 已写入（回读 {written} 字符）")

    if failures:
        print(f"\n{failures} 个仓库有问题")
        return 1
    print("\n全部完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
