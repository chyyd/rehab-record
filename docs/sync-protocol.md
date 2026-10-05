# 离线同步协议（sync-protocol）

> **状态**：已定稿，**与后端实现逐条对齐**（本文描述的都是实测行为，不是设想）。
> **读者**：安卓 App（Flutter）开发者、后端维护者。
> **地位**：`开发计划.md` T4.5 的 DoD 要求"客户端本地库与服务端字段映射有文档"，
> 本文即该文档；它同时是 `docs/data-model.md` 中**同步相关部分**的替代（该文件尚未创建）。
>
> **文档优先级**（与 README 一致）：迁移文件 / `worktime.py`（代码） > `开发计划.md` > `设计.md`。
> 本文若与代码冲突，**以代码为准**，并回头修正本文。

---

## 0. 一句话总览

服务端提供 **3 个同步接口**：

| 接口 | 作用 |
|---|---|
| `GET /api/v1/sync/info` | 能力探测：可推送/可拉取实体、批量上限、冲突策略说明 |
| `POST /api/v1/sync/push` | **批量幂等推送**客户端本地变更（**一期只有治疗记录**） |
| `GET /api/v1/sync/pull` | 按**游标**增量拉取服务端变更 |

核心机制：**客户端生成 `client_uuid` 做幂等 + 整数 `revision` 做乐观锁 + `change_log.id` 做游标**。

> **2026-10-05**：排期（`appointment`）随"排班不是本系统的职责"这一决策整体下线，
> 同步通道**只剩治疗记录**。原 appointment 通道的 payload、冲突策略行与本地镜像表均已删除。

---

## 1. ★ 患者数据不走进同步接口（2026-10-03 重要约定）

**这是本协议最容易踩错的一条，必须先读。**

### 事实

- `pullable_entities` 里**确实写着 `patient`**，但 `change_log` 表里**永远不会出现 `entity='patient'` 的行**。
  实测：开发库里 `change_log` 的实体只有 `treatment_record` 一种（排期下线后 `appointment` 的历史行
  已由迁移 `008_drop_scheduling.sql` 清掉），**`patient` 0 行**。
- 原因：`app/api/v1/patients.py` **完全不写 `change_log`**（只有 `write_audit`），
  而 `change_log` 的写入点只有治疗记录（4 处）。

### 因此（客户端必须这样做）

| 数据 | 获取方式 |
|---|---|
| **患者主数据** | **走 `GET /api/v1/patients` 分页拉取**（登录时 + 前台定期 + 下拉刷新），**不要**指望 pull |
| 治疗记录 | 走 `POST /sync/push` 与 `GET /sync/pull`（增量） |
| 字典 / 选项集 / 模板 / 患者反应定义 | 走各自只读接口，**整包 JSON 缓存**（见 §8） |

### 为什么不"补上"患者变更日志

`change_log` 的一行对**所有客户端是同一行**，没有"按人可见性"维度。
而患者可见性是有状态、会变化的（在院/暂停/出院、归属变更）。
若把患者写进 `change_log`：

1. 客户端会拉到本无权看到的患者（**数据泄露**）；
2. 患者状态与归属变更会让可见性频繁变化，`change_log` 语义被污染。

**结论**：一期**不把患者写进 `change_log`**。"统一游标"的代价大于收益；
患者量小（科室百级），整表分页拉取的代价可接受。二期若要做，需要先给 `change_log`
加"可见性维度"并重新评估。

> 客户端实现建议：把"患者列表刷新"做成一个独立任务（如每 5 分钟或进入前台时），
> 与同步引擎解耦；失败不影响治疗记录的同步。

---

## 2. 可见性范围（2026-10-03 起为"全科白板"）

同步的数据范围由服务端按**当前登录人**决定，客户端不需要自己过滤，但必须理解语义：

- **在院（`in_hospital`）+ 暂停（`paused`）** 的患者：**全科治疗师可见**，
  其治疗记录**可读可写**（写记录时只能以自己名义）。
- **已出院（`discharged`）**：默认**不可见**（`GET /patients` 与其记录/汇总都不可见）；
  管理员可用 `scope=all` 查看全表。
- 归属（`assigned_therapist_id`）只影响**列表排序**（"我的患者优先"，组内按我最近一次已提交治疗降序）
  与文书署名，**不再是可见性闸门**。

> 这意味着客户端**不能假设**"我在本地有的患者，下次一定还能看到"——
> 患者可能已出院而从白板消失。本地库里对已不可见的患者做软标记，不要直接删除本地记录
> （否则历史记录会失去患者信息）。

---

## 3. 实体清单

### 3.1 可推送（离线可写）

```
PUSHABLE_ENTITIES = ("treatment_record",)   # 一期只有治疗记录（排期已于 2026-10-05 下线）
MAX_PUSH_BATCH   = 200                      # 单次最多 200 条
```

推送其它实体（**包括 `patient`**）→ **422**，响应 `details.allowed` 给出允许值：

```json
{"code":"INVALID","message":"该实体不在离线可写范围内（一期只允许治疗记录）",
 "details":{"entity":"patient","allowed":["treatment_record"]}}
```

### 3.2 可拉取

```
PULLABLE_ENTITIES = ("patient", "treatment_record")   # 注意 §1：patient 实际为空
MAX_PULL_LIMIT    = 500                               # 单次最多 500 条
```

`entities=` 参数只接受上述两个值，传其它值 → **422**。

---

## 4. 推送协议（`POST /api/v1/sync/push`）

### 4.1 请求体

```json
{
  "changes": [
    {
      "entity": "treatment_record",
      "client_uuid": "9f1c2d3e-4a5b-4c6d-8e7f-0a1b2c3d4e5f",
      "op": "insert",
      "base_revision": null,
      "payload": { "...": "实体字段快照" }
    }
  ]
}
```

| 字段 | 约束 | 说明 |
|---|---|---|
| `entity` | 必填，∈ 可推送实体 | |
| `client_uuid` | **必填**，长度 8–64 | **客户端生成 UUIDv4**；同一条变更**重试必须带同一个值** |
| `op` | `insert` / `update` / `delete`，默认 `update` | 非法值 → **422** |
| `base_revision` | 可空整数 | 乐观锁基线；**新建时不传** |
| `payload` | 对象 | 见 §4.3 |

- `changes` 条数 **1–200**；空数组或超过 200 → **422**（**明确报错，不静默截断**）。
- **同一批里重复的 `client_uuid`**：后一条记为 `skipped`，`reason="duplicate_in_batch"`。

### 4.2 响应体

```json
{
  "applied":   [{"outcome":"applied","client_uuid":"…","entity":"treatment_record",
                 "entity_id":42,"op":"insert","revision":1}],
  "skipped":   [{"outcome":"skipped","client_uuid":"…","entity":"…","reason":"duplicate_in_batch"}],
  "conflicts": [{"outcome":"conflict","client_uuid":"…","entity":"treatment_record","entity_id":42,
                 "server_revision":3,"server_status":"submitted",
                 "reason":"server_status=submitted"}],
  "cursor": 128
}
```

**逐条独立处理：一条冲突不会让整批失败。** 客户端必须按三个数组分别处理，
不能只看 HTTP 状态码。

`cursor` 是服务端当前最大 `change_log.id`，可存下来供下次 `pull` 使用。

### 4.3 各实体的 `payload` 形状

**`treatment_record`**（`sync.py::_push_treatment_record`）：

```json
{
  "patient_no": "ZY001",
  "therapist_id": 2,
  "record_date": "2027-03-01",
  "session_period": "am",
  "duration_min": 30,
  "note": "备注",
  "status": "draft",
  "patient_response": {"tags": ["no_discomfort"],
                       "items": [{"code":"nrs","label":"疼痛","value_type":"number",
                                  "value_key":"nrs","value":3,"unit":"分"}]},
  "items": [
    {"main_item_id": 1, "sub_item_id": 11, "params": {"side": "左", "position": "坐位"}}
  ]
}
```

- `items[].params` 的键**一律是 `param_key`**（英文），不是显示名。
- `therapist_id` 省略时默认取当前登录人；**传别人 → 403 `RECORD_OTHER_THERAPIST`**。
- 更新时 `update_record` **只改传入的字段**；`status` **不能**通过 push 流转
  （提交/锁定走 `POST /records/{id}/submit` 与 `/lock`，见 §4.5）。
- **没有 `appointment` 通道**：排期功能已于 2026-10-05 整体删除，`payload` 里也不需要
  `appointment_id` / `is_temporary` / `original_therapist_id` 三个字段（记录表已删除这三列；
  `is_temporary` 改由服务端**查询时推导**：记录人 ≠ 该患者在记录创建时刻的归属治疗师）。

### 4.4 冲突判定（服务端实现，客户端只需理解）

服务端按 `client_uuid` 找是否已存在（`find_by_client_uuid`）：

```
不存在            → 走正常创建路径（insert）
存在（即"重试"）  → resolve_conflict(is_retry=True)
```

`resolve_conflict` 的判定（`sync.py::resolve_conflict`）：

| 情况 | 结果 | `reason` |
|---|---|---|
| `base_revision` 与服务端 `revision` **相等** | 无冲突，直接应用 | — |
| `treatment_record` 且服务端仍是 `draft` | **客户端优先** | `server_still_draft` |
| `treatment_record` 且服务端已 `submitted`/`locked` | **服务端优先** | `server_status=submitted` / `=locked` |
| 其它实体、**是重试**且未给基线 | **客户端优先**（保证幂等） | `idempotent_retry` |
| 其它实体、首次推送、未给基线 | **服务端优先** | `missing_base_revision` |
| 其它实体、首次推送、给了过期基线 | **服务端优先** | `entity_prefers_server` |

**★ 关键：`client_uuid` 的重试不能带 `base_revision`。**
客户端重推自己创建的变更时**不要**带 `base_revision`——服务端识别为"重试"后按客户端优先处理。
若带上过期基线，反而会被判成冲突（`entity_prefers_server`），弱网下每次重试都失败。

> 表里"其它实体"那三行现在是**理论分支**：一期唯一可推送的实体 `treatment_record` 本身就有
> "客户端优先"窗口，`CLIENT_WINS_ENTITIES` 里也只有它。

### 4.5 不能通过 push 完成的动作

以下动作**必须在联网时**调专用接口，不要塞进离线队列：

| 动作 | 接口 |
|---|---|
| 提交记录（`draft → submitted`，分配 `seq_no`） | `POST /api/v1/records/{id}/submit` |
| 锁定记录（管理员） | `POST /api/v1/records/{id}/lock` |
| 删除草稿 | `DELETE /api/v1/records/{id}` —— **只能删自己的草稿** |
| 认领 / 放弃 / 分配患者归属 | `POST /api/v1/patients/claim` / `{no}/release` / `{no}/assign` |
| 治疗师本人密码 | `PUT /api/v1/auth/password` |

> 离线时这些入口应**置灰并提示"需联网"**，而不是排进队列（一期不做患者离线写）。
> ~~登记/撤销请假、休息块增删改~~ 的接口**已随排期功能删除**（2026-10-05）。

---

## 5. 拉取协议（`GET /api/v1/sync/pull`）

### 5.1 请求

| 参数 | 默认 | 说明 |
|---|---|---|
| `cursor` | `0` | 上次返回的 `cursor`；`0` 表示从头（首次全量） |
| `limit` | `500` | 1–500；超过 500 会被**钳制**到 500（查询参数由 FastAPI 校验） |
| `entities` | 空 | 逗号分隔，仅接受两个可拉取实体；**只用于首次全量同步**，见 §5.3 |

### 5.2 响应

```json
{
  "cursor": 128,
  "latest_cursor": 128,
  "changes": [
    {"id": 121, "entity": "treatment_record", "entity_id": "42", "op": "update",
     "revision": 3, "actor_user_id": 2, "payload": { "...": "完整实体快照" },
     "created_at": "2027-03-01T02:00:00.000Z"}
  ],
  "has_more": false
}
```

- `changes[].id` **就是游标**；`entity_id` 是**字符串**（治疗记录为 `id`，患者为 `inpatient_no`）。
- **无新变更时 `cursor` 不前移**（与请求值相同），客户端不要自己推进。
- `has_more=true` 表示还有未拉取的变更（含"因 `entities` 过滤而留下的其它实体变更"），
  客户端应**继续拉**直到 `false`。

### 5.3 `entities` 过滤的语义（易错）

被过滤掉的变更**不返回**，但**游标仍会前进到"最后一条返回记录"的位置**。
因此它**只适合首次全量同步**（客户端从空库开始，不关心其它实体的历史）：

```
首次全量： pull(cursor=0, entities="treatment_record", limit=500) × N 轮
          直到 has_more=false；终点用 latest_cursor
之后增量： pull(cursor=本地游标, limit=500)   ← 不带 entities，在客户端按 entity 筛选
```

若在增量阶段继续带 `entities`，会**永久跳过**被过滤实体的中间变更。

### 5.4 payload 是完整快照（不是增量）

- `treatment_record` 的 payload 带上 `items`（**含两层快照**：
  `sub_item_name_snapshot` 与 `params_snapshot_json`），
  代码注释明确写了"客户端据此在本地完整重建这条记录"。
- `op='delete'` 的 payload 可能为 `null` —— 客户端按 `entity` + `entity_id` 删除本地行。
- **不再有 `appointment` 的 payload**（排期通道已随功能删除）。

因此客户端可以安全地做 **`INSERT ... ON CONFLICT DO UPDATE`（upsert）**，**幂等应用**。

### 5.5 变更日志的保留

一期**不清理** `change_log`（无归档任务）。客户端应保存自己的 `last_cursor`，
长期离线后按游标续拉即可；不要用时间戳做游标（时钟偏移会漏数据）。

---

## 6. 同步状态机（客户端）

推荐每个"待同步本地行"维护：

```
local ──(入队)──> pending ──(push applied)──> synced
                     │
                     └──(push conflict)──> conflict ──(人工处理后重提)──> pending
```

| 状态 | 含义 | 处置 |
|---|---|---|
| `local` | 仅本地存在，尚未入队 | 立刻入队为 `pending` |
| `pending` | 已入队，等待推送 | 网络可用时批量推送（≤200 条） |
| `synced` | 服务端已确认 | 记录 `revision` 与 `client_uuid` |
| `conflict` | 服务端优先，本地版本被拒 | **不要静默丢弃**：提示治疗师，支持"以我的版本重提"（带上服务端返回的 `server_revision` 作为新基线） |

**队列字段建议**（见 §7.2）：`client_uuid`、`entity`、`op`、`base_revision`、
`sync_status`、`retry_count`、`last_error`、`created_at`。

重试策略：**指数退避**（如 2s / 4s / 8s …），网络恢复后重试；`retry_count` 用于提示"迟迟传不上去"。

---

## 7. 客户端本地库（Drift）设计

### 7.1 分工（2026-10-03 定稿，2026-10-05 修订）

| 数据 | 本地形态 | 理由 |
|---|---|---|
| `patient` / `treatment_record`（含 items） | **镜像表** | 要支持查询、按游标增量 upsert、离线读写 |
| 字典树（主/子项目/参数定义） | **整包 JSON 缓存**（`ref_cache`） | 只读；89 个参数定义建成表换不来查询收益，反而多一套迁移 |
| 选项集解析结果（按 `code`） | 整包 JSON 缓存 | 同上；解析规则在服务端（个人→科室→全局→内置） |
| 患者反应定义 / 记录模板 | 整包 JSON 缓存 | 同上 |

> `ref_cache` 建议字段：`key`（如 `dict_tree` / `options:side` / `templates`）、
> `payload`（JSON 文本）、`fetched_at`、`etag`（可空）。**整包原子替换**，避免半套数据。

### 7.2 建议的表（★ 与 `app/lib/data/local/tables.dart` 的实际列逐字对齐）

```
patient(inpatient_no PK, name, diagnosis, admin_note, assigned_therapist_id,
        visible_therapist_id, status, revision, visible, fetched_at)
        -- 2026-10-05：`visibility_state` 列**已删除**（本地 schemaVersion 3 → 4）。
        -- 服务端该字段已退化为恒 'assigned'，镜像一个常量没有意义。

treatment_record(id PK, patient_no, therapist_id, record_date, session_period,
                 duration_min, note, patient_response_json, status, seq_no,
                 edit_count, revision, is_temporary, original_therapist_id,
                 client_uuid, sync_status, pending_items_json)
                 -- `is_temporary` / `original_therapist_id` 在本地**保留**，只为与服务端
                 -- 字段一一对应（2026-10-03 起恒为 false / NULL）；不要再用它做 UI 判断。

record_item(id PK, record_id FK, main_item_id, sub_item_id,
            sub_item_name_snapshot, params_json, params_snapshot_json, sort)

change_queue(client_uuid PK, entity, op, base_revision, payload_json,
             sync_status, retry_count, last_error, created_at)

sync_state(key PK, value)     -- last_cursor / last_patient_sync_at / last_full_sync_at
ref_cache(key PK, payload, fetched_at, etag)
```

**要点**：

1. **主键用服务端 id**（`treatment_record.id`），
   本地新建时先用临时负数 id 或本地 UUID，服务端确认后回写真实 id。
2. `client_uuid` 建唯一索引（服务端也有 `ux_record_client_uuid` 对应）。
3. **不要**在本地复制 `change_log`；只存 `last_cursor`。
4. 已不可见的患者（出院）**软标记**，不要级联删除本地记录（§2）。
5. **不要**再建 `appointments` 镜像表：排期功能已删除，本地库 schemaVersion 由 **2 升到 3**
   （删除整张表 + 删除 `treatment_records.appointment_id` 列）；2026-10-05 再升到 **4**
   （删除 `patients.visibility_state` 列 —— 临时指派删除后该列已退化）。
6. `scope=temp` **已删除**（2026-10-05）：服务端患者列表的 `Scope` 只剩
   `mine` / `unassigned` / `all` / `visible` / `dept`，记录与时间轴只剩 `mine` / `visible`；
   App 的时间轴枚举也只有 `visible` / `mine` 两个。
   注意**记录级的 `is_temporary` 标记仍然保留**（服务端查询时推导，PDF / 汇总 / 后台在用），
   它与已删除的 `scope=temp` 筛选、`temporary_assignment` 表**都没有关系**。

---

## 8. 首次同步流程（建议顺序）

```
1. 登录 → 存 access/refresh token（refresh 进安全存储，见下）
2. GET /sync/info                → 确认 pushable / max_push_batch / limit
3. 拉参考数据（整包 JSON 缓存）：
   GET /dict/tree · GET /response-defs/grouped · GET /templates · GET /option-sets
4. 首次全量同步（按实体过滤，直到 has_more=false）：
   GET /sync/pull?cursor=0&entities=treatment_record&limit=500 × N
5. 拉患者列表（分页，直到取完）：
   GET /patients?scope=dept&page=N&page_size=…        ← 注意 §1：患者不走 pull
6. 记录 last_cursor = 步骤 4 的 latest_cursor
7. 之后：增量 pull（不带 entities） + 定期刷新患者列表 + 推送本地队列
```

**令牌存放**（D01 + 2026-10-03 决定）：refresh token 放 `flutter_secure_storage`（Android Keystore），
access token 只放内存。自签 CA 用 Dart 层 `SecurityContext` 注入，**不得关闭证书校验**。

---

## 9. 错误码与处置

| 场景 | HTTP | code | 客户端处置 |
|---|---|---|---|
| 未认证 / token 过期 | 401 | `AUTH_REQUIRED` | 用 refresh token 静默换新；失败则跳登录 |
| refresh 当 access 用 | 401 | `TOKEN_WRONG_TYPE` | 代码 bug，按登录处理 |
| 推送了不可离线写实体 | 422 | `INVALID` | 代码 bug（`patient` 不该进队列） |
| 批量 >200 / 空批次 | 422 | `INVALID` | 拆批重推 |
| 给自己的患者之外的治疗师写记录 | 403 | `RECORD_OTHER_THERAPIST` | 只能以自己名义写 |
| 记录已锁定 | 403 | `RECORD_LOCKED` | 提示"已锁定，需管理员" |
| 患者不可见（已出院） | 403 | `PATIENT_NOT_VISIBLE` | 刷新患者列表，提示可能已出院 |

> ~~排期命中休息块 / 请假 → 409~~ 这一类错误**已随排期功能删除**（2026-10-05），不会再有。

---

## 10. 与历史变更的关系（给后来者）

### 2026-10-05：排期下线

科室确认**排班不是本系统的职责**（只记录"每天做了哪些治疗、每次治疗干了什么"）。
本次变更**删除**了：

1. **删除 `appointment` / `rest_block` / `leave_record` 三张表**与全部排期、休息、请假接口；
2. **删除 `appointment` 同步通道**：`PUSHABLE_ENTITIES` 由 `("treatment_record", "appointment")`
   减为 `("treatment_record",)`，`PULLABLE_ENTITIES` 删除 `appointment`，
   冲突策略里的 appointment 行、payload 形状与本地镜像表一并删除；
3. **删除 `treatment_record` 的三个存储列**：`appointment_id`、`is_temporary`、`original_therapist_id`
   （`is_temporary` 改为**服务端查询时推导**：记录人 ≠ 该患者在**记录创建时刻**的归属治疗师）。

**未变**：幂等（`client_uuid`）、游标（`change_log.id`）、冲突分层、批量上限、`base_revision` 语义、
"患者不走 pull"（§1）。

### 2026-10-05（第二步）：临时指派与 `scope=temp` 删除

**与同步协议本身无关**（推送实体、游标、冲突策略一行未动），但影响可见归属与"范围筛选"的语义：

1. **`temporary_assignment` 表、`v_open_temporary_assignment` 视图与触发器已删除**（迁移 009；
   该迁移文件即 `009_drop_temporary_assignment.sql`，**删除**表、视图与触发器），
   `v_patient_visibility` 简化为"可见归属 = 原归属"；
   `scope=mine` 因此等价于"归属是我"，`scope=unassigned` 等价于"归属为 NULL"。
2. **`scope=temp` 两处筛选都已删除**：患者列表（`Scope` 白名单）与记录/时间轴
   （`api/v1/records.py` 现在只接受 `mine` / `visible`）。
3. **`is_temporary` 记录级标记保留**：它是服务端查询时推导的，与已删除的表没有依赖关系，
   PDF / 患者每日汇总 / 后台记录列表三个消费方都还在用它（§7.2 要点 6）。
4. 本地镜像表：`patients.visibility_state` 列**已删除**（schemaVersion 3 → 4）；
   `change_log` 里 `entity='temporary_assignment'` 的历史游标由 009 **删除**。

### 2026-10-03：全科白板

本次"全科白板 + 半日格子不互斥"的变更**改变了**：

1. **可见性**：治疗师能看到的患者从"我的/未分配/临时"扩展到"科室在院+暂停"；
2. ~~**排期冲突**：从三条减为两条~~（**已随排期删除**）；
3. **`scope` 取值**：新增 `dept`（治疗师默认），`visible` 保留为同义兼容值，`all` 仍仅管理员；
4. ~~**`is_temporary` / `original_therapist_id`**：字段保留但新写入恒为 `false`/`NULL`~~
   —— **2026-10-05 服务端已直接删除这两列**，不要再依赖它们（本地镜像表仍留着列位做字段对齐，
   值恒为 `false` / `NULL`，见 §7.2 要点）。

---

## 11. 待办 / 已知缺口

| # | 事项 | 说明 |
|---|---|---|
| 1 | `patient` 不进 `change_log` | 见 §1；二期若要做需给 `change_log` 加可见性维度 |
| 2 | 变更日志无归档 | 一期不清理；长期运行后 `change_log` 会持续增长 |
| 3 | `docs/api.md` / `docs/data-model.md` | 仍未创建；接口契约可直接用 `/openapi.json` 导出 |
| 4 | 冲突解决 UI 形态 | **已落地**（App 冲突列表 +「保留我的 / 采用服务端」两向裁决，见 `CHANGELOG.md`）；文案与交互仍以现场反馈为准 |
| 5 | 患者离线认领 | 当前推送 `patient` 会 422；床旁现场认领是否要离线支持待定 |
