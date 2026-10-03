/** 用户管理（M2）：CRUD + 重置密码 + 活跃会话查看与踢下线。 */
import { useState } from 'react'
import {
  Button,
  Drawer,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { usersApi, type AuthSessionOut, type UserOut } from '../api/endpoints'
import { errorMessage } from '../api/client'
import { ErrorBox, PageHeader, PageSkeleton, useAsync } from '../components/Feedback'
import { notify } from '../components/notify'

export function UsersPage() {
  const [page, setPage] = useState(1)
  const [role, setRole] = useState<string | undefined>()
  const [status, setStatus] = useState<string | undefined>()
  const [editing, setEditing] = useState<UserOut | null>(null)
  const [creating, setCreating] = useState(false)
  const [resetTarget, setResetTarget] = useState<UserOut | null>(null)
  const [sessionTarget, setSessionTarget] = useState<UserOut | null>(null)

  const { data, loading, error, reload } = useAsync(
    () => usersApi.list({ page, page_size: 20, role, status }),
    [page, role, status],
  )

  const columns = [
    { title: '工号', dataIndex: 'employee_no', width: 120 },
    { title: '姓名', dataIndex: 'name', width: 120 },
    {
      title: '角色',
      dataIndex: 'role',
      width: 100,
      render: (v: string) =>
        v === 'admin' ? <Tag color="gold">管理员</Tag> : <Tag color="blue">治疗师</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: string) =>
        v === 'active' ? <Tag color="green">在职</Tag> : <Tag color="default">已停用</Tag>,
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: unknown, record: UserOut) => (
        <Space size="small" wrap>
          <Button size="small" type="link" onClick={() => setEditing(record)}>
            编辑
          </Button>
          <Button size="small" type="link" onClick={() => setResetTarget(record)}>
            重置密码
          </Button>
          <Button size="small" type="link" onClick={() => setSessionTarget(record)}>
            登录会话
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        title="用户管理"
        description="维护治疗师与管理员账号、重置密码、查看并踢下线。"
        extra={
          <>
            <Select
              placeholder="角色"
              allowClear
              style={{ width: 120 }}
              value={role}
              onChange={(v) => {
                setPage(1)
                setRole(v)
              }}
              options={[
                { value: 'therapist', label: '治疗师' },
                { value: 'admin', label: '管理员' },
              ]}
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
                { value: 'active', label: '在职' },
                { value: 'disabled', label: '已停用' },
              ]}
            />
            <Button icon={<ReloadOutlined />} onClick={reload}>
              刷新
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
              新建用户
            </Button>
          </>
        }
      />

      {error ? (
        <ErrorBox message={error} onRetry={reload} />
      ) : loading ? (
        <PageSkeleton />
      ) : (
        <Table
          rowKey="id"
          size="middle"
          columns={columns}
          dataSource={data?.items ?? []}
          pagination={{
            current: page,
            pageSize: 20,
            total: data?.total ?? 0,
            showSizeChanger: false,
            onChange: setPage,
            showTotal: (t) => `共 ${t} 个账号`,
          }}
        />
      )}

      <UserFormModal
        open={creating || editing !== null}
        user={editing}
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

      <ResetPasswordModal
        user={resetTarget}
        onClose={() => setResetTarget(null)}
        onSaved={() => setResetTarget(null)}
      />

      <SessionsDrawer user={sessionTarget} onClose={() => setSessionTarget(null)} onChanged={reload} />
    </>
  )
}

function UserFormModal({
  open,
  user,
  onClose,
  onSaved,
}: {
  open: boolean
  user: UserOut | null
  onClose: () => void
  onSaved: () => void
}) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const isEdit = user !== null

  const handleOk = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      if (isEdit) {
        await usersApi.update(user.id, values)
        notify.success('已保存')
      } else {
        await usersApi.create(values)
        notify.success('已新建用户')
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
      title={isEdit ? `编辑用户 ${user?.name}` : '新建用户'}
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
              ? { name: user.name, role: user.role, status: user.status, phone: user.phone }
              : { role: 'therapist', status: 'active' },
          )
        }
      }}
    >
      <Form form={form} layout="vertical">
        {!isEdit ? (
          <>
            <Form.Item
              name="employee_no"
              label="工号"
              rules={[{ required: true, message: '请输入工号' }]}
            >
              <Input placeholder="如 T001" />
            </Form.Item>
            <Form.Item
              name="password"
              label="初始密码"
              rules={[
                { required: true, message: '请设置初始密码' },
                { min: 8, message: '至少 8 位' },
              ]}
              extra="请通过可靠方式告知本人，并提醒其首次登录后自行修改"
            >
              <Input.Password autoComplete="new-password" />
            </Form.Item>
          </>
        ) : null}
        <Form.Item name="name" label="姓名" rules={[{ required: true, message: '请输入姓名' }]}>
          <Input />
        </Form.Item>
        <Form.Item name="phone" label="联系电话">
          <Input />
        </Form.Item>
        <Form.Item
          name="role"
          label="角色"
          rules={[{ required: true }]}
          extra="系统必须保留至少一个管理员，因此不会允许把最后一个管理员降级"
        >
          <Select
            options={[
              { value: 'therapist', label: '治疗师' },
              { value: 'admin', label: '管理员' },
            ]}
          />
        </Form.Item>
        {isEdit ? (
          <Form.Item
            name="status"
            label="状态"
            extra="停用后该账号无法登录，但历史记录保留"
          >
            <Select
              options={[
                { value: 'active', label: '在职' },
                { value: 'disabled', label: '已停用' },
              ]}
            />
          </Form.Item>
        ) : null}
      </Form>
    </Modal>
  )
}

function ResetPasswordModal({
  user,
  onClose,
  onSaved,
}: {
  user: UserOut | null
  onClose: () => void
  onSaved: () => void
}) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)

  const handleOk = async () => {
    const values = await form.validateFields()
    if (!user) return
    setSaving(true)
    try {
      await usersApi.resetPassword(user.id, values.new_password)
      notify.success('密码已重置，该用户的所有登录会话已失效')
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
      title={`重置密码：${user?.name ?? ''}`}
      open={user !== null}
      onOk={handleOk}
      onCancel={() => {
        form.resetFields()
        onClose()
      }}
      confirmLoading={saving}
      okText="确认重置"
      cancelText="取消"
      destroyOnHidden
    >
      <Typography.Paragraph type="warning">
        重置后该账号在所有设备上的登录都会失效，需要用它新密码重新登录。
      </Typography.Paragraph>
      <Form form={form} layout="vertical">
        <Form.Item
          name="new_password"
          label="新密码"
          rules={[
            { required: true, message: '请输入新密码' },
            { min: 8, message: '至少 8 位' },
          ]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function SessionsDrawer({
  user,
  onClose,
  onChanged,
}: {
  user: UserOut | null
  onClose: () => void
  onChanged: () => void
}) {
  const sessions = useAsync(
    () => (user ? usersApi.sessions(user.id) : Promise.resolve([] as AuthSessionOut[])),
    [user?.id],
  )

  const handleRevoke = async () => {
    if (!user) return
    try {
      await usersApi.revokeSessions(user.id)
      notify.success('已踢下线')
      sessions.reload()
      onChanged()
    } catch (err) {
      notify.error(errorMessage(err))
    }
  }

  return (
    <Drawer
      title={`登录会话：${user?.name ?? ''}`}
      size={560}
      open={user !== null}
      onClose={onClose}
      destroyOnHidden
      extra={
        <Button danger onClick={handleRevoke}>
          全部踢下线
        </Button>
      }
    >
      {sessions.loading ? (
        <PageSkeleton />
      ) : sessions.error ? (
        <ErrorBox message={sessions.error} onRetry={sessions.reload} />
      ) : (
        <Table
          rowKey="id"
          size="small"
          dataSource={sessions.data ?? []}
          pagination={false}
          columns={[
            {
              title: '设备',
              dataIndex: 'device_info',
              render: (v: string | null) => v || <Typography.Text type="secondary">未知</Typography.Text>,
            },
            {
              title: '创建时间',
              dataIndex: 'created_at',
              width: 150,
              render: (v: string) => dayjs(v).format('MM-DD HH:mm'),
            },
            {
              title: '状态',
              dataIndex: 'revoked_at',
              width: 90,
              render: (v: string | null) =>
                v ? <Tag color="default">已吊销</Tag> : <Tag color="green">有效</Tag>,
            },
          ]}
        />
      )}
    </Drawer>
  )
}
