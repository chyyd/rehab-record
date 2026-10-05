/** 路由表与路由守卫。 */
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { Result, Spin } from 'antd'
import { useAuth } from './auth/AuthProvider'
import { AppLayout } from './layouts/AppLayout'
import { LoginPage } from './pages/LoginPage'
import { DashboardPage } from './pages/DashboardPage'
import { PatientsPage } from './pages/PatientsPage'
import { UsersPage } from './pages/UsersPage'
import { RecordsPage } from './pages/RecordsPage'
import { SummaryPage } from './pages/SummaryPage'
import { AuditLogsPage } from './pages/AuditLogsPage'

function FullScreenLoading() {
  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}>
      <Spin size="large" description="正在校验登录状态…">
        <div style={{ width: 160, height: 40 }} />
      </Spin>
    </div>
  )
}

/** 需要登录；未登录时记下来路，登录后跳回去。 */
function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, ready } = useAuth()
  const location = useLocation()

  // 首次 Cookie 校验完成前不能判断，否则会闪一下登录页
  if (!ready) return <FullScreenLoading />
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <>{children}</>
}

/** 仅管理员。治疗师直接访问管理页时应看到明确提示，而不是空白页。 */
function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  if (user?.role !== 'admin') {
    return (
      <Result
        status="403"
        title="无权访问"
        subTitle="该功能仅管理员可用。如需权限请联系科室管理员。"
      />
    )
  }
  return <>{children}</>
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="patients" element={<PatientsPage />} />
        <Route path="records" element={<RecordsPage />} />
        <Route path="summary" element={<SummaryPage />} />
        <Route
          path="users"
          element={
            <RequireAdmin>
              <UsersPage />
            </RequireAdmin>
          }
        />
        {/* 2026-10-05：删除 /dict、/option-sets、/response-defs、/templates 四条路由。
            记录内容改由 `templates/*.json` **文件**驱动（用户要求「使用 json 格式保存模板，
            不进数据库，以便以后我手动修改」），后台不再需要维护字典；
            这四组后端接口也整体删除，留着路由只会点进去 404。 */}
        <Route
          path="audit-logs"
          element={
            <RequireAdmin>
              <AuditLogsPage />
            </RequireAdmin>
          }
        />
      </Route>
      <Route
        path="*"
        element={<Result status="404" title="页面不存在" subTitle="请从左侧菜单进入需要的功能。" />}
      />
    </Routes>
  )
}
