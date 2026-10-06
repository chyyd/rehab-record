# 环境搭建与运行（setup）

**当前状态**：阶段 0–5 后端、管理后台与安卓 App 均已交付并验证（**355 个测试通过、0 skip**；
端到端 275 项、跨文档一致性由 `check_docs_consistency.py` 自报（379 项）、浏览器 UI 验收 60 项）。

**2026-10-05（第三步）：治疗记录从「参数表格」改成「SOAP 模板驱动」** —— 迁移 011 重建
`treatment_record`（19 列，含 `body_json` / `rendered_text`），012 删掉字典 / 选项集 / 患者反应定义
六张表，013 给 `patient.status` 加 `pending_discharge`；有效表从 17 张降到 **8 张**、视图 **2 个**；
记录模板改由仓库根的 `templates/*.json`（**16 份**）承载，**不进数据库**。
代价：后端测试 454 → **334**，安卓端（`app/`）**已适配 SOAP 记录页**（Drift schemaVersion 4 → 5 → 6、
`body` 契约、**131 个本地测试全部通过**、`flutter analyze` 无问题、`flutter build apk --debug` 成功），
`admin/` 的字典 / 选项集 / 反应定义 / 模板四个页面**已删除**。

**2026-10-06：复评周期从「每 20 次日常治疗」改成「距首评 30 个自然日」**（用户：
「设定为距离首评或上一次复评 30 个自然日。如果当日没有治疗，顺延到下一次治疗时评估，
也就是 1 个月评一次」）—— 迁移 **014** 删掉 `treatment_record.span_seq`
（**19 列 → 18 列**），`ux_record_assessment_span` 换成 `ux_record_one_initial`；
复评判定的唯一实现是 `services/record_template.py::next_reassessment_due()`
（锚点 = **首评日**，应做日 = `首评日 + 30 × k`）。迁移总数 **14 个（001–014）**。

**排期、休息块、请假三项功能已于 2026-10-05 整体下线**（科室确认排班不是本系统的职责），
`appointment`/`rest_block`/`leave_record` 三张表已由迁移 008 删除；
**临时指派（`temporary_assignment`）与 `scope=temp` 筛选也已删除**（迁移 009），
可见归属现在恒等于 `assigned_therapist_id`。

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
| `APScheduler` 3.11.3 | 每日备份（也可用系统计划任务）；**曾用于临时指派到期清理，该功能已删除** | 标准库 `threading.Timer` 或系统计划任务 |

需要重装或换机器时：

```powershell
& $py -m pip install argon2-cffi APScheduler
```

---

## 1. 运行

```powershell
cd backend
$py = "C:\Users\youda\AppData\Local\Programs\Python\Python313\python.exe"

& $py -m app.cli init           # 建库 + 应用迁移 001–014 到最新 + 健康检查
& $py -m app.cli seed           # 已废弃：种子数据（字典/选项集/反应定义/模板）随迁移 012 下线，
                                # 现在不再有任何需要导入的种子；记录模板是 templates/*.json 文件
& $py -m app.cli health         # 健康检查（JSON）
& $py -m app.cli periods        # 半日制作息（Q11；`session_period` 已删除，这里只用于 /health 与作息展示）
& $py -m app.cli tables         # 列出表与行数
& $py -m app.cli auto-discharge --days 7   # 待出院满 7 天的患者自动出院（管理员也可用
                                           # POST /patients/{no}/discharge/confirm 提前确认）
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
& $py -m unittest discover -s tests -t . -v      # 355 个测试
& $py scripts\verify_http.py                     # 阶段 0 HTTP 端到端（14 项）
& $py scripts\verify_stage1.py                   # 阶段 1 认证与患者（25 项）
& $py scripts\verify_stage2.py                   # 患者列表排序：我最近一次已提交治疗（31 项）
& $py scripts\verify_stage3.py                   # 阶段 3 SOAP 模板记录（59 项）
& $py scripts\verify_stage4.py                   # 阶段 4 离线与同步（36 项）
& $py scripts\verify_stage5.py                   # 阶段 5 汇总打印、后台与 SOAP 文本（67 项）
& $py scripts\verify_soap_flow.py              # SOAP 记录全链路：表单/门禁/出院/输出（43 项）
& $py scripts\count_verify_checks.py             # 复核上面 7 个脚本的项数（合计 275 项）
& $py scripts\check_docs_consistency.py          # 跨文档一致性
```

> **数字怎么来的**：`scripts/count_verify_checks.py` 用 AST 数"运行时会执行的 `check()` 次数"
> （字面量循环会展开，如 `verify_stage2.py` 里一次核对 6 个已下线的接口路径、
> `verify_stage5.py` 里一次核对 7 个 PDF 关键词）。
> `check_docs_consistency.py` 会拿这份结果去核对本节的数字，改了脚本却忘了改文档就会失败。
> 口径已用**运行时输出**复核：把 7 个脚本各跑一遍、数 `OK` / `FAIL` 行，
> 得到 14 / 25 / 31 / 59 / 36 / 67 / 43（合计 **275**），与静态结果逐个吻合。
>
> **2026-10-05（SOAP 改造）后的主题变化**：`verify_stage3.py` 由「字典 / 记录 / 患者反应」
> **重写为「SOAP 模板记录」验收**（取表单 → 建首评 → 当天日常、缺首评/缺复评 409、
> 同一天同一大类至多 2 条、必填缺失 422、`rendered_text` 落库且是 SOAP 文本），35 → 56 项；
> `verify_stage4.py` 改用 `body` payload，并**新增「离线推送同样受硬阻断约束」**一项、后又把该拦截改为逐条 conflict，28 → 36 项；
> `verify_stage5.py` 断言输出是 **SOAP 文本而不是表格**、多日按时间顺序连排，58 → 67 项；
> `verify_stage2.py` 31 项（新增"评估文书不参与排序"）。
>
> **2026-10-06（复评改按 30 个自然日）**：`verify_stage3.py` 56 → 59 项、
> `verify_soap_flow.py` 39 → 43 项，端到端合计 268 → **275 项**。

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
- 实测渲染中文后，用 `pypdf` 反向提取文本，`康复医学科`/`主观资料：`/`本次训练项目`/`张三`
  全部命中；
- 因此**不需要**在容器里打包 `fonts-noto-cjk`，也避开了 WeasyPrint 的 GTK/Pango 原生依赖。

**版式（2026-10-05 SOAP 改造）**：正文是记录落库时**冻结的 `rendered_text`（SOAP 纯文本）**，
不再是参数表格；**多日按时间顺序往下排，不分页、不一天一张**。只有「基本信息 / 统计」
这类元信息仍用小表格（那是抬头，不是病历内容）。

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
阶段 0–5 后端、管理后台 Web 与安卓 App（**记录页已适配 SOAP 改造**）均已交付。

**2026-10-05 的两次下线**：
1. **排期、休息块、请假与临时指派已整体下线**（迁移 008 与 009）；
2. **参数表格模型（字典 / 选项集 / 患者反应定义 / 科室模板）已整体下线**（迁移 011 与 012）——
   治疗记录改为 SOAP 模板驱动，模板是 `templates/*.json` 文件（**不进数据库**）。

原剩余待办均已闭环：`app/` 的安卓记录页与离线 payload **已适配** SOAP 契约
（`GET /records/form` + `body`，Drift schemaVersion 6，**131 个本地测试全部通过**）；
`admin/` 的字典 / 选项集 / 反应定义 / 模板四个页面**已删除**。
见 `README.md` 进度表与 `开发计划.md` 第 9 章的下一步。

**不建议**为本项目另建 venv：当前系统 Python 已装好全部所需包，另建 venv 需要重新下载安装，
反而引入不必要的失败点。如果后续要隔离，再迁到 venv 也不影响仓库内容。

