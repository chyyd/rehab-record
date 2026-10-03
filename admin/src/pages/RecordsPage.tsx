/** 治疗记录查阅（M9）：列表筛选 + 明细（含快照）+ 锁定。 */
import { useState } from 'react'
import {
  Button,
  DatePicker,
  Descriptions,
  Drawer,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import type { Dayjs } from 'dayjs'
import {
  recordsApi,
  usersApi,
  type RecordListItemOut,
  type RecordOut,
} from '../api/endpoints'
import { errorMessage } from '../api/client'
import { ErrorBox, PageHeader, PageSkeleton, useAsync } from '../components/Feedback'
import { useAuth } from '../auth/AuthProvider'
import { notify } from '../components/notify'

const STATUS_LABEL: Record<string, { text: string; color: string }> = {
  draft: { text: '草稿', color: 'default' },
  submitted: { text: '已提交', color: 'blue' },
  locked: { text: '已锁定', color: 'green' },
}

const PERIOD_LABEL: Record<string, string> = { am: '上午', pm: '下午' }

export function RecordsPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState<string | undefined>()
  const [therapistId, setTherapistId] = useState<number | undefined>()
  // patientNo 目前只用于筛选传参；保留 state 供后续加输入框
  const [patientNo] = useState<string | undefined>()
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null)
  const [detailId, setDetailId] = useState<number | null>(null)

  const therapists = useAsync(async () => {
    const r = await usersApi.list({ page: 1, page_size: 200, role: 'therapist' })
    return r.items
  }, [])

  const { data, loading, error, reload } = useAsync(
    () =>
      recordsApi.list({
        page,
        page_size: 20,
        status,
        therapist_id: therapistId,
        patient_no: patientNo || undefined,
        from: range?.[0]?.format('YYYY-MM-DD'),
        to: range?.[1]?.format('YYYY-MM-DD'),
      }),
    [page, status, therapistId, patientNo, range?.[0]?.valueOf(), range?.[1]?.valueOf()],
  )

  const lock = async (id: number) => {
    try {
      await recordsApi.lock(id)
      notify.success('已锁定')
      reload()
    } catch (err) {
      notify.error(errorMessage(err))
    }
  }

  return (
    <>
      <PageHeader
        title="治疗记录"
        description="查阅治疗记录。已提交的记录由触发器自动留痕，锁定后治疗师不能再修改。"
        extra={
          <>
            <Select
              allowClear
              placeholder="状态"
              style={{ width: 120 }}
              value={status}
              onChange={(v) => {
                setPage(1)
                setStatus(v)
              }}
              options={[
                { value: 'draft', label: '草稿' },
                { value: 'submitted', label: '已提交' },
                { value: 'locked', label: '已锁定' },
              ]}
            />
            <Select
              allowClear
              placeholder="治疗师"
              style={{ width: 150 }}
              value={therapistId}
              onChange={(v) => {
                setPage(1)
                setTherapistId(v)
              }}
              showSearch
              optionFilterProp="label"
              options={(therapists.data ?? []).map((t) => ({
                value: t.id,
                label: `${t.name}（${t.employee_no}）`,
              }))}
            />
            <DatePicker.RangePicker
              value={range}
              onChange={(v) => setRange(v as [Dayjs, Dayjs] | null)}
              placeholder={['开始', '结束']}
            />
            <Button icon={<ReloadOutlined />} onClick={reload}>
              刷新
            </Button>
          </>
        }
      />

      {error ? (
        <ErrorBox message={error} onRetry={reload} />
      ) : loading ? (
        <PageSkeleton />
      ) : (
        <Table<RecordListItemOut>
          rowKey="id"
          size="middle"
          dataSource={data?.items ?? []}
          pagination={{
            current: page,
            pageSize: 20,
            total: data?.total ?? 0,
            showSizeChanger: false,
            onChange: setPage,
            showTotal: (t) => `共 ${t} 条记录`,
          }}
          columns={[
            { title: '日期', dataIndex: 'record_date', width: 110 },
            {
              title: '半日',
              dataIndex: 'session_period',
              width: 70,
              render: (v: string | null) => (v ? PERIOD_LABEL[v] ?? v : '—'),
            },
            {
              title: '患者',
              key: 'patient',
              width: 160,
              render: (_: unknown, r: RecordListItemOut) => (
                <span>
                  {r.patient_name}
                  <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 6 }}>
                    {r.patient_no}
                  </Typography.Text>
                </span>
              ),
            },
            { title: '治疗师', dataIndex: 'therapist_name', width: 100 },
            {
              title: '序次',
              dataIndex: 'seq_no',
              width: 70,
              render: (v: number | null) => (v ? `第 ${v} 次` : <Typography.Text type="secondary">草稿</Typography.Text>),
            },
            {
              title: '状态',
              dataIndex: 'status',
              width: 90,
              render: (v: string) => {
                const item = STATUS_LABEL[v] ?? { text: v, color: 'default' }
                return <Tag color={item.color}>{item.text}</Tag>
              },
            },
            {
              title: '修改次数',
              dataIndex: 'edit_count',
              width: 90,
              render: (v: number) =>
                v > 0 ? <Typography.Text type="warning">{v} 次</Typography.Text> : '—',
            },
            {
              title: '操作',
              key: 'a',
              width: 130,
              render: (_: unknown, r: RecordListItemOut) => (
                <Space size="small">
                  <Button size="small" type="link" onClick={() => setDetailId(r.id)}>
                    明细
                  </Button>
                  {isAdmin && r.status === 'submitted' ? (
                    <Button size="small" type="link" onClick={() => lock(r.id)}>
                      锁定
                    </Button>
                  ) : null}
                </Space>
              ),
            },
          ]}
        />
      )}

      <RecordDetailDrawer recordId={detailId} onClose={() => setDetailId(null)} />
    </>
  )
}

function RecordDetailDrawer({
  recordId,
  onClose,
}: {
  recordId: number | null
  onClose: () => void
}) {
  const detail = useAsync(
    () => (recordId ? recordsApi.get(recordId) : Promise.resolve(null as RecordOut | null)),
    [recordId],
  )
  const record = detail.data

  return (
    <Drawer
      title={record ? `治疗记录 #${record.id}` : '治疗记录明细'}
      size={720}
      open={recordId !== null}
      onClose={onClose}
      destroyOnHidden
    >
      {detail.loading ? (
        <PageSkeleton />
      ) : detail.error ? (
        <ErrorBox message={detail.error} onRetry={detail.reload} />
      ) : record ? (
        <>
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label="患者">
              {record.patient_name}（{record.patient_no}）
            </Descriptions.Item>
            <Descriptions.Item label="治疗师">{record.therapist_name}</Descriptions.Item>
            <Descriptions.Item label="日期">{record.record_date}</Descriptions.Item>
            <Descriptions.Item label="半日">
              {record.session_period ? PERIOD_LABEL[record.session_period] : '—'}
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              {STATUS_LABEL[record.status]?.text ?? record.status}
            </Descriptions.Item>
            <Descriptions.Item label="序次">
              {record.seq_no ? `第 ${record.seq_no} 次` : '草稿（未占序次）'}
            </Descriptions.Item>
            <Descriptions.Item label="时长">
              {record.duration_min != null ? `${record.duration_min} 分钟` : '—'}
            </Descriptions.Item>
            <Descriptions.Item label="修改次数">{record.edit_count}</Descriptions.Item>
            <Descriptions.Item label="是否临时治疗" span={2}>
              {record.is_temporary ? (
                <Tag color="orange">是（记录人不是患者归属治疗师）</Tag>
              ) : (
                '否'
              )}
            </Descriptions.Item>
            <Descriptions.Item label="备注" span={2}>
              {record.note || '—'}
            </Descriptions.Item>
            <Descriptions.Item label="患者反应" span={2}>
              {record.patient_response ? JSON.stringify(record.patient_response) : '—'}
            </Descriptions.Item>
          </Descriptions>

          <Typography.Title level={5} style={{ marginTop: 20 }}>
            治疗明细（含当时的快照）
          </Typography.Title>
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={record.items}
            columns={[
              {
                title: '子项目',
                dataIndex: 'sub_item_name_snapshot',
                render: (v: string | null) => v || '—',
              },
              {
                title: '参数',
                dataIndex: 'params',
                render: (params: Record<string, unknown>) => {
                  const entries = Object.entries(params ?? {})
                  if (entries.length === 0) return <Typography.Text type="secondary">—</Typography.Text>
                  return (
                    <Space size={4} wrap>
                      {entries.map(([k, v]) => (
                        <Tag key={k}>
                          {k}：{Array.isArray(v) ? v.join('、') : String(v)}
                        </Tag>
                      ))}
                    </Space>
                  )
                },
              },
            ]}
          />
          <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 12 }}>
            子项目名称与参数都是**记录当时的快照**。字典后来改名不会改变这里的内容，
            这正是历史记录可追溯的关键。
          </Typography.Paragraph>
        </>
      ) : null}
    </Drawer>
  )
}
