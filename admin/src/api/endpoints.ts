/**
 * 后端接口的类型定义与调用封装。
 *
 * 类型与 `backend/app/schemas/` 对齐；字段名沿用后端（snake_case），
 * 不做驼峰转换 —— 少一层映射就少一处会漂移的地方。
 */
import { api } from './client'

// --------------------------------------------------------------------------- //
// 通用
// --------------------------------------------------------------------------- //
export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface PageParams {
  page?: number
  page_size?: number
}

export interface UserOut {
  id: number
  employee_no: string
  name: string
  role: 'admin' | 'therapist'
  status: 'active' | 'disabled'
  phone?: string | null
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  user: UserOut
}

// --------------------------------------------------------------------------- //
// 认证
// --------------------------------------------------------------------------- //
export const authApi = {
  login: (employee_no: string, password: string) =>
    api.post<LoginResponse>('/api/v1/auth/login', { employee_no, password }),
  logout: (refresh_token?: string) =>
    api.post<void>('/api/v1/auth/logout', undefined, {
      params: refresh_token ? { refresh_token } : undefined,
    }),
  me: () => api.get<UserOut>('/api/v1/auth/me'),
  changePassword: (old_password: string, new_password: string) =>
    api.put<void>('/api/v1/auth/password', { old_password, new_password }),
}

// --------------------------------------------------------------------------- //
// 健康与运维
// --------------------------------------------------------------------------- //
export interface HealthOut {
  status?: string
  checks?: Record<string, unknown>
  schema_version?: number
  [key: string]: unknown
}

export const healthApi = {
  check: () => api.get<HealthOut>('/api/v1/health'),
}

// --------------------------------------------------------------------------- //
// 用户
// --------------------------------------------------------------------------- //
export interface UserCreate {
  employee_no: string
  name: string
  role: 'admin' | 'therapist'
  password: string
  phone?: string | null
}

export interface UserUpdate {
  name?: string
  role?: 'admin' | 'therapist'
  status?: 'active' | 'disabled'
  phone?: string | null
}

export interface AuthSessionOut {
  id: number
  device_info?: string | null
  created_at: string
  expires_at: string
  revoked_at?: string | null
}

export const usersApi = {
  list: (params: PageParams & { role?: string; status?: string; keyword?: string } = {}) =>
    api.get<Page<UserOut>>('/api/v1/users', params),
  create: (payload: UserCreate) => api.post<UserOut>('/api/v1/users', payload),
  get: (id: number) => api.get<UserOut>(`/api/v1/users/${id}`),
  update: (id: number, payload: UserUpdate) => api.put<UserOut>(`/api/v1/users/${id}`, payload),
  resetPassword: (id: number, new_password: string) =>
    api.post<void>(`/api/v1/users/${id}/reset-password`, { new_password }),
  sessions: (id: number) => api.get<AuthSessionOut[]>(`/api/v1/users/${id}/sessions`),
  revokeSessions: (id: number) => api.delete<void>(`/api/v1/users/${id}/sessions`),
}

// --------------------------------------------------------------------------- //
// 患者
// --------------------------------------------------------------------------- //
export interface PatientOut {
  inpatient_no: string
  name: string
  diagnosis?: string | null
  admin_note?: string | null
  assigned_therapist_id?: number | null
  visible_therapist_id?: number | null
  status: string
  created_at?: string
  updated_at?: string
  revision?: number
}

export interface AssignmentHistoryOut {
  id: number
  patient_no: string
  action: string
  from_therapist_id?: number | null
  to_therapist_id?: number | null
  reason?: string | null
  created_at: string
}

export const patientsApi = {
  list: (params: PageParams & { status?: string; keyword?: string; therapist_id?: number } = {}) =>
    api.get<Page<PatientOut>>('/api/v1/patients', params),
  create: (payload: Partial<PatientOut> & { inpatient_no: string; name: string }) =>
    api.post<PatientOut>('/api/v1/patients', payload),
  get: (no: string) => api.get<PatientOut>(`/api/v1/patients/${encodeURIComponent(no)}`),
  update: (no: string, payload: Partial<PatientOut>) =>
    api.put<PatientOut>(`/api/v1/patients/${encodeURIComponent(no)}`, payload),
  assign: (no: string, therapist_id: number) =>
    api.post<PatientOut>(`/api/v1/patients/${encodeURIComponent(no)}/assign`, { therapist_id }),
  release: (no: string) =>
    api.post<PatientOut>(`/api/v1/patients/${encodeURIComponent(no)}/release`),
  assignments: (no: string) =>
    api.get<AssignmentHistoryOut[]>(`/api/v1/patients/${encodeURIComponent(no)}/assignments`),

  // ------------------------------------------------------------------------- //
  // 出院流程（2026-10-05 新增）
  //
  // 发起人**可以是任何治疗师**（治疗师才是写小结的人），所以 requestDischarge 在
  // 任何登录身份下都可用；确认与取消是管理员动作，后端用 AdminUser 强制。
  // ------------------------------------------------------------------------- //
  /** 发起出院：必须带上该患者**已提交的出院小结**的 record_id（出院 = 小结写完，不是点按钮）。 */
  requestDischarge: (no: string, record_id: number) =>
    api.post<PatientOut>(`/api/v1/patients/${encodeURIComponent(no)}/discharge`, { record_id }),
  /** 确认出院：待出院 → 已出院（管理员）。 */
  confirmDischarge: (no: string) =>
    api.post<PatientOut>(`/api/v1/patients/${encodeURIComponent(no)}/discharge/confirm`),
  /** 取消待出院：待出院 → 在院（管理员，用于患者反悔）。 */
  cancelDischarge: (no: string) =>
    api.post<PatientOut>(`/api/v1/patients/${encodeURIComponent(no)}/discharge/cancel`),
}

// --------------------------------------------------------------------------- //
// 治疗记录（SOAP 模板驱动）
//
// 2026-10-05：记录内容改由 `templates/*.json` **文件**驱动（用户要求
// 「使用 json 格式保存模板，不进数据库，以便以后我手动修改」），
// 所以**字典 / 选项集 / 患者反应定义 / 科室模板**这四组接口与页面整体删除 ——
// 后台不再需要维护字典：字段定义改文件即可，不需要动代码、不需要迁移。
//
// 已删除的端点（**不要再调用**，后端已无这些路由，会 404）：
// `/api/v1/dict/**`、`/api/v1/templates*`、`/api/v1/option-sets*`、
// `/api/v1/admin/option-sets*`、`/api/v1/response-defs*`。
//
// 同时记录本身也变成了「结构化 body + 冻结的 rendered_text」：
// 列表与详情都直接给 **SOAP 纯文本**，不再有 `items` / `session_period`（半日）/
// `duration_min` / `patient_response` 这些旧字段。
// --------------------------------------------------------------------------- //

/** 康复大类（`templates/disciplines.json` 的四项，后端枚举接口也返回同一份）。 */
export type Discipline = 'PT' | 'OT' | 'ST_SW' | 'ST_SP'

/** 记录形态：首评 / 日常 / 阶段性复评 / 出院小结。只有 daily 计治疗次数。 */
export type RecordKind = 'initial' | 'daily' | 'reassessment' | 'discharge'

export type RecordStatus = 'draft' | 'submitted' | 'locked'

export interface RecordEnumsOut {
  statuses: string[]
  kinds: string[]
  disciplines: { key: string; name: string; order: number }[]
}

export interface RecordListItemOut {
  id: number
  patient_no: string
  patient_name?: string | null
  therapist_id: number
  therapist_name?: string | null
  /** 推导值：记录人 ≠ 当时的归属治疗师；**不是存储列**。 */
  is_temporary: number
  record_date: string
  discipline: string
  discipline_name?: string | null
  kind: string
  kind_label?: string | null
  /** 第几次日常；只有 `daily` 有（评估文书为 null）。 */
  seq_no?: number | null
  // 2026-10-06：`span_seq`（评估文书挂靠的日常序号）已随迁移 014 删除。
  // 复评改成「距首评或上一次复评 30 个自然日」，不再有"挂靠第几次"这种概念。
  status: RecordStatus | string
  edit_count: number
  /** 生成时**冻结**的 SOAP 纯文本。 */
  rendered_text: string
  /** 列表用的一行摘要（后端截断后的纯文本）。 */
  rendered_excerpt?: string
}

export interface RecordOut extends RecordListItemOut {
  /** `{field_key: value}` 结构化答案（模板字段的原始取值）。 */
  body: Record<string, unknown>
  note?: string | null
  locked_at?: string | null
  created_at?: string | null
  submitted_at?: string | null
  updated_at?: string | null
  revision: number
}

/**
 * SOAP 表单里的一个字段（`GET /records/form` 的 `soap[].fields[]`）。
 *
 * 只有 4 种类型 + 1 个"自动只读"标志，所以后台可以像 App 那样**通用渲染**，
 * 不需要为每个大类写死界面（出院小结 17–23 个字段、四大类各不相同）。
 */
export interface SoapField {
  key: string
  /** `single` / `multi` / `number` / `text`。 */
  type: string
  label: string
  options?: string[]
  required?: boolean
  /** `number` 的单位（如 `分` / `级`）。 */
  unit?: string | null
  hint?: string | null
  /** `auto` 非空即"服务端算好的只读字段"（如出院小结的「治疗过程汇总」）。 */
  auto?: unknown
  collapsible_after?: number | null
}

export interface SoapSection {
  key: string
  label: string
  heading: string
  fields: SoapField[]
}

/** `GET /records/form`：App/后台渲染一次录入所需的全部信息。 */
export interface RecordFormOut {
  patient: { inpatient_no: string; name: string; status: string }
  discipline: string
  discipline_name: string
  kind: string
  kind_label: string
  title: string
  next_seq: number
  total_daily: number
  pending_document?: string | null
  template_version: number
  soap: SoapSection[]
  frequent_options?: Record<string, string[]>
  /** 每个字段的带入值（`{field_key: value}`）。 */
  prefill: Record<string, unknown>
  prefill_source?: Record<string, string>
  footer?: string[]
  existing?: RecordOut | null
}

export const recordsApi = {
  /** 记录列表。`status` 走 `status` 参数；日期区间走 `from` / `to`。 */
  list: (params: PageParams & {
    patient_no?: string
    therapist_id?: number
    status?: string
    discipline?: string
    kind?: string
    from?: string
    to?: string
    scope?: 'mine' | 'visible'
  } = {}) => api.get<Page<RecordListItemOut>>('/api/v1/records', params),
  get: (id: number) => api.get<RecordOut>(`/api/v1/records/${id}`),
  lock: (id: number) => api.post<RecordOut>(`/api/v1/records/${id}/lock`),
  submit: (id: number) => api.post<RecordOut>(`/api/v1/records/${id}/submit`),
  /** 状态 / 形态 / 四大类枚举（界面的下拉项应与后端同源）。 */
  enums: () => api.get<RecordEnumsOut>('/api/v1/records/enums'),
  /**
   * 取一次录入的表单（模板字段定义 + 预填值）。
   *
   * `kind='discharge'` 用来取出院小结 —— 它不是门禁推出来的，
   * 而是"要出院"这个显式动作（与 App 的出院按钮同源）。
   */
  form: (params: {
    patient_no: string
    discipline: string
    date?: string
    kind?: string
  }) => api.get<RecordFormOut>('/api/v1/records/form', params),
  /** 新建记录。`status='submitted'` 时出院小结会**自动把患者置为待出院**。 */
  create: (payload: {
    patient_no: string
    discipline: string
    kind: string
    body: Record<string, unknown>
    record_date?: string
    status?: string
    note?: string | null
  }) => api.post<RecordOut>('/api/v1/records', payload),
  timeline: (params: PageParams & {
    from?: string
    to?: string
    discipline?: string
    kind?: string
    scope?: 'mine' | 'visible'
  } = {}) => api.get<Page<RecordListItemOut>>('/api/v1/timeline', params),
}

// --------------------------------------------------------------------------- //
// 汇总与打印
//
// 2026-10-05：汇总与打印全部改为 **SOAP 纯文本**口径，不再是表格。
// - 计数：只算 `kind='daily'` 且 `status IN ('submitted','locked')`
//   —— 首评 / 复评 / 出院小结是独立文书，**不计治疗次数**；
// - 内容：`rendered_text`（多日按时间顺序往下排、不分页）。
// --------------------------------------------------------------------------- //
export interface TotalsOut {
  /** 治疗次数：只算日常记录，按记录去重。 */
  record_count: number
  /** 涉及患者数（同样只算日常）。 */
  patient_count: number
  therapist_counts: Record<string, number>
  /** 按康复大类（中文名）分布。 */
  discipline_counts: Record<string, number>
}

/** 汇总行 = 列表项 + 患者姓名与临时标记（后端 `SummaryRowOut`）。 */
/**
 * 按日期汇总里的一行。
 *
 * ⚠ **不要写成 `extends RecordListItemOut`**：从那里继承来的 `id: number` 是必填的，
 * 而汇总接口**根本不返回 `id`**（只有 `record_id`）。
 *
 * 2026-10-06：`SummaryPage` 里写了 `key={row.id}` —— `key={undefined}` 等于没给 key，
 * React 报 "Each child in a list should have a unique key prop … Check the render
 * method of Card. It was passed a child from DateSummary."。
 * 因为基接口声明了必填的 `id`，**tsc 拦不住这个笔误**，警告又指向别处，很难查。
 * 用 `Omit` 去掉 `id` 之后，再写成 `row.id` 会被类型检查直接指出。
 */
export interface SummaryRowOut extends Omit<RecordListItemOut, 'id'> {
  record_id: number
}

export interface DateSummaryOut {
  date: string
  group_by: string
  totals: TotalsOut
  groups: { key: string; totals: TotalsOut; rows: SummaryRowOut[] }[]
}

export interface PatientDailyRecordOut {
  record_id: number
  discipline: string
  discipline_name?: string | null
  kind: string
  kind_label?: string | null
  seq_no?: number | null
  status: string
  therapist_name?: string | null
  is_temporary: number
  note?: string | null
  rendered_text: string
}

export interface PatientDailyRowOut {
  record_date: string
  /**
   * 当天的**日常**记录条数（评估文书不计）。
   * ⚠ 只含出院小结 / 首评的那天会是 `0` —— 这是**预期行为**，不是缺数据。
   */
  record_count: number
  therapists: string[]
  disciplines: string[]
  temporary: boolean
  records: PatientDailyRecordOut[]
  /** 当天各条文书的 SOAP 纯文本（按时间顺序）。 */
  texts: string[]
}

export interface PatientDailySummaryOut {
  patient: {
    inpatient_no: string
    name: string
    diagnosis?: string | null
    admin_note?: string | null
    status?: string | null
  }
  date_from?: string | null
  date_to?: string | null
  totals: TotalsOut
  days: PatientDailyRowOut[]
}

export const summaryApi = {
  byDate: (date: string, group_by = 'therapist') =>
    api.get<DateSummaryOut>('/api/v1/summary/date', { date, group_by }),
  byPatient: (no: string, params: { from?: string; to?: string } = {}) =>
    api.get<PatientDailySummaryOut>(`/api/v1/summary/patient/${encodeURIComponent(no)}`, params),
  /** 单患者总览：基本信息 + 全部文书（SOAP 文本）+ 统计。 */
  overview: (no: string) =>
    api.get<{
      patient: PatientDailySummaryOut['patient']
      totals: TotalsOut
      records: (PatientDailyRecordOut & { record_no: number; record_date: string })[]
    }>(`/api/v1/summary/patient/${encodeURIComponent(no)}/overview`),
  /** PDF 走浏览器直接下载（带 Cookie 与 Bearer 由后端各自处理） */
  printPatientUrl: (no: string) => `/api/v1/print/patient/${encodeURIComponent(no)}`,
  printDateUrl: (date: string, group_by = 'therapist') =>
    `/api/v1/print/summary/date?date=${date}&group_by=${group_by}`,
  printPatientDailyUrl: (no: string, from?: string, to?: string) => {
    const q = new URLSearchParams()
    if (from) q.set('from', from)
    if (to) q.set('to', to)
    const suffix = q.toString() ? `?${q}` : ''
    return `/api/v1/print/summary/patient/${encodeURIComponent(no)}${suffix}`
  },
}

// --------------------------------------------------------------------------- //
// 审计日志
// --------------------------------------------------------------------------- //
export interface AuditLogOut {
  id: number
  user_id?: number | null
  user_name?: string | null
  employee_no?: string | null
  action: string
  target_type: string
  target_id?: string | null
  before?: unknown
  after?: unknown
  created_at: string
}

export const auditApi = {
  list: (params: PageParams & {
    user_id?: number
    action?: string
    target_type?: string
    target_id?: string
    from?: string
    to?: string
  } = {}) => api.get<Page<AuditLogOut>>('/api/v1/audit-logs', params),
  facets: () =>
    api.get<{ actions: string[]; target_types: string[] }>('/api/v1/audit-logs/facets'),
}
