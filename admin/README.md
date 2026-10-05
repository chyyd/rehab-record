# 康复科管理后台（Web）

React + Vite + Ant Design（`开发计划.md` D02 定稿形态）。独立于安卓 App 构建，
产物为静态文件，生产由 Nginx 托管并反代 `/api`。

## 快速开始

```powershell
cd admin
npm install                     # 首次
npm run dev                     # 开发：http://127.0.0.1:5173
npm run build                   # 生产构建 → dist/
npm run preview                 # 本地预览构建产物
```

开发期 Vite 会把 `/api` 代理到后端（默认 `http://127.0.0.1:8000`）。
后端不在默认端口时：

```powershell
$env:VITE_API_TARGET='http://127.0.0.1:9000'; npm run dev
```

先起后端（在 `backend/` 下）：

```powershell
$py = 'C:\Users\youda\AppData\Local\Programs\Python\Python313\python.exe'
& $py -m app.cli init           # 建库 + 迁移 001–013
# & $py -m app.cli seed         # 已废弃：种子数据随迁移 012 下线，现在没有种子要导
$env:KB_ADMIN_PASSWORD='Admin#2026pass'; & $py -m app.cli create-admin A001 --name 科室管理员
& $py -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 环境要求与已知限制

- **Node 22 / npm 11**（本机实测版本）。pnpm / yarn 未安装，本项目用 npm。
- **Vite 构建需要非受限环境**。Windows 下 Vite 会调用 `net use` 解析真实路径，
  在受限（沙箱）环境中会报 `spawn EPERM`。这是环境限制，不是项目缺陷：
  `tsc` 类型检查在受限环境下可正常通过。
- 本机把 npm 缓存放在用户目录时会被拒绝写入，因此构建脚本里用
  `npm_config_cache=<仓库>/.npm-cache`（该目录已 gitignore）。

## 目录结构

```
admin/
├── index.html            # 入口（必须指向 /src/main.tsx）
├── vite.config.ts        # 代理与分包
├── tsconfig.json         # 注意：必须显式声明 "jsx": "react-jsx" 与 React 类型
└── src/
    ├── api/
    │   ├── client.ts     # axios 实例：内存 access token、401 静默刷新、统一错误体
    │   └── endpoints.ts  # 与后端 schemas 对齐的类型与调用封装
    ├── auth/
    │   └── AuthProvider.tsx   # 登录状态；启动时用 Cookie 换 access token
    ├── layouts/AppLayout.tsx  # 侧边菜单 + 顶栏（菜单与路由同源）
    ├── components/Feedback.tsx # useAsync / 错误框 / 空态 / 页头，统一三态处理
    ├── routes.tsx        # 路由表与守卫（RequireAuth / RequireAdmin）
    └── pages/            # 各功能模块
```

## 认证设计（与后端对应）

- **access token 只放内存**，刷新页面即丢 —— 页面加载时用 httpOnly Cookie
  静默换一个新的，用户无感。
- **refresh token 在 httpOnly Cookie 里**，JS 永远读不到，XSS 偷不走长期凭证。
- 401 时自动刷新一次并重放原请求；并发 401 **共用同一个刷新 Promise**，
  否则 refresh 轮换会让先到的请求作废（令牌是一次性的）。
- 后端取用顺序是 Cookie 优先，安卓端仍走请求体，协议未破坏。

## 模块清单

> **当前共 6 个模块**（与 `src/layouts/AppLayout.tsx` 的 `NAV_ITEMS` 及 `src/routes.tsx` 一一对应）。

> **2026-10-05**：「全局排期」与「请假管理」两个页面**随排期功能下线一并删除**
> （科室确认排班不是本系统的职责，后端 `/schedule`、`/rest-blocks`、`/leave` 接口也已删除）。
>
> **2026-10-05（第二步）**：「字典管理」「选项集管理」「患者反应定义」「科室模板」四个页面
> **已删除** —— 后端承载它们的六张表已随迁移 012 删除，对应接口
> `/dict/**`、`/option-sets*`、`/response-defs*`、`/templates*` 也**已下线**。
> 记录模板改由仓库根的 `templates/*.json` **文件**承载（不进数据库），后台**不做模板维护**。
> `admin/src/pages/` 下已无这四个页面文件，导航与路由也一并移除。
>
> > **`npm run build` 的目录清单已核对**：删除四个页面后重新构建 **exit 0**
> >（`tsc && vite build` 通过，`✓ built in 468ms`）。

| 模块 | 路由 | 说明 |
|---|---|---|
| 总览 | `/` | 关键计数 + 系统状态 + 最近操作 |
| 患者管理 | `/patients` | CRUD、注意事项、归属分配/取消、归属历史；**出院确认 / 取消待出院也在这里**（`POST /patients/{no}/discharge/confirm` / `cancel`） |
| 治疗记录 | `/records` | 列表筛选、明细、锁定；明细展示服务端**冻结的 `rendered_text`（SOAP 纯文本）**，列表用 `rendered_excerpt` 摘要；不再有"参数明细 / 患者反应"列。「是否临时治疗」列用的是**记录级 `is_temporary`**（与已删除的临时指派机制无关，见 `设计.md` 3.7） |
| 汇总与打印 | `/summary` | 按日期/按患者汇总 + 三套 PDF 下载（正文是 SOAP 纯文本） |
| 用户管理 | `/users` | CRUD、重置密码、会话查看与踢下线 |
| 审计日志 | `/audit-logs` | 按人/对象/时间查询 + 变更前后对比 |
| ~~字典管理~~ | ~~`/dict`~~ | **已删除**（后端接口已下线） |
| ~~选项集管理~~ | ~~`/option-sets`~~ | **已删除**（后端接口已下线） |
| ~~患者反应定义~~ | ~~`/response-defs`~~ | **已删除**（后端接口已下线） |
| ~~科室模板~~ | ~~`/templates`~~ | **已删除**（模板改由 `templates/*.json` 承载） |

> ~~全局排期 `/schedule`~~、~~请假管理 `/leave`~~：**已删除**，不要再加回来。

## 两处需要留意的实现约定

1. **PDF 下载走 fetch 而不是 `<a download>`**：PDF 接口需要 `Authorization` 头，
   而 `<a>` / `window.open` 带不上自定义头，直接打开会拿到 401。
   因此用 fetch 取 blob 再触发下载。
2. **记录页不要自己拼 SOAP 文本**：列表与详情直接用服务端返回的 `rendered_text` /
   `rendered_excerpt`。服务端存的是**生成那一刻冻结**的文本 ——
   病历是法律文书，措辞不该因前端模板版本不同而变。
