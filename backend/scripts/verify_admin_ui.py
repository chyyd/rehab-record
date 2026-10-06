"""在真实浏览器里验证管理后台（阶段：后台 UI 验收）。

## 这一步在验证什么

类型检查与构建只能证明"代码能编译、接口能对上"，**不能证明页面真的渲染正常**。
本脚本用本机 Edge（headless + CDP，见 `_cdp.py`）实际打开后台并逐页走一遍，
重点抓两类只有浏览器里才暴露的问题：

1. **运行时崩溃**（React 组件 props 误用、undefined 解构等）；
2. **接口与页面对不上**（页面请求了不存在的字段、后端返回结构与前端假设不一致）。

## 前置

- 后端跑在 127.0.0.1:8000，前端 dev server 跑在 127.0.0.1:5173（Vite 代理 /api）。
- Edge 以 `--remote-debugging-port=9222` 启动。

    cd backend
    python scripts/verify_admin_ui.py

脚本**不自己启动**后端与 Edge（它们需要非受限环境），只负责驱动与断言；
缺哪个会明确报出来。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cdp import Cdp, CdpError, new_target  # noqa: E402

ADMIN_URL = "http://localhost:5173"
API_URL = "http://127.0.0.1:8000"
CDP_PORT = 9222
ADMIN_EMPLOYEE_NO = "A001"

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_admin_password() -> str:
    """管理员密码的来源，按优先级：

    1. 环境变量 `KB_ADMIN_PASSWORD`（CI 里显式指定）；
    2. 仓库根目录的 `.dev-admin-password.txt` —— **`start.ps1` 首次运行会随机生成**它。

    为什么要这样找：早先这里硬编码 `Admin#2026pass`，等 `start.ps1` 改成随机密码后
    脚本一跑就崩（`TypeError: 'NoneType' object is not subscriptable`，因为登录失败后
    拿不到 token）。密码是"每台机器一个"的运行时状态，不该写死在验收脚本里。
    """
    env_pw = os.environ.get("KB_ADMIN_PASSWORD")
    if env_pw:
        return env_pw
    pwd_file = _REPO_ROOT / ".dev-admin-password.txt"
    if pwd_file.exists():
        # 显式去掉 U+FEFF：历史上这个文件被写出过 UTF-8 BOM，
        # 那会变成一个真实的字符串首字符，让密码"多一位"而登录 403。
        return pwd_file.read_text(encoding="utf-8").strip().lstrip("\ufeff")
    raise SystemExit(
        "找不到管理员密码：请先运行仓库根目录的 .\\start.ps1（它会生成 "
        ".dev-admin-password.txt），或设置环境变量 KB_ADMIN_PASSWORD。"
    )


ADMIN_PW = _resolve_admin_password()
THERAPIST_PW = "Ther#2026pass"


def _latest_schema_version() -> int:
    """迁移目录里的**最高版本号**（`001_…sql` → 1）。

    为什么要算而不是写死：这里原来断言的是 `schema_version == 5`，
    而迁移早就走到 014 了 —— 于是脚本**必然失败**，而失败信息
    （`FAIL 数据库迁移到最新  [14]`）看起来像"数据库有问题"，
    实际上坏的是这句断言。写死的版本号会随每次迁移悄悄过期。
    """
    mig_dir = _REPO_ROOT / "backend" / "app" / "db" / "migrations"
    versions = [
        int(p.name.split("_", 1)[0])
        for p in mig_dir.glob("*.sql")
        if p.name.split("_", 1)[0].isdigit()
    ]
    return max(versions) if versions else 0

failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def api(path: str, method: str = "GET", body: dict | None = None, token: str | None = None):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(API_URL + path, method=method, data=data)
    if data:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        return exc.code, None


def wait_for(predicate, timeout: float = 12.0, interval: float = 0.3) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def main() -> int:
    # -- 前置检查 --------------------------------------------------------- #
    print("前置检查")
    try:
        with urllib.request.urlopen(f"{API_URL}/api/v1/health", timeout=8) as resp:
            health = json.loads(resp.read().decode())
        check("后端在运行", resp.status == 200, str(resp.status))
        check("数据库迁移到最新", health.get("database", {}).get("schema_version") == _latest_schema_version(),
              f"实际 {health.get('database', {}).get('schema_version')}，"
              f"迁移目录最新 {_latest_schema_version()}")
    except Exception as exc:  # noqa: BLE001
        print(f"  后端不可达：{exc}\n  请先启动：python -m uvicorn app.main:app --port 8000")
        return 2

    try:
        with urllib.request.urlopen(ADMIN_URL, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        check("前端 dev server 在运行", resp.status == 200, str(resp.status))
        check("前端返回的是应用页面", '<div id="root">' in html, html[:120])
    except Exception as exc:  # noqa: BLE001
        print(f"  前端不可达：{exc}\n  请先启动：cd admin && npm run dev")
        return 2

    try:
        urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=8)
        check("Edge 调试端口可用", True)
    except Exception as exc:  # noqa: BLE001
        print(f"  Edge CDP 不可达：{exc}")
        return 2

    # -- 造点数据，保证各页不是空的 --------------------------------------- #
    _, admin = api("/api/v1/auth/login", "POST",
                   {"employee_no": ADMIN_EMPLOYEE_NO, "password": ADMIN_PW})
    if not admin or "access_token" not in admin:
        print("  管理员登录失败：请确认已运行 .\\start.ps1 生成密码，或设置 KB_ADMIN_PASSWORD。")
        return 2
    token = admin["access_token"]
    for no, name in (("UITEST1", "界面测试患者甲"), ("UITEST2", "界面测试患者乙")):
        api("/api/v1/patients", "POST",
            {"inpatient_no": no, "name": name, "diagnosis": "脑卒中恢复期",
             "admin_note": "注意防跌倒"}, token)

    # -- 打开页面 --------------------------------------------------------- #
    print("\n浏览器验证")
    ws_url = new_target(CDP_PORT)
    browser = Cdp(ws_url)
    try:
        # 不开 Network 域：它会给首屏每个子资源产生事件（数千个），
        # 而我们要的只是"有没有报错"，`Log.entryAdded` 已覆盖资源加载失败。
        browser.enable(network=False)

        # 上一次运行留下的 Cookie 会让页面直接是"已登录"状态，
        # 那样就测不到登录页与登录流程了。先清干净再开始。
        browser.call("Network.clearBrowserCookies")
        browser.call("Storage.clearDataForOrigin",
                     {"origin": ADMIN_URL, "storageTypes": "local_storage,session_storage,cookies"})
        browser.goto(ADMIN_URL, settle=1.5)
        browser.goto(ADMIN_URL, settle=2.5)  # 再走一次，确保在清空状态下完成首屏

        # 1) 未登录应停在登录页
        title = browser.eval("document.title")
        check("页面标题正确", title == "康复科管理后台", str(title))
        has_login = browser.eval(
            "!!document.querySelector('input[autocomplete=\"username\"]')"
        )
        check("未登录时显示登录页", bool(has_login))

        # 2) 登录
        browser.eval(
            """
            (() => {
              const set = (el, v) => {
                const proto = Object.getPrototypeOf(el);
                const desc = Object.getOwnPropertyDescriptor(proto, 'value');
                desc.set.call(el, v);
                el.dispatchEvent(new Event('input', { bubbles: true }));
              };
              set(document.querySelector('input[autocomplete="username"]'), 'A001');
              set(document.querySelector('input[autocomplete="current-password"]'), __ADMIN_PW__);
              const btn = [...document.querySelectorAll('button')]
                .find(b => b.type === 'submit' || b.textContent.includes('登录'));
              btn.click();
              return true;
            })()
            """.replace("__ADMIN_PW__", json.dumps(ADMIN_PW))
        )

        # 等到真的离开登录页：URL 变为 / 且登录表单消失。
        # 注意不能只判断"页面上有没有'康复科管理后台'" —— 登录页标题里也有这几个字，
        # 那样即使没登录成功也会通过（实测踩到过，白等 15 秒还报"成功"）。
        logged_in = wait_for(
            lambda: browser.eval("location.pathname") == "/"
            and not browser.eval(
                "!!document.querySelector('input[autocomplete=\"current-password\"]')"
            ),
            timeout=20,
        )
        body_text = browser.eval("document.body.innerText") or ""
        current_path = browser.eval("location.pathname")
        check("登录成功并跳转到总览", logged_in, f"URL={current_path}")
        check("登录后不再显示登录表单",
              not browser.eval(
                  "!!document.querySelector('input[autocomplete=\"current-password\"]')"
              ))
        check("侧边菜单已渲染", "患者管理" in body_text and "审计日志" in body_text,
              body_text[:160])

        # 3) 令牌不能落在 localStorage（关键安全断言）
        storage_dump = browser.eval(
            "JSON.stringify({local: Object.assign({}, localStorage),"
            " session: Object.assign({}, sessionStorage)})"
        )
        check("access/refresh token 不落 Web Storage",
              "access_token" not in str(storage_dump) and "kb_refresh" not in str(storage_dump),
              str(storage_dump)[:200])

        # 4) 总览页有内容（用统计卡独有的字眼，别用菜单里也有的词）
        check("总览页渲染出统计卡",
              "在院患者" in body_text and "系统状态" in body_text and "今日治疗人次" in body_text,
              body_text[:200])
        check("总览页显示了当前登录人", "科室管理员" in body_text, body_text[:200])

        # 5) 逐页导航
        #
        # ⚠ 这里**只列真的存在的页面**。2026-10-06 清掉了四条过期项：
        # `/dict`（字典管理）、`/option-sets`（选项集管理）、
        # `/response-defs`（患者反应定义）、`/templates`（科室模板）——
        # 它们**随迁移 011/012 一起删掉了**（记录改由 JSON 模板驱动，
        # 那四组接口也已删除），但脚本还在验证它们，于是长期 FAIL。
        # 失败信息（"缺少 ['主项目', '子项目']"）看着像页面坏了，
        # 实际上坏的是这句断言 —— 与上面那个写死的 `schema_version == 5` 同类。
        #
        # 与 2026-10-05 删「全局排期 / 请假管理」时的口径一致：
        # **不补占位项**，页面真的没了就不该在这里留一条。
        routes = [
            # ★ 2026-10-06：这里原来直接断言列表里有「界面测试患者甲」。
            # 但本脚本每次运行都会**新建患者**（"浏览器新建患者" / "出院恢复验收患者"），
            # 而患者列表是分页的 —— 跑够多次之后这条断言必然失败
            #（实测库里已积累 21 个测试患者，把 UITEST1 挤到了第 2 页）。
            # 那属于"脚本自己污染了自己的前置条件"。
            #
            # 改成只断言**列本身**（住院编号），并在 §7 里用搜索精确验证那条数据。
            ("/patients", "患者管理", ["住院编号"]),
            ("/records", "治疗记录", ["状态"]),
            ("/summary", "汇总与打印", ["按日期汇总", "导出 PDF"]),
            ("/users", "用户管理", ["工号", "新建用户"]),
            ("/audit-logs", "审计日志", ["操作人", "对象类型"]),
        ]
        for path, menu_name, needles in routes:
            browser.eval(f"history.pushState({{}}, '', '{path}'); window.dispatchEvent(new PopStateEvent('popstate'))")
            time.sleep(1.8)
            text = browser.eval("document.body.innerText") or ""
            url = browser.eval("location.pathname")
            if url != path:
                # pushState 后 React Router 不一定响应；退化为直接点击菜单项
                clicked = browser.eval(
                    f"""
                    (() => {{
                      const link = [...document.querySelectorAll('a')]
                        .find(a => a.getAttribute('href') === '{path}');
                      if (link) {{ link.click(); return true; }}
                      return false;
                    }})()
                    """
                )
                if clicked:
                    time.sleep(1.8)
                    text = browser.eval("document.body.innerText") or ""
                    url = browser.eval("location.pathname")
            check(f"进入 {menu_name}（{path}）", url == path, f"实际 URL {url}")
            missing = [n for n in needles if n not in text]
            check(f"{menu_name} 页面渲染出关键内容", not missing, f"缺少 {missing}")
            crashed = "页面出错" in text or "Something went wrong" in text
            check(f"{menu_name} 未出现错误页", not crashed, text[:160])

        # 6) 患者页表格确实有数据行 + **归属治疗师列已去掉**（2026-10-06 用户要求）
        browser.eval(
            """
            (() => {
              const link = [...document.querySelectorAll('a')].find(a => a.getAttribute('href') === '/patients');
              if (link) link.click();
              return true;
            })()
            """
        )
        time.sleep(2.2)
        row_count = browser.eval("document.querySelectorAll('.ant-table-tbody tr.ant-table-row').length")
        check("患者表格渲染出数据行", int(row_count or 0) > 0, f"行数 {row_count}")

        # 用户原话：「患者管理页去掉归属治疗师列」。
        # 注意**不能**用 `"归属治疗师" not in text` 来判：列头虽然没了，
        # 但行内的「分配归属」按钮还在，`innerText` 里仍会出现"归属"二字。
        # 所以直接按**表头单元格文本**比对。
        headers = browser.eval(
            "JSON.stringify([...document.querySelectorAll('.ant-table-thead th')]"
            + ".map(th => th.innerText.trim()))"
        )
        header_list = json.loads(headers) if headers else []
        check("患者表格的表头里没有「归属治疗师」",
              not any("归属治疗师" in h for h in header_list), str(header_list))
        check("患者表格仍有「注意事项」列（只删该删的）",
              any("注意事项" in h for h in header_list), str(header_list))

        # 6b) 用**搜索**精确验证既有患者能在列表里显示
        #     （不再依赖分页 —— 见 routes 里的说明）。
        #
        #     注意这是 antd 的 `Input.Search`：**光 set value + input 事件不会触发搜索**，
        #     要点那个放大镜按钮（或回车）。所以这里填完值再点按钮。
        browser.eval(
            """
            (() => {
              const input = [...document.querySelectorAll('input')]
                .find(i => (i.placeholder || '').includes('住院编号'));
              if (!input) return 'no-input';
              const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
              setter.call(input, '界面测试患者甲');
              input.dispatchEvent(new Event('input', { bubbles: true }));
              // `Input.Search` 支持回车触发；比点放大镜更稳（不用猜按钮在哪一层）。
              for (const type of ['keydown', 'keypress', 'keyup']) {
                input.dispatchEvent(new KeyboardEvent(type, {
                  key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true,
                }));
              }
              return 'entered';
            })()
            """
        )
        time.sleep(2.6)
        found_text = browser.eval("document.body.innerText") or ""
        check("搜「界面测试患者甲」能搜到 UITEST1",
              "界面测试患者甲" in found_text and "UITEST1" in found_text,
              found_text[:200])

        # ★ 搜完必须**把筛选清掉**再继续。
        # 下面 §7b 会新建患者并断言"提交后新患者出现在列表里" ——
        # 列表若还筛着「界面测试患者甲」，那条断言必然失败（而且后面几条会连锁失败）。
        # 我自己第一版就漏了这一步，一次跑出 6 条无关失败。
        browser.eval(
            """
            (() => {
              const input = [...document.querySelectorAll('input')]
                .find(i => (i.placeholder || '').includes('住院编号'));
              if (!input) return false;
              const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
              setter.call(input, '');
              input.dispatchEvent(new Event('input', { bubbles: true }));
              for (const type of ['keydown', 'keypress', 'keyup']) {
                input.dispatchEvent(new KeyboardEvent(type, {
                  key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true,
                }));
              }
              return true;
            })()
            """
        )
        time.sleep(2.4)

        # 7b) 交互：打开"新建患者"弹窗并提交，确认表单能真正写库
        #     （只验证渲染不够 —— 表单绑定、校验、提交链路都要走一遍）
        new_no = f"UI{int(time.time()) % 100000:05d}"
        browser.eval(
            """
            (() => {
              const btn = [...document.querySelectorAll('button')]
                .find(b => b.textContent.includes('新建患者'));
              if (btn) { btn.click(); return true; }
              return false;
            })()
            """
        )
        time.sleep(1.5)
        # 弹窗有开启动画，且 **antd 6 把内容容器从 `.ant-modal-content` 改成了
        # `.ant-modal-container`** —— 沿用 v5 的选择器会一直得到 0（实测踩到过）。
        # 这里用 `.ant-modal` 作为根，再找它里面的表单控件，不依赖内部类名细节。
        modal_open = wait_for(
            lambda: bool(
                browser.eval(
                    "document.querySelectorAll('.ant-modal input').length > 0"
                    " || document.querySelectorAll('.ant-modal textarea').length > 0"
                )
            ),
            timeout=10,
        )
        check("新建患者弹窗已打开且表单可填", modal_open)

        if modal_open:
            browser.eval(
                """
                (() => {
                  const set = (el, v) => {
                    const proto = Object.getPrototypeOf(el);
                    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v);
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                  };
                  const modal = document.querySelector('.ant-modal');
                  const byLabel = (label) => {
                    const item = [...modal.querySelectorAll('.ant-form-item')]
                      .find(f => f.textContent.includes(label));
                    return item ? item.querySelector('input') : null;
                  };
                  set(byLabel('住院编号'), __NEW_NO__);
                  set(byLabel('姓名'), '浏览器新建患者');
                  // antd 会在两个中文字之间插入空格（"保 存"），因此要先去空白再比对
                  const norm = (s) => (s || '').replace(/\\s+/g, '');
                  const ok = [...modal.querySelectorAll('button')]
                    .find(b => norm(b.textContent) === '保存');
                  if (!ok) return 'NO_SAVE_BUTTON';
                  ok.click();
                  return true;
                })()
                """.replace("__NEW_NO__", json.dumps(new_no))
            )
            time.sleep(3.0)
            created = browser.eval("document.body.innerText.includes('浏览器新建患者')")
            toast = browser.eval(
                "[...document.querySelectorAll('.ant-message-notice-content')]"
                ".map(e => e.textContent).join('|')"
            )
            modal_still_open = browser.eval("!!document.querySelector('.ant-modal')")
            check(
                "提交后新患者出现在列表里",
                bool(created),
                f"页面提示：{toast}；弹窗仍在：{modal_still_open}",
            )
            status, _ = api(f"/api/v1/patients/{new_no}", token=token)
            check("新患者确实写入数据库", status == 200, f"HTTP {status}")

            # 收尾：关掉可能仍开着的弹窗，避免影响后续断言
            browser.eval(
                """
                (() => {
                  const norm = (s) => (s || '').replace(/\\s+/g, '');
                  const cancel = [...document.querySelectorAll('.ant-modal button')]
                    .find(b => norm(b.textContent) === '取消');
                  if (cancel) cancel.click();
                  return true;
                })()
                """
            )
            time.sleep(0.8)

        # 7c) 出院恢复：管理员应能把"已出院"改回"在院"（Q9）
        #
        # 这是一条**业务不变式**，必须常驻验收：曾经 PUT /patients/{no} 里有一条
        # "已出院不能再改状态"的判断，把管理员自己的权限也挡了，形成死锁
        # （提示"请联系系统管理员"，而调用者就是管理员）。
        # 单测盯得住接口，但盯不住"表单里的下拉能否真的改回去" —— 这里两种情况都覆盖。
        restore_no = f"RM{int(time.time()) % 100000:05d}"
        create_status, _ = api(
            "/api/v1/patients",
            method="POST",
            body={"inpatient_no": restore_no, "name": "出院恢复验收患者"},
            token=token,
        )
        check("准备恢复用例：创建患者", create_status == 201, f"HTTP {create_status}")
        discharge_status, _ = api(
            f"/api/v1/patients/{restore_no}",
            method="PUT",
            body={"status": "discharged"},
            token=token,
        )
        check("准备恢复用例：置为已出院", discharge_status == 200, f"HTTP {discharge_status}")

        # 刷新列表让新患者出现
        browser.eval(
            """
            (() => {
              const btn = [...document.querySelectorAll('button')].find(b => b.textContent.includes('刷新'));
              if (btn) btn.click();
              return true;
            })()
            """
        )
        time.sleep(2.0)

        opened_restore = browser.eval(
            """
            (() => {
              const rows = [...document.querySelectorAll('.ant-table-tbody tr.ant-table-row')];
              const row = rows.find(r => r.textContent.includes('__RESTORE_NO__'));
              if (!row) return 'NO_ROW';
              const btn = [...row.querySelectorAll('button')].find(b => b.textContent.includes('编辑'));
              if (!btn) return 'NO_EDIT';
              btn.click();
              return 'ok';
            })()
            """.replace("__RESTORE_NO__", restore_no)
        )
        check("已出院患者可以打开编辑", opened_restore == "ok", str(opened_restore))
        time.sleep(2.0)

        restore_modal = browser.eval("(document.querySelector('.ant-modal') || {}).innerText || ''")
        check("弹窗提示已出院可恢复", "该患者已出院" in restore_modal, restore_modal[:200])
        check("弹窗说明会单独记入审计", "恢复（出院改回）" in restore_modal, restore_modal[:240])

        # 注意：**antd 6 的 Select 触发器是 `.ant-select-content`**，
        # v5 的 `.ant-select-selector` 在 6 里已经不存在 —— 沿用它只会拿到 null（实测踩到过）。
        opened_select = browser.eval(
            """
            (() => {
              const item = [...document.querySelectorAll('.ant-modal .ant-form-item')]
                .find(x => x.textContent.includes('状态'));
              if (!item) return 'NO_ITEM';
              const box = item.querySelector('.ant-select-content') || item.querySelector('.ant-select');
              if (!box) return 'NO_BOX';
              box.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
              return 'opened';
            })()
            """
        )
        check("展开状态下拉", opened_select == "opened", str(opened_select))
        time.sleep(1.2)

        picked = browser.eval(
            """
            (() => {
              const opts = [...document.querySelectorAll('.ant-select-item-option')];
              const target = opts.find(o => o.textContent.trim() === '在院');
              if (!target) return 'NO_OPTION:' + opts.length;
              target.dispatchEvent(new MouseEvent('click', { bubbles: true }));
              return 'picked';
            })()
            """
        )
        check("下拉里可以选回「在院」", picked == "picked", str(picked))
        time.sleep(0.8)

        saved_restore = browser.eval(
            """
            (() => {
              const modal = document.querySelector('.ant-modal');
              if (!modal) return 'NO_MODAL';
              const norm = (s) => (s || '').replace(/\\s+/g, '');
              const ok = [...modal.querySelectorAll('button')].find(b => norm(b.textContent) === '保存');
              if (!ok) return 'NO_SAVE';
              ok.click();
              return 'saved';
            })()
            """
        )
        check("保存恢复结果", saved_restore == "saved", str(saved_restore))
        time.sleep(3.0)

        restore_toast = browser.eval(
            "[...document.querySelectorAll('.ant-message-notice-content')]"
            ".map(e => e.textContent).join('|')"
        )
        check(
            "恢复过程没有报「不能改回」",
            "不能改回" not in restore_toast and "403" not in restore_toast,
            f"提示={restore_toast}",
        )

        _, restored = api(f"/api/v1/patients/{restore_no}", token=token)
        check(
            "已出院患者确实改回在院",
            bool(restored) and restored.get("status") == "in_hospital",
            str(restored and restored.get("status")),
        )

        _, logs = api("/api/v1/audit-logs?target_type=patient&page=1&page_size=5", token=token)
        actions = [item["action"] for item in (logs or {}).get("items", [])]
        check("恢复单独记为 restore 动作", "restore" in actions, str(actions))

        # 8) 运行时错误总账
        browser.drain()
        console_errors = [e for e in browser.console_errors if e.strip()]
        page_errors = [e for e in browser.page_errors if e.strip()]

        # 未登录首次进入后台时会**故意**用 Cookie 试一次 refresh，必然 400/401。
        # 这是设计行为（见 AuthProvider.bootstrap），不是缺陷。
        console_errors = [
            e for e in console_errors
            if "favicon" not in e.lower()
            and "status of 400" not in e and "status of 401" not in e
        ]
        # ★ 2026-10-06：剔掉**浏览器扩展**抛的异常。
        #
        # 本脚本用本机 Edge 跑，而真实 Edge 会加载用户已装的扩展；实测有个扩展
        # （`chrome-extension://amkbmndfnliijdhojkpoglbnaaahippg`）在每次按键时
        # 抛 `TypeError: Cannot read properties of undefined (reading 'toLowerCase')`。
        # 那与后台代码无关，却会把"没有未捕获的页面异常"这项**永远**判失败 ——
        # 一项永远失败的检查等于没有检查。
        #
        # 只按来源过滤，**不按错误内容**过滤：后台自己的异常仍会被抓到。
        page_errors = [e for e in page_errors if "chrome-extension://" not in e]
        console_errors = [e for e in console_errors if "chrome-extension://" not in e]
        check("没有未捕获的页面异常", not page_errors, str(page_errors[:3]))
        check("没有 console.error", not console_errors, str(console_errors[:3]))

        # 9) 网络层：没有收集 Network 事件时，退化为检查 console/log 里是否出现
        #    "Failed to load resource"（4xx/5xx 会以这种方式出现）
        resource_failures = [
            e for e in browser.console_errors
            if "failed to load resource" in e.lower()
            and "400" not in e and "401" not in e and "favicon" not in e.lower()
        ]
        check("没有失败的业务资源请求", not resource_failures, str(resource_failures[:3]))
    except CdpError as exc:
        check(f"CDP 交互失败：{exc}", False)
    finally:
        browser.close()

    print()
    if failures:
        print(f"{len(failures)}/{checks} 项失败：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print(f"全部 {checks} 项通过：管理后台在真实浏览器中可正常登录与逐页使用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
