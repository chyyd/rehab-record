/** 患者管理（M1）：CRUD + 注意事项 + 归属分配/取消 + 归属历史。 */
import { useState } from 'react'
import {
  Button,
  Drawer,
  Descriptions,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Timeline,
  Typography,
} from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { patientsApi, usersApi, type PatientOut } from '../api/endpoints'
import { errorMessage } from '../api/client'
import { ErrorBox, PageHeader, PageSkeleton, useAsync } from '../components/Feedback'
import { useAuth } from '../auth/AuthProvider'
import { notify } from '../components/notify'

const STATUS_LABEL: Record<string, { text: string; color: string }> = {
  in_hospital: { text: '在院', color: 'green' },
  discharged: { text: '已出院', color: 'default' },
  paused: { text: '暂停', color: 'orange' },
}

export function PatientsPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [keyword, setKeyword] = useState('')
  const [status, setStatus] = useState<string | undefined>()
  const [page, setPage] = useState(1)
  const [editing, setEditing] = useState<PatientOut | null>(null)
  const [creating, setCreating] = useState(false)
  const [assignTarget, setAssignTarget] = useState<PatientOut | null>(null)
  const [detailTarget, setDetailTarget] = useState<string | null>(null)

  const { data, loading, error, reload } = useAsync(
    () => patientsApi.list({ page, page_size: 20, keyword: keyword || undefined, status }),
    [page, keyword, status],
  )

  const therapists = useAsync(async () => {
    const result = await usersApi.list({ page: 1, page_size: 200, role: 'therapist', status: 'active' })
    return result.items
  }, [])

  const columns = [
    { title: '住院编号', dataIndex: 'inpatient_no', width: 120 },
    { title: '姓名', dataIndex: 'name', width: 100 },
    {
      title: '诊断',
      dataIndex: 'diagnosis',
      ellipsis: true,
      render: (v: string | null) => v || <Typography.Text type="secondary">—</Typography.Text>,
    },
    {
      title: '注意事项',
      dataIndex: 'admin_note',
      width: 200,
      ellipsis: true,
      render: (v: string | null) =>
        v ? (
          <Typography.Text type="warning">{v}</Typography.Text>
        ) : (
          <Typography.Text type="secondary">—</Typography.Text>
        ),
    },
    {
      title: '归属治疗师',
      dataIndex: 'assigned_therapist_id',
      width: 130,
      render: (id: number | null) => {
        if (!id) return <Tag>未分配</Tag>
        const t = therapists.data?.find((x) => x.id === id)
        return t?.name ?? `#${id}`
      },
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
      title: '操作',
      key: 'actions',
      width: 220,
      render: (_: unknown, record: PatientOut) => (
        <Space size="small" wrap>
          <Button size="small" type="link" onClick={() => setDetailTarget(record.inpatient_no)}>
            详情
          </Button>
          {isAdmin ? (
            <>
              <Button size="small" type="link" onClick={() => setEditing(record)}>
                编辑
              </Button>
              <Button size="small" type="link" onClick={() => setAssignTarget(record)}>
                分配归属
              </Button>
            </>
          ) : null}
        </Space>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        title="患者管理"
        description={
          isAdmin
            ? '维护患者基本信息与注意事项，并分配归属治疗师。'
            : '查看患者基本信息（注意事项、归属分配由管理员维护）。'
        }
        extra={
          <>
            <Input.Search
              placeholder="住院编号 / 姓名"
              allowClear
              style={{ width: 200 }}
              onSearch={(v) => {
                setPage(1)
                setKeyword(v)
              }}
            />
            <Select
              placeholder="状态"
              allowClear
              style={{ width: 120 }}
              value={status}
              onChange={(v) => {
                setPage(1)
                setStatus(v)
              }}
              options={[
                { value: 'in_hospital', label: '在院' },
                { value: 'discharged', label: '已出院' },
                { value: 'paused', label: '暂停' },
              ]}
            />
            <Button icon={<ReloadOutlined />} onClick={reload}>
              刷新
            </Button>
            {isAdmin ? (
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
                新建患者
              </Button>
            ) : null}
          </>
        }
      />

      {error ? (
        <ErrorBox message={error} onRetry={reload} />
      ) : loading ? (
        <PageSkeleton />
      ) : (
        <Table
          rowKey="inpatient_no"
          size="middle"
          columns={columns}
          dataSource={data?.items ?? []}
          pagination={{
            current: page,
            pageSize: 20,
            total: data?.total ?? 0,
            showSizeChanger: false,
            onChange: setPage,
            showTotal: (t) => `共 ${t} 位患者`,
          }}
        />
      )}

      <PatientFormModal
        open={creating || editing !== null}
        patient={editing}
        onClose={() => {
          setCreating(false)
          setEditing(null)
        }}
        onSaved={() => {
          setCreating(false)
          setEditing(null)
          reload()
        }}
      />

      <AssignModal
        patient={assignTarget}
        therapists={therapists.data ?? []}
        onClose={() => setAssignTarget(null)}
        onSaved={() => {
          setAssignTarget(null)
          reload()
        }}
      />

      <PatientDetailDrawer
        inpatientNo={detailTarget}
        onClose={() => setDetailTarget(null)}
        isAdmin={isAdmin}
      />
    </>
  )
}

function PatientFormModal({
  open,
  patient,
  onClose,
  onSaved,
}: {
  open: boolean
  patient: PatientOut | null
  onClose: () => void
  onSaved: () => void
}) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const isEdit = patient !== null

  const handleOk = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      if (isEdit) {
        await patientsApi.update(patient.inpatient_no, values)
        notify.success('已保存')
      } else {
        await patientsApi.create(values)
        notify.success('已新建患者')
      }
      form.resetFields()
      onSaved()
    } catch (err) {
      notify.error(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={isEdit ? `编辑患者 ${patient?.name}` : '新建患者'}
      open={open}
      onOk={handleOk}
      onCancel={() => {
        form.resetFields()
        onClose()
      }}
      confirmLoading={saving}
      okText="保存"
      cancelText="取消"
      destroyOnHidden
      afterOpenChange={(visible) => {
        if (visible) {
          form.setFieldsValue(
            isEdit
              ? {
                  name: patient.name,
                  diagnosis: patient.diagnosis,
                  admin_note: patient.admin_note,
                  status: patient.status,
                }
              : { status: 'in_hospital' },
          )
        }
      }}
    >
      <Form form={form} layout="vertical">
        {!isEdit ? (
          <Form.Item
            name="inpatient_no"
            label="住院编号"
            rules={[{ required: true, message: '请输入住院编号' }]}
          >
            <Input placeholder="如 ZY2026001" />
          </Form.Item>
        ) : null}
        <Form.Item name="name" label="姓名" rules={[{ required: true, message: '请输入姓名' }]}>
          <Input />
        </Form.Item>
        <Form.Item name="diagnosis" label="诊断">
          <Input.TextArea rows={2} placeholder="如 脑卒中恢复期" />
        </Form.Item>
        <Form.Item
          name="admin_note"
          label="注意事项"
          extra="治疗师只读，请在医嘱允许的范围内填写（如过敏、防跌倒、体位限制）"
        >
          <Input.TextArea rows={3} />
        </Form.Item>
        <Form.Item
          name="status"
          label="状态"
          rules={[{ required: true }]}
          extra={
            isEdit && patient?.status === 'discharged' ? (
              <Typography.Text type="warning">
                该患者已出院。改回「在院」或「暂停」即为恢复，此操作会以
                「恢复（出院改回）」单独记入审计日志，请确认确实需要恢复。
              </Typography.Text>
            ) : undefined
          }
        >
          <Select
            options={[
              { value: 'in_hospital', label: '在院' },
              { value: 'paused', label: '暂停' },
              { value: 'discharged', label: '已出院' },
            ]}
          />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function AssignModal({
  patient,
  therapists,
  onClose,
  onSaved,
}: {
  patient: PatientOut | null
  therapists: { id: number; name: string; employee_no: string }[]
  onClose: () => void
  onSaved: () => void
}) {
  const [value, setValue] = useState<number | undefined>()
  const [saving, setSaving] = useState(false)

  const handleAssign = async () => {
    if (!patient || !value) {
      notify.warning('请选择治疗师')
      return
    }
    setSaving(true)
    try {
      await patientsApi.assign(patient.inpatient_no, value)
      notify.success('已分配归属')
      onSaved()
    } catch (err) {
      notify.error(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  const handleRelease = async () => {
    if (!patient) return
    setSaving(true)
    try {
      await patientsApi.release(patient.inpatient_no)
      notify.success('已取消归属')
      onSaved()
    } catch (err) {
      notify.error(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={`分配归属：${patient?.name ?? ''}`}
      open={patient !== null}
      onCancel={onClose}
      footer={[
        <Button key="cancel" onClick={onClose}>
          取消
        </Button>,
        <Button key="release" danger onClick={handleRelease} loading={saving}>
          取消归属
        </Button>,
        <Button key="ok" type="primary" onClick={handleAssign} loading={saving}>
          确认分配
        </Button>,
      ]}
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary">
        首页向治疗师（原归属）。单日假期间患者会临时释放，原归属不变；多日假会正式排空归属。
      </Typography.Paragraph>
      <Select
        style={{ width: '100%' }}
        placeholder="选择治疗师"
        value={value}
        onChange={setValue}
        showSearch
        optionFilterProp="label"
        options={therapists.map((t) => ({
          value: t.id,
          label: `${t.name}（${t.employee_no}）`,
        }))}
      />
    </Modal>
  )
}

function PatientDetailDrawer({
  inpatientNo,
  onClose,
  isAdmin,
}: {
  inpatientNo: string | null
  onClose: () => void
  isAdmin: boolean
}) {
  const detail = useAsync(
    () => (inpatientNo ? patientsApi.get(inpatientNo) : Promise.resolve(null)),
    [inpatientNo],
  )
  const history = useAsync(
    () => (inpatientNo ? patientsApi.assignments(inpatientNo) : Promise.resolve([])),
    [inpatientNo],
  )

  const patient = detail.data

  return (
    <Drawer
      title={patient ? `${patient.name}（${patient.inpatient_no}）` : '患者详情'}
      size={560}
      open={inpatientNo !== null}
      onClose={onClose}
      destroyOnHidden
    >
      {detail.loading ? (
        <PageSkeleton />
      ) : detail.error ? (
        <ErrorBox message={detail.error} onRetry={detail.reload} />
      ) : patient ? (
        <>
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="住院编号">{patient.inpatient_no}</Descriptions.Item>
            <Descriptions.Item label="姓名">{patient.name}</Descriptions.Item>
            <Descriptions.Item label="诊断">{patient.diagnosis || '—'}</Descriptions.Item>
            <Descriptions.Item label="状态">
              {STATUS_LABEL[patient.status]?.text ?? patient.status}
            </Descriptions.Item>
            <Descriptions.Item label="注意事项">
              {patient.admin_note ? (
                <Typography.Text type="warning">{patient.admin_note}</Typography.Text>
              ) : (
                '—'
              )}
            </Descriptions.Item>
          </Descriptions>

          <Typography.Title level={5} style={{ marginTop: 24 }}>
            归属变更历史
          </Typography.Title>
          {history.loading ? (
            <PageSkeleton />
          ) : (history.data?.length ?? 0) === 0 ? (
            <Typography.Text type="secondary">暂无归属变更记录。</Typography.Text>
          ) : (
            <Timeline
              items={history.data!.map((item) => ({
                children: (
                  <>
                    <div>
                      <Tag>{item.action}</Tag>
                      {dayjs(item.created_at).format('YYYY-MM-DD HH:mm')}
                    </div>
                    {item.reason ? (
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {item.reason}
                      </Typography.Text>
                    ) : null}
                  </>
                ),
              }))}
            />
          )}

          {isAdmin ? (
            <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 16 }}>
              归属分配与注意事项编辑在列表页操作。
            </Typography.Paragraph>
          ) : null}
        </>
      ) : null}
    </Drawer>
  )
}
