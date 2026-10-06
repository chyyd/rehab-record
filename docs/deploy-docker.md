# Docker 部署

把**后端 + 管理后台**打包成两个镜像，换一台机器只带走镜像与一个 `.env` 就能跑。

- `kf-record/backend` — FastAPI + SQLite（数据在卷里）
- `kf-record/admin` — Nginx 托管前端静态产物 + 同源反代 `/api` → 后端

> 安卓 App **不**在镜像里：它是客户端，装在治疗师手机上，通过 HTTP 访问这套服务。

---

## 一、在 Windows 上安装 Docker（本机是 Win11 专业工作站版，Build 26200）

Win11 + 虚拟化已启用，走 **WSL2 + Docker Desktop** 这条最省事的路。

> ⚠ **以下命令都需要「管理员」权限**。当前会话不是管理员（实测确认），
> 所以请自己开一个：**右键开始菜单 →「终端(管理员)」** 或「Windows PowerShell (管理员)」。

### 1. 安装 WSL2（这一步会要求重启）

```powershell
wsl --install
```

它会装好「适用于 Linux 的 Windows 子系统」与「虚拟机平台」两个功能，并装一个 Ubuntu。
**装完必须重启一次**，否则 Docker Desktop 起不来。

重启后确认（不需要管理员）：

```powershell
wsl --status          # 应显示"默认版本: 2"
wsl -l -v             # 应能看到一个发行版，STATE 为 Running 或 Stopped
```

> 如果 `wsl --install` 报"虚拟化未启用"：BIOS 里开 Intel VT-x / AMD-V。
> 本机实测 `VirtualizationFirmwareEnabled = True`，一般不会遇到。

### 2. 安装 Docker Desktop

```powershell
winget install --id Docker.DockerDesktop -e
```

装完**手动启动一次 Docker Desktop**（开始菜单里找），等托盘图标变成"引擎已运行"。
它会要你接受服务条款；个人/小团队用选免费档即可。

验证（新开一个普通 PowerShell）：

```powershell
docker version          # 应同时有 Client 与 Server 两段
docker compose version  # 应显示 v2.x
```

> **磁盘提示**：Docker 默认把镜像存在 `C:`（实测只剩 47.6 GB，`D:` 有 658 GB）。
> 想换到 D 盘：Docker Desktop → Settings → Resources → "Disk image location" → 改成
> `D:\DockerData`。**在第一次拉大镜像之前改**，之后改要重建虚拟盘。

### 3. 登录镜像仓库（轩辕镜像）

```powershell
docker login docker.xuanyuan.run
# Username: 15094690223
# Password: （你的镜像密码）
```

登录成功后凭据存在 Windows 凭据管理器里，`docker push` / `docker pull` 会直接用。

> ⚠ 这个密码已经在对话里出现过，建议改用**访问令牌**（如果轩辕支持）或在推完后改一次密码。

---

## 二、构建并推送到镜像仓库

在仓库根目录（`D:\code\rehab-record`）：

```powershell
# 1) 前端产物要先构建好 —— Dockerfile.admin 直接 COPY admin/dist
cd admin
npm run build
cd ..

# 2) 准备 .env（compose 会读它来拼镜像名与数据目录）
copy .env.example .env
#    默认值就能跑：密钥会**自动生成**到数据目录的 secrets\ 下，不用手填。
#    要确认/改的只有 KB_DATA_DIR（默认 D:/kf-record-data）与 ADMIN_PORT（默认 8080）。
#    IMAGE_PREFIX 默认已是 docker.xuanyuan.run/kf-record

# 3) 构建
docker compose build

# 4) 推上去
docker compose push
```

> **基础镜像走的是轩辕镜像**（`docker.xuanyuan.run/library/...`）。
> 国内直连 Docker Hub 的 `auth.docker.io` 实测反复超时，所以 Dockerfile 里
> 把基础镜像做成了 build arg，默认带镜像前缀。要用官方地址就在 `.env` 里设
> `BASE_IMAGE=python:3.13-slim` 与 `NGINX_IMAGE=nginx:1.27-alpine`。

`docker compose push` 会按 `.env` 里的 `IMAGE_PREFIX`/`IMAGE_TAG` 推到：
```
docker.xuanyuan.run/kf-record/backend:latest
docker.xuanyuan.run/kf-record/admin:latest
```

> 想带版本号：把 `.env` 里的 `IMAGE_TAG` 改成 `2026-10-06`（或 `v1`）再 build/push。
> **别只用 `latest`** —— 回滚时无从下手。

---

## 三、在目标机器上部署

目标机器只需要 **`compose.yml` + `.env`**（不需要源码、不需要 Node/Python）。

```powershell
docker login docker.xuanyuan.run
docker compose up -d
```

打开 `http://<目标机IP>:8080`。

> `compose.yml` 里 `image:` 与 `build:` 同时存在：**有镜像就不重建**，
> 所以目标机器上直接 `up -d` 会拉镜像；要在本机强制重建才用 `--build`。

### 端口

| 端口 | 谁 |
|---|---|
| `${ADMIN_PORT}`（默认 **8080**）→ 容器 80 | 管理后台。内网客户端访问的就是它 |
| 8000 | 后端，**不映射到宿主机**，只在 compose 网络里，由 Nginx 反代 `/api` |

要直接调后端接口：走 `http://<IP>:8080/docs`（Nginx 已反代）。

### 首次启动会发生什么

`backend/docker-entrypoint.sh` 依次做：
1. 准备数据目录、把**密钥落成文件**（见下）；
2. 建库 + 应用迁移（幂等）；
3. 该管理员**不存在**时创建它，并把密码打印出来；
4. 提醒是否还在用开发用的 JWT 默认密钥；
5. 启动 uvicorn。

### 数据落在哪（用户要求：D 盘一个目录，便于备份）

**绑挂**到宿主机目录（不是 Docker 具名卷）—— 这样你随时能在资源管理器里看到、拷贝：

```
D:\kf-record-data\                 ← .env 里的 KB_DATA_DIR
├── db\
│   ├── kf.db                      SQLite 数据库
│   ├── kf.db-wal / kf.db-shm      WAL 文件（运行时产生，备份时一起拷）
└── secrets\
    ├── admin_password.txt         管理员密码（**可以直接打开看**）
    └── jwt_secret.txt             JWT 签名密钥（64 字符）
```

- **备份 = 把这个目录整个拷走。** 恢复 = 拷回来再 `docker compose up -d`。
- 密码不需要你设：首次启动自动生成 12 位随机密码，写进
  `secrets\admin_password.txt`，同时**打印在后端日志里**：

  ```powershell
  docker compose logs backend | Select-String '管理员'
  ```

- **管理员已存在时不会重置密码** —— 避免"容器一重启密码就变回去"。
  要主动重置：改 `secrets\admin_password.txt`（或 `.env` 里的 `KB_ADMIN_PASSWORD`）
  再 `docker compose up -d`。

### 想带上现有数据（可选）

容器用的是 `D:\kf-record-data\db\kf.db`，不是仓库里的 `data\kf.db`。
想把这边的数据带进容器 —— 直接**拷文件**就行（绑挂的好处）：

```powershell
docker compose stop backend
copy .\data\kf.db D:\kf-record-data\db\kf.db
docker compose start backend
```

> ⚠ 会**覆盖**容器里已有的数据。先按上面那段备份一次更稳。

### 备份

```powershell
# 最直接：整个目录拷走（容器不用停，SQLite 是 WAL 模式，一致性够用；
# 要绝对一致就先 docker compose stop backend）
Copy-Item D:\kf-record-data "E:\backup\kf-record-data-$(Get-Date -Format yyyyMMdd)" -Recurse

# 或者看容器内视角
docker compose exec backend ls -l /data /data/secrets
```

---

## 四、常见问题

### 打开页面一片空白 / 全站 404

多半是 `deploy/nginx.conf` 里 `proxy_pass http://backend:8000;` **末尾多了斜杠**。
带斜杠时 nginx 会把 location 前缀剥掉，`/api/v1/x` 变成 `/v1/x`。
配置里已注释说明，改完 `docker compose up -d --force-recreate admin`。

### 登录成功但一刷新就掉线

refresh token 走 httpOnly Cookie，`SameSite=lax` 只在**同源**下发送。
本 compose 是 Nginx 同源反代，默认就对。
若你自己改成前后端分域名，必须同时设 `KB_REFRESH_COOKIE_SAMESITE=none` 与
`KB_REFRESH_COOKIE_SECURE=true`，并且上 HTTPS。

### 重启容器后所有人被踢下线

正常不会：密钥自动生成在 `secrets\jwt_secret.txt`，重启会复用（已实测）。
真发生了就查两件事：

1. **`secrets\jwt_secret.txt` 被删了或变成空文件** ——
   那样 entrypoint 会重新生成一个新密钥，旧 token 全部失效；
2. **`.env` 里填了 `KB_JWT_SECRET`** —— 填了就会**覆盖**文件里的值
   （刻意如此，让配置能跟着 `.env` 走）。想回到"自动生成"就清空它再 up。

无论哪种，重新登录一次即可，**数据不受影响**。

### 启动时改过的密码没生效

entrypoint **只在管理员不存在时创建**，不会重置已存在的密码
（这是为了不让"每次重启都把密码改回去"）。要主动重置：
改 `secrets\admin_password.txt` 或 `.env` 里的 `KB_ADMIN_PASSWORD`，再
`docker compose up -d`。

### 页面能开但接口 502

后端还没起来或已崩：
```powershell
docker compose logs backend --tail 100
docker compose ps
```
最常见的原因是迁移失败（卷权限、磁盘满）。

### 前端改了没生效

`Dockerfile.admin` 是 `COPY admin/dist/` —— 改了源码**必须先在宿主机
`cd admin && npm run build`**，再 `docker compose build admin`。
（刻意如此：容器里不重装 npm 依赖，见该 Dockerfile 的说明。）

### 构建很慢 / 上下文几百 MB

`.dockerignore` 已排除 `**/node_modules`。若你自己加了新的大目录，记得同步加进去。
⚠ 注意里面那条 `/app` **必须带前导斜杠** —— 写成 `app` 会把 `backend/app/`（后端源码）
一起排除，报错要等到启动时才出现。

---

## 五、这套镜像里有什么 / 没有什么

**有**：Python 3.13 + 后端运行期依赖（fastapi/uvicorn/pydantic/reportlab/PyJWT/
argon2-cffi/APScheduler）、迁移 SQL、`templates/*.json`、Nginx + 前端静态产物。

**没有**（刻意的）：
- **数据库**：在你绑挂的宿主机目录里（默认 `D:\kf-record-data`），不在镜像里（否则每次重建都会覆盖真实病历）；
- **镜像里不含测试**：`pytest` 等 dev 依赖没装；
- **安卓 App**：客户端，不打包。
