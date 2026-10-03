/**
 * 认证状态（React Context + hook）。
 *
 * 令牌策略（与后端 `app/api/v1/auth.py` 对应）：
 * - **access token 只放内存**，刷新页面即丢，靠 Cookie 静默续；
 * - **refresh token 在 httpOnly Cookie 里**，JS 永远拿不到，因此 XSS 偷不走长期凭证。
 *
 * 页面加载时会调用一次 `bootstrap()`：用 Cookie 换 access token。
 * 这一步失败（没有 Cookie / 已吊销）就当作未登录，不弹错误提示 —— 未登录是正常状态。
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { authApi, type UserOut } from '../api/endpoints'
import {
  ApiError,
  setAccessToken,
  setUnauthorizedHandler,
} from '../api/client'

interface AuthState {
  user: UserOut | null
  /** 首次校验 Cookie 是否完成（未完成时要显示全屏 loading，避免闪一下登录页） */
  ready: boolean
  login: (employeeNo: string, password: string) => Promise<UserOut>
  logout: () => Promise<void>
  refreshUser: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserOut | null>(null)
  const [ready, setReady] = useState(false)
  const bootstrapped = useRef(false)

  // 刷新也救不回来时：清空内存状态，路由守卫会把用户送回登录页
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setAccessToken(null)
      setUser(null)
    })
    return () => setUnauthorizedHandler(null)
  }, [])

  useEffect(() => {
    if (bootstrapped.current) return
    bootstrapped.current = true
    void (async () => {
      try {
        // 用 httpOnly Cookie 换一个 access token（共享的 axios 实例会自动带上 Cookie）
        const resp = await fetch(`${import.meta.env.VITE_API_BASE ?? ''}/api/v1/auth/refresh`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: '{}',
        })
        if (!resp.ok) throw new Error('no session')
        const data = (await resp.json()) as { access_token: string }
        setAccessToken(data.access_token)
        const me = await authApi.me()
        setUser(me)
      } catch (error) {
        // 未登录是正常状态，不提示；但要确保内存里没有残留 token
        setAccessToken(null)
        if (!(error instanceof ApiError) && import.meta.env.DEV) {
          console.debug('[auth] 静默续期失败，按未登录处理', error)
        }
      } finally {
        setReady(true)
      }
    })()
  }, [])

  const login = useCallback(async (employeeNo: string, password: string) => {
    const result = await authApi.login(employeeNo, password)
    setAccessToken(result.access_token)
    setUser(result.user)
    return result.user
  }, [])

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } catch {
      // 后端不可达也要让本地退出，否则用户被卡在页面里
    } finally {
      setAccessToken(null)
      setUser(null)
    }
  }, [])

  const refreshUser = useCallback(async () => {
    const me = await authApi.me()
    setUser(me)
  }, [])

  const value = useMemo<AuthState>(
    () => ({ user, ready, login, logout, refreshUser }),
    [user, ready, login, logout, refreshUser],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth 必须在 AuthProvider 内使用')
  return ctx
}
