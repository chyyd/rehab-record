/**
 * 选项集管理（M4）：科室级 / 全局选项集维护。
 *
 * 解析顺序是 **个人 → 科室 → 全局 → 参数内置**（`设计.md` 3.6.4）。
 * 页面上提供"解析预览"，让管理员能直接看到某个 code 最终生效的是哪一层 ——
 * 否则"我改了全局却没生效"这类问题只能靠猜（多半是被某个人的个人选项盖住了）。
 */
import { useState } from 'react'
import {
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import { optionSetsApi, type OptionSetOut } from '../api/endpoints'
import { errorMessage } from '../api/client'
import { ErrorBox, PageHeader, PageSkeleton, useAsync } from '../components/Feedback'
import { notify } from '../components/notify'

const SCOPE_LABEL: Record<string, { text: string; color: string }> = {
  global: { text: '全局', color: 'blue' },
  dept: { text: '科室', color: 'cyan' },
  personal: { text: '个人', color: 'default' },
}

export function OptionSetsPage() {
  const [scope, setScope] = useState<string | undefined>('global')
  const [editing, setEditing] = useState<OptionSetOut | null>(null)
  const [creating, setCreating] = useState(false)

  const { data, loading, error, reload } = useAsync(() => optionSetsApi.all(scope), [scope])

  const remove = async (item: OptionSetOut) => {
    try {
      await optionSetsApi.remove(item.id)
      notify.success('已删除')
      reload()
    } catch (err) {
      notify.error(errorMessage(err))
    }
  }

  return (
    <>
      <PageHeader
        title="选项集管理"
        description="维护科室级与全局选项集。个人快捷选项由治疗师自己在 App 内维护，管理员不能删除。"
        extra={
          <>
            <Select
              allowClear
              placeholder="范围"
              style={{ width: 130 }}
              value={scope}
              onChange={setScope}
              options={[
                { value: 'global', label: '全局' },
                { value: 'dept', label: '科室' },
                { value: 'personal', label: '个人' },
              ]}
            />
            <Button icon={<ReloadOutlined />} onClick={reload}>
              刷新
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
              新建 / 覆盖
            </Button>
          </>
        }
      />

      {error ? (
        <ErrorBox message={error} onRetry={reload} />
      ) : loading ? (
        <PageSkeleton />
      ) : (
        <>
          <Table
            rowKey="id"
            size="middle"
            dataSource={data ?? []}
            pagination={{ pageSize: 20, showSizeChanger: false }}
            columns={[
              {
                title: '范围',
                dataIndex: 'scope',
                width: 90,
                render: (v: string) => {
                  const item = SCOPE_LABEL[v] ?? { text: v, color: 'default' }
                  return <Tag color={item.color}>{item.text}</Tag>
                },
              },
              { title: 'code', dataIndex: 'code', width: 170 },
              { title: '名称', dataIndex: 'name', width: 150 },
              { title: '科室标签', dataIndex: 'dept_tag', width: 100, render: (v: string | null) => v || '—' },
              {
                title: '选项',
                dataIndex: 'items',
                render: (items: OptionSetOut['items'], record: OptionSetOut) => (
                  <Space size={4} wrap>
                    {items.map((i) => (
                      <Tag key={i.value} color={i.is_default ? 'green' : undefined}>
                        {i.value}
                        {i.is_default ? '（默认）' : ''}
                      </Tag>
                    ))}
                    {record.scope === 'personal' ? (
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        仅本人可见
                      </Typography.Text>
                    ) : null}
                  </Space>
                ),
              },
              {
                title: '操作',
                key: 'a',
                width: 110,
                render: (_: unknown, record: OptionSetOut) => (
                  <Space size={0}>
                    <Button
                      size="small"
                      type="text"
                      icon={<EditOutlined />}
                      disabled={record.scope === 'personal'}
                      onClick={() => setEditing(record)}
                    />
                    <Popconfirm
                      title="删除该选项集？"
                      description="删除后该 code 会回落到下一层（科室 → 全局 → 参数内置）。"
                      onConfirm={() => remove(record)}
                      okText="删除"
                      cancelText="取消"
                      disabled={record.scope === 'personal'}
                    >
                      <Button
                        size="small"
                        type="text"
                        danger
                        icon={<DeleteOutlined />}
                        disabled={record.scope === 'personal'}
                      />
                    </Popconfirm>
                  </Space>
                ),
              },
            ]}
          />
          <ResolvePreview />
        </>
      )}

      <OptionSetModal
        open={creating || editing !== null}
        item={editing}
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
    </>
  )
}

/** 解析预览：输入 code，看最终生效的是哪一层。 */
function ResolvePreview() {
  const [code, setCode] = useState('')
  const [result, setResult] = useState<{ source: string; options: { value: string }[] } | null>(null)
  const [loading, setLoading] = useState(false)

  const run = async () => {
    if (!code.trim()) return
    setLoading(true)
    try {
      const data = await optionSetsApi.resolve(code.trim())
      setResult(data)
    } catch (err) {
      notify.error(errorMessage(err))
      setResult(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card size="small" title="解析预览" style={{ marginTop: 16 }}>
      <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
        查看某个 code 最终生效的是哪一层的选项。顺序：个人 → 科室 → 全局 → 参数内置。
        如果你改了全局却不生效，多半是被某个人的个人选项集盖住了。
      </Typography.Paragraph>
      <Space.Compact style={{ width: '100%', maxWidth: 520 }}>
        <Input
          placeholder="输入 code，如 side"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          onPressEnter={run}
        />
        <Button type="primary" onClick={run} loading={loading}>
          解析
        </Button>
      </Space.Compact>
      {result ? (
        <div style={{ marginTop: 12 }}>
          <Space>
            <span>生效层：</span>
            <Tag color={result.source === 'builtin' ? 'default' : 'green'}>
              {SCOPE_LABEL[result.source]?.text ?? result.source}
            </Tag>
          </Space>
          <div style={{ marginTop: 8 }}>
            {result.options.length === 0 ? (
              <Typography.Text type="secondary">该 code 没有任何选项（可能是拼错了）。</Typography.Text>
            ) : (
              result.options.map((o) => <Tag key={o.value}>{o.value}</Tag>)
            )}
          </div>
        </div>
      ) : null}
    </Card>
  )
}

function OptionSetModal({
  open,
  item,
  onClose,
  onSaved,
}: {
  open: boolean
  item: OptionSetOut | null
  onClose: () => void
  onSaved: () => void
}) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const isEdit = item !== null

  return (
    <Modal
      title={isEdit ? `覆盖选项集 ${item?.code}` : '新建 / 覆盖选项集'}
      open={open}
      onCancel={onClose}
      destroyOnHidden
      confirmLoading={saving}
      okText="保存"
      cancelText="取消"
      onOk={async () => {
        const values = await form.validateFields()
        const values_list: string[] = String(values.values)
          .split('\n')
          .map((s) => s.trim())
          .filter(Boolean)
        const defaults: string[] = Array.isArray(values.default_values)
          ? values.default_values
          : values.default_values
            ? [values.default_values]
            : []
        if (values_list.length === 0) {
          notify.warning('至少填写一个选项')
          return
        }
        const invalid = defaults.filter((d) => !values_list.includes(d))
        if (invalid.length > 0) {
          notify.warning(`默认值必须来自选项列表：${invalid.join('、')}`)
          return
        }
        setSaving(true)
        try {
          await optionSetsApi.upsert({
            code: values.code,
            name: values.name,
            values: values_list,
            dept_tag: values.dept_tag || null,
            default_values: defaults,
          })
          notify.success('已保存')
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
          form.setFieldsValue(
            isEdit
              ? {
                  code: item.code,
                  name: item.name,
                  dept_tag: item.dept_tag,
                  values: item.items.map((i) => i.value).join('\n'),
                  default_values: item.items.filter((i) => i.is_default).map((i) => i.value),
                }
              : { dept_tag: null },
          )
        }
      }}
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="code"
          label="code"
          rules={[{ required: true, message: '请输入 code' }]}
          extra="与参数的 param_key 对应，决定这个选项集覆盖哪个参数"
        >
          <Input placeholder="如 side" disabled={isEdit} />
        </Form.Item>
        <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
          <Input placeholder="如 侧别" />
        </Form.Item>
        <Form.Item
          name="dept_tag"
          label="科室标签"
          extra="留空即全局；填了（如 PT）则是科室级，只对该科室的默认解析生效"
        >
          <Input placeholder="如 PT / OT / ST" />
        </Form.Item>
        <Form.Item
          name="values"
          label="选项"
          rules={[{ required: true, message: '请填写选项' }]}
          extra="每行一个，保存时会覆盖该层的全部选项（不是追加）"
        >
          <Input.TextArea rows={5} placeholder={'左\n右\n双侧'} />
        </Form.Item>
        <Form.Item name="default_values" label="默认值" extra="必须来自上面的选项">
          <Select mode="tags" placeholder="选择或输入默认值" options={[]} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
