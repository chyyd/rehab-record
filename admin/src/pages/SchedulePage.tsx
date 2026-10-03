/**
 * 全局排期（M8）：半日格子视图。
 *
 * 半日制是这套系统的核心约定（`设计.md` 3.4、S1）：格子 = (日期, 上午/下午)，
 * 不是具体时间点。因此这里用"治疗师 × 半日"的矩阵，而不是日历式时间轴。
 */
import { useMemo, useState } from 'react'
import {
  Button,
  Card,
  Col,
  DatePicker,
  Form,
  Input,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import { ReloadOutlined, CopyOutlined, PlusOutlined } from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import {
  patientsApi,
  scheduleApi,
  usersApi,
  type AppointmentOut,
  type AvailabilitySlotOut,
} from '../api/endpoints'
import { errorMessage } from '../api/client'
import { ErrorBox, PageHeader, PageSkeleton, useAsync } from '../components/Feedback'
import { notify } from '../components/notify'

const PERIODS: { key: 'am' | 'pm'; label: string }[] = [
  { key: 'am', label: '上午' },
  { key: 'pm', label: '下午' },
]

export function SchedulePage() {
  const [date, setDate] = useState<Dayjs>(dayjs())
  const [therapistId, setTherapistId] = useState<number | undefined>()
  const [creating, setCreating] = useState(false)

  const day = date.format('YYYY-MM-DD')

  const therapists = useAsync(async () => {
    const r = await usersApi.list({ page: 1, page_size: 200, role: 'therapist', status: 'active' })
    return r.items
  }, [])

  const appointments = useAsync(
    () => scheduleApi.list({ from: day, to: day, therapist_id: therapistId }),
    [day, therapistId],
  )

  const availability = useAsync(
    () => scheduleApi.availability({ from: day, to: day, therapist_id: therapistId }),
    [day, therapistId],
  )

  const reload = () => {
    appointments.reload()
    availability.reload()
  }

  /** 把选中的治疗师按"上午/下午"两列展开成矩阵行。 */
  const rows = useMemo(() => {
    const list = therapistId
      ? (therapists.data ?? []).filter((t) => t.id === therapistId)
      : (therapists.data ?? [])
    const byKey = new Map<string, AppointmentOut>()
    for (const a of appointments.data ?? []) {
      byKey.set(`${a.therapist_id}-${a.period}`, a)
    }
    return list.map((t) => ({
      key: t.id,
      therapist: t,
      am: byKey.get(`${t.id}-am`),
      pm: byKey.get(`${t.id}-pm`),
    }))
  }, [therapists.data, appointments.data, therapistId])

  const availableMap = useMemo(() => {
    const map = new Map<string, AvailabilitySlotOut>()
    for (const slot of availability.data ?? []) {
      map.set(`${slot.date}-${slot.period}`, slot)
    }
    return map
  }, [availability.data])

  const cancel = async (id: number) => {
    try {
      await scheduleApi.cancel(id)
      notify.success('已取消排期')
      reload()
    } catch (err) {
      notify.error(errorMessage(err))
    }
  }

  const copyYesterday = () => {
    notify.confirm({
      title: '复制昨天的排期到今天？',
      content: '冲突的格子会被跳过并逐条回报，不会整体失败。',
      okText: '复制',
      cancelText: '取消',
      onOk: async () => {
        try {
          const result = (await scheduleApi.copy({
            mode: 'yesterday',
            target_date: day,
          })) as { created?: unknown[]; skipped?: unknown[] }
          notify.success(
            `已复制 ${result.created?.length ?? 0} 条，跳过 ${result.skipped?.length ?? 0} 条`,
          )
          reload()
        } catch (err) {
          notify.error(errorMessage(err))
        }
      },
    })
  }

  const renderCell = (therapistIdValue: number, period: 'am' | 'pm', appt?: AppointmentOut) => {
    const slot = availableMap.get(`${day}-${period}`)
    if (appt) {
      return (
        <div>
          <Space orientation="vertical" size={2}>
            <span>
              <strong>{appt.patient_name ?? appt.patient_no}</strong>
              <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 6 }}>
                {appt.patient_no}
              </Typography.Text>
            </span>
            {appt.slot_label ? <Tag>{appt.slot_label}</Tag> : null}
            <Popconfirm
              title="取消该排期？"
              onConfirm={() => cancel(appt.id)}
              okText="取消排期"
              cancelText="返回"
            >
              <Button size="small" type="link" danger style={{ padding: 0 }}>
                取消
              </Button>
            </Popconfirm>
          </Space>
        </div>
      )
    }
    return (
      <Space orientation="vertical" size={2}>
        <Typography.Text type="secondary">空闲</Typography.Text>
        {slot && !slot.available && slot.reasons.length > 0 ? (
          <Tooltip title={slot.reasons.join('、')}>
            <Tag color="orange">不可排（{slot.reasons[0]}）</Tag>
          </Tooltip>
        ) : null}
        <Button
          size="small"
          type="link"
          style={{ padding: 0 }}
          onClick={() => {
            setCreating(true)
            setTimeout(() => {
              window.dispatchEvent(
                new CustomEvent('schedule-prefill', {
                  detail: { therapist_id: therapistIdValue, period, date: day },
                }),
              )
            }, 0)
          }}
        >
          排一台
        </Button>
      </Space>
    )
  }

  return (
    <>
      <PageHeader
        title="全局排期"
        description="半日制格子：一位治疗师在一个半日内只排一台治疗。格子 = 日期 + 上午/下午。"
        extra={
          <>
            <DatePicker
              value={date}
              onChange={(v) => v && setDate(v)}
              allowClear={false}
              // 快捷切换昨天/明天，排班时最常用
              presets={[
                { label: '昨天', value: dayjs().subtract(1, 'day') },
                { label: '今天', value: dayjs() },
                { label: '明天', value: dayjs().add(1, 'day') },
              ]}
            />
            <Select
              allowClear
              placeholder="全部治疗师"
              style={{ width: 160 }}
              value={therapistId}
              onChange={setTherapistId}
              showSearch
              optionFilterProp="label"
              options={(therapists.data ?? []).map((t) => ({
                value: t.id,
                label: `${t.name}（${t.employee_no}）`,
              }))}
            />
            <Button icon={<ReloadOutlined />} onClick={reload}>
              刷新
            </Button>
            <Button icon={<CopyOutlined />} onClick={copyYesterday}>
              复制昨天
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
              新建排期
            </Button>
          </>
        }
      />

      {appointments.error ? (
        <ErrorBox message={appointments.error} onRetry={reload} />
      ) : appointments.loading ? (
        <PageSkeleton />
      ) : rows.length === 0 ? (
        <Card>
          <Typography.Text type="secondary">
            没有可显示的治疗师。请先在「用户管理」里创建在职治疗师。
          </Typography.Text>
        </Card>
      ) : (
        <Table
          rowKey="key"
          size="middle"
          pagination={false}
          dataSource={rows}
          columns={[
            {
              title: '治疗师',
              dataIndex: ['therapist', 'name'],
              width: 140,
              render: (_: unknown, r: (typeof rows)[number]) => (
                <span>
                  {r.therapist.name}
                  <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 6 }}>
                    {r.therapist.employee_no}
                  </Typography.Text>
                </span>
              ),
            },
            ...PERIODS.map((p) => ({
              title: `${p.label}（${p.key === 'am' ? '06:00–11:30' : '13:00–17:30'}）`,
              key: p.key,
              render: (_: unknown, r: (typeof rows)[number]) =>
                renderCell(r.therapist.id, p.key, r[p.key]),
            })),
          ]}
        />
      )}

      <RestBlockCard therapists={therapists.data ?? []} date={day} onChanged={reload} />

      <AppointmentFormModal
        open={creating}
        date={day}
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

/** 休息块维护：周固定 / 指定日期 × 上午下午。 */
/** 休息块表格行（与 RestBlockOut 一致，单独命名便于列渲染函数标注类型）。 */
interface RestBlockRow {
  id: number
  scope: string
  weekday?: number | null
  specific_date?: string | null
}

function RestBlockCard({
  therapists,
  date,
  onChanged,
}: {
  therapists: { id: number; name: string }[]
  date: string
  onChanged: () => void
}) {
  const [therapistId, setTherapistId] = useState<number | undefined>()
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)

  const blocks = useAsync(
    () => scheduleApi.restBlocks(therapistId),
    [therapistId],
  )

  const add = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      await scheduleApi.createRestBlock({
        therapist_id: values.therapist_id,
        scope: values.scope,
        weekday: values.scope === 'weekly' ? values.weekday : null,
        specific_date: values.scope === 'date' ? date : null,
        period: values.period,
        reason: values.reason || null,
      })
      notify.success('已添加休息块')
      form.resetFields()
      blocks.reload()
      onChanged()
    } catch (err) {
      notify.error(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  const remove = async (id: number) => {
    try {
      await scheduleApi.deleteRestBlock(id)
      notify.success('已删除')
      blocks.reload()
      onChanged()
    } catch (err) {
      notify.error(errorMessage(err))
    }
  }

  const scope = Form.useWatch('scope', form)

  return (
    <Card size="small" title="休息块" style={{ marginTop: 16 }}>
      <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
        休息块只影响排期，不同于请假（请假还会释放患者归属）。粒度是半日。
      </Typography.Paragraph>

      <Form form={form} layout="inline" initialValues={{ scope: 'date', period: 'am' }}>
        <Form.Item name="therapist_id" rules={[{ required: true, message: '选择治疗师' }]}>
          <Select
            placeholder="治疗师"
            style={{ width: 150 }}
            options={therapists.map((t) => ({ value: t.id, label: t.name }))}
            onChange={setTherapistId}
          />
        </Form.Item>
        <Form.Item name="scope">
          <Select
            style={{ width: 130 }}
            options={[
              { value: 'date', label: `指定日期（${dayjs(date).format('M-D')}）` },
              { value: 'weekly', label: '每周固定' },
            ]}
          />
        </Form.Item>
        {scope === 'weekly' ? (
          <Form.Item name="weekday" rules={[{ required: true, message: '选择星期' }]}>
            <Select
              placeholder="星期"
              style={{ width: 110 }}
              options={[
                { value: 1, label: '周一' },
                { value: 2, label: '周二' },
                { value: 3, label: '周三' },
                { value: 4, label: '周四' },
                { value: 5, label: '周五' },
                { value: 6, label: '周六' },
                { value: 7, label: '周日' },
              ]}
            />
          </Form.Item>
        ) : null}
        <Form.Item name="period">
          <Select
            style={{ width: 100 }}
            options={[
              { value: 'am', label: '上午' },
              { value: 'pm', label: '下午' },
            ]}
          />
        </Form.Item>
        <Form.Item name="reason">
          <Input placeholder="原因（可选）" style={{ width: 160 }} />
        </Form.Item>
        <Form.Item>
          <Button type="primary" onClick={add} loading={saving}>
            添加
          </Button>
        </Form.Item>
      </Form>

      <Table
        rowKey="id"
        size="small"
        style={{ marginTop: 12 }}
        loading={blocks.loading}
        dataSource={blocks.data ?? []}
        pagination={false}
        columns={[
          {
            title: '治疗师',
            dataIndex: 'therapist_id',
            render: (v: number) => therapists.find((t) => t.id === v)?.name ?? `#${v}`,
          },
          {
            title: '类型',
            dataIndex: 'scope',
            render: (v: string) => (v === 'weekly' ? '每周固定' : '指定日期'),
          },
          {
            title: '时间',
            key: 'when',
            render: (_: unknown, record: RestBlockRow) =>
              record.scope === 'weekly' ? `周${record.weekday ?? '?'}` : (record.specific_date ?? '—'),
          },
          {
            title: '半日',
            dataIndex: 'period',
            render: (v: string | null) => (v === 'am' ? '上午' : v === 'pm' ? '下午' : '全天'),
          },
          {
            title: '操作',
            key: 'a',
            width: 80,
            render: (_: unknown, record: RestBlockRow) => (
              <Button size="small" type="link" danger onClick={() => remove(record.id)}>
                删除
              </Button>
            ),
          },
        ]}
      />
    </Card>
  )
}

function AppointmentFormModal({
  open,
  date,
  therapists,
  onClose,
  onSaved,
}: {
  open: boolean
  date: string
  therapists: { id: number; name: string; employee_no: string }[]
  onClose: () => void
  onSaved: () => void
}) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [patients, setPatients] = useState<{ value: string; label: string }[]>([])

  const searchPatients = async (keyword: string) => {
    try {
      const r = await patientsApi.list({ page: 1, page_size: 30, keyword: keyword || undefined })
      setPatients(
        r.items.map((p) => ({ value: p.inpatient_no, label: `${p.name}（${p.inpatient_no}）` })),
      )
    } catch {
      /* 搜索失败不阻断排期 */
    }
  }

  return (
    <Modal
      title="新建排期"
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
          await scheduleApi.create({
            patient_no: values.patient_no,
            therapist_id: values.therapist_id,
            date: values.date.format('YYYY-MM-DD'),
            period: values.period,
            slot_label: values.slot_label || null,
            note: values.note || null,
          })
          notify.success('已新建排期')
          form.resetFields()
          onSaved()
        } catch (err) {
          notify.error(errorMessage(err))
        } finally {
          setSaving(false)
        }
      }}
      afterOpenChange={(v) => {
        if (v) {
          form.setFieldsValue({ date: dayjs(date), period: 'am' })
          void searchPatients('')
        }
      }}
    >
      <Form form={form} layout="vertical">
        <Form.Item label="患者" name="patient_no" rules={[{ required: true, message: '请选择患者' }]}>
          <Select
            showSearch
            filterOption={false}
            onSearch={searchPatients}
            placeholder="输入住院编号或姓名搜索"
            options={patients}
          />
        </Form.Item>
        <Form.Item label="治疗师" name="therapist_id" rules={[{ required: true, message: '请选择治疗师' }]}>
          <Select
            showSearch
            optionFilterProp="label"
            options={therapists.map((t) => ({
              value: t.id,
              label: `${t.name}（${t.employee_no}）`,
            }))}
          />
        </Form.Item>
        <Row gutter={12}>
          <Col span={12}>
            <Form.Item label="日期" name="date" rules={[{ required: true }]}>
              <DatePicker style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              label="半日"
              name="period"
              rules={[{ required: true }]}
              extra="半日为单位，不是具体时间点"
            >
              <Select
                options={[
                  { value: 'am', label: '上午 06:00–11:30' },
                  { value: 'pm', label: '下午 13:00–17:30' },
                ]}
              />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item label="台次标签" name="slot_label" extra="仅作展示，如「上午第 1 台」">
          <Input />
        </Form.Item>
        <Form.Item label="备注" name="note">
          <Input.TextArea rows={2} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
