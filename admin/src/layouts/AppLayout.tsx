/**
 * 应用外壳：侧边菜单 + 顶栏 + 内容区。
 *
 * 菜单由 `routes.tsx` 的同一份清单生成 —— 菜单与路由**同源**，
 * 避免出现"菜单里有但点进去 404"这类不一致（新增页面只改一处）。
 */
import { useMemo, useState } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Avatar, Dropdown, Layout, Menu, Typography } from 'antd'
import {
  AppstoreOutlined,
  AuditOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  FormOutlined,
  LogoutOutlined,
  PrinterOutlined,
  TeamOutlined,
  UserOutlined,
  KeyOutlined,
} from '@ant-design/icons'
import { useAuth } from '../auth/AuthProvider'
import { ChangePasswordModal } from '../pages/ChangePasswordModal'
import { notify } from '../components/notify'

const { Header, Sider, Content } = Layout

export interface NavItem {
  key: string
  label: string
  icon?: React.ReactNode
  adminOnly?: boolean
}

/** 侧边菜单项。key 即路由路径，与 `routes.tsx` 一一对应。
 *
 * 2026-10-05：移除「全局排期」与「请假管理」—— 排期功能整体下线，
 * 本系统只记录"已经做了什么"，不做排班。
 */
export const NAV_ITEMS: NavItem[] = [
  { key: '/', label: '总览', icon: <DashboardOutlined /> },
  { key: '/patients', label: '患者管理', icon: <TeamOutlined /> },
  { key: '/records', label: '治疗记录', icon: <FileTextOutlined /> },
  { key: '/summary', label: '汇总与打印', icon: <PrinterOutlined /> },
  { key: '/users', label: '用户管理', icon: <UserOutlined />, adminOnly: true },
  { key: '/dict', label: '字典管理', icon: <DatabaseOutlined />, adminOnly: true },
  { key: '/option-sets', label: '选项集管理', icon: <AppstoreOutlined />, adminOnly: true },
  { key: '/response-defs', label: '患者反应定义', icon: <FormOutlined />, adminOnly: true },
  { key: '/templates', label: '科室模板', icon: <FormOutlined />, adminOnly: true },
  { key: '/audit-logs', label: '审计日志', icon: <AuditOutlined />, adminOnly: true },
]

export function AppLayout() {
  const { user, logout } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const [collapsed, setCollapsed] = useState(false)
  const [pwdOpen, setPwdOpen] = useState(false)

  const isAdmin = user?.role === 'admin'

  const menuItems = useMemo(
    () =>
      NAV_ITEMS.filter((item) => !item.adminOnly || isAdmin).map((item) => ({
        key: item.key,
        icon: item.icon,
        label: <Link to={item.key}>{item.label}</Link>,
      })),
    [isAdmin],
  )

  // 选中项取"最长匹配"的前缀，保证 /records/123 时"治疗记录"仍高亮
  const selectedKey = useMemo(() => {
    const visible = NAV_ITEMS.filter((item) => !item.adminOnly || isAdmin)
    const matches = visible
      .filter((item) => (item.key === '/' ? location.pathname === '/' : location.pathname.startsWith(item.key)))
      .sort((a, b) => b.key.length - a.key.length)
    return matches[0]?.key ?? '/'
  }, [location.pathname, isAdmin])

  const handleLogout = () => {
    notify.confirm({
      title: '确认退出登录？',
      content: '退出后会同时吊销本机的登录凭证。',
      okText: '退出',
      cancelText: '取消',
      onOk: async () => {
        await logout()
        notify.success('已退出登录')
        navigate('/login', { replace: true })
      },
    })
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed} theme="dark" width={208}>
        <div
          style={{
            height: 56,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontSize: collapsed ? 13 : 15,
            fontWeight: 600,
            letterSpacing: 1,
          }}
        >
          {collapsed ? '康复' : '康复科管理后台'}
        </div>
        <Menu theme="dark" mode="inline" selectedKeys={[selectedKey]} items={menuItems} />
      </Sider>

      <Layout>
        <Header
          style={{
            background: '#fff',
            padding: '0 20px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid #f0f0f0',
          }}
        >
          <Typography.Text type="secondary">
            {user?.role === 'admin' ? '管理员视图' : '治疗师视图'}
          </Typography.Text>
          <Dropdown
            menu={{
              items: [
                { key: 'pwd', icon: <KeyOutlined />, label: '修改密码', onClick: () => setPwdOpen(true) },
                { type: 'divider' },
                { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: handleLogout },
              ],
            }}
          >
            <div style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8 }}>
              <Avatar size="small" icon={<UserOutlined />} />
              <span>
                {user?.name}
                <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                  {user?.employee_no}
                </Typography.Text>
              </span>
            </div>
          </Dropdown>
        </Header>

        <Content style={{ margin: 16, padding: 20, background: '#fff', borderRadius: 8 }}>
          <Outlet />
        </Content>
      </Layout>

      <ChangePasswordModal open={pwdOpen} onClose={() => setPwdOpen(false)} />
    </Layout>
  )
}
