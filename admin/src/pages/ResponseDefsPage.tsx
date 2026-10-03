/**
 * 患者反应定义（M5）—— **只读**。
 *
 * 后端目前只提供 `GET /response-defs`（`开发计划.md` 4.5 也只要求读）。
 * 页面明确标注"当前只读"，避免管理员改了没反应还以为系统出问题。
 */
import { useState } from 'react'
import { Button, Select, Space, Table, Tag, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { dictApi, responseDefsApi, type ResponseDefOut } from '../api/endpoints'
import { ErrorBox, PageHeader, PageSkeleton, useAsync } from '../components/Feedback'

const TYPE_LABEL: Record<string, { text: string; color: string }> = {
  tag: { text: '标签', color: 'blue' },
  number: { text: '数值', color: 'green' },
  select: { text: '单选', color: 'cyan' },
  text: { text: '文本', color: 'default' },
}

export function ResponseDefsPage() {
  const [mainItemId, setMainItemId] = useState<number | undefined>()

  const mainItems = useAsync(() => dictApi.mainItems(), [])
  const { data, loading, error, reload } = useAsync(
    () => responseDefsApi.list(mainItemId),
    [mainItemId],
  )

  const mainName = (id: number | null | undefined) =>
    id ? (mainItems.data?.find((m) => m.id === id)?.name ?? `#${id}`) : '全科通用'

  return (
    <>
      <PageHeader
        title="患者反应定义"
        description="记录页可选的「患者反应」项。当前为只读视图（后端暂未提供维护接口）。"
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
          </>
        }
      />

      {error ? (
        <ErrorBox message={error} onRetry={reload} />
      ) : loading ? (
        <PageSkeleton />
      ) : (
        <Table<ResponseDefOut>
          rowKey="id"
          size="middle"
          dataSource={data ?? []}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          columns={[
            { title: '显示名', dataIndex: 'label', width: 150 },
            { title: 'code', dataIndex: 'code', width: 160 },
            {
              title: '类型',
              dataIndex: 'value_type',
              width: 90,
              render: (v: string) => {
                const item = TYPE_LABEL[v] ?? { text: v, color: 'default' }
                return <Tag color={item.color}>{item.text}</Tag>
              },
            },
            {
              title: '取值标识',
              dataIndex: 'value_key',
              width: 130,
              render: (v: string | null) => v || '—',
            },
            {
              title: '单位',
              dataIndex: 'value_unit',
              width: 80,
              render: (v: string | null) => v || '—',
            },
            {
              title: '取值范围',
              key: 'range',
              width: 110,
              render: (_: unknown, r: ResponseDefOut) =>
                r.value_min === null && r.value_max === null
                  ? '—'
                  : `${r.value_min ?? '—'} ~ ${r.value_max ?? '—'}`,
            },
            {
              title: '选项',
              dataIndex: 'options',
              render: (options: string[]) =>
                options.length === 0 ? (
                  <Typography.Text type="secondary">—</Typography.Text>
                ) : (
                  <Space size={4} wrap>
                    {options.map((o) => (
                      <Tag key={o}>{o}</Tag>
                    ))}
                  </Space>
                ),
            },
            {
              title: '适用主项目',
              dataIndex: 'main_item_id',
              width: 150,
              render: (v: number | null) => mainName(v),
            },
          ]}
        />
      )}
    </>
  )
}
