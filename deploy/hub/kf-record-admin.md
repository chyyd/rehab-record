# 康复科治疗过程记录系统 — 管理后台（Web）

康复科治疗过程记录的**浏览器管理后台**：患者管理、治疗记录查阅、汇总与打印、
用户与权限、审计日志。

> 这是**前端**镜像（Nginx），它同时把 `/api` **反代到后端容器** ——
> 所以浏览器视角是**同源**的，才能正常带上 httpOnly 的 refresh Cookie。
> 请配合 [`chyyd/kf-record-backend`](https://hub.docker.com/r/chyyd/kf-record-backend) 使用。

---

## 快速开始（两个容器一起）

本镜像默认把后端地址写成 compose 服务名 `backend:8000`，所以**必须**和它同网络：

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
      KB_JWT_SECRET: ""
      KB_ADMIN_PASSWORD: ""
    volumes:
      - /your/data/dir:/data

  admin:
    image: chyyd/kf-record-admin:2026-10-06
    restart: unless-stopped
    depends_on:
      backend:
        condition: service_healthy      # 等后端迁移完再起前端
    ports:
      - "8080:80"
```

```bash
docker compose up -d
```

打开 **`http://<主机>:8080`**，用工号 `A001` 与后端在 `secrets/admin_password.txt`
里那份密码登录（也在后端日志里打印过：`docker logs <后端容器> | grep 管理员`）。

---

## 只跑本镜像（后端在别处）

镜像内置的 Nginx 把 `/api` 反代到 `backend:8000`。后端不在这个地址时，
挂一份自己的 nginx 配置覆盖进去：

```bash
docker run -d -p 8080:80 \
  -v ./my-nginx.conf:/etc/nginx/conf.d/default.conf:ro \
  chyyd/kf-record-admin:2026-10-06
```

把 `proxy_pass http://backend:8000;` 换成你的后端地址。

> ⚠ **末尾不要加斜杠**：写成 `http://backend:8000/` 会让 nginx 把 location 前缀剥掉，
> `/api/v1/x` 变成 `/v1/x`，表现为**全站 404**，而报错信息完全不指向原因。

---

## 为什么走同源反代

管理后台的 refresh token 放在 **httpOnly Cookie**（`Path=/api/v1/auth`、`SameSite=lax`）。
同源时浏览器会正常带上；一旦前后端分属不同源，`lax` 就不再发送跨站 Cookie，
表现为**"登录成功但一刷新就掉线"**，而且很难看出原因。

所以本镜像刻意把前端与 `/api` 放在**同一个源**下。

若你确实要分域名部署，必须同时：
1. 后端设 `KB_REFRESH_COOKIE_SAMESITE=none` 与 `KB_REFRESH_COOKIE_SECURE=true`；
2. **上 HTTPS**（`Secure` 的 Cookie 只在 HTTPS 下发送）。

---

## 主要界面

| 页面 | 内容 |
|---|---|
| 总览 | 当日治疗次数、涉及患者、按大类分布 |
| 患者管理 | 建档、编辑（含注意事项/状态）、归属分配、出院流程；右下角悬浮「+」新建 |
| 治疗记录 | 按患者/治疗师/日期/状态筛选，查看 SOAP 正文 |
| 汇总与打印 | 按日期汇总、按患者汇总，导出 PDF |
| 用户管理 | 人员增删改、重置密码、在线会话（管理员） |
| 审计日志 | 谁在什么时候对什么对象做了什么，含变更前后内容（管理员） |

治疗师登录后只看得到科室在院/暂停的患者（全科白板）；管理员可看全表含已出院。

---

## 健康检查

```bash
docker inspect --format '{{.State.Health.Status}}' kf-admin    # healthy
curl -fsS http://127.0.0.1:8080/healthz                        # ok
```

---

## 标签

| 标签 | 说明 |
|---|---|
| `2026-10-06` | 指定日期版本（**生产建议用这个**） |
| `latest` | 跟随最新推送 |

同一个日期标签与 `latest` 指向**同一份内容**（digest 相同）。
精确锁定时可直接用 digest：
`chyyd/kf-record-admin@sha256:067151d59903be9a26a920c978a839249a8a9351b5d08d7bd9d2a1bcdb54d478`

---

## 说明

- 基于 `nginx:1.27-alpine`，内含已构建好的前端静态文件（无需 Node 运行时）。
- **改前端需要重新构建镜像**：前端产物是在构建阶段 COPY 进镜像的
  （刻意不在容器里 `npm install` —— 那会让构建依赖外网 npm 源且慢得多）。
- SPA 路由（如 `/patients` 直接刷新）由 nginx `try_files` 兜底到 `index.html`。
- 已开启 gzip 与静态资源长缓存；`index.html` 明确 `no-store`，避免发版后
  浏览器拿着旧 index 去引用已删除的 chunk。
- 部署细节（Windows 装 Docker、防火墙、排障）见源码仓库 `docs/deploy-docker.md`。
