# 环境搭建与运行（setup）

**当前状态**：阶段 0–5 后端、管理后台与安卓 App 均已交付并验证（**469 个测试通过、0 skip**；
端到端 182 项、跨文档一致性由 `check_docs_consistency.py` 自报、浏览器 UI 验收 60 项）。
**排期、休息块、请假三项功能已于 2026-10-05 整体下线**（科室确认排班不是本系统的职责），
`appointment`/`rest_block`/`leave_record` 三张表已由迁移 008 删除。

---

## 0. 用哪个 Python（最容易搞错的一点）

**必须用系统 Python 3.13**：

```
C:\Users\youda\AppData\Local\Programs\Python\Python313\python.exe
```

DSH 自带的 `dsh-primary-runtime` Python 3.12 **不要用** —— 那个环境里没有任何第三方库，
用它跑会看到 `pip install fastapi` → `No matching distribution found`，从而误判成"网络不通"。
（2026-10-03 我曾因此把项目误判为阻塞，实际是探错了解释器。）

系统 Python 3.13.3 里已就绪：`fastapi 0.116.1`、`SQLAlchemy 2.0.45`、`alembic 1.17.2`、
`uvicorn 0.35.0`、`pydantic 2.11.3`、`PyJWT 2.10.1`、`Jinja2 3.1.6`、`reportlab 4.4.6`、
`pypdf 6.6.0`、`pytest 8.4.1`、`httpx 0.28.1`、`ruff 0.15.20`。

**可选依赖（当前本机已装；缺失时有兜底，不装也能跑）**：

| 包 | 用途 | 未装时的兜底 |
|---|---|---|
| `argon2-cffi` 25.1.0 | 密码哈希 | 标准库 `hashlib.scrypt` / `pbkdf2_hmac` |
| `APScheduler` 3.11.3 | 临时指派到期清理、每日备份（也可用系统计划任务） | 标准库 `threading.Timer` 或系统计划任务 |

需要重装或换机器时：

```powershell
& $py -m pip install argon2-cffi APScheduler
```

---

## 1. 运行

```powershell
cd backend
$py = "C:\Users\youda\AppData\Local\Programs\Python\Python313\python.exe"

& $py -m app.cli init      # 建库 + 迁移到最新 + 健康检查
& $py -m app.cli seed      # 导入全部种子（字典/反应定义/选项集/四大高频模板，幂等）
& $py -m app.cli health    # 健康检查（JSON）
& $py -m app.cli periods   # 半日制作息（Q11：决定记录的 session_period 与临时指派到期时点）
& $py -m app.cli tables    # 列出表与行数
```

数据库默认落在 `data/kf.db`，可用环境变量覆盖：

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `KB_DB_PATH` | `<repo>/data/kf.db` | SQLite 文件路径 |
| `KB_SQLITE_BUSY_TIMEOUT_MS` | `5000` | 写锁等待（D05） |
| `KB_SQLITE_WAL` | `on` | 是否启用 WAL |

### 跑测试

```powershell
cd backend
& $py -m unittest discover -s tests -t . -v      # 469 个测试
& $py scripts\verify_http.py                     # 阶段 0 HTTP 端到端（14 项）
& $py scripts\verify_stage1.py                   # 阶段 1 认证与患者（25 项）
& $py scripts\verify_stage2.py                   # 患者列表排序：我最近一次已提交治疗（22 项）
& $py scripts\verify_stage3.py                   # 阶段 3 字典与治疗记录（35 项）
& $py scripts\verify_stage4.py                   # 阶段 4 离线与同步（28 项）
& $py scripts\verify_stage5.py                   # 阶段 5 汇总打印、后台与模板种子（58 项）
& $py scripts\count_verify_checks.py             # 复核上面 6 个脚本的项数（合计 182 项）
& $py scripts\check_docs_consistency.py          # 跨文档一致性
```

> **数字怎么来的**：`scripts/count_verify_checks.py` 用 AST 数"运行时会执行的 `check()` 次数"
> （字面量循环会展开，如 `verify_stage2.py` 里一次核对 3 个已下线的接口路径）。
> `check_docs_consistency.py` 会拿这份结果去核对本节的数字，改了脚本却忘了改文档就会失败。
> 注意 `verify_stage2.py` 已**重写**为"患者列表排序"验收（原排期/请假断言随功能下线作废），
> 所以项数由 29 降到 22；`verify_stage4.py` 去掉了 1 条排期幂等断言（29 → 28）。

---

## 2. 健康检查解读

`python -m app.cli health` 的 `status` 三种取值：

| status | 含义 | 处置 |
|---|---|---|
| `ok` | 全部检查通过 | 无 |
| `degraded` | 能跑但有问题（存在未应用迁移、非 WAL 模式等），`database.problems` 列出原因 | 看 `problems` 逐条修 |
| `down` | **JSON1 或外键不可用** | 拒绝服务。这两种情况都会静默产生坏数据，必须先修环境 |

---

## 3. PDF 中文渲染（D03，已验证）

**方案：`reportlab` + 内置 CID 字体 `STSong-Light`**，不用 WeasyPrint。

- 该字体是 reportlab **自带的**，不依赖任何系统字体文件，Windows 开发机与 Linux 容器都一样可用；
- 实测渲染中文表格后，用 `pypdf` 反向提取文本，`康复科`/`偏瘫肢体综合训练`/`糊状`/`张三` 全部命中；
- 因此**不需要**在容器里打包 `fonts-noto-cjk`，也避开了 WeasyPrint 的 GTK/Pango 原生依赖。

回归防线：`tests/test_pdf_smoke.py` 会真实渲染 PDF 并校验文本层，字体方案一旦退化就会失败。

---

## 4. 测试临时文件的存放位置（本机踩过的坑）

测试临时文件**直接建在 `backend/data/` 下**（唯一文件名 + 显式删除），没有用系统临时目录，也没有建子目录。原因：

| 做法 | 本机实测结果 |
|---|---|
| `tempfile.TemporaryDirectory()`（系统 `%TEMP%`） | 测试能跑，但解释器退出时清理被拒：`PermissionError [WinError 5]` |
| `tempfile.mkdtemp(dir=backend/data/_test_tmp)` | **创建出来的子目录当前用户无权访问**，往里写文件直接 `Permission denied` |
| `tempfile.mkstemp(dir=backend/data)` ← 当前采用 | 正常，测试结束后自动删除，无残留 |

> **已知残留**：早期调试用 `mkdtemp` 生成的一批空目录位于 `backend/data/` 下
> （`_test_tmp/`、`kf-pdf-*/`）。这些目录带有显式**拒绝删除**权限项，连所有者也无法直接删除，
> 需要先改每个目录自身的权限。它们不含任何代码或业务数据，且 `data/` 已在 `.gitignore` 中，
> 可以安全忽略；若要彻底清除，用本仓库的诊断脚本对每个目录各跑一次。
>
> 这些都是**早期脚手架**留下的：现在的 `tests/support.py` 与 `tests/test_pdf_smoke.py`
> 都改用 `mkstemp` 建唯一文件、并在 `tearDown` 里显式删除，不会再产生新残留。

---

## 5. 后续

系统 Python 3.13 已具备 FastAPI / SQLAlchemy / Alembic / PyJWT / reportlab / pypdf，
阶段 0–5 后端、管理后台 Web 与安卓 App 均已交付并验证完毕。
**排期、休息块、请假已整体下线**（2026-10-05），当前没有排期相关待办，
见 `README.md` 进度表与 `开发计划.md` 末尾的下一步。

**不建议**为本项目另建 venv：当前系统 Python 已装好全部所需包，另建 venv 需要重新下载安装，
反而引入不必要的失败点。如果后续要隔离，再迁到 venv 也不影响仓库内容。

