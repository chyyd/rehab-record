/**
 * 总览页（M12 健康与运维面板的一部分）。
 *
 * 数据来源全部是既有接口拼出来的 —— 后端没有专门的统计接口，
 * 因此这里刻意只做"少量关键计数"，不做重型聚合（避免开页面就打一堆全表扫描）。
 */
import { Card, Col, Descriptions, Row, Statistic, Tag, Typography } from 'antd'
import dayjs from 'dayjs'
import { useAuth } from '../auth/AuthProvider'
import { auditApi, healthApi, patientsApi, recordsApi, usersApi, summaryApi } from '../api/endpoints'
import { ErrorBox, PageHeader, PageSkeleton, useAsync } from '../components/Feedback'

interface Overview {
  activePatients: number
  inpatients: number
  therapists: number
  todayRecords: number
  todayDuration: number
  schemaVersion: unknown
  healthStatus: string
  recentAudits: { id: number; action: string; target_type: string; user_name?: string | null; created_at: string }[]
}

const today = () => dayjs().format('YYYY-MM-DD')

export function DashboardPage() {
  const { user } = useAuth()

  const { data, loading, error, reload } = useAsync<Overview>(async () => {
    const date = today()
    // 并发取数；任何一项失败不应该让整页白屏，因此用 allSettled 再逐项兜底
    const [patients, users, records, summary, health, audits] = await Promise.allSettled([
      patientsApi.list({ page: 1, page_size: 1 }),
      usersApi.list({ page: 1, page_size: 200 }),
      recordsApi.list({ page: 1, page_size: 1, from: date, to: date }),
      summaryApi.byDate(date),
      healthApi.check(),
      auditApi.list({ page: 1, page_size: 8 }),
    ])

    const pick = <T,>(r: PromiseSettledResult<T>, fallback: T): T =>
      r.status === 'fulfilled' ? r.value : fallback

    const patientPage = pick(patients, { items: [], total: 0, page: 1, page_size: 1 })
    const userPage = pick(users, { items: [], total: 0, page: 1, page_size: 200 })
    const recordPage = pick(records, { items: [], total: 0, page: 1, page_size: 1 })
    const summaryData = pick(summary, null) as { totals?: { total_duration_min?: number } } | null
    const healthData = pick(health, null) as Record<string, unknown> | null
    const auditPage = pick(audits, { items: [], total: 0, page: 1, page_size: 8 })

    return {
      activePatients: patientPage.total,
      inpatients: patientPage.items.filter((p) => p.status === 'in_hospital').length,
      therapists: userPage.items.filter((u) => u.role === 'therapist' && u.status === 'active').length,
      todayRecords: recordPage.total,
      todayDuration: summaryData?.totals?.total_duration_min ?? 0,
      schemaVersion: healthData?.schema_version ?? '—',
      healthStatus: String(healthData?.status ?? 'unknown'),
      recentAudits: auditPage.items,
    }
  }, [])

  if (loading) return <PageSkeleton />
  if (error) return <ErrorBox message={error} onRetry={reload} />
  if (!data) return null

  return (
    <>
      <PageHeader
        title={`${dayjs().format('YYYY年M月D日')} 总览`}
        description={`当前登录：${user?.name}（${user?.role === 'admin' ? '管理员' : '治疗师'}）`}
      />

      <Row gutter={[16, 16]}>
        <Col xs={12} md={6}>
          <Card>
            <Statistic title="在院患者" value={data.activePatients} suffix="人" />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic title="今日治疗人次" value={data.todayRecords} suffix="次" />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic title="今日总时长" value={data.todayDuration} suffix="分钟" />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic title="在职治疗师" value={data.therapists} suffix="人" />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={10}>
          <Card title="系统状态" size="small">
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="服务状态">
                <Tag color={data.healthStatus === 'ok' || data.healthStatus === 'healthy' ? 'green' : 'orange'}>
                  {data.healthStatus}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="数据库迁移版本">{String(data.schemaVersion)}</Descriptions.Item>
              <Descriptions.Item label="排期粒度">上午 / 下午（半日）</Descriptions.Item>
              <Descriptions.Item label="作息">06:00–11:30 ／ 13:00–17:30</Descriptions.Item>
            </Descriptions>
            <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 12, marginBottom: 0 }}>
              数据每进入页面刷新一次。需要完整的自检明细请访问接口 <code>/api/v1/health</code>。
            </Typography.Paragraph>
          </Card>
        </Col>

        <Col xs={24} lg={14}>
          <Card title="最近操作" size="small">
            {data.recentAudits.length === 0 ? (
              <Typography.Text type="secondary">暂无操作记录。</Typography.Text>
            ) : (
              <Descriptions column={1} size="small">
                {data.recentAudits.map((log) => (
                  <Descriptions.Item
                    key={log.id}
                    label={dayjs(log.created_at).format('MM-DD HH:mm')}
                  >
                    {log.user_name ?? '系统'} · {log.action} · {log.target_type}
                  </Descriptions.Item>
                ))}
              </Descriptions>
            )}
            {user?.role !== 'admin' ? (
              <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }}>
                完整审计日志仅管理员可查。
              </Typography.Paragraph>
            ) : null}
          </Card>
        </Col>
      </Row>
    </>
  )
}
