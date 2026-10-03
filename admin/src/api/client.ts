/**
 * HTTP 客户端。
 *
 * 设计要点（与后端约定严格对应）：
 *
 * 1. **统一错误体**：后端所有错误都是 `{"code","message","details"}`。
 *    这里把它转成 `ApiError`，调用方只看 `code` 做分支、`message` 做提示。
 *
 * 2. **access token 只存内存**（见 `authStore`），**绝不落 localStorage**：
 *    refresh token 在 httpOnly Cookie 里、JS 读不到；access token 若再放进
 *    localStorage，等于把 XSS 的收益又还回去一部分。放内存的代价是刷新页面即丢，
 *    但页面加载时会用 Cookie 静默换一次新的，用户无感。
 *
 * 3. **401 自动刷新一次并重放原请求**，同时用一个"刷新中"的 Promise 收敛并发：
 *    页面首屏往往同时发好几个请求，若各刷各的，会因为 refresh 轮换而互相作废
 *    （后端的 refresh 是一次性轮换，旧 token 用完即吊销）。
 */
import axios, { AxiosError, type AxiosRequestConfig, type InternalAxiosRequestConfig } from 'axios'

export interface ApiErrorBody {
  code: string
  message: string
  details?: Record<string, unknown>
}

export class ApiError extends Error {
  code: string
  status: number
  details: Record<string, unknown>

  constructor(status: number, body: ApiErrorBody) {
    super(body.message || body.code)
    this.name = 'ApiError'
    this.status = status
    this.code = body.code || 'UNKNOWN'
    this.details = body.details ?? {}
  }

  /** 附带字段级错误（后端校验失败时可能给出 `details.fields`）。 */
  get fieldErrors(): Record<string, string> {
    const fields = this.details?.fields
    if (fields && typeof fields === 'object') return fields as Record<string, string>
    return {}
  }
}

/** 后端基地址。开发期走 Vite 代理（同源 `/api`），生产由 Nginx 反代。 */
const BASE_URL = import.meta.env.VITE_API_BASE ?? ''

export const http = axios.create({
  baseURL: BASE_URL,
  timeout: 20000,
  // 必须带上 Cookie，否则 httpOnly 的 refresh token 不会随请求发送
  withCredentials: true,
})

// --------------------------------------------------------------------------- //
// 内存中的 access token
// --------------------------------------------------------------------------- //
let accessToken: string | null = null
let onUnauthorized: (() => void) | null = null

export function setAccessToken(token: string | null): void {
  accessToken = token
}

export function getAccessToken(): string | null {
  return accessToken
}

/** 注册"彻底登出"回调（刷新也救不回来时由 authStore 清理状态并跳登录页）。 */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler
}

http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  if (accessToken) {
    config.headers.set('Authorization', `Bearer ${accessToken}`)
  }
  return config
})

// --------------------------------------------------------------------------- //
// 401 → 静默刷新 → 重放
// --------------------------------------------------------------------------- //
interface RetriableConfig extends InternalAxiosRequestConfig {
  _retried?: boolean
}

let refreshPromise: Promise<string> | null = null

async function refreshAccessToken(): Promise<string> {
  // 共用一个刷新请求：并发 401 时不能各自去刷新（轮换会让先到的那个作废）
  if (!refreshPromise) {
    refreshPromise = axios
      .post<{ access_token: string }>(
        `${BASE_URL}/api/v1/auth/refresh`,
        {},
        { withCredentials: true, timeout: 20000 },
      )
      .then((resp) => {
        const token = resp.data.access_token
        accessToken = token
        return token
      })
      .finally(() => {
        refreshPromise = null
      })
  }
  return refreshPromise
}

http.interceptors.response.use(
  (resp) => resp,
  async (error: AxiosError<ApiErrorBody>) => {
    const status = error.response?.status ?? 0
    const config = error.config as RetriableConfig | undefined
    const url = config?.url ?? ''

    // 认证类接口自身返回 401/403 时不重试，否则会死循环
    const isAuthCall = url.includes('/auth/login') || url.includes('/auth/refresh')

    if (status === 401 && config && !config._retried && !isAuthCall) {
      config._retried = true
      try {
        const token = await refreshAccessToken()
        config.headers.set('Authorization', `Bearer ${token}`)
        return http.request(config)
      } catch {
        accessToken = null
        onUnauthorized?.()
        return Promise.reject(toApiError(error))
      }
    }

    if (status === 401 && !isAuthCall) {
      onUnauthorized?.()
    }
    return Promise.reject(toApiError(error))
  },
)

function toApiError(error: AxiosError<ApiErrorBody>): ApiError {
  const status = error.response?.status ?? 0
  const body = error.response?.data
  if (body && typeof body === 'object' && 'code' in body) {
    return new ApiError(status, body)
  }
  // 网络错误 / 超时 / 非 JSON 响应
  const message =
    status === 0
      ? `无法连接到服务端（${error.message}）`
      : `请求失败（HTTP ${status}）`
  return new ApiError(status, { code: 'NETWORK_ERROR', message })
}

// --------------------------------------------------------------------------- //
// 便捷方法
// --------------------------------------------------------------------------- //

/**
 * 查询参数类型。
 *
 * 用 `object` 而不是 `Record<string, unknown>`：调用方传的是具名接口
 * （如 `PageParams & { role?: string }`），它**没有索引签名**，
 * 无法赋给 `Record<string, unknown>`，会报 TS2345。
 * `object` 足够宽松且仍能挡住原始值。
 */
export type QueryParams = object

export const api = {
  get: <T>(url: string, params?: QueryParams, config?: AxiosRequestConfig) =>
    http.get<T>(url, { params, ...config }).then((r) => r.data),
  post: <T>(url: string, data?: unknown, config?: AxiosRequestConfig) =>
    http.post<T>(url, data, config).then((r) => r.data),
  put: <T>(url: string, data?: unknown, config?: AxiosRequestConfig) =>
    http.put<T>(url, data, config).then((r) => r.data),
  delete: <T>(url: string, config?: AxiosRequestConfig) =>
    http.delete<T>(url, config).then((r) => r.data),
}

/** 把后端错误转成一句可直接展示的中文提示。 */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return '未知错误'
}
