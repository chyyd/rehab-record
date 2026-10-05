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
  /** 已退化：2026-10-05 临时指派删除后恒为 'assigned'，仅为与后端响应字段对齐而保留 */
  visibility_state?: string
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
}

// --------------------------------------------------------------------------- //
// 字典
// --------------------------------------------------------------------------- //
export interface ParamDefOut {
  id: number
  sub_item_id: number
  param_key: string
  param_name: string
  input_type: 'select' | 'multi_select' | 'number' | 'text'
  options: string[]
  default_value?: string | null
  required: number
  unit?: string | null
  sort: number
}

export interface SubItemOut {
  id: number
  main_item_id: number
  name: string
  code: string
  alias?: string | null
  sort: number
  status: string
  params?: ParamDefOut[]
}

export interface MainItemOut {
  id: number
  name: string
  code: string
  alias?: string | null
  sort: number
  status: string
  sub_items?: SubItemOut[]
}

export interface DeleteResultOut {
  id: number
  deleted: boolean
  soft_deleted?: boolean
  reason?: string | null
  name?: string | null
  code?: string | null
  status?: string | null
}

export const dictApi = {
  tree: () => api.get<MainItemOut[]>('/api/v1/dict/tree'),
  /** 含停用项，供管理端展示完整字典 */
  mainItems: () => api.get<MainItemOut[]>('/api/v1/dict/main-items'),
  subItems: (main_item_id?: number) =>
    api.get<SubItemOut[]>('/api/v1/dict/sub-items', main_item_id ? { main_item_id } : undefined),
  params: (sub_item_id: number) =>
    api.get<ParamDefOut[]>(`/api/v1/dict/sub-items/${sub_item_id}/params`),

  createMainItem: (payload: Partial<MainItemOut>) =>
    api.post<MainItemOut>('/api/v1/dict/main-items', payload),
  updateMainItem: (id: number, payload: Partial<MainItemOut>) =>
    api.put<MainItemOut>(`/api/v1/dict/main-items/${id}`, payload),
  deleteMainItem: (id: number) => api.delete<DeleteResultOut>(`/api/v1/dict/main-items/${id}`),

  createSubItem: (payload: Partial<SubItemOut>) =>
    api.post<SubItemOut>('/api/v1/dict/sub-items', payload),
  updateSubItem: (id: number, payload: Partial<SubItemOut>) =>
    api.put<SubItemOut>(`/api/v1/dict/sub-items/${id}`, payload),
  deleteSubItem: (id: number) => api.delete<DeleteResultOut>(`/api/v1/dict/sub-items/${id}`),

  createParam: (sub_item_id: number, payload: Record<string, unknown>) =>
    api.post<ParamDefOut>(`/api/v1/dict/sub-items/${sub_item_id}/params`, payload),
  updateParam: (id: number, payload: Record<string, unknown>) =>
    api.put<ParamDefOut>(`/api/v1/dict/params/${id}`, payload),
  deleteParam: (id: number) => api.delete<DeleteResultOut>(`/api/v1/dict/params/${id}`),
}

// --------------------------------------------------------------------------- //
// 选项集
// --------------------------------------------------------------------------- //
export interface OptionItemOut {
  id?: number
  value: string
  label: string
  is_default: number
  sort: number
}

export interface OptionSetOut {
  id: number
  scope: 'global' | 'dept' | 'personal'
  owner_user_id?: number | null
  dept_tag?: string | null
  code: string
  name: string
  alias?: string | null
  items: OptionItemOut[]
}

export const optionSetsApi = {
  all: (scope?: string) => api.get<OptionSetOut[]>('/api/v1/admin/option-sets', scope ? { scope } : undefined),
  upsert: (payload: {
    code: string
    name: string
    values: string[]
    dept_tag?: string | null
    default_values?: string[]
  }) => api.put<OptionSetOut>('/api/v1/admin/option-sets', payload),
  remove: (id: number) => api.delete<void>(`/api/v1/admin/option-sets/${id}`),
  resolve: (code: string) =>
    api.get<{ code: string; source: string; options: { value: string; label: string }[]; defaults: string[] }>(
      '/api/v1/option-sets/resolve',
      { code },
    ),
}

// --------------------------------------------------------------------------- //
// 患者反应定义（只读）
// --------------------------------------------------------------------------- //
export interface ResponseDefOut {
  id: number
  main_item_id?: number | null
  code: string
  label: string
  value_type: 'tag' | 'number' | 'select' | 'text'
  value_key?: string | null
  value_unit?: string | null
  value_min?: number | null
  value_max?: number | null
  options: string[]
}

export const responseDefsApi = {
  list: (main_item_id?: number) =>
    api.get<ResponseDefOut[]>('/api/v1/response-defs', main_item_id ? { main_item_id } : undefined),
}

// --------------------------------------------------------------------------- //
// 模板
// --------------------------------------------------------------------------- //
export interface TemplateItemOut {
  id?: number
  template_id?: number
  sub_item_id: number
  params: Record<string, unknown>
  sort: number
}

export interface TemplateOut {
  id: number
  scope: 'dept' | 'personal'
  owner_user_id?: number | null
  main_item_id: number
  code?: string | null
  name: string
  sort: number
  status: string
  items: TemplateItemOut[]
}

export const templatesApi = {
  list: (main_item_id?: number) =>
    api.get<TemplateOut[]>('/api/v1/templates', main_item_id ? { main_item_id } : undefined),
  get: (id: number) => api.get<TemplateOut>(`/api/v1/templates/${id}`),
  create: (payload: {
    name: string
    scope: string
    main_item_id: number
    items: { sub_item_id: number; params: Record<string, unknown> }[]
    sort?: number
  }) => api.post<TemplateOut>('/api/v1/templates', payload),
  update: (id: number, payload: Record<string, unknown>) =>
    api.put<TemplateOut>(`/api/v1/templates/${id}`, payload),
  remove: (id: number) => api.delete<void>(`/api/v1/templates/${id}`),
  apply: (id: number) => api.post<Record<string, unknown>>(`/api/v1/templates/${id}/apply`),
}

// --------------------------------------------------------------------------- //
// 治疗记录
// --------------------------------------------------------------------------- //
export interface RecordListItemOut {
  id: number
  patient_no: string
  patient_name?: string | null
  therapist_id: number
  therapist_name?: string | null
  record_date: string
  session_period?: string | null
  seq_no?: number | null
  status: 'draft' | 'submitted' | 'locked'
  edit_count: number
  item_count: number
}

export interface RecordItemOut {
  id: number
  main_item_id: number
  sub_item_id: number
  sub_item_name_snapshot?: string | null
  params: Record<string, unknown>
  params_snapshot?: { param_key: string; param_name: string; value: unknown }[] | null
}

export interface RecordOut extends RecordListItemOut {
  is_temporary: number
  duration_min?: number | null
  patient_response?: Record<string, unknown> | null
  note?: string | null
  locked_at?: string | null
  submitted_at?: string | null
  revision: number
  items: RecordItemOut[]
}

export const recordsApi = {
  list: (params: PageParams & {
    patient_no?: string
    therapist_id?: number
    status?: string
    from?: string
    to?: string
    scope?: string
  } = {}) => api.get<Page<RecordListItemOut>>('/api/v1/records', params),
  get: (id: number) => api.get<RecordOut>(`/api/v1/records/${id}`),
  lock: (id: number) => api.post<RecordOut>(`/api/v1/records/${id}/lock`),
  timeline: (params: PageParams & { from?: string; to?: string; scope?: string } = {}) =>
    api.get<Page<RecordListItemOut & { main_item_names: string[] }>>('/api/v1/timeline', params),
}

// --------------------------------------------------------------------------- //
// 汇总与打印
// --------------------------------------------------------------------------- //
export interface TotalsOut {
  record_count: number
  item_count: number
  total_duration_min: number
  patient_count: number
  main_item_counts: Record<string, number>
  sub_item_counts: Record<string, number>
  therapist_counts: Record<string, number>
}

export const summaryApi = {
  byDate: (date: string, group_by = 'therapist') =>
    api.get<{ date: string; group_by: string; totals: TotalsOut; groups: unknown[] }>(
      '/api/v1/summary/date',
      { date, group_by },
    ),
  byPatient: (no: string, params: { from?: string; to?: string } = {}) =>
    api.get<Record<string, unknown>>(`/api/v1/summary/patient/${encodeURIComponent(no)}`, params),
  overview: (no: string) =>
    api.get<{ patient: PatientOut; totals: TotalsOut; records: unknown[] }>(
      `/api/v1/summary/patient/${encodeURIComponent(no)}/overview`,
    ),
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