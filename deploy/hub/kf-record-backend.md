# 康复科治疗过程记录系统 — 后端 API

康复科（物理治疗 / 作业治疗 / 言语 / 吞咽）**治疗过程记录**的电子化系统后端。
面向**科室局域网**部署：一次记录一位患者的一次治疗，支持**离线录入**与
**打印/导出 PDF**，并提供患者、治疗记录、汇总与审计的 REST API。

> 这是**服务端**镜像。管理后台（浏览器界面）请配合
> [`chyyd/kf-record-admin`](https://hub.docker.com/r/chyyd/kf-record-admin) 使用 ——
> 它是个 Nginx，托管前端静态文件并把 `/api` 反代到本镜像。

FastAPI + SQLite，内嵌 14 个数据库迁移，启动时自动建库/升级。

---

## 快速开始

**推荐直接用 compose**，它会把后端与管理后台一起拉起来（见
[`chyyd/kf-record-admin`](https://hub.docker.com/r/chyyd/kf-record-admin) 的说明）。
单独跑本镜像：

```bash
docker run -d --name kf-backend \
  -v /your/data/dir:/data \
  -e KB_JWT_SECRET="$(openssl rand -base64 48)" \
  -e KB_ADMIN_PASSWORD='你自己的密码（至少 8 位）' \
  chyyd/kf-record-backend:2026-10-06
```

或 docker compose：

```yaml
services:
  backend:
    image: chyyd/kf-record-backend:2026-10-06
    restart: unless-stopped
    environment:
      KB_DATA_DIR: /data
      KB_DB_PATH: /data/db/kf.db
      KB_TEMPLATES_DIR: /app/templates
      TZ: Asia/Shanghai
      KB_JWT_SECRET: ""            # 留空 = 首次启动自动生成并写入 secrets/
      KB_ADMIN_PASSWORD: ""        # 留空 = 同上
    volumes:
      - /your/data/dir:/data
```

启动后：`http://<主机>:8000/docs`（Swagger）。

---

## 数据与密钥放在哪

挂载 `/data` 一个卷即可，目录结构：

```
/data/
├── db/kf.db                 SQLite 数据库（含 -wal / -shm）
└── secrets/
    ├── jwt_secret.txt       JWT 签名密钥
    └── admin_password.txt   管理员密码（明文，便于查看与备份）
```

- **备份 = 把这个目录整个拷走**；恢复 = 拷回来再启动。
- 两个密钥**留空环境变量即可**，首次启动会自动生成随机值并写进 `secrets/`。
  想主动重置就把新值写进对应文件（或设环境变量，会覆盖文件）。
- ⚠ `jwt_secret.txt` 丢掉 = 所有已登录用户需要重新登录（数据不受影响）。

---

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `KB_DATA_DIR` | `/data` | 数据根目录（容器内） |
| `KB_DB_PATH` | `$KB_DATA_DIR/db/kf.db` | SQLite 文件路径 |
| `KB_TEMPLATES_DIR` | `/app/templates` | SOAP 记录模板（JSON）目录 |
| `KB_JWT_SECRET` | 自动生成 | 留空则生成并写入 `secrets/jwt_secret.txt` |
| `KB_ADMIN_PASSWORD` | 自动生成 | 留空则生成并写入 `secrets/admin_password.txt`（≥8 位） |
| `KB_ADMIN_EMPLOYEE_NO` | `A001` | 初始管理员工号 |
| `KB_ADMIN_NAME` | `科室管理员` | 初始管理员姓名 |
| `KB_SQLITE_WAL` | `true` | 启用 WAL（并发读写更好） |
| `KB_SQLITE_BUSY_TIMEOUT_MS` | `5000` | SQLite 忙等待 |
| `KB_REFRESH_COOKIE_SAMESITE` | `lax` | 同源部署保持 `lax` |
| `KB_REFRESH_COOKIE_SECURE` | `false` | 上 HTTPS 且**分域名**时才设 `true` |
| `TZ` | — | 建议 `Asia/Shanghai`（"今天"、跨零点判定依赖它） |

### 管理员账号

- 首次启动：`KB_ADMIN_PASSWORD` 或自动生成的密码 → **创建**管理员；
- 之后启动：**不会重置密码**（避免"容器一重启密码就变回去"）。
  要重置就改 `secrets/admin_password.txt` 或环境变量再启动。

看当前密码：`docker logs kf-backend | grep 管理员`

---

## 主要能力

- **SOAP 模板驱动**的治疗记录：四大类 × 四种形态（首评 / 日常 / 阶段性复评 / 出院小结），
  字段来自 `templates/*.json`，改模板不需要数据库迁移。
- **评估文书硬门禁**：该做首评/复评时不写就先弹它，且**离线推送时同样生效**。
- **离线同步协议**：客户端本地库 + 增量拉取 + 幂等推送 + 冲突分层裁决。
- **PDF 打印/导出**：单患者每日汇总、按日期汇总（内嵌中文字体，服务器无需装字体）。
- **审计与变更留痕**：患者/记录的关键动作都写入 `audit_log` / `change_log`。

---

## 健康检查

镜像内置 `HEALTHCHECK`，探的是业务健康接口而非端口：

```bash
docker inspect --format '{{.State.Health.Status}}' kf-backend   # healthy
curl -fsS http://127.0.0.1:8000/api/v1/health
```

---

## 标签

| 标签 | 说明 |
|---|---|
| `2026-10-06` | 指定日期版本（**生产建议用这个**） |
| `latest` | 跟随最新推送 |

同一个日期标签与 `latest` 指向**同一份内容**（digest 相同）。
要精确锁定某次构建，可以直接用 digest：
`chyyd/kf-record-backend@sha256:bbbb30e6c874c4e0898772a74923443e9e8e97932ce5592d44c71252a1f872c3`

---

## 说明

- 镜像基于 `python:3.13-slim`，以**非 root**（uid 10001）运行。
- **不含数据库**：数据在你挂载的卷里，所以重建容器不会丢病历。
- **不含安卓 App**：那是装在治疗师手机上的客户端，通过 HTTP 访问本服务。
- 镜像里没有测试依赖（pytest 等），只装运行期依赖。
- 部署细节（Windows 装 Docker、防火墙、Nginx 同源反代、排障）见源码仓库
  `docs/deploy-docker.md`。
