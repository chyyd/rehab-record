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

**推荐用 `tool/build_env.ps1` 包装** —— 它一次设好镜像、SDK/JDK 与代理：

```powershell
cd app
pwsh -NoLogo -ExecutionPolicy Bypass -Command "& './tool/build_env.ps1'"                                  # 默认：build apk --debug
pwsh -NoLogo -ExecutionPolicy Bypass -Command "& './tool/build_env.ps1' -FlutterCommand 'flutter analyze'"
pwsh -NoLogo -ExecutionPolicy Bypass -Command "& './tool/build_env.ps1' -FlutterCommand 'flutter test'"
pwsh -NoLogo -ExecutionPolicy Bypass -Command "& './tool/build_env.ps1' -NoProxy -FlutterCommand 'flutter pub get'"
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

---

## 当前状态

工程骨架已建（`flutter create` + 依赖 + 镜像配置），
`flutter analyze` 无问题、`flutter build apk --debug` 成功产出 APK。

**尚未实现任何业务功能** —— `lib/` 里目前只有 `flutter create` 的默认示例。
下一步按协议 §8 的顺序做端到端竖切：
Drift 表 → 登录 + 令牌存储 + CA 注入 → 患者列表 → 同步引擎。
