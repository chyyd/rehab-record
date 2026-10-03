/**
 * 每个页面共用的加载 / 空态 / 错误处理小工具。
 *
 * 后台页面几乎都是"取数据 → 表格"的形状，把这三态收敛到一处，
 * 避免每个页面各写一份 `loading` 与 `catch`，也避免有的页面忘了处理错误。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Button, Empty, Skeleton, Space, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import { ApiError, errorMessage } from '../api/client'

interface AsyncState<T> {
  data: T | null
  loading: boolean
  error: string | null
  reload: () => void
}

/**
 * 取数 hook：统一 loading / error / reload。
 *
 * `deps` 变化会重新取数。用 `useRef` 记录"最新一次请求"，
 * 丢弃过期响应 —— 快速切筛选条件时，先发的请求可能后到，
 * 不过滤就会把旧数据盖在新界面上。
 */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  const requestId = useRef(0)

  const reload = useCallback(() => setTick((t) => t + 1), [])

  useEffect(() => {
    const id = ++requestId.current
    setLoading(true)
    setError(null)
    loader()
      .then((result) => {
        if (id !== requestId.current) return // 已有更新的请求，丢弃本次结果
        setData(result)
      })
      .catch((err) => {
        if (id !== requestId.current) return
        // 403/401 由全局处理，这里只在页面上给出可读原因
        setError(err instanceof ApiError && err.status === 403 ? '无权访问该数据' : errorMessage(err))
      })
      .finally(() => {
        if (id === requestId.current) setLoading(false)
      })
    // loader 每次渲染都是新函数，故意不放进依赖，只跟随 deps
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  return { data, loading, error, reload }
}

export function PageSkeleton() {
  return <Skeleton active paragraph={{ rows: 6 }} />
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <Alert
      type="error"
      showIcon
      message="加载失败"
      description={message}
      action={
        onRetry ? (
          <Button size="small" icon={<ReloadOutlined />} onClick={onRetry}>
            重试
          </Button>
        ) : undefined
      }
    />
  )
}

export function EmptyBox({ text = '暂无数据' }: { text?: string }) {
  return <Empty description={text} image={Empty.PRESENTED_IMAGE_SIMPLE} />
}

/** 页面标题 + 右侧操作区，统一各页的头部形态。 */
export function PageHeader({
  title,
  description,
  extra,
}: {
  title: string
  description?: string
  extra?: React.ReactNode
}) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        marginBottom: 16,
        gap: 16,
        flexWrap: 'wrap',
      }}
    >
      <div>
        <Typography.Title level={4} style={{ margin: 0 }}>
          {title}
        </Typography.Title>
        {description ? (
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            {description}
          </Typography.Text>
        ) : null}
      </div>
      <Space wrap>{extra}</Space>
    </div>
  )
}

/** 非组件环境（如全局错误边界）复用的错误页。 */
export function renderErrorPage(error: unknown) {
  return (
    <div style={{ padding: 24 }}>
      <Alert type="error" showIcon message="页面出错" description={errorMessage(error)} />
      <Space style={{ marginTop: 16 }}>
        <Link to="/">返回总览</Link>
      </Space>
    </div>
  )
}
