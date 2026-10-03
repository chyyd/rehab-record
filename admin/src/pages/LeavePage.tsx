/** 请假管理（M7）：全部请假记录 + 代录 + 撤销。 */
import { useState } from 'react'
import {
  Button,
  DatePicker,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Table,
  Tag,
  Typography,
} from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import type { Dayjs } from 'dayjs'
import { leaveApi, usersApi, type LeaveOut } from '../api/endpoints'
import { errorMessage } from '../api/client'
import { ErrorBox, PageHeader, PageSkeleton, useAsync } from '../components/Feedback'
import { notify } from '../components/notify'

const LEAVE_TYPE_LABEL: Record<string, string> = {
  half_day_am: '上午半天',
  half_day_pm: '下午半天',
  full_day: '全天',
  multi_day: '多日',
}

export function LeavePage() {
  const [therapistId, setTherapistId] = useState<number | undefined>()
  const [status, setStatus] = useState<string | undefined>('active')
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null)
  const [creating, setCreating] = useState(false)

  const therapists = useAsync(async () => {
    const r = await usersApi.list({ page: 1, page_size: 200, role: 'therapist' })
    return r.items
  }, [])

  const { data, loading, error, reload } = useAsync(
    () =>
      leaveApi.list({
        therapist_id: therapistId,
        status,
        from: range?.[0]?.format('YYYY-MM-DD'),
        to: range?.[1]?.format('YYYY-MM-DD'),
      }),
    [therapistId, status, range?.[0]?.valueOf(), range?.[1]?.valueOf()],
  )

  const cancel = async (item: LeaveOut) => {
    try {
      const result = await leaveApi.cancel(item.id)
      const restored = (result as { restored?: string[] }).restored
      if (restored && restored.length > 0) {
        notify.success(`已撤销，并恢复 ${restored.length} 位患者的归属`)
      } else {
        notify.success('已撤销')
      }
      reload()
    } catch (err) {
      notify.error(errorMessage(err))
    }
  }

  const nameOf = (id: number) => therapists.data?.find((t) => t.id === id)?.name ?? `#${id}`

  return (
    <>
      <PageHeader
        title="请假管理"
        description="请假登记即生效（无审批流）。单日假会临时释放患者；多日假会正式排空归属。"
        extra={
          <>
            <Select
              allowClear
              placeholder="治疗师"
              style={{ width: 150 }}
              value={therapistId}
              onChange={setTherapistId}
              showSearch
              optionFilterProp="label"
              options={(therapists.data ?? []).map((t) => ({
                value: t.id,
                label: `${t.name}（${t.employee_no}）`,
              }))}
            />
            <Select
              allowClear
              placeholder="状态"
              style={{ width: 120 }}
              value={status}
              onChange={setStatus}
              options={[
                { value: 'active', label: '生效中' },
                { value: 'cancelled', label: '已撤销' },
              ]}
            />
            <DatePicker.RangePicker
              value={range}
              onChange={(v) => setRange(v as [Dayjs, Dayjs] | null)}
              placeholder={['开始', '结束']}
            />
            <Button icon={<ReloadOutlined />} onClick={reload}>
              刷新
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
              代录请假
            </Button>
          </>
        }
      />

      {error ? (
        <ErrorBox message={error} onRetry={reload} />
      ) : loading ? (
        <PageSkeleton />
      ) : (
        <Table<LeaveOut>
          rowKey="id"
          size="middle"
          dataSource={data ?? []}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          columns={[
            {
              title: '治疗师',
              dataIndex: 'therapist_id',
              width: 130,
              render: (v: number, r: LeaveOut) => r.therapist_name ?? nameOf(v),
            },
            {
              title: '类型',
              dataIndex: 'leave_type',
              width: 110,
              render: (v: string) => LEAVE_TYPE_LABEL[v] ?? v,
            },
            { title: '开始日期', dataIndex: 'start_date', width: 115 },
            {
              title: '结束日期',
              dataIndex: 'end_date',
              width: 115,
              render: (v: string | null) => v || '—',
            },
            {
              title: '状态',
              dataIndex: 'status',
              width: 90,
              render: (v: string) =>
                v === 'active' ? <Tag color="green">生效中</Tag> : <Tag>已撤销</Tag>,
            },
            {
              title: '来源',
              dataIndex: 'source',
              width: 100,
              render: (v: string) =>
                v === 'admin_entry' ? <Tag color="orange">管理员代录</Tag> : <Tag>本人登记</Tag>,
            },
            {
              title: '原因',
              dataIndex: 'reason',
              ellipsis: true,
              render: (v: string | null) => v || <Typography.Text type="secondary">—</Typography.Text>,
            },
            {
              title: '操作',
              key: 'a',
              width: 90,
              render: (_: unknown, record: LeaveOut) =>
                record.status === 'active' ? (
                  <Popconfirm
                    title="撤销该请假？"
                    description="若期间产生了临时认领，已被认领的患者不会被自动恢复。"
                    onConfirm={() => cancel(record)}
                    okText="撤销"
                    cancelText="取消"
                  >
                    <Button size="small" type="link" danger>
                      撤销
                    </Button>
                  </Popconfirm>
                ) : (
                  <Typography.Text type="secondary">—</Typography.Text>
                ),
            },
          ]}
        />
      )}

      <LeaveFormModal
        open={creating}
        therapists={therapists.data ?? []}
        onClose={() => setCreating(false)}
        onSaved={() => {
          setCreating(false)
          reload()
        }}
      />
    </>
  )
}

function LeaveFormModal({
  open,
  therapists,
  onClose,
  onSaved,
}: {
  open: boolean
  therapists: { id: number; name: string; employee_no: string }[]
  onClose: () => void
  onSaved: () => void
}) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const leaveType = Form.useWatch('leave_type', form)

  return (
    <Modal
      title="代录请假"
      open={open}
      onCancel={onClose}
      destroyOnHidden
      confirmLoading={saving}
      okText="保存"
      cancelText="取消"
      onOk={async () => {
        const values = await form.validateFields()
        setSaving(true)
        try {
          await leaveApi.adminCreate({
            therapist_id: values.therapist_id,
            leave_type: values.leave_type,
            start_date: values.start_date.format('YYYY-MM-DD'),
            end_date:
              values.leave_type === 'multi_day' && values.end_date
                ? values.end_date.format('YYYY-MM-DD')
                : values.leave_type === 'multi_day'
                  ? null
                  : values.start_date.format('YYYY-MM-DD'),
            reason: values.reason || null,
          })
          notify.success('已登记请假')
          form.resetFields()
          onSaved()
        } catch (err) {
          notify.error(errorMessage(err))
        } finally {
          setSaving(false)
        }
      }}
      afterOpenChange={(v) => {
        if (v) form.setFieldsValue({ leave_type: 'half_day_am' })
      }}
    >
      <Typography.Paragraph type="warning" style={{ fontSize: 13 }}>
        代录的请假**立即生效**，无需审批。请确认与本人核实过。
      </Typography.Paragraph>
      <Form form={form} layout="vertical">
        <Form.Item
          name="therapist_id"
          label="治疗师"
          rules={[{ required: true, message: '请选择治疗师' }]}
        >
          <Select
            showSearch
            optionFilterProp="label"
            options={therapists.map((t) => ({
              value: t.id,
              label: `${t.name}（${t.employee_no}）`,
            }))}
          />
        </Form.Item>
        <Form.Item name="leave_type" label="请假类型" rules={[{ required: true }]}>
          <Select
            options={Object.entries(LEAVE_TYPE_LABEL).map(([value, label]) => ({ value, label }))}
          />
        </Form.Item>
        <Form.Item
          name="start_date"
          label="开始日期"
          rules={[{ required: true, message: '请选择日期' }]}
        >
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>
        {leaveType === 'multi_day' ? (
          <Form.Item
            name="end_date"
            label="结束日期"
            rules={[{ required: true, message: '多日假必须填结束日期' }]}
            extra="多日假会把归属正式排空（不自动恢复），撤销时只回收仍未被认领的患者"
          >
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        ) : (
          <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
            单日假只做**临时释放**：原归属不变，到期自动恢复；他人可在这期间临时认领该患者。
          </Typography.Paragraph>
        )}
        <Form.Item name="reason" label="原因">
          <Input.TextArea rows={2} placeholder="如 门诊 / 外出学习 / 病假" />
        </Form.Item>
      </Form>
    </Modal>
  )
}
