# 康复科治疗过程记录系统

治疗师床旁快速记录工具。**认领患者 → 治疗 → 记录 → 汇总打印**，选择为主、少打字、可离线、可追溯。

- **范围**：治疗过程记录。**不含**排班/排期、收费、医保、患者签字、治疗组、绩效统计。
  > **2026-10-05**：科室确认**排班不是本系统的职责**——"app功能过剩，违背方便记录的初衷"。
  > 排期、休息块、请假三项功能已**整体下线**（后端 + 管理后台 + 安卓），
  > `appointment`/`rest_block`/`leave_record` 三张表已删除；患者列表改按
  > **"我最近一次已提交治疗"**排序。
  > 同日第二步：**临时指派（`temporary_assignment`）与 `scope=temp` 筛选也已删除**（迁移 009）——
  > 可见归属**恒等于** `assigned_therapist_id`；但**记录级的 `is_temporary` 标记保留**（PDF / 汇总 / 后台在用），
  > 两者不是一回事。
  > **2026-10-05 第三步**：治疗记录由**参数表格**改为 **SOAP 模板驱动** —— 模板是
  > `templates/*.json` 文件（**不进数据库**，用户要求「使用json格式保存模板，不进数据库，
  > 以便以后我手动修改」）；**四大类分开记录**（`PT` 运动 / `OT` 生活技能 / `ST_SW` 吞咽 /
  > `ST_SP` 言语，理由「考虑到可能是不同的治疗师操作」）；评估文书（首评 / 复评 / 出院小结）
  > **不占用日常训练次数**且**不能跳过**（用户原话「1A。2不能。3不能。」）；
  > **复评按自然日算**（2026-10-06 改，原「每 20 次日常后复评」已废）—— 锚点是**首评日**，
  > 应做日 = `首评日 + 30 × k`（`REASSESS_INTERVAL_DAYS = 30`），应做日那天没治疗就顺延，
  > 下次来治疗时照样拦（用户：「也就是 1 个月评一次」）；
  > 出院走 `pending_discharge`（**任何治疗师可发起**，管理员确认或满 7 天由
  > `app.cli auto-discharge --days 7` 自动出院）。记录内容存 `body_json` + **冻结的
  > `rendered_text`（SOAP 纯文本）**。**已删除**：字典 / 选项集 / 患者反应定义 / 科室模板
  > **已删除**：字典 / 选项集 / 患者反应定义 / 科室模板六张表（迁移 011/012），
  > 以及 `/dict/**`、`/option-sets*`、`/response-defs*`、`/templates*` 四组接口（均已删除）。
  > 决策与代价见 [CHANGELOG.md](CHANGELOG.md)。
- **技术栈**：后端 Python + SQLite + JSON；移动端 Android（Flutter）；管理后台 React + Vite + Ant Design。

## 文档导航

| 文档 | 内容 | 读者 |
|---|---|---|
| [设计.md](设计.md) | 业务设计与技术文档（**V1.4**）。业务意图的唯一来源 | 全员 |
| [开发计划.md](开发计划.md) | 可执行规格（**V0.8**）：设计评估与问题清单、数据模型修订、接口清单、五阶段计划与验收标准、风险、已确认结论 | 全员 |
| [CHANGELOG.md](CHANGELOG.md) | 全部变更记录。**每次改动都必须在这里留一条** | 全员 |
| [docs/setup.md](docs/setup.md) | 环境搭建与运行、依赖安装、已知环境问题 | 开发 |
| [docs/deploy-docker.md](docs/deploy-docker.md) | **Docker 部署**：镜像构建与推送（轩辕镜像）、目标机器一键起、数据卷迁移、排障 | 部署 |
| [docs/sync-protocol.md](docs/sync-protocol.md) | **离线同步协议**（游标/幂等/冲突分层、客户端本地库设计、**评估文书硬阻断在离线推送时同样生效**）。App 开工前必读 | 移动端 |
| [templates/README.md](templates/README.md) | **SOAP 记录模板**（JSON）的字段说明与改法。模板是内容不是数据，改它不需要迁移 | 全员 |

> 文档冲突时的优先级：**迁移文件 / `templates/*.json`（代码） > `开发计划.md` > `设计.md`（业务意图）**。
> 发现不一致要立刻回头修文档，不允许长期并存。

## 常用约定（开工前必读）

- **时间戳**一律 UTC ISO8601 带毫秒：`strftime('%Y-%m-%dT%H:%M:%fZ','now')`。
  **禁止** `datetime('now','localtime')`——SQLite 无时区概念，该修饰符在 +08:00 下会写出快 8 小时的时间戳。
- **日期/时刻**（记录日期、作息）用本地墙钟：日期 `YYYY-MM-DD`，时刻 `HH:MM`。
- **半日制作息**（Q11 定稿）：上午 `06:00–11:30`、下午 `13:00–17:30`。
  注意 `session_period`（"一条记录属于哪个半日"）**已随 SOAP 改造删除**，
  这套作息现在只由 `backend/app/core/worktime.py` 提供给 `/health` 与 `app.cli periods`。
- **患者列表排序**：归属分组优先（我的 → 未分配 → 其他），组内按**我最近一次已提交治疗**的日期**降序**；
  只算 `kind='daily'` 且 `status='submitted'`（草稿、首评/复评/出院小结、已锁定都不算），
  从没治过的排最后（视图 `v_patient_last_treated`）。
- **记录内容**：`body_json`（`{field_key: value}`）是答案，**冻结的 `rendered_text`** 是 SOAP 纯文本 ——
  打印与归档一律用后者，**不得**在打印时从模板重算（病历是法律文书）。
- **记录模板**是 `templates/<大类>/<形态>.json`（4 大类 × 4 形态 = **16 份**），
  **不进数据库**；「本次训练项目」的候选值来自 `templates/disciplines.json` 的 `therapy_options`
  （运动 58 / 生活技能 5 / 吞咽 4 / 言语 13）。
- **归属解析**：唯一真源是 `v_patient_visibility` 视图 + `app/models/patient.py::visibility_from()` 的
  scope 条件（`mine` / `unassigned`）。2026-10-05 起该视图**直接投影 `assigned_therapist_id`**
  （可见归属恒等于原归属），`scope=temp` 与 `temporary_assignment` 表**已删除**（迁移 009）。
- **枚举**在库层用 `CHECK` 约束兜底，业务层仍需校验（双重保护）。
- **JSON 字段**用 `json_valid()` 兜底，防止写入非 JSON 导致读取期才爆炸。

## 当前进度

| 阶段 | 内容 | 状态 |
|---|---|---|
| 阶段 0 | SQLite 初始化与迁移、作息定义、健康检查、CLI、**FastAPI 骨架 + 统一错误体** | **已完成** |
| 阶段 1 | **认证（argon2 + JWT 轮换）、用户管理、患者与归属、可见归属解析** | **已完成** |
| 阶段 2 | ~~排期（半日格子）、冲突规则、可排性查询、休息块、请假~~ | **已取消**（2026-10-05：排班不是本系统的职责；患者列表排序改按实际治疗，验收脚本已重写为 31 项） |
| 阶段 3 | **SOAP 模板记录**（`GET /records/form` 表单、四大类 × 四形态、评估文书不占次数且不可跳过、**距首评 30 个自然日复评**、`rendered_text` 冻结、出院流程） | **已完成** |
| 阶段 4 | **离线幂等推送（client_uuid）、游标增量拉取、冲突分层（草稿客户端优先）、离线推送也走同一套门禁** | **已完成** |
| 阶段 5 | **三套中文 PDF 汇总打印（SOAP 纯文本、多日按时间顺序连排）、审计日志查询** | **已完成** |
| 记录模板 | **`templates/` 16 份 JSON 模板**（4 大类 × 4 形态）+ `schema.json` / `disciplines.json`；疗法清单运动 58 / 生活技能 5 / 吞咽 4 / 言语 13 | **已完成**（D04 / T3.2 闭环，改后不需迁移） |
| 文档 | `设计.md` 修订至 **V1.4**、`开发计划.md` **V0.8**；跨文档校验 384 项 0 失败 | **已完成** |
| 种子数据 | `app.cli seed` 与字典/选项集/反应定义/模板四类种子**已废弃**（承载它们六张表已由迁移 012 删除） | **已废弃** |
| 中文 PDF | **reportlab + 内置 CID 字体 `STSong-Light`**，三套模板经 pypdf 反向文本校验 | **已完成**（D03 修订，Q10 版式 + SOAP 正文） |
| 测试 | **366 个测试全部通过、0 skip**；端到端 277 项 + **浏览器 UI 验收 60 项** | **已完成** |
| 接口 | **46 个接口**（38 个路径：认证、用户、患者与出院、SOAP 记录表单、同步、汇总、打印、审计） | **已完成**（字典/选项集/反应定义/模板四组接口已删除） |
| 管理后台 Web | **React 19 + Vite 8 + Ant Design 6 + TS**，**6 个模块**（总览 / 患者 / 治疗记录 / 汇总打印 / 用户 / 审计）；排期页、请假页、字典/选项集/反应定义/模板四个页面**已删除**；记录与汇总改为 SOAP 纯文本；患者页含**出院确认 / 取消待出院** | **已完成**（删除四个页面后重新构建 exit 0） |
| 安卓 App | Flutter：**3 个页签**（患者 / 时间轴 / 我的）、汇总与 PDF 打印（三种去向）、同步与冲突处理；**Drift schemaVersion 6**（记录表按 SOAP 重建、删除 `record_items` 表）。**记录页已适配 SOAP 改造**（`GET /records/form` 一屏 chip + `body` 契约），**131 个本地测试全部通过** | **已完成** |

> **用哪个 Python**：必须用系统 Python 3.13
> （`C:\Users\youda\AppData\Local\Programs\Python\Python313\python.exe`）。
> DSH 自带的 `dsh-primary-runtime` Python 3.12 里没有第三方库，用它跑会误判成"网络不通" —— 详见 [docs/setup.md](docs/setup.md) 第 0 节。

## 快速开始

### 最省事：一键脚本（推荐）

```powershell
.\start.ps1              # 启动后端 + 管理后台，打印管理员账号密码，并自动打开浏览器到登录页
.\start.ps1 -LocalOnly   # 只绑本机（默认是**同时**供内网其它客户端访问）
.\start.ps1 stop         # 停止（含后端与管理后台的整棵进程树）
.\start.ps1 status       # 查看运行状态与健康检查
.\start.ps1 restart      # 重启
.\start.ps1 clean        # 清理运行时产物（缓存/日志/测试临时文件/浏览器剖析目录）
.\start.ps1 clean -IncludeData   # 连开发数据库一起删（下次启动会重建并应用迁移）
.\start.ps1 -NoBrowser   # 只启动，不打开浏览器
```

> **默认就把服务开在局域网上**：后端与 Vite 都绑 `0.0.0.0`（**仅 IPv4，不监听 IPv6**），
> 并自动放行防火墙入站端口 —— 启动信息里会直接打印内网访问地址，
> 科室里其它电脑（治疗师/护士）用那个地址就能打开管理后台。
> 放行防火墙需要**管理员**权限；不是管理员时脚本会打印可直接复制的命令，
> 本机访问不受影响。确实不需要内网访问时用 `-LocalOnly`。详见 `admin/README.md`。

首次运行会自动完成：建库 → 应用迁移 001–014 → 创建管理员 → 安装前端依赖。
（曾经还会"导入种子"——`app.cli seed` 现在是**已废弃的空操作**：字典 / 选项集 / 反应定义 /
模板四类种子随迁移 011/012 下线，记录模板改由 `templates/*.json` 承载。）
**管理员密码是随机生成的**，会打印在窗口里并保存到 `.dev-admin-password.txt`
（已 gitignore）。之后每次启动都复用同一个密码，不会把上次的作废。

启动后脚本会**自校验**一次（用刚配置的密码真的调一次登录接口）——避免出现
"窗口里打印了密码却登不进去"这种最难自己想明白的情况。

> 若提示"禁止运行脚本"，用其中任一种：
> `powershell -ExecutionPolicy Bypass -File .\start.ps1`
> 或 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

脚本会自动找 Python（优先 `.python-path` 文件 → `KB_PYTHON` 环境变量 → 常见安装位置）。
各人 Python 路径不同时，在仓库根目录建一个 `.python-path` 文件写上解释器完整路径即可。

### Docker 方式（换机器部署用）

要交付到另一台机器、不想在那台机器上装 Python/Node，就把后端与管理后台打成镜像：

```powershell
cd admin; npm run build; cd ..     # 前端产物（镜像直接 COPY 它）
copy .env.example .env             # 填 KB_JWT_SECRET 与 KB_ADMIN_PASSWORD
docker compose build
docker compose push                # 推到 docker.xuanyuan.run/kf-record/*
```

目标机器只要 `compose.yml` + `.env`，`docker compose up -d`，打开 `http://<IP>:8080`。
完整步骤（含 Windows 装 Docker、数据卷迁移、排障）见
**[docs/deploy-docker.md](docs/deploy-docker.md)**。

### 目录结构

```
├── backend/                 后端（FastAPI + SQLite）
│   ├── app/                 按 api → services → models/core 分层
│   │   ├── api/v1/          路由
│   │   ├── services/        业务逻辑（不依赖 FastAPI；`record_template.py` 是模板加载与 SOAP 渲染）
│   │   ├── models/          数据访问
│   │   ├── schemas/         请求/响应模型
│   │   ├── core/            配置、安全、错误、依赖
│   │   └── db/migrations/   **14 个 SQL 迁移**（带 checksum 校验；011 SOAP 记录重建、
│   │                        012 删除字典六表、013 患者待出院、014 删除 span_seq）
│   ├── seed/                种子数据（**已废弃**：字典/选项集/反应定义/模板四类随迁移 012 下线）
│   ├── scripts/             端到端验收脚本（_ 前缀的是共用工具）
│   ├── tests/               单元与集成测试
│   └── data/                测试临时文件目录（用时自动建，内容自动清）
├── templates/               **SOAP 记录模板（JSON，不进数据库）**：schema.json + disciplines.json
│                            + README.md + PT/OT/ST_SW/ST_SP 各 4 份 = **16 份**
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

& $py -m app.cli init      # 建库 + 应用迁移 001–014 + 健康检查
& $py -m app.cli seed      # 已废弃：字典/选项集/反应定义/模板四类种子随迁移 012 下线，现无种子可导
$env:KB_ADMIN_PASSWORD = 'Admin#2026pass'
& $py -m app.cli create-admin A001 --name 科室管理员   # 初始管理员
& $py -m app.cli health    # 健康检查（JSON）
& $py -m app.cli periods   # 打印半日制作息（`session_period` 已删除，这里只用于 /health 与作息展示）
& $py -m app.cli auto-discharge --days 7   # 待出院满 7 天自动出院（管理员也可确认/取消）

& $py -m app.main --reload # 启动服务端：http://127.0.0.1:8000/docs
& $py -m unittest discover -s tests -t . -v      # 355 个测试
& $py scripts\verify_http.py                     # 阶段 0 HTTP 端到端（14 项）
& $py scripts\verify_stage1.py                   # 阶段 1 认证与患者（27 项）
& $py scripts\verify_stage2.py                   # 患者列表排序（原阶段 2 排期已取消）（31 项）
& $py scripts\verify_stage3.py                   # 阶段 3 SOAP 模板记录（59 项）
& $py scripts\verify_stage4.py                   # 阶段 4 离线与同步（36 项）
& $py scripts\verify_stage5.py                   # 阶段 5 汇总打印、后台与 SOAP 文本（67 项）
& $py scripts\verify_soap_flow.py                # SOAP 记录全链路：表单 / 门禁 / 出院 / 输出（43 项）
& $py scripts\count_verify_checks.py             # 复核上面 7 个脚本的验收项数（277 项）
& $py scripts\check_docs_consistency.py          # 跨文档一致性（376 项）
```

> **验收脚本可在同一个库上重复运行**（端到端 277 项检查；项数用 `scripts/count_verify_checks.py`
> 复核，它会按"循环展开"数出运行时会执行的 `check()` 次数，并已用运行时输出逐项对齐）。
> 清理统一走 `scripts/_e2e.py` 的 `purge_*`，按外键顺序删除，不要在脚本里手写 `DELETE` ——
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

**在真实浏览器里验收后台**（60 项检查，含登录、逐页导航与一次真实表单提交）：

```powershell
# 需要三样同时就绪：后端(8000)、Vite dev(5173)、Edge 带调试端口
& $msedge --headless=new --remote-debugging-port=9222 --user-data-dir=<临时目录> about:blank
cd backend; & $py scripts\verify_admin_ui.py
```

浏览器驱动是 `scripts/_cdp.py`（**只用标准库**的最小 CDP 客户端，模块说明里写了为何不引入
Playwright）。这一步不是可选项 —— 类型检查与构建**测不出**并发下的 500、也测不出页面渲染问题：
本项目的 SQLite 跨线程缺陷正是它抓到的。

**依赖用系统 Python 3.13 已装好的那一套**（FastAPI / uvicorn / PyJWT / reportlab / pypdf 等，
清单与版本见 [docs/setup.md](docs/setup.md) 第 0 节）；不需要 pip、不需要 venv。

## 仓库结构

```
├─ 设计.md / 开发计划.md / CHANGELOG.md / README.md
├─ docs/          setup.md（环境）、sync-protocol.md（**离线同步协议**）、后续补 api.md / data-model.md
├─ templates/     **SOAP 记录模板（JSON，不进数据库）**：schema.json + disciplines.json + README.md
│                 + PT/OT/ST_SW/ST_SP 各 4 份 = **16 份**（4 大类 × 4 形态）
├─ backend/
│  ├─ app/        core（配置/作息/健康）· db（存储/迁移）· cli.py · main.py
│  │  └─ db/migrations/   **001–014（14 个）**：表结构、触发器、可见归属视图、同步、模板 code、
│  │                      放开半日互斥、排序视图、**删除排期**、**删除临时指派**、
│  │                      **删除 visibility_state**、**SOAP 记录重建（011）**、
│  │                      **删除字典六表（012）**、**患者待出院（013）**、
│  │                      **删除 span_seq（014，复评改按 30 个自然日）**
│  ├─ seed/       **已废弃**（字典 4/29/89、反应 27、选项集 47/208、模板 4/29 随迁移 011/012 下线）
│  ├─ scripts/    7 个验收脚本（http + 阶段 1–5 + verify_soap_flow）· count_verify_checks.py · check_docs_consistency.py · verify_admin_ui.py（CDP）
│  └─ tests/      **366 个测试**（标准库 unittest）
├─ app/           Flutter 客户端（3 个页签，Drift schemaVersion 6；**记录页已适配 SOAP**，见 `app/README.md`）
├─ admin/         管理后台 React 19 + Vite 8 + Ant Design 6（字典/选项集/反应定义/模板四个页面已删除）
└─ deploy/        Docker Compose + Nginx（待建）
```
