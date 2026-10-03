/**
 * 字典管理（M3）：主项目 / 子项目 / 参数定义三级 CRUD。
 *
 * 删除语义与后端一致：用过的子项目**只会被停用**，接口会返回 `soft_deleted` 与
 * `reason`。这里必须把这件事如实告诉管理员 —— 显示"删除成功"却在列表里又看到它，
 * 会让人以为系统坏了。
 */
import { useState } from 'react'
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import {
  dictApi,
  type DeleteResultOut,
  type MainItemOut,
  type ParamDefOut,
  type SubItemOut,
} from '../api/endpoints'
import { errorMessage } from '../api/client'
import { ErrorBox, PageHeader, PageSkeleton, useAsync } from '../components/Feedback'
import { notify } from '../components/notify'

const INPUT_TYPE_LABEL: Record<string, string> = {
  select: '单选',
  multi_select: '多选',
  number: '数字',
  text: '文本',
}

/** 把后端返回的删除结果转成提示：软删时必须说清楚发生了什么。 */
function reportDelete(result: DeleteResultOut, onDone: () => void) {
  if (result.deleted) {
    notify.success('已删除')
  } else {
    notify.info_modal({
      title: '该项已被使用，已改为停用',
      content: (
        <>
          <Typography.Paragraph>{result.reason ?? '该项目已有历史数据引用，无法物理删除。'}</Typography.Paragraph>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            历史治疗记录不受影响（记录里保存了当时的名称与参数快照）；它只是不会再出现在新记录的选项里。
          </Typography.Paragraph>
        </>
      ),
      okText: '知道了',
    })
  }
  onDone()
}

export function DictPage() {
  const [selectedMain, setSelectedMain] = useState<number | null>(null)
  const [selectedSub, setSelectedSub] = useState<number | null>(null)
  const [mainModal, setMainModal] = useState<{ open: boolean; item: MainItemOut | null }>({
    open: false,
    item: null,
  })
  const [subModal, setSubModal] = useState<{ open: boolean; item: SubItemOut | null }>({
    open: false,
    item: null,
  })
  const [paramModal, setParamModal] = useState<{ open: boolean; item: ParamDefOut | null }>({
    open: false,
    item: null,
  })

  const tree = useAsync(() => dictApi.tree(), [])
  const mainItems = useAsync(() => dictApi.mainItems(), [])
  const subItems = useAsync(
    () => (selectedMain ? dictApi.subItems(selectedMain) : Promise.resolve([] as SubItemOut[])),
    [selectedMain],
  )
  const params = useAsync(
    () => (selectedSub ? dictApi.params(selectedSub) : Promise.resolve([] as ParamDefOut[])),
    [selectedSub],
  )

  const reloadAll = () => {
    tree.reload()
    mainItems.reload()
    subItems.reload()
    params.reload()
  }

  const removeMain = async (item: MainItemOut) => {
    try {
      reportDelete(await dictApi.deleteMainItem(item.id), reloadAll)
    } catch (error) {
      notify.error(errorMessage(error))
    }
  }

  const removeSub = async (item: SubItemOut) => {
    try {
      reportDelete(await dictApi.deleteSubItem(item.id), reloadAll)
    } catch (error) {
      notify.error(errorMessage(error))
    }
  }

  const removeParam = async (item: ParamDefOut) => {
    try {
      reportDelete(await dictApi.deleteParam(item.id), reloadAll)
    } catch (error) {
      notify.error(errorMessage(error))
    }
  }

  // 首次取到主项目后默认选中第一项，避免右侧空着让人以为坏了
  const mains = mainItems.data ?? []
  if (selectedMain === null && mains.length > 0) {
    setTimeout(() => setSelectedMain(mains[0].id), 0)
  }
  const subs = subItems.data ?? []
  if (selectedSub === null && subs.length > 0) {
    setTimeout(() => setSelectedSub(subs[0].id), 0)
  }

  if (mainItems.loading && mains.length === 0) return <PageSkeleton />
  if (mainItems.error) return <ErrorBox message={mainItems.error} onRetry={reloadAll} />

  return (
    <>
      <PageHeader
        title="字典管理"
        description="维护主项目 / 子项目 / 参数定义。被历史记录引用过的项只能停用，不会真正删除。"
        extra={
          <Button icon={<ReloadOutlined />} onClick={reloadAll}>
            刷新
          </Button>
        }
      />

      <Row gutter={16}>
        <Col xs={24} lg={7}>
          <Card
            size="small"
            title="主项目"
            extra={
              <Button
                size="small"
                type="link"
                icon={<PlusOutlined />}
                onClick={() => setMainModal({ open: true, item: null })}
              >
                新建
              </Button>
            }
          >
            <Table
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={mains}
              rowClassName={(r) => (r.id === selectedMain ? 'ant-table-row-selected' : '')}
              onRow={(record) => ({
                onClick: () => {
                  setSelectedMain(record.id)
                  setSelectedSub(null)
                },
                style: { cursor: 'pointer' },
              })}
              columns={[
                {
                  title: '名称',
                  dataIndex: 'name',
                  render: (v: string, r: MainItemOut) => (
                    <Space size={4}>
                      <span>{v}</span>
                      {r.status !== 'active' ? <Tag>停用</Tag> : null}
                    </Space>
                  ),
                },
                {
                  title: '',
                  key: 'a',
                  width: 70,
                  render: (_: unknown, r: MainItemOut) => (
                    <Space size={0}>
                      <Button
                        size="small"
                        type="text"
                        icon={<EditOutlined />}
                        onClick={(e) => {
                          e.stopPropagation()
                          setMainModal({ open: true, item: r })
                        }}
                      />
                      <Popconfirm
                        title="删除主项目？"
                        description="其下若有启用的子项目会被拒绝。"
                        onConfirm={() => removeMain(r)}
                        okText="删除"
                        cancelText="取消"
                      >
                        <Button
                          size="small"
                          type="text"
                          danger
                          icon={<DeleteOutlined />}
                          onClick={(e) => e.stopPropagation()}
                        />
                      </Popconfirm>
                    </Space>
                  ),
                },
              ]}
            />
          </Card>
        </Col>

        <Col xs={24} lg={8}>
          <Card
            size="small"
            title="子项目"
            extra={
              <Button
                size="small"
                type="link"
                icon={<PlusOutlined />}
                disabled={selectedMain === null}
                onClick={() => setSubModal({ open: true, item: null })}
              >
                新建
              </Button>
            }
          >
            {selectedMain === null ? (
              <Typography.Text type="secondary">请先选择左侧主项目。</Typography.Text>
            ) : (
              <Table
                rowKey="id"
                size="small"
                pagination={false}
                dataSource={subs}
                onRow={(record) => ({
                  onClick: () => setSelectedSub(record.id),
                  style: { cursor: 'pointer' },
                })}
                rowClassName={(r) => (r.id === selectedSub ? 'ant-table-row-selected' : '')}
                columns={[
                  {
                    title: '名称',
                    dataIndex: 'name',
                    render: (v: string, r: SubItemOut) => (
                      <Space size={4}>
                        <span>{v}</span>
                        {r.status !== 'active' ? <Tag color="default">停用</Tag> : null}
                      </Space>
                    ),
                  },
                  { title: 'code', dataIndex: 'code', width: 130, ellipsis: true },
                  {
                    title: '',
                    key: 'a',
                    width: 70,
                    render: (_: unknown, r: SubItemOut) => (
                      <Space size={0}>
                        <Button
                          size="small"
                          type="text"
                          icon={<EditOutlined />}
                          onClick={(e) => {
                            e.stopPropagation()
                            setSubModal({ open: true, item: r })
                          }}
                        />
                        <Popconfirm
                          title="删除子项目？"
                          description="若已被记录或模板引用，将改为停用。"
                          onConfirm={() => removeSub(r)}
                          okText="删除"
                          cancelText="取消"
                        >
                          <Button
                            size="small"
                            type="text"
                            danger
                            icon={<DeleteOutlined />}
                            onClick={(e) => e.stopPropagation()}
                          />
                        </Popconfirm>
                      </Space>
                    ),
                  },
                ]}
              />
            )}
          </Card>
        </Col>

        <Col xs={24} lg={9}>
          <Card
            size="small"
            title="参数定义"
            extra={
              <Button
                size="small"
                type="link"
                icon={<PlusOutlined />}
                disabled={selectedSub === null}
                onClick={() => setParamModal({ open: true, item: null })}
              >
                新建
              </Button>
            }
          >
            {selectedSub === null ? (
              <Typography.Text type="secondary">请先选择中间的子项目。</Typography.Text>
            ) : (
              <Table
                rowKey="id"
                size="small"
                pagination={false}
                dataSource={params.data ?? []}
                columns={[
                  { title: '显示名', dataIndex: 'param_name', ellipsis: true },
                  { title: '键', dataIndex: 'param_key', width: 110, ellipsis: true },
                  {
                    title: '类型',
                    dataIndex: 'input_type',
                    width: 64,
                    render: (v: string) => <Tag>{INPUT_TYPE_LABEL[v] ?? v}</Tag>,
                  },
                  {
                    title: '默认值',
                    dataIndex: 'default_value',
                    width: 90,
                    ellipsis: true,
                    render: (v: string | null) => v ?? <Typography.Text type="secondary">—</Typography.Text>,
                  },
                  {
                    title: '',
                    key: 'a',
                    width: 70,
                    render: (_: unknown, r: ParamDefOut) => (
                      <Space size={0}>
                        <Button
                          size="small"
                          type="text"
                          icon={<EditOutlined />}
                          onClick={() => setParamModal({ open: true, item: r })}
                        />
                        <Popconfirm
                          title="删除参数？"
                          onConfirm={() => removeParam(r)}
                          okText="删除"
                          cancelText="取消"
                        >
                          <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                        </Popconfirm>
                      </Space>
                    ),
                  },
                ]}
              />
            )}
          </Card>
        </Col>
      </Row>

      <MainItemModal
        {...mainModal}
        onClose={() => setMainModal({ open: false, item: null })}
        onSaved={() => {
          setMainModal({ open: false, item: null })
          reloadAll()
        }}
      />
      <SubItemModal
        {...subModal}
        mainItemId={selectedMain}
        mainItemName={mains.find((m) => m.id === selectedMain)?.name}
        existingCodes={(subs ?? []).map((s) => s.code)}
        onClose={() => setSubModal({ open: false, item: null })}
        onSaved={() => {
          setSubModal({ open: false, item: null })
          reloadAll()
        }}
      />
      <ParamModal
        {...paramModal}
        subItemId={selectedSub}
        onClose={() => setParamModal({ open: false, item: null })}
        onSaved={() => {
          setParamModal({ open: false, item: null })
          reloadAll()
        }}
      />
    </>
  )
}

function MainItemModal({
  open,
  item,
  onClose,
  onSaved,
}: {
  open: boolean
  item: MainItemOut | null
  onClose: () => void
  onSaved: () => void
}) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const isEdit = item !== null

  return (
    <Modal
      title={isEdit ? `编辑主项目 ${item?.name}` : '新建主项目'}
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
          if (isEdit) await dictApi.updateMainItem(item!.id, values)
          else await dictApi.createMainItem(values)
          notify.success('已保存')
          form.resetFields()
          onSaved()
        } catch (error) {
          notify.error(errorMessage(error))
        } finally {
          setSaving(false)
        }
      }}
      afterOpenChange={(v) => {
        if (v) form.setFieldsValue(isEdit ? { ...item } : { sort: 0 })
      }}
    >
      <Form form={form} layout="vertical">
        <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
          <Input placeholder="如 运动功能障碍训练" />
        </Form.Item>
        <Form.Item
          name="code"
          label="code"
          rules={[{ required: true, message: '请输入 code' }]}
          extra="业务键，全局唯一；历史数据与同步靠它关联，创建后不建议修改"
        >
          <Input placeholder="如 motor_function" />
        </Form.Item>
        <Form.Item name="alias" label="别名">
          <Input placeholder="如 PT" />
        </Form.Item>
        <Form.Item name="sort" label="排序">
          <InputNumber min={0} style={{ width: '100%' }} />
        </Form.Item>
        {isEdit ? (
          <Form.Item name="status" label="状态" extra="停用后不再出现在记录页的选项里">
            <Select
              options={[
                { value: 'active', label: '启用' },
                { value: 'disabled', label: '停用' },
              ]}
            />
          </Form.Item>
        ) : null}
      </Form>
    </Modal>
  )
}

function SubItemModal({
  open,
  item,
  mainItemId,
  mainItemName,
  existingCodes,
  onClose,
  onSaved,
}: {
  open: boolean
  item: SubItemOut | null
  mainItemId: number | null
  mainItemName?: string
  existingCodes: string[]
  onClose: () => void
  onSaved: () => void
}) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const isEdit = item !== null

  return (
    <Modal
      title={isEdit ? `编辑子项目 ${item?.name}` : `新建子项目${mainItemName ? `（${mainItemName}）` : ''}`}
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
          if (isEdit) await dictApi.updateSubItem(item!.id, values)
          else await dictApi.createSubItem({ ...values, main_item_id: mainItemId })
          notify.success('已保存')
          form.resetFields()
          onSaved()
        } catch (error) {
          notify.error(errorMessage(error))
        } finally {
          setSaving(false)
        }
      }}
      afterOpenChange={(v) => {
        if (v) form.setFieldsValue(isEdit ? { ...item } : { sort: 0 })
      }}
    >
      <Form form={form} layout="vertical">
        <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
          <Input placeholder="如 偏瘫肢体综合训练" />
        </Form.Item>
        <Form.Item
          name="code"
          label="code"
          rules={[{ required: true, message: '请输入 code' }]}
          extra={
            existingCodes.length > 0
              ? `建议命名：${mainItemName ?? '主项目'}_编号。全局唯一。`
              : '全局唯一'
          }
        >
          <Input placeholder="如 motor_function_01" />
        </Form.Item>
        <Form.Item name="sort" label="排序">
          <InputNumber min={0} style={{ width: '100%' }} />
        </Form.Item>
        {isEdit ? (
          <Form.Item
            name="main_item_id"
            label="所属主项目"
            extra="可把子项目移到另一个主项目下"
          >
            <InputNumber style={{ width: '100%' }} />
          </Form.Item>
        ) : null}
        {isEdit ? (
          <Form.Item name="status" label="状态">
            <Select
              options={[
                { value: 'active', label: '启用' },
                { value: 'disabled', label: '停用' },
              ]}
            />
          </Form.Item>
        ) : null}
      </Form>
    </Modal>
  )
}

function ParamModal({
  open,
  item,
  subItemId,
  onClose,
  onSaved,
}: {
  open: boolean
  item: ParamDefOut | null
  subItemId: number | null
  onClose: () => void
  onSaved: () => void
}) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [inputType, setInputType] = useState<string>('select')
  const isEdit = item !== null

  return (
    <Modal
      title={isEdit ? `编辑参数 ${item?.param_name}` : '新建参数定义'}
      open={open}
      onCancel={onClose}
      destroyOnHidden
      confirmLoading={saving}
      okText="保存"
      cancelText="取消"
      width={560}
      onOk={async () => {
        const values = await form.validateFields()
        const payload: Record<string, unknown> = {
          param_key: values.param_key,
          param_name: values.param_name,
          input_type: values.input_type,
          required: values.required ? 1 : 0,
          unit: values.unit || null,
          sort: values.sort ?? 0,
        }
        if (values.input_type === 'select' || values.input_type === 'multi_select') {
          payload.options = values.options ?? []
          payload.default_value = values.default_value ?? null
        } else {
          payload.options = []
          payload.default_value = values.default_value ?? null
        }
        setSaving(true)
        try {
          if (isEdit) await dictApi.updateParam(item!.id, payload)
          else await dictApi.createParam(subItemId!, payload)
          notify.success('已保存')
          form.resetFields()
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
          // 单选默认值在库里是长度 1 的数组，表单要拿标量
          let def: unknown = item!.default_value
          if (item!.input_type === 'select' && typeof def === 'string') {
            try {
              const parsed = JSON.parse(def)
              def = Array.isArray(parsed) ? parsed[0] : parsed
            } catch {
              /* 非 JSON 就原样展示 */
            }
          } else if (item!.input_type === 'multi_select' && typeof def === 'string') {
            try {
              def = JSON.parse(def)
            } catch {
              /* 原样 */
            }
          } else if (item!.input_type === 'number' && typeof def === 'string') {
            def = Number(def)
          }
          form.setFieldsValue({ ...item, default_value: def ?? undefined })
          setInputType(item!.input_type)
        } else {
          form.setFieldsValue({ input_type: 'select', required: false, sort: 0 })
          setInputType('select')
        }
      }}
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="param_name"
          label="显示名"
          rules={[{ required: true, message: '请输入显示名' }]}
        >
          <Input placeholder="如 体位" />
        </Form.Item>
        <Form.Item
          name="param_key"
          label="键（param_key）"
          rules={[{ required: true, message: '请输入 param_key' }]}
          extra="记录里以它作 JSON 键，同一子项目内唯一"
        >
          <Input placeholder="如 position" />
        </Form.Item>
        <Form.Item name="input_type" label="输入类型" rules={[{ required: true }]}>
          <Select
            onChange={setInputType}
            options={Object.entries(INPUT_TYPE_LABEL).map(([value, label]) => ({ value, label }))}
          />
        </Form.Item>

        {inputType === 'select' || inputType === 'multi_select' ? (
          <Form.Item
            name="options"
            label="选项"
            rules={[{ required: true, message: '选择题至少要有一个选项' }]}
            extra="每行一个选项"
          >
            <Input.TextArea rows={4} placeholder={'仰卧\n俯卧\n坐位'} />
          </Form.Item>
        ) : null}

        <Form.Item
          name="default_value"
          label="默认值"
          extra={
            inputType === 'select'
              ? '必须来自上面的选项'
              : inputType === 'multi_select'
                ? '必须来自上面的选项（可多个）'
                : '数字型填数字，留空表示无默认值'
          }
        >
          {inputType === 'select' || inputType === 'multi_select' ? (
            <Select
              mode={inputType === 'multi_select' ? 'multiple' : undefined}
              allowClear
              placeholder="选择默认值"
              options={(Form.useWatch('options', form) ?? [])
                .map((line: string) => String(line).trim())
                .filter(Boolean)
                .map((v: string) => ({ value: v, label: v }))}
            />
          ) : inputType === 'number' ? (
            <InputNumber style={{ width: '100%' }} />
          ) : (
            <Input />
          )}
        </Form.Item>

        <Form.Item name="unit" label="单位">
          <Input placeholder="如 次 / 分钟 / 级" style={{ width: 180 }} />
        </Form.Item>
        <Form.Item name="required" label="必填" valuePropName="checked">
          <Switch />
        </Form.Item>
        <Form.Item name="sort" label="排序">
          <InputNumber min={0} style={{ width: 180 }} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
