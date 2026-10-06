# 康复科治疗过程记录系统 —— 安卓端（`app/`）

治疗师**床旁快速记录**工具。离线优先、选择为主、少打字。

> 后端（阶段 0–5）与管理后台已完成，安卓端功能已全部实现（进度见 [../README.md](../README.md)）。
>
> ✅ **2026-10-05（SOAP 改造）：本端已适配完成。**
> 治疗记录从「参数表格」改成 **SOAP 模板驱动**（后端迁移 011/012/013）后，本端同步换了契约：
> 记录页按 `GET /records/form` 返回的 `soap[]` 渲染**一屏 chip**（点一下就是选中）、
> 提交体换成 `body`，Drift 本地库 **schemaVersion 4 → 5**（**删除** `RecordItems` 表与
> `session_period` / `duration_min` / `patient_response_json` 三列 —— 均随旧模型一并删除），
> 时间轴/汇总改用 `rendered_text`（SOAP 纯文本，不再拼表格）。详见下文「记录页：SOAP 模板驱动」。

---

## 它做什么

- 登录 → 患者列表（**全科白板**）→ 患者详情 → 治疗记录 → 时间轴 / 汇总 / 分享 PDF
- **3 个页签**：**患者** / **时间轴** / **我的**（2026-10-05 起，排期页已删除，页签由 4 个减为 3 个）
- **离线可用**：断网也能录入，联网后自动推送；冲突可逐条裁决
- **PDF 导出三种去向**：**发送给微信 / 其他应用**、**系统打印（含无线打印机）**、**先打开看看**

## 它不做什么（一期明确不做，见 [`../开发计划.md`](../开发计划.md) 2.4）

- **排班/排期**：科室确认排班不是本系统的职责（排期、休息块、请假功能已整体下线；
  临时指派与 `scope=temp` 筛选随后也一并删除，见文末两段）
- 收费 / 医保、患者签字、绩效统计、治疗组管理
- **任何时间合规判定** —— 本系统只记录"做了哪些治疗、每次干了什么"；
  具体时间与合规由**另一个患者签字系统**负责
- 附件 / 治疗部位拍照；请假登记与审批；消息推送；iOS（代码兼容但不验收不打包）

---

## 开工前必读

1. **[`../docs/sync-protocol.md`](../docs/sync-protocol.md)** —— 离线同步协议。
   游标语义、幂等 `client_uuid`、冲突分层、Drift 本地库设计、首次同步流程全在里面。
   其中两条最容易踩的约定：
   - **患者不走同步接口**：`patient` 变更**从不进 `change_log`**，必须用
     `GET /api/v1/patients` 分页拉取；
   - **重试不能带 `base_revision`**，否则会被判成冲突、幂等失效。
2. **[`../设计.md`](../设计.md)** 3.4（半日与作息 + 患者列表排序）、3.7（治疗记录）、5.4（离线同步）。
3. **[`../docs/setup.md`](../docs/setup.md)** —— 环境搭建（用哪个 Python / Node）。

## 权限语义（2026-10-03 起为"全科白板"）

- 治疗师能看到**科室在院 + 暂停**的全部患者，并可读写其治疗记录；
- **已出院默认隐藏**（管理员 `scope=all` 可见全表）；
- 归属（`assigned_therapist_id`）只决定**排序**（"我的患者优先"，组内按**我最近一次已提交治疗**降序）
  与文书署名，**不是**可见性闸门；
- 患者主数据（诊断、注意事项、出院/恢复）**仅管理员可改**。

---

## 技术栈

| 用途 | 选型 | 说明 |
|---|---|---|
| 本地库 | **Drift** | 拍定非 sqflite：类型安全 + 迁移 + 响应式查询，离线优先收益明显；**schemaVersion 6** |
| 状态管理 | **Riverpod** | `flutter_riverpod 3.x` |
| 网络 | **Dio** | 自签 CA 走 **Dart 层 `SecurityContext`** 注入 |
| 令牌存储 | **flutter_secure_storage** | refresh token 进 Android Keystore；access token 只放内存 |
| 日期选择 | Flutter 自带 `showDatePicker` | 用于**记录日期与时间轴/汇总的日期筛选**（`table_calendar` 与半日格子视图已随排期功能删除） |
| PDF | `printing` + `share_plus` + `open_filex` | 调后端 PDF 接口 → **发送给微信 / 系统打印 / 打开**（见协议 §11） |
| 代码生成 | `build_runner` + `drift_dev` | Drift 表与 DAO |

---

## 目录结构（当前实际结构，对齐协议 §7）

```
lib/
├─ core/         主题、路由、常量（四大类）、错误模型、网络配置（baseUrl / CA）
├─ data/
│  ├─ local/     Drift：patient / treatment_record 镜像表
│  │             + change_queue（client_uuid, entity, op, base_revision, sync_status）
│  │             + sync_state（last_cursor）+ ref_cache（**记录页表单缓存** +
│  │               多选字段的"最近用过"顺序；字典/选项集/反应定义已随迁移 011/012 删除）
│  ├─ remote/    Dio 客户端、DTO（表单 DTO 是 SOAP 模板驱动的）
│  └─ repo/      仓库层（本地优先）
├─ sync/         同步引擎：推送（幂等、≤200/批）、拉取（游标、≤500/次）、冲突处理、
│                主动定时同步（`auto_sync.dart`）
├─ features/     auth / home / patients / records / timeline / settings / sync
└─ tool/         开发脚本（build_env.ps1、run_on_emulator.ps1）
```

---

## 增量同步的触发规则（2026-10-06 起）

同步是**离线优先**的：本地 Drift 库是唯一数据源，UI 只读本地；
服务端只通过下面这些时机被拉取/推送。

### 事件触发（原有）

| 时机 | 动作 |
|---|---|
| 登录成功 | 首次：`pullInitial` 全量；已有游标：`pullIncremental` |
| 患者列表**首次进入** | 推队列 + 刷新患者 + 增量拉 |
| 从详情/记录页**返回列表**（`didPopNext`） | 同上（用户 2026-10-05：「每次返回患者页自动刷新」） |
| 从记录页返回**患者详情** | 同上 |
| 患者列表**下拉刷新** / 顶部同步按钮 | 同上 |
| 「我的」→ 立即同步 | 同上 |
| 保存一条记录后 | 只推该条（`pushPending`） |
| 处理冲突（保留我的 / 用服务端的） | 推 + 增量拉 |
| 看板回到前台（记录页） | 只校正"日期是否跨天"，**不**同步 |

### 定时触发（2026-10-06 新增，`auto_sync.dart`）

原来缺"什么都没发生"时的那条路径，而全科共享视图恰恰需要它：
**张三记了一条，李四的手机停在患者列表上不动，他看不到** ——
列表是本地 Drift 流，没人 pull 就不会变。

| 项 | 值 |
|---|---|
| 前台间隔 | **30 秒** |
| 失败退避 | 30 → 60 → 120 秒（上限 120），成功立刻回到 30 秒 |
| 回到前台 | **立刻**同步一次（不等下一个 30 秒） |
| 进入后台 | **停表**（国产 ROM 会杀后台网络，留着一条"看起来在跑"的死表只会误导） |

挂在主界面外壳（`home_shell.dart`）而不是各页面：它只在**登录后**存在，
生命周期与"有人正在用这个 App"一致。

**刻意不引入 `connectivity_plus` / `workmanager`**：
前者只说明"有网"，不说明"服务器可达"（医院内网常见有 WiFi 但连不上后端），
而真正可用的判据是"请求成功"——那正是退避逻辑在做的事；后者在国产 ROM 上
后台执行不可靠，还要处理权限与白名单。

### 防重入（定时器带来的新要求）

定时器到点时，用户可能正好点了同步按钮、或刚从详情页返回 ——
并发调用从"可能"变成"必然"。`PatientSyncController.refresh()` 因此
**让后来者等待同一次同步**，而不是各自再跑一遍：

- 不防的后果不只是费流量：`pullIncremental` 会互相覆盖游标，
  还会把 UI 刷成"已更新"，让人以为同步成功了；
- 也**不能直接丢弃**后来者 —— 那样用户手动点同步会"看起来没反应"。

离线失败时 `refresh()` **不抛异常**（调用方 `initState`、`didPopNext`、
`onPressed` 都没有 catch），只把结果写进 `lastFailed` 供调度器决定退避。

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

**受限环境下的替代验证**（当 `flutter` 命令被沙箱挡住时 —— flutter 必须写
`bin/cache` 与用户级缓存，且 Dart 进程无法 spawn 子进程，所以 `flutter analyze` /
`flutter test` / `build_runner` 都会失败）：

```powershell
cd app
```

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

8. **★ 模拟器连本机后端：首选 `adb reverse`；`10.0.2.2` 能不能用取决于防火墙。**
   安卓模拟器通常用 `10.0.2.2` 访问宿主机。**本机 2026-10-04 首次实测时它不通**：
   模拟器能 ping 通 `8.8.8.8`，却连不上 `10.0.2.2:<port>`；在宿主机开临时监听确认过，
   **只收到 `127.0.0.1` 的连接、没有来自模拟器的** —— Windows 防火墙入站默认阻止，
   而 uvicorn 没有放行规则。
   > **补充（同日稍后）**：后来 App 用默认的 `10.0.2.2:8000`（未加 `--dart-define`）
   > 也能正常同步 —— 很可能是首次运行时 Windows 弹了"是否允许防火墙访问"并被放行。
   > 也就是说 `10.0.2.2` **不是必然不通**，取决于防火墙是否已放行该进程/端口。
   > 结论：**优先用 `adb reverse`（确定性、不依赖防火墙）**，`10.0.2.2` 当作"能用就用"。

   反向转发的做法（流量走 adb 通道、**完全不过防火墙**）：
   ```powershell
   adb reverse tcp:8000 tcp:8000
   flutter run --dart-define=KB_BASE_URL=http://127.0.0.1:8000
   ```
   `tool/run_on_emulator.ps1` 已封装这两步。

   > `adb reverse` 在**模拟器重启后会失效**，需要重跑。
   > `AppConfig` 的默认值在安卓上仍是 `10.0.2.2`（真机/已放行网络下是对的），
   > 联调时也可以用 `--dart-define` 覆盖成 `127.0.0.1`。

   ### ★ 部署到别的环境：运行期手填服务器地址（2026-10-06）

   一份 APK 要装到多套互不相通的内网里，**装完才发现连不上时必须有补救入口** ——
   现场没有构建环境，"回去重新打包"不现实。

   **登录页底部 →「服务器设置」**：填地址 → **测试连接**（打 `/health`，无需登录）
   → 通过才保存。探测结果会带上服务端自报的服务名与版本，用来确认"连的是哪一套"。

   地址优先级：**手填地址 > `--dart-define=KB_BASE_URL` > 平台默认值**。
   手填的存在 `flutter_secure_storage`（与 refresh token 同一处）。

   **换服务器会切换本地数据副本。** 本地库把服务端主键当自己的主键用
   （`treatment_records.id` 就是服务端记录 id、`patients.inpatient_no` 是住院号、
   `sync_state.last_cursor` 是服务端变更日志游标），所以两台服务器的数据
   **结构上不可能混用**。实现方式是**按后端指纹分库文件**：

   | 后端 | 库文件 |
   |---|---|
   | 编译期默认那台（含升级前的旧库） | `rehab_app.sqlite` |
   | 其它任何地址 | `rehab_app_<host>_<port>.sqlite`，如 `rehab_app_10_0_0_8_8000.sqlite` |

   分文件比"切地址时记得清库"可靠：清库依赖每个切换路径都写对，
   分文件是**结构上不可能串**。老用户升级后仍用 `rehab_app.sqlite`，数据不丢。

   > 指纹按 **host + port** 算（忽略 scheme、路径、大小写、尾部斜杠），
   > 且**必含** `http://` 补全 —— 用户直接填 `10.0.0.8:8000` 时
   > `Uri` 会把 `10.0.0.8` 当 scheme、host 为空，不补就会让所有地址撞成同一个指纹。
   > 相关纯函数有单测：`test/server_settings_test.dart`。

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

已完成**三个页签的端到端竖切**（登录 → 患者 → 时间轴 → 记录/汇总/打印），
患者/时间轴/汇总/打印在真实后端上验证过；记录页在 SOAP 改造后已换到新契约
（见下文「记录页：SOAP 模板驱动」）：

- **患者 → 同步**：登录成功、14 名患者自动落库并渲染、注意事项醒目、详情页可进
  （含该患者的历史记录列表）；
- **记录**（**SOAP 模板驱动**）：按 `soap[]` 分段渲染的一屏 chip 表单、离线草稿
  （本地 + 队列）、`body` 契约提交、`rendered_text` 冻结文本；
- **时间轴**：全科记录流分页、**两个 scope**（全科 / 我写的）、日期 + 大类 + 形态筛选；
- **汇总与打印**：当日汇总（两种分组）、患者每日汇总；三份 PDF 都能下载，
  实测文件头 `%PDF` 且与后端字节数吻合。

### 记录页：SOAP 模板驱动（已实现）

后端契约（`app/api/v1/records.py`，实测已上线）：

1. **取表单**：`GET /api/v1/records/form?patient_no=…&discipline=PT[&date=…][&kind=…]`
   - `patient_no`、`discipline`（`PT`/`OT`/`ST_SW`/`ST_SP`）**必填**；`date` 可选；
   - `kind` 可选，**出院小结必须显式传 `kind=discharge`**（门禁永远推不出"该出院了"）；
   - 返回值里有 `kind` / `kind_label` / `title` / `next_seq` / `total_daily` /
     `days_until_reassessment`（`int?`，**负数 = 逾期**，`null` = 还没有首评）/
     `reassessment_due`（`String?`，应做日）/
     `reassessment_interval_days`（= **30**，复评周期，天）/
     `pending_document`（**非空时 `kind` 就是那份待补的评估文书**）/
     `soap`（四段字段定义，直接渲染）/ `prefill` / `prefill_source` / `existing`。
     > ★ 2026-10-06：原 `sessions_until_reassessment`（"还差 N **次**"）**已删除** ——
     > 复评改成「距**首评** 30 个自然日」（锚点是首评日，不是最近一次评估日），
     > 单位是**天**不是次数。
2. **渲染**：按 `soap[].fields` 渲染四段表单 —— **段名 + 冒号，段内字段是 chip**：
   `single` 点一下选中、再点取消；`multi` 可多选；选项超过 10 项自动出现**搜索框**，
   并把**最近用过的排最前**（`ref_cache` 的 `recent_options:<field_key>`）；
   `number` 是带 `unit` 后缀的数字输入；`text` 是多行输入（`hint` 作 placeholder）；
   `auto` 字段只读（出院小结的「治疗过程汇总」由服务端算好）。
   `options_source: "therapy_options"` 的字段选项由服务端展开成
   该大类的疗法清单（运动 58 / 生活技能 5 / 吞咽 4 / 言语 13）。
3. **提交**：`POST /api/v1/records`，请求体
   `{patient_no, record_date, discipline, kind, body: {field_key: value}, status, note, client_uuid}`。
   **不要**再发 `items` / `session_period` / `patient_response`（三者均已删除），也**不要**自己填
   `seq_no` / `rendered_text`（服务端算并冻结）。
4. **展示**：列表用 `rendered_excerpt` 一行摘要，详情/打印用完整的 `rendered_text`。
5. **本地库**：`TreatmentRecords` 是 `discipline` / `kind` / `seq_no` / `body_json` /
   `rendered_text`；**`RecordItems` 表已删除**（没有"明细"了）；`ref_cache` 存表单缓存与
   "最近用过"顺序。**schemaVersion 6**（4 → 5 的迁移把旧行**直接丢弃** ——
   旧结构与新模型之间没有可计算的映射，服务端也已清空重建；详见 `app_database.dart` v5 注释）。
6. **离线推送同样受硬阻断约束**（服务端会拒，见 `docs/sync-protocol.md` §4.3.1）：
   缺首评/缺复评/同一天同一大类第 3 条/待出院 → 409，且**整个请求**失败。
   客户端把 `details.missing` / `missing_document` / `limit` 分别翻成可操作的话
   （`features/records/record_failure.dart`）。
7. **出院**：患者详情页「出院」按钮在四个大类按钮**左侧**（任何治疗师可用）→
   `kind=discharge` 的出院小结 → 提交后调 `POST /patients/{no}/discharge`
   （body `{record_id}`）→ 患者转 `pending_discharge`，本地立刻从白板隐藏但不删行。

| 已实现 | 说明 |
|---|---|
| Drift 本地库 | 5 张表；`change_queue` 是离线队列，`sync_state` 存游标；**schemaVersion 6** |
| 认证 | 工号+密码登录、refresh token 进安全存储、冷启动自动恢复、401 静默刷新 |
| 患者列表 | 全科白板 + 我的/未分配筛选 + 本地搜索；**响应式**（落库即刷新） |
| 患者详情 | 注意事项醒目、诊断/状态/归属、**竖排四大类按钮**（带"已记录 N 次 / 距复评 N 天"，到点后显示"该复评了"）、**出院按钮**、历史记录列表、汇总与打印入口 |
| 记录 | **SOAP 一屏 chip 表单**（点一下就是选中）、离线草稿、必填校验只在提交时做、422/409 分别提示、退出前拦截未保存 |
| 时间轴 | 全科记录流、分页自动加载、全科/我写的、日期 + 大类 + 形态筛选、条目显示 SOAP 文本 |
| 汇总/打印 | 当日汇总（按治疗师↔按患者）、患者每日汇总、三份 PDF 下载并以**三种去向**输出（发送给微信 / 系统打印 / 打开） |
| 冲突处理 | 冲突列表 + **本地这一版改了什么**（`body` 各项）+ 「保留我的 / 采用服务端」两向裁决 |
| 同步引擎 | 幂等推送（≤200/批）、游标增量拉取、按快照 upsert、**推送成功后把本地占位 id 换成服务端 id** |
| 「我的」页 | 后端地址、证书状态、待同步条数、**冲突入口**、上次同步时间、退出登录 |

`flutter analyze` 无问题；测试在 `app/test/`（`flutter test` 运行）。
> **SOAP 改造这一轮的验证状态**：静态检查 **0 issue**；`app/test/` 已按新契约重写，
> 并新增 4 个测试文件 —— `record_repository_test`（四种字段类型、`body` 载荷形状、
> 表单缓存按大类分开）、`record_error_test`（422 `missing` / 409 `missing_document` / `limit`）、
> `migration_test`（schemaVersion 4 → 5）、`discharge_test`（出院流程的状态变化）。
> ⚠ 本次交付环境**无法运行 `flutter test` / `flutter build apk`**（沙箱禁止 flutter
> 写 `bin/cache` 与用户级缓存，且 Dart 进程无法 spawn 子进程）—— 请在正常权限下用
> `tool/build_env.ps1` 复核一次。

> **2026-10-05 SOAP 改造对本端的影响（已完成）**：
> 后端删掉了字典 / 选项集 / 患者反应定义 / 科室模板六张表与 `/dict/**`、`/option-sets*`、
> `/response-defs*`、`/templates*` 四组接口；治疗记录改为
> `discipline` + `kind` + `body`(`{field_key: value}`) + 冻结的 `rendered_text`。
> **本端已做的**：记录页改取 `/records/form`（见上文「记录页：SOAP 模板驱动」）、
> Drift 表与同步 payload 换契约（schemaVersion 4 → 5）、删掉 `RecordItems` 相关代码与测试。

> **2026-10-05 排期功能下线对本端的影响**（已完成，删除范围如下）：
> 删除了 `app/lib/features/schedule/` 目录以及 `schedule_dto.dart`、`schedule_repository.dart`；
> 删除了 Drift 的 `Appointments` 表与 `TreatmentRecords.appointmentId` 列（**schemaVersion 2 → 3**）；
> 页签由 4 个减为 3 个（患者 / 时间轴 / 我的）；PDF 导出改为三种去向。

> **2026-10-05 临时指派功能删除对本端的影响**（已完成）：
> 服务端删掉了 `temporary_assignment` 表，可见归属**直接等于**原归属；客户端本地库本来
> 就没有临时指派表，只删掉了镜像表里那个已退化的 `Patients.visibilityState` 列
> （**schemaVersion 3 → 4**）。时间轴页签由「全科 / 我写的 / 临时治疗」减为
> 「全科 / 我写的」——`scope=temp` 已按用户决定删除。
> 注意**记录级的 `is_temporary` 标记仍然保留**（打印 PDF 与汇总在用），
> 它与 `scope=temp` 是两件事，不要混为一谈。

### 接入记录页时踩到的两个接口坑（**已随 SOAP 改造失效**，留作历史）

1. ~~`multi_select` 必须提交数组~~ —— 参数模型已删除，现在按模板 `type: multi` 提交数组即可，
   服务端不再做"选项集成员"校验（只校验模板里 `required` 的字段是否填了）。
2. ~~患者反应定义按主项目分组~~ —— 患者反应定义表**已随迁移 012 删除**，
   `main_item_id` / `response_defs` **都已删除**；表单缓存键也简化为
   `record_form:<患者>:<大类>`（不再按主项目分作用域）。

### 打印 PDF 的坑

**不能把打印 URL 直接丢给浏览器或 PDF 阅读器**：那些组件不会带我们的
`Authorization` 头，打开只会看到 401。必须自己用 `ApiClient.requestBytes`
带 Bearer 下载到本地，再交给系统阅读器（`open_filex`）。
`requestBytes` 走 `ResponseType.bytes`，但**失败体仍是 JSON 错误体**，
所以要转回文本再交给 `AppError.fromBody`。

### 冲突处理为什么不需要新接口

服务端 `resolve_conflict` 的第一条判定是
`base_revision == server_revision → 无冲突，直接应用`。
所以"用我的版本覆盖服务端"只要把基线对齐到服务端当前版本再推一次。
分两步：先**清空基线**推一次（服务端必然再判冲突，响应带回当前 `server_revision`），
再用它当基线推。清空基线这一步是必须的 —— 沿用旧基线时若恰好与服务端一致，
服务端会直接应用，那就成了"推着推着悄悄覆盖"，而不是治疗师确认后的覆盖。

> 历史上还有一个**后端种子缺陷**（89 个参数里 19 个的带入值落在自己的选项集之外，
> 根因见 `CHANGELOG.md` TODO-12）—— 那套参数与选项集**已随迁移 011/012 删除**，
> 缺陷本身随之消失，不需要再修。

**App 侧功能已全部实现**（协议 §8 的竖切走完），**并已完成 SOAP 契约适配**。
剩下需单独安排：
- **TODO-09**：PDF 模板版式细化（当初约定"App 功能全部实现后再做"，现在可以开始了）；
- ~~**TODO-13**：记录页 SOAP 适配~~ —— **已完成**（取 `/records/form`、换 `body` 契约、
  Drift schemaVersion 4 → 5、删掉 `RecordItems` 相关代码与测试）。
