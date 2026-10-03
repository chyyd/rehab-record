/**
 * 科室模板管理（M6）。
 *
 * 四套标准模板由种子导入（`code` 非空），可编辑、可删除；
 * `code` 非空的模板会被"重新导种子"覆盖回标准内容 —— 页面上要提示这一点。
 */
import { useState } from 'react'
import {
  Button,
  Col,
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
import { DeleteOutlined, EditOutlined, ReloadOutlined, EyeOutlined } from '@ant-design/icons'
import { dictApi, templatesApi, type SubItemOut, type TemplateOut } from '../api/endpoints'
import { errorMessage } from '../api/client'
import { ErrorBox, PageHeader, PageSkeleton, useAsync } from '../components/Feedback'
import { notify } from '../components/notify'

export function TemplatesPage() {
  const [mainItemId, setMainItemId] = useState<number | undefined>()
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<TemplateOut | null>(null)
  const [previewing, setPreviewing] = useState<TemplateOut | null>(null)

  const mainItems = useAsync(() => dictApi.mainItems(), [])
  const { data, loading, error, reload } = useAsync(
    () => templatesApi.list(mainItemId),
    [mainItemId],
  )

  const remove = async (item: TemplateOut) => {
    try {
      await templatesApi.remove(item.id)
      notify.success('已删除')
      reload()
    } catch (err) {
      notify.error(errorMessage(err))
    }
  }

  return (
    <>
      <PageHeader
        title="科室模板"
        description="一键套用的子项目组合。四套标准模板（运动/生活/言语/吞咽）由种子导入，参数预填值取自字典默认值。"
        extra={
          <>
            <Select
              allowClear
              placeholder="按主项目筛选"
              style={{ width: 200 }}
              value={mainItemId}
              onChange={setMainItemId}
              options={(mainItems.data ?? []).map((m) => ({ value: m.id, label: m.name }))}
            />
            <Button icon={<ReloadOutlined />} onClick={reload}>
              刷新
            </Button>
            <Button type="primary" onClick={() => setCreating(true)}>
              新建模板
            </Button>
          </>
        }
      />

      {error ? (
        <ErrorBox message={error} onRetry={reload} />
      ) : loading ? (
        <PageSkeleton />
      ) : (
        <Table<TemplateOut>
          rowKey="id"
          size="middle"
          dataSource={data ?? []}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          columns={[
            {
              title: '模板名称',
              dataIndex: 'name',
              render: (v: string, r: TemplateOut) => (
                <Space size={4}>
                  <span>{v}</span>
                  {r.code ? (
                    <Tooltip title="由种子导入的标准模板：重新执行数据初始化会把它恢复为标准内容">
                      <Tag color="blue">标准</Tag>
                    </Tooltip>
                  ) : (
                    <Tag>自建</Tag>
                  )}
                  {r.scope === 'personal' ? <Tag color="default">个人</Tag> : null}
                </Space>
              ),
            },
            {
              title: '所属主项目',
              dataIndex: 'main_item_id',
              width: 200,
              render: (v: number) => mainItems.data?.find((m) => m.id === v)?.name ?? `#${v}`,
            },
            {
              title: '子项目数',
              dataIndex: 'items',
              width: 100,
              render: (items: TemplateOut['items']) => `${items.length} 项`,
            },
            {
              title: '操作',
              key: 'a',
              width: 190,
              render: (_: unknown, record: TemplateOut) => (
                <Space size="small">
                  <Button size="small" type="link" icon={<EyeOutlined />} onClick={() => setPreviewing(record)}>
                    查看
                  </Button>
                  <Button size="small" type="link" icon={<EditOutlined />} onClick={() => setEditing(record)}>
                    编辑
                  </Button>
                  <Popconfirm
                    title="删除该模板？"
                    description="删除后治疗师就不能再一键套用它了。"
                    onConfirm={() => remove(record)}
                    okText="删除"
                    cancelText="取消"
                  >
                    <Button size="small" type="link" danger icon={<DeleteOutlined />}>
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      )}

      <TemplateFormModal
        open={creating || editing !== null}
        template={editing}
        mainItems={mainItems.data ?? []}
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

      <TemplatePreviewModal template={previewing} onClose={() => setPreviewing(null)} />
    </>
  )
}

function TemplatePreviewModal({
  template,
  onClose,
}: {
  template: TemplateOut | null
  onClose: () => void
}) {
  const preview = useAsync(
    () => (template ? templatesApi.apply(template.id) : Promise.resolve(null)),
    [template?.id],
  )

  return (
    <Modal
      title={`模板预览：${template?.name ?? ''}`}
      open={template !== null}
      onCancel={onClose}
      footer={null}
      width={640}
      destroyOnHidden
    >
      {preview.loading ? (
        <PageSkeleton />
      ) : preview.error ? (
        <ErrorBox message={preview.error} onRetry={preview.reload} />
      ) : (
        <>
          <Typography.Paragraph type="secondary">
            下面是"一键套用"后预填进记录表单的内容。套用只是预填，治疗师仍可自由修改。
          </Typography.Paragraph>
          <Table
            rowKey={(r) => String((r as { sub_item_id: number }).sub_item_id)}
            size="small"
            pagination={false}
            dataSource={
              ((preview.data?.items as { sub_item_id: number; sub_item_name: string; params: Record<string, unknown> }[]) ??
                [])
            }
            columns={[
              { title: '子项目', dataIndex: 'sub_item_name' },
              {
                title: '预填参数',
                dataIndex: 'params',
                render: (params: Record<string, unknown>) => {
                  const entries = Object.entries(params ?? {})
                  if (entries.length === 0) {
                    return <Typography.Text type="secondary">无（需手填）</Typography.Text>
                  }
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
        </>
      )}
    </Modal>
  )
}

function TemplateFormModal({
  open,
  template,
  mainItems,
  onClose,
  onSaved,
}: {
  open: boolean
  template: TemplateOut | null
  mainItems: { id: number; name: string }[]
  onClose: () => void
  onSaved: () => void
}) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [subItems, setSubItems] = useState<SubItemOut[]>([])
  const [mainItemId, setMainItemId] = useState<number | undefined>()
  const isEdit = template !== null

  const loadSubItems = async (id: number) => {
    try {
      setSubItems(await dictApi.subItems(id))
    } catch (error) {
      notify.error(errorMessage(error))
    }
  }

  return (
    <Modal
      title={isEdit ? `编辑模板 ${template?.name}` : '新建模板'}
      open={open}
      onCancel={onClose}
      destroyOnHidden
      confirmLoading={saving}
      okText="保存"
      cancelText="取消"
      width={620}
      onOk={async () => {
        const values = await form.validateFields()
        setSaving(true)
        try {
          const items = (values.sub_item_ids as number[]).map((sub_item_id) => ({
            sub_item_id,
            // 新建时不给参数，让记录页按字典默认值带入；已有参数不在这里覆盖
            params: {},
          }))
          if (isEdit) {
            await templatesApi.update(template!.id, {
              name: values.name,
              main_item_id: values.main_item_id,
              items,
            })
          } else {
            await templatesApi.create({
              name: values.name,
              scope: 'dept',
              main_item_id: values.main_item_id,
              items,
            })
          }
          notify.success('已保存')
          form.resetFields()
          setSubItems([])
          setMainItemId(undefined)
          onSaved()
        } catch (error) {
          notify.error(errorMessage(error))
        } finally {
          setSaving(false)
        }
      }}
      afterOpenChange={(v) => {
        if (!v) return
        if (isEdit) {
          form.setFieldsValue({
            name: template!.name,
            main_item_id: template!.main_item_id,
            sub_item_ids: template!.items.map((i) => i.sub_item_id),
          })
          setMainItemId(template!.main_item_id)
          void loadSubItems(template!.main_item_id)
        } else {
          form.resetFields()
          setSubItems([])
          setMainItemId(undefined)
        }
      }}
    >
      <Row gutter={12}>
        <Col span={12}>
          <Form.Item name="name" label="模板名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如 运动功能障碍训练·常规" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item
            name="main_item_id"
            label="所属主项目"
            rules={[{ required: true, message: '请选择主项目' }]}
            extra="模板必须归属一个主项目，且只能选该项目下的子项目"
          >
            <Select
              placeholder="选择主项目"
              options={mainItems.map((m) => ({ value: m.id, label: m.name }))}
              onChange={(id: number) => {
                setMainItemId(id)
                form.setFieldValue('sub_item_ids', [])
                void loadSubItems(id)
              }}
            />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item
        name="sub_item_ids"
        label="包含的子项目"
        rules={[{ required: true, message: '请至少选择一个子项目' }]}
      >
        <Select
          mode="multiple"
          placeholder={mainItemId ? '选择子项目' : '请先选择主项目'}
          disabled={!mainItemId}
          optionFilterProp="label"
          options={subItems.map((s) => ({ value: s.id, label: s.name }))}
        />
      </Form.Item>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }}>
        预填参数取自字典里的参数默认值。需要为模板单独指定参数时，请到治疗师端的记录页调整。
      </Typography.Paragraph>
    </Modal>
  )
}
