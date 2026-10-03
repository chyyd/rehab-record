import { App as AntApp, ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import { useEffect } from 'react'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from './auth/AuthProvider'
import { AppRoutes } from './routes'
import { registerNotify } from './components/notify'

dayjs.locale('zh-cn')

/**
 * 把 antd `App` 提供的 message/modal/notification 实例注册给 `notify`。
 *
 * 必须放在 `<AntApp>` **内部**才能拿到上下文（主题、locale）。
 * 直接调用静态 `message.success()` 会打印
 * "Static function can not consume context like dynamic theme" 警告，
 * 且在动态主题下样式不正确。
 */
function NotifyBridge() {
  const { message, modal, notification } = AntApp.useApp()
  useEffect(() => {
    registerNotify({ message, modal, notification })
  }, [message, modal, notification])
  return null
}

export default function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: '#1677ff',
          borderRadius: 6,
          // 科室里多为 19–24 寸显示器，字号略放大便于长时间阅读
          fontSize: 14,
        },
        components: {
          // 表格是后台使用最密集的组件，行距收紧以便一屏看更多
          Table: { cellPaddingBlock: 8 },
        },
      }}
    >
      <AntApp>
        <NotifyBridge />
        <BrowserRouter>
          <AuthProvider>
            <AppRoutes />
          </AuthProvider>
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  )
}
