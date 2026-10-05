/** 患者管理（M1）：CRUD + 注意事项 + 归属分配/取消 + 归属历史 + 出院流程。 */
import { useState } from 'react'
import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Timeline,
  Typography,
} from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { patientsApi, recordsApi, usersApi, type PatientOut } from '../api/endpoints'
import { errorMessage } from '../api/client'
import { ErrorBox, PageHeader, PageSkeleton, useAsync } from '../components/Feedback'
import { useAuth } from '../auth/AuthProvider'
import { notify } from '../components/notify'

const STATUS_LABEL: Record<string, { text: string; color: string }> = {
  in_hospital: { text: '在院', color: 'green' },
  // 2026-10-05 新增：出院小结已提交、等管理员确认（或满 7 天自动出院）的中间态。
  // 此时患者**从治疗师白板消失、不能再记新治疗**，所以列表上必须一眼看得出来。
  pending_discharge: { text: '待出院', color: 'volcano' },
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
  const [dischargeTarget, setDischargeTarget] = useState<PatientOut | null>(null)
  const [dischargeBusy, setDischargeBusy] = useState<string | null>(null)

  const { data, loading, error, reload } = useAsync(
    () => patientsApi.list({ page, page_size: 20, keyword: keyword || undefined, status }),
    [page, keyword, status],
  )

  const therapists = useAsync(async () => {
    const result = await usersApi.list({ page: 1, page_size: 200, role: 'therapist', status: 'active' })
    return result.items
  }, [])

  // 只统计**当前页**里的待出院患者 —— 页面只是提醒，不是全量统计接口。
  const pendingDischarge = (data?.items ?? []).filter((p) => p.status === 'pending_discharge').length

  /** 管理员确认出院：待出院 → 已出院。 */
  const confirmDischarge = async (patient: PatientOut) => {
    setDischargeBusy(patient.inpatient_no)
    try {
      await patientsApi.confirmDischarge(patient.inpatient_no)
      notify.success(`${patient.name} 已出院`)
      reload()
    } catch (err) {
      notify.error(errorMessage(err))
    } finally {
      setDischargeBusy(null)
    }
  }

  /** 管理员取消待出院（患者反悔）：待出院 → 在院。 */
  const cancelDischarge = async (patient: PatientOut) => {
    setDischargeBusy(patient.inpatient_no)
    try {
      await patientsApi.cancelDischarge(patient.inpatient_no)
      notify.success(`${patient.name} 已取消待出院，恢复在院`)
      reload()
    } catch (err) {
      notify.error(errorMessage(err))
    } finally {
      setDischargeBusy(null)
    }
  }

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
      width: 120,
      render: (v: string) => {
        const item = STATUS_LABEL[v] ?? { text: v, color: 'default' }
        return (
          <Space size={4}>
            <Tag color={item.color}>{item.text}</Tag>
            {v === 'pending_discharge' ? <Tag color="red">待确认出院</Tag> : null}
          </Space>
        )
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 300,
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
          {/* 出院动作区：待出院时给出「确认出院 / 取消待出院」（仅管理员，后端 AdminUser 强制）；
              其它状态给出「发起出院」—— 出院小结写完后任何治疗师都可以把患者推入待出院。 */}
          {record.status === 'pending_discharge' && isAdmin ? (
            <>
              <Popconfirm
                title={`确认 ${record.name} 出院？`}
                description="确认后患者进入已出院，从治疗师白板与在院列表中消失。"
                okText="确认出院"
                cancelText="取消"
                onConfirm={() => confirmDischarge(record)}
              >
                <Button size="small" type="link" danger loading={dischargeBusy === record.inpatient_no}>
                  确认出院
                </Button>
              </Popconfirm>
              <Popconfirm
                title={`取消 ${record.name} 的待出院？`}
                description="患者会恢复为在院，重新出现在治疗师白板上。"
                okText="取消待出院"
                cancelText="返回"
                onConfirm={() => cancelDischarge(record)}
              >
                <Button size="small" type="link" loading={dischargeBusy === record.inpatient_no}>
                  取消待出院
                </Button>
              </Popconfirm>
            </>
          ) : null}
          {record.status === 'in_hospital' || record.status === 'paused' ? (
            <Button size="small" type="link" onClick={() => setDischargeTarget(record)}>
              发起出院
            </Button>
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
                { value: 'pending_discharge', label: '待出院' },
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

      {/* 待出院患者：从治疗师白板消失、不能再记治疗，但出院动作还没完成。
          页面上必须醒目地提示 + 就近给出「确认出院 / 取消待出院」，否则这批患者会悄悄卡住。 */}
      {pendingDischarge > 0 ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={`有 ${pendingDischarge} 位患者处于「待出院」（本页范围内）`}
          description={
            isAdmin
              ? '他们的出院小结已提交，已从治疗师白板消失、不能再记新治疗。请核对后确认出院，或取消待出院让患者回到在院。'
              : '他们的出院小结已提交，等待管理员确认出院；在确认前不会出现在治疗白板上，也不能再记新治疗。'
          }
        />
      ) : null}

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

      <DischargeModal
        patient={dischargeTarget}
        onClose={() => setDischargeTarget(null)}
        onSaved={() => {
          setDischargeTarget(null)
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

/**
 * 发起出院。
 *
 * `POST /patients/{no}/discharge` 要求带**该患者已提交的出院小结**的 `record_id` ——
 * 出院不是点一下按钮，而是"这份小结写完了"，所以这里只能从小结列表里挑。
 * 接口对任何登录用户开放（用户要求：「所有治疗师都能发起出院」）。
 */
function DischargeModal({
  patient,
  onClose,
  onSaved,
}: {
  patient: PatientOut | null
  onClose: () => void
  onSaved: () => void
}) {
  const [selected, setSelected] = useState<number | undefined>()
  const [saving, setSaving] = useState(false)

  // 只列**已提交/已锁定**的出院小结：后端拿不到合格小结会报错，先把选项过滤掉更清楚
  const summaries = useAsync(
    () =>
      patient
        ? recordsApi.list({
            page: 1,
            page_size: 50,
            patient_no: patient.inpatient_no,
            kind: 'discharge',
          })
        : Promise.resolve(null),
    [patient?.inpatient_no],
  )

  const candidates = (summaries.data?.items ?? []).filter(
    (r) => r.status === 'submitted' || r.status === 'locked',
  )

  const handleOk = async () => {
    if (!patient) return
    if (!selected) {
      notify.warning('请选择一份已提交的出院小结')
      return
    }
    setSaving(true)
    try {
      await patientsApi.requestDischarge(patient.inpatient_no, selected)
      notify.success('已发起出院，患者进入「待出院」，等待管理员确认')
      setSelected(undefined)
      onSaved()
    } catch (err) {
      notify.error(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={`发起出院：${patient?.name ?? ''}`}
      open={patient !== null}
      onOk={handleOk}
      onCancel={() => {
        setSelected(undefined)
        onClose()
      }}
      okText="发起出院"
      cancelText="取消"
      confirmLoading={saving}
      destroyOnHidden
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="出院小结先写完，再点这里"
        description="发起后患者进入「待出院」：从治疗师白板消失、不能再记新治疗，需管理员确认出院（或满 7 天自动出院）。"
      />
      {summaries.loading ? (
        <PageSkeleton />
      ) : summaries.error ? (
        <ErrorBox message={summaries.error} onRetry={summaries.reload} />
      ) : candidates.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="该患者还没有已提交的出院小结，无法发起出院。"
        />
      ) : (
        <List
          size="small"
          bordered
          dataSource={candidates}
          renderItem={(item) => (
            <List.Item
              onClick={() => setSelected(item.id)}
              style={{
                cursor: 'pointer',
                background: selected === item.id ? '#e6f4ff' : undefined,
              }}
            >
              <Space wrap>
                <Tag color={selected === item.id ? 'blue' : 'default'}>
                  {item.record_date}
                </Tag>
                <Typography.Text>
                  #{item.id} · {item.discipline_name ?? item.discipline} ·{' '}
                  {item.kind_label ?? item.kind}
                </Typography.Text>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {item.therapist_name ?? '—'} · {item.status === 'locked' ? '已锁定' : '已提交'}
                </Typography.Text>
              </Space>
            </List.Item>
          )}
        />
      )}
    </Modal>
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
            isEdit && patient?.status === 'pending_discharge' ? (
              <Typography.Text type="warning">
                该患者处于「待出院」（出院小结已提交）。确认出院 / 取消待出院请用**列表页的出院操作区**；
                这里直接改状态会跳过留痕动作。
              </Typography.Text>
            ) : isEdit && patient?.status === 'discharged' ? (
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
