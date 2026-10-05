# 康复科治疗过程记录系统 —— 安卓端（`app/`）

治疗师**床旁快速记录**工具。离线优先、选择为主、少打字。

> **本目录是仓库里唯一未完成的大块**（进度见 [../README.md](../README.md)）。
> 后端（阶段 0–5）与管理后台已完成。

---

## 它做什么

- 登录 → 患者列表（**全科白板**）→ 患者详情 → 治疗记录 → 时间轴 / 汇总 / 分享 PDF
- **半日格子排期页**（上午/下午两行 × 日期列，自绘 `Grid`）
- **离线可用**：断网也能录入，联网后自动推送

## 它不做什么（一期明确不做，见 [`../开发计划.md`](../开发计划.md) 2.4）

- 收费 / 医保、患者签字、绩效统计、治疗组管理
- **任何时间合规判定** —— 本系统只记录"做了哪些治疗、每次干了什么"；
  具体时间与合规由**另一个患者签字系统**负责
- 附件 / 治疗部位拍照；请假审批流；消息推送；iOS（代码兼容但不验收不打包）

---

## 开工前必读

1. **[`../docs/sync-protocol.md`](../docs/sync-protocol.md)** —— 离线同步协议。
   游标语义、幂等 `client_uuid`、冲突分层、Drift 本地库设计、首次同步流程全在里面。
   其中两条最容易踩的约定：
   - **患者不走同步接口**：`patient` 变更**从不进 `change_log`**，必须用
     `GET /api/v1/patients` 分页拉取；
   - **重试不能带 `base_revision`**，否则会被判成冲突、幂等失效。
2. **[`../设计.md`](../设计.md)** 3.4（半日制排期）、3.7（治疗记录）、5.4（离线同步）。
3. **[`../docs/setup.md`](../docs/setup.md)** —— 环境搭建（用哪个 Python / Node）。

## 权限语义（2026-10-03 起为"全科白板"）

- 治疗师能看到**科室在院 + 暂停**的全部患者，并可读写其治疗记录；
- **已出院默认隐藏**（管理员 `scope=all` 可见全表）；
- 归属（`assigned_therapist_id`）只决定**排序**（"我的患者优先"）与文书署名，
  **不是**可见性闸门；
- 患者主数据（诊断、注意事项、出院/恢复）**仅管理员可改**。

---

## 技术栈

| 用途 | 选型 | 说明 |
|---|---|---|
| 本地库 | **Drift** | 拍定非 sqflite：类型安全 + 迁移 + 响应式查询，离线优先收益明显 |
| 状态管理 | **Riverpod** | `flutter_riverpod 3.x` |
| 网络 | **Dio** | 自签 CA 走 **Dart 层 `SecurityContext`** 注入 |
| 令牌存储 | **flutter_secure_storage** | refresh token 进 Android Keystore；access token 只放内存 |
| 日期选择 | **table_calendar** | **只负责日期维度**；上午/下午半日格子自绘 `Grid` |
| PDF | `printing` + `pdfx` | 一期建议只做"调后端 PDF 接口 → 分享"（待定，见协议 §11） |
| 代码生成 | `build_runner` + `drift_dev` | Drift 表与 DAO |

---

## 目录结构（规划，按 [`../开发计划.md`](../开发计划.md) 3 节与协议 §7）

```
lib/
├─ core/         主题、路由、常量、错误模型、网络配置（baseUrl / CA）
├─ data/
│  ├─ local/     Drift：patient / appointment / treatment_record 镜像表
│  │             + change_queue（client_uuid, entity, op, base_revision, sync_status）
│  │             + sync_state（last_cursor）+ ref_cache（字典/选项集/模板 JSON 缓存）
│  ├─ remote/    Dio 客户端、DTO
│  └─ repo/      仓库层（本地优先）
├─ sync/         同步引擎：推送（幂等、≤200/批）、拉取（游标、≤500/次）、冲突处理
├─ features/     auth / home / schedule / patient / record / timeline / summary / print
└─ widgets/      通用选择器（选项集、参数表单、患者反应）
```

---

## 常用命令

**推荐用 `tool/` 下的两个脚本** —— 它们把本机的镜像/代理/地址坑都处理好了：

```powershell
cd app

# 构建与静态检查（自动设镜像 + SDK/JDK + 代理）
pwsh -NoLogo -ExecutionPolicy Bypass -Command "& './tool/build_env.ps1'"                                  # 默认 build apk --debug
pwsh -NoLogo -ExecutionPolicy Bypass -Command "& './tool/build_env.ps1' -FlutterCommand 'flutter analyze'"
pwsh -NoLogo -ExecutionPolicy Bypass -Command "& './tool/build_env.ps1' -FlutterCommand 'flutter test'"
pwsh -NoLogo -ExecutionPolicy Bypass -Command "& './tool/build_env.ps1' -NoProxy -FlutterCommand 'flutter pub get'"

# 在模拟器上跑并连本机后端（自动 adb reverse + 按需起模拟器）
pwsh -NoLogo -ExecutionPolicy Bypass -Command "& './tool/run_on_emulator.ps1'"
```

> 不要用 `pwsh -File tool\build_env.ps1 -FlutterCommand ...`：`-File` 的命名参数绑定
> 不可靠（实测代理被误设成 `analyze`）。用上面的 `-Command "& '...' -参数 值"`。

各命令本身：

```powershell
flutter pub get                 # 安装依赖（走 pub.flutter-io.cn 镜像）
flutter analyze                 # 静态检查
flutter test                    # 单元测试
dart run build_runner build     # Drift 代码生成（改表后必须跑）
flutter build apk --debug       # 构建调试包
flutter run                     # 跑到已连接设备/模拟器（已有 AVD rehab_pixel8）
```

---

## ⚠️ 本机环境注意事项（都踩过，别重复）

1. **`flutter` 必须在非受限环境运行**。
   DSH 沙箱（`workspace-write`）下它**完全静默地卡死**——没有 stdout、没有 stderr、
   进程也不退出，因为无法写用户目录（analytics / 日志 / 缓存）。
   同一台机器、同一条命令，非受限模式下 15 秒就跑完。
   **不要误判成"网络慢"而盲目延长等待。**

2. **Gradle wrapper 的 `distributionUrl` 必须指向国内镜像**。
   `flutter create` 生成的工程默认指向 `services.gradle.org`（国内不可达），
   wrapper 会按 URL 的 hash 建目录，导致**已有的 234 MB 缓存永远命中不到**，
   每次新建空目录 + 0 字节 `.part`，最后报
   `Timeout of 120000 reached waiting for exclusive access`。
   已在本工程改为 `mirrors.cloud.tencent.com/gradle/`。
   **每个新 Flutter 工程都要改这一行。**

3. **Gradle 仓库镜像在全局 `~/.gradle/init.gradle`**。
   Flutter 把插件仓库声明在 `settings.gradle.kts` 的 `pluginManagement` 里，
   只对 `allprojects` 生效的脚本管不到它，所以镜像必须用 `beforeSettings` 注入，
   且要尊重 `RepositoriesMode.PREFER_SETTINGS`（否则构建直接失败）。

4. **镜像环境变量**（已固化在用户级，换机器需重设）：
   ```
   PUB_HOSTED_URL             = https://pub.flutter-io.cn
   FLUTTER_STORAGE_BASE_URL   = https://storage.flutter-io.cn
   ANDROID_HOME               = D:\Android\sdk
   JAVA_HOME                  = D:\Program Files\Android\Android Studio\jbr
   ```

5. **构建 Android 包必须有可用代理**（`sqlite3` 的 native assets）。
   `sqlite3` 通过 native assets 机制从 **GitHub Releases** 下载预编译库
   （`libsqlite3.*.android.so`），该地址在国内不可达，拿不到就直接构建失败：
   ```
   Target build_hooks failed: Error: Building native assets failed
   ... attempted to download https://github.com/simolus3/sqlite3.dart/releases/...
   ```
   这不是代码问题。`tool/build_env.ps1` 会自动探测本地代理端口（10808 / 10809 /
   7890 / 7897 / 1080）并设置 `HTTP_PROXY`/`HTTPS_PROXY`；也可 `-Proxy` 显式指定。
   构建成功后该库会进缓存，之后无需代理也能重建。
   > 只影响构建期；App 运行期不需要代理（后端在内网）。

6. **本机分析器拒绝"向上/跨子树"的相对导入**。
   `lib/data/remote/x.dart` 里写 `import '../core/y.dart';` 会报
   `Target of URI doesn't exist`（同目录的相对导入正常）。
   因此本项目**统一用 `package:rehab_app/...` 绝对导入** —— 这本就是 Dart 官方
   风格指南推荐的做法，同时也更抗重构。

7. **`library;` 指令必须在使用之前**。
   带文档注释的 `library;` 要放在文件最前面（在 `import` 之前），
   否则 `build_runner` 会报 `Could not resolve Dart library ... The library
   directive must appear before all other directives`，生成的 `.g.dart` 会是坏的。

8. **★ 模拟器连本机后端：用 `adb reverse`，不要指望 `10.0.2.2`。**
   安卓模拟器通常用 `10.0.2.2` 访问宿主机，但**本机这条路走不通**：
   实测模拟器能 ping 通 `8.8.8.8`，却连不上 `10.0.2.2:<port>`；
   在宿主机开临时监听确认过，**只收到 `127.0.0.1` 的连接、没有来自模拟器的** ——
   原因是 Windows 防火墙入站默认阻止，而 uvicorn 没有放行规则。

   可用做法是把模拟器的本地端口反向转发到宿主机：
   ```powershell
   adb reverse tcp:8000 tcp:8000
   flutter run --dart-define=KB_BASE_URL=http://127.0.0.1:8000
   ```
   流量走 adb 通道、**不过防火墙**。`tool/run_on_emulator.ps1` 已封装这两步。

   > `adb reverse` 在**模拟器重启后会失效**，需要重跑。
   > `AppConfig` 的默认值在安卓上仍是 `10.0.2.2`（真机/正常网络下是对的），
   > 本机模拟器联调时用上面的 `--dart-define` 覆盖。

9. **模拟器里没有 `curl`**（`toybox` 也没有 `wget`），只有 `nc`。
   要在模拟器内验证网络，用 `adb shell "printf 'GET / HTTP/1.1\r\n...' | toybox nc ..."`，
   或者直接看宿主机侧 `netstat`/后端日志 —— `nc` 的 stdout 经 adb 捕获并不可靠。

10. **`adb shell input` 对 Flutter 输入框有两处不可靠**（联调时踩到）：
    - 特殊字符：`#` 会被 `adb shell` 当注释吞掉，且没有可靠的转义方式。
      要自动化登录，**另建一个无特殊字符密码的账号**更省事；
    - `input keyevent 67`（退格）对 Flutter 文本框**不生效**，清空内容请
      `pm clear <包名>` 或重启应用拿干净状态。

---

## 当前状态

已完成**端到端竖切**（登录 → 患者列表 → 同步），已在 `rehab_pixel8` 模拟器上
对真实后端跑通：登录成功、14 名患者自动落库并渲染、注意事项醒目、详情页可进。

| 已实现 | 说明 |
|---|---|
| Drift 本地库 | 7 张表；`change_queue` 是离线队列，`sync_state` 存游标 |
| 认证 | 工号+密码登录、refresh token 进安全存储、冷启动自动恢复会话、401 静默刷新 |
| 患者列表 | 全科白板 + 我的/未分配筛选 + 本地搜索；**响应式**（落库即刷新） |
| 患者详情 | 注意事项醒目、诊断/状态/归属 |
| 同步引擎 | 幂等推送（≤200/批）、游标增量拉取、按快照 upsert |
| 「我的」页 | 后端地址、证书状态、待同步条数、上次同步时间、退出登录 |

`flutter analyze` 无问题；**34 个测试通过**。

**下一步**（按协议 §8 与 `开发计划.md` 阶段 3–4）：
排期页（半日格子）→ 记录页（动态表单 + 患者反应 + 模板套用）→ 时间轴/汇总 →
离线冲突处理 UI。
