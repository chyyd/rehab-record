# 康复科治疗过程记录系统

治疗师床旁快速记录工具。**排期 → 治疗 → 记录 → 汇总打印**，选择为主、少打字、可离线、可追溯。

- **范围**：治疗过程记录 + 轻量排期。**不含**收费、医保、患者签字、治疗组、绩效统计。
- **技术栈**：后端 Python + SQLite + JSON；移动端 Android（Flutter）；管理后台 React + Vite + Ant Design。

## 文档导航

| 文档 | 内容 | 读者 |
|---|---|---|
| [设计.md](设计.md) | 业务设计与技术文档（**V1.2**）。业务意图的唯一来源 | 全员 |
| [开发计划.md](开发计划.md) | 可执行规格：设计评估与问题清单、数据模型修订、接口清单、五阶段计划与验收标准、风险、已确认结论 | 全员 |
| [CHANGELOG.md](CHANGELOG.md) | 全部变更记录。**每次改动都必须在这里留一条** | 全员 |
| [docs/setup.md](docs/setup.md) | 环境搭建与运行、依赖安装、已知环境问题 | 开发 |

> 文档冲突时的优先级：**迁移文件 / `worktime.py`（代码） > `开发计划.md` > `设计.md`（业务意图）**。
> 发现不一致要立刻回头修文档，不允许长期并存。

## 常用约定（开工前必读）

- **时间戳**一律 UTC ISO8601 带毫秒：`strftime('%Y-%m-%dT%H:%M:%fZ','now')`。
  **禁止** `datetime('now','localtime')`——SQLite 无时区概念，该修饰符在 +08:00 下会写出快 8 小时的时间戳。
- **日期/时刻**（排期、作息）用本地墙钟：日期 `YYYY-MM-DD`，时刻 `HH:MM`。
- **半日制作息**（Q11 定稿）：上午 `06:00–11:30`、下午 `13:00–17:30`。
  排期、休息、请假的时间语义统一由 `backend/app/core/worktime.py` 提供，**任何模块不得自己写时间字面量**。
- **排期不变量**（S1 / Q1 / Q2）：治疗师半日 = 一台；患者半日 = 一名治疗师。
- **请假无审批流**（Q6）：登记即生效；治疗师自己请，管理员可代录。
- **枚举**在库层用 `CHECK` 约束兜底，业务层仍需校验（双重保护）。
- **JSON 字段**用 `json_valid()` 兜底，防止写入非 JSON 导致读取期才爆炸。

## 当前进度

| 阶段 | 内容 | 状态 |
|---|---|---|
| 阶段 0 | SQLite 初始化与迁移、作息定义、健康检查、CLI、**FastAPI 骨架 + 统一错误体** | **已完成** |
| 阶段 1 | **认证（argon2 + JWT 轮换）、用户管理、患者与归属、可见归属解析** | **已完成** |
| 阶段 2 | **排期（半日格子）、三条冲突规则、可排性查询、休息块、请假（登记即生效）** | **已完成** |
| 阶段 3 | **字典与选项集解析、治疗记录状态机、参数带入、两层快照、患者反应** | **已完成** |
| 阶段 4 | **离线幂等推送（client_uuid）、游标增量拉取、冲突分层（草稿客户端优先）** | **已完成** |
| 阶段 5 | **三套中文 PDF 汇总打印、记录模板、审计日志查询、后台选项集维护** | **已完成** |
| 模板种子 | **四大高频模板**（运动/生活/言语/吞咽，4 套科室模板 / 29 条明细，参数取自字典默认值） | **已完成**（D04 / T3.2 闭环） |
| 文档 | `设计.md` 修订至 V1.2/V1.3（半日制排期、无审批流请假、Q11 作息、PDF 方案修订） | **已完成**（跨文档校验 156 项 0 失败） |
| 种子数据 | 字典 4/29/89 + 患者反应 27 条 + 全局选项集 47 套/208 项 + 模板 4 套，全部幂等导入 | **已完成** |
| 中文 PDF | **reportlab + 内置 CID 字体 `STSong-Light`**，三套模板经 pypdf 反向文本校验 | **已完成**（D03 修订，Q10 版式） |
| 测试 | **538 个测试全部通过、0 skip**；端到端 183 项 + **浏览器 UI 验收 55 项** | **已完成** |
| 接口 | **87 个**（认证、用户、患者、排期、休息、请假、字典读写、选项集、记录、同步、汇总、打印、模板、审计、后台） | **已完成** |
| 管理后台 Web | **React 19 + Vite 8 + Ant Design 6 + TS**，13 个模块全部实现，构建通过（`admin/`） | **已完成**（T5.4 前端） |
| 安卓 App | Flutter 骨架、排期页、记录页、同步引擎（T1.6/T2.7/T2.8/T3.8/T4.4/T4.5） | 未开始 |

> **用哪个 Python**：必须用系统 Python 3.13
> （`C:\Users\youda\AppData\Local\Programs\Python\Python313\python.exe`）。
> DSH 自带的 `dsh-primary-runtime` Python 3.12 里没有第三方库，用它跑会误判成"网络不通" —— 详见 [docs/setup.md](docs/setup.md) 第 0 节。

## 快速开始

### 最省事：一键脚本（推荐）

```powershell
.\start.ps1              # 启动后端 + 管理后台，打印管理员账号密码，并自动打开浏览器到登录页
.\start.ps1 stop         # 停止（含后端与管理后台的整棵进程树）
.\start.ps1 status       # 查看运行状态与健康检查
.\start.ps1 restart      # 重启
.\start.ps1 clean        # 清理运行时产物（缓存/日志/测试临时文件/浏览器剖析目录）
.\start.ps1 clean -IncludeData   # 连开发数据库一起删（下次启动会重建并导种子）
.\start.ps1 -NoBrowser   # 只启动，不打开浏览器
```

首次运行会自动完成：建库 → 应用迁移 → 导入种子 → 创建管理员 → 安装前端依赖。
**管理员密码是随机生成的**，会打印在窗口里并保存到 `.dev-admin-password.txt`
（已 gitignore）。之后每次启动都复用同一个密码，不会把上次的作废。

启动后脚本会**自校验**一次（用刚配置的密码真的调一次登录接口）——避免出现
"窗口里打印了密码却登不进去"这种最难自己想明白的情况。

> 若提示"禁止运行脚本"，用其中任一种：
> `powershell -ExecutionPolicy Bypass -File .\start.ps1`
> 或 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

脚本会自动找 Python（优先 `.python-path` 文件 → `KB_PYTHON` 环境变量 → 常见安装位置）。
各人 Python 路径不同时，在仓库根目录建一个 `.python-path` 文件写上解释器完整路径即可。

### 目录结构

```
├── backend/                 后端（FastAPI + SQLite）
│   ├── app/                 按 api → services → models/core 分层
│   │   ├── api/v1/          路由
│   │   ├── services/        业务逻辑（不依赖 FastAPI）
│   │   ├── models/          数据访问
│   │   ├── schemas/         请求/响应模型
│   │   ├── core/            配置、安全、错误、依赖
│   │   └── db/migrations/   5 个 SQL 迁移（带 checksum 校验）
│   ├── seed/                种子数据（字典/选项集/反应定义/模板，JSON + 导入器）
│   ├── scripts/             端到端验收脚本（_ 前缀的是共用工具）
│   ├── tests/               单元与集成测试
│   └── data/                测试临时文件目录（用时自动建，内容自动清）
├── admin/                   管理后台前端（React + Vite + Ant Design）
│   └── src/                 api / auth / components / layouts / pages
├── docs/setup.md            环境与依赖说明（用哪个 Python、沙箱坑等）
├── data/kf.db               开发数据库（gitignore；真实数据在这里）
├── start.ps1                一键启停/清理脚本
├── 设计.md                   业务与系统设计（含全部决策 Q1–Q11）
├── 开发计划.md               阶段与任务清单
├── CHANGELOG.md             全部改动记录
└── README.md
```

运行时产物（`.run/`、`admin/node_modules/`、`admin/dist/`、`data/`、`.npm-cache/`、
`__pycache__` 等）全部已 gitignore；需要腾空间时跑 `.\start.ps1 clean`。

### 手动方式（后端）

```powershell
cd backend
# 必须用系统 Python 3.13（见下方"用哪个 Python"）
$py = "C:\Users\youda\AppData\Local\Programs\Python\Python313\python.exe"

& $py -m app.cli init      # 建库 + 迁移到最新 + 健康检查
& $py -m app.cli seed      # 导入全部种子（字典/反应定义/选项集/四大高频模板，幂等）
$env:KB_ADMIN_PASSWORD = 'Admin#2026pass'
& $py -m app.cli create-admin A001 --name 科室管理员   # 初始管理员
& $py -m app.cli close-expired   # 关闭过期临时指派（建议每 5 分钟由计划任务调用）
& $py -m app.cli health    # 健康检查（JSON）
& $py -m app.cli periods   # 打印半日制作息与请假到期时点

& $py -m app.main --reload # 启动服务端：http://127.0.0.1:8000/docs
& $py -m unittest discover -s tests -t . -v      # 543 个测试
& $py scripts\verify_http.py                     # 阶段 0 HTTP 端到端
& $py scripts\verify_stage1.py                   # 阶段 1 认证与患者
& $py scripts\verify_stage2.py                   # 阶段 2 排期与请假
& $py scripts\verify_stage3.py                   # 阶段 3 字典与治疗记录
& $py scripts\verify_stage4.py                   # 阶段 4 离线与同步
& $py scripts\verify_stage5.py                   # 阶段 5 汇总打印、后台与模板种子
& $py scripts\check_docs_consistency.py          # 跨文档一致性（156 项）
```

> **验收脚本可在同一个库上重复运行**（共 183 项检查）。清理统一走
> `scripts/_e2e.py` 的 `purge_*`，按外键顺序删除，不要在脚本里手写 `DELETE` ——
> 早先就是因为在一次性干净库上验收，掩盖了"重跑必失败"的外键顺序问题。

### 管理后台 Web

```powershell
cd admin
npm install            # 首次
npm run dev            # http://127.0.0.1:5173（自动把 /api 代理到 127.0.0.1:8000）
npm run build          # 生产构建 → dist/
```

细节与已知环境限制见 [admin/README.md](admin/README.md)。
**Vite 构建需要非受限环境**（Windows 下它会调用 `net use`，受限环境中报 `spawn EPERM`）；
`tsc` 类型检查不受影响。

**在真实浏览器里验收后台**（55 项检查，含登录、逐页导航与一次真实表单提交）：

```powershell
# 需要三样同时就绪：后端(8000)、Vite dev(5173)、Edge 带调试端口
& $msedge --headless=new --remote-debugging-port=9222 --user-data-dir=<临时目录> about:blank
cd backend; & $py scripts\verify_admin_ui.py
```

浏览器驱动是 `scripts/_cdp.py`（**只用标准库**的最小 CDP 客户端，模块说明里写了为何不引入
Playwright）。这一步不是可选项 —— 类型检查与构建**测不出**并发下的 500、也测不出页面渲染问题：
本项目的 SQLite 跨线程缺陷正是它抓到的。

**当前不需要 pip、不需要 venv**：M0 骨架只用标准库。

## 仓库结构

```
├─ 设计.md / 开发计划.md / CHANGELOG.md / README.md
├─ docs/          setup.md（环境）、后续补 api.md / data-model.md / sync-protocol.md
├─ backend/
│  ├─ app/        core（配置/作息/健康）· db（存储/迁移）· cli.py · main.py
│  │  └─ db/migrations/   001 表结构、002 触发器（时间戳与留痕策略的唯一来源）
│  ├─ seed/       字典种子（幂等，按 code upsert；待阶段 3 补全）
│  ├─ scripts/    运维与验证脚本
│  └─ tests/      88 个测试（标准库 unittest）
├─ app/           Flutter 客户端（待建）
├─ admin/         管理后台 React + Ant Design（待建）
└─ deploy/        Docker Compose + Nginx（待建）
```
