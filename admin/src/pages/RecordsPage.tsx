/**
 * 治疗记录查阅：列表筛选 + 明细（SOAP 纯文本）+ 锁定。
 *
 * 2026-10-05（脊柱级改造后）：
 * - 记录内容由 `templates/*.json` **文件**驱动，记录是「结构化 `body` + 生成时冻结的
 *   `rendered_text`」两件东西。**界面以 `rendered_text` 为准**（它就是签名文书上的文字），
 *   `body` 只作折叠的排查视图 —— 因此这里**没有表格**：表格会把 A4 上的行文拆散，
 *   与打印出来的东西不一致，反而误导。
 * - 旧的 `items` / `session_period`（半日）/ `duration_min` / `patient_response`
 *   后端已彻底删除，这里也不再有任何渲染：同一患者同一天同一大类至多 2 条，
 *   不再按"上午/下午"占位。
 */
import { useState } from 'react'
import {
  Button,
  Collapse,
  DatePicker,
  Descriptions,
  Drawer,
  Empty,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import type { Dayjs } from 'dayjs'
import { recordsApi, usersApi, type RecordListItemOut, type RecordOut } from '../api/endpoints'
import { errorMessage } from '../api/client'
import { ErrorBox, PageHeader, PageSkeleton, useAsync } from '../components/Feedback'
import { useAuth } from '../auth/AuthProvider'
import { notify } from '../components/notify'

const STATUS_LABEL: Record<string, { text: string; color: string }> = {
  draft: { text: '草稿', color: 'default' },
  submitted: { text: '已提交', color: 'blue' },
  locked: { text: '已锁定', color: 'green' },
}

/**
 * 四大类的中文名。
 *
 * 后端在列表里已经给了 `discipline_name`（来自 `templates/disciplines.json`），
 * 这里只作**离线兜底**：万一字段缺失（旧缓存、接口裁剪）也不至于把 `ST_SW` 直接甩给用户。
 * `templates/disciplines.json` 是权威来源，改名字会同时改后端返回值 —— 不会漂移。
 */
const DISCIPLINE_LABEL: Record<string, string> = {
  PT: '运动',
  OT: '生活技能',
  ST_SW: '吞咽',
  ST_SP: '言语',
}

/** 形态的中文名（后端 `record_template.KIND_LABELS`，同名同义）。 */
const KIND_LABEL: Record<string, string> = {
  initial: '首评',
  daily: '日常',
  reassessment: '阶段性复评',
  discharge: '出院小结',
}

const KIND_COLOR: Record<string, string> = {
  initial: 'purple',
  daily: 'default',
  reassessment: 'geekblue',
  discharge: 'orange',
}

const DISCIPLINE_OPTIONS = Object.entries(DISCIPLINE_LABEL).map(([value, label]) => ({ value, label }))
const KIND_OPTIONS = Object.entries(KIND_LABEL).map(([value, label]) => ({ value, label }))

const disciplineText = (r: { discipline: string; discipline_name?: string | null }) =>
  r.discipline_name || DISCIPLINE_LABEL[r.discipline] || r.discipline

const kindText = (r: { kind: string; kind_label?: string | null }) =>
  r.kind_label || KIND_LABEL[r.kind] || r.kind

export function RecordsPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState<string | undefined>()
  const [therapistId, setTherapistId] = useState<number | undefined>()
  const [discipline, setDiscipline] = useState<string | undefined>()
  const [kind, setKind] = useState<string | undefined>()
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
        discipline,
        kind,
        patient_no: patientNo || undefined,
        from: range?.[0]?.format('YYYY-MM-DD'),
        to: range?.[1]?.format('YYYY-MM-DD'),
      }),
    [
      page,
      status,
      therapistId,
      discipline,
      kind,
      patientNo,
      range?.[0]?.valueOf(),
      range?.[1]?.valueOf(),
    ],
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
        description="查阅治疗记录（SOAP 纯文本）。已提交的记录由触发器自动留痕，锁定后治疗师不能再修改。评估文书（首评/复评/出院小结）不计治疗次数。"
        extra={
          <>
            <Select
              allowClear
              placeholder="状态"
              style={{ width: 110 }}
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
              placeholder="大类"
              style={{ width: 120 }}
              value={discipline}
              onChange={(v) => {
                setPage(1)
                setDiscipline(v)
              }}
              options={DISCIPLINE_OPTIONS}
            />
            <Select
              allowClear
              placeholder="形态"
              style={{ width: 140 }}
              value={kind}
              onChange={(v) => {
                setPage(1)
                setKind(v)
              }}
              options={KIND_OPTIONS}
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
            { title: '日期', dataIndex: 'record_date', width: 105 },
            {
              title: '患者',
              key: 'patient',
              width: 150,
              render: (_: unknown, r: RecordListItemOut) => (
                <span>
                  {r.patient_name}
                  <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 6 }}>
                    {r.patient_no}
                  </Typography.Text>
                </span>
              ),
            },
            {
              title: '大类',
              key: 'discipline',
              width: 90,
              render: (_: unknown, r: RecordListItemOut) => <Tag>{disciplineText(r)}</Tag>,
            },
            {
              title: '形态',
              key: 'kind',
              width: 110,
              render: (_: unknown, r: RecordListItemOut) => (
                <Tag color={KIND_COLOR[r.kind] ?? 'default'}>{kindText(r)}</Tag>
              ),
            },
            {
              title: '治疗师',
              key: 'therapist',
              width: 110,
              render: (_: unknown, r: RecordListItemOut) => (
                <span>
                  {r.therapist_name}
                  {r.is_temporary ? (
                    <Tag color="orange" style={{ marginLeft: 4 }}>
                      临时
                    </Tag>
                  ) : null}
                </span>
              ),
            },
            {
              title: '序次',
              dataIndex: 'seq_no',
              width: 90,
              render: (v: number | null, r: RecordListItemOut) => {
                if (r.kind !== 'daily') {
                  // 评估文书不占日常次数 —— 把"第几次"显示在评估文书上是错的
                  return <Typography.Text type="secondary">—</Typography.Text>
                }
                return v ? `第 ${v} 次` : <Typography.Text type="secondary">草稿</Typography.Text>
              },
            },
            {
              title: '内容摘要',
              key: 'excerpt',
              ellipsis: true,
              render: (_: unknown, r: RecordListItemOut) => {
                const text = r.rendered_excerpt || r.rendered_text || ''
                return text ? (
                  text
                ) : (
                  <Typography.Text type="secondary">（未提交，暂无文本）</Typography.Text>
                )
              },
            },
            {
              title: '状态',
              dataIndex: 'status',
              width: 88,
              render: (v: string) => {
                const item = STATUS_LABEL[v] ?? { text: v, color: 'default' }
                return <Tag color={item.color}>{item.text}</Tag>
              },
            },
            {
              title: '修改次数',
              dataIndex: 'edit_count',
              width: 88,
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

/** 结构化的 `body` 值转成可读字符串（`body` 只用于排查，不做美化）。 */
function bodyValueText(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (Array.isArray(value)) return value.length === 0 ? '—' : value.map((v) => String(v)).join('、')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
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
      size={760}
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
            <Descriptions.Item label="治疗师">
              {record.therapist_name}
              {record.is_temporary ? '（临时）' : ''}
            </Descriptions.Item>
            <Descriptions.Item label="日期">{record.record_date}</Descriptions.Item>
            <Descriptions.Item label="大类">{disciplineText(record)}</Descriptions.Item>
            <Descriptions.Item label="形态">
              <Tag color={KIND_COLOR[record.kind] ?? 'default'}>{kindText(record)}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="序次">
              {record.kind === 'daily'
                ? record.seq_no
                  ? `第 ${record.seq_no} 次日常`
                  : '草稿（未占序次）'
                : /* 评估文书不计次数、也没有"挂靠第几次"的概念了
                     （2026-10-06 复评改成每 30 个自然日一次，span_seq 列已删） */
                  '评估文书（不计次数）'}
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              {STATUS_LABEL[record.status]?.text ?? record.status}
            </Descriptions.Item>
            <Descriptions.Item label="修改次数">{record.edit_count}</Descriptions.Item>
            <Descriptions.Item label="提交时间" span={2}>
              {record.submitted_at ?? '—'}
            </Descriptions.Item>
            <Descriptions.Item label="锁定时间" span={2}>
              {record.locked_at ?? '—'}
            </Descriptions.Item>
            {record.note ? (
              <Descriptions.Item label="备注" span={2}>
                {record.note}
              </Descriptions.Item>
            ) : null}
          </Descriptions>

          <Typography.Title level={5} style={{ marginTop: 20 }}>
            记录正文（SOAP）
          </Typography.Title>
          {record.rendered_text ? (
            <pre
              style={{
                background: '#fafafa',
                border: '1px solid #f0f0f0',
                borderRadius: 6,
                padding: 12,
                margin: 0,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                fontFamily:
                  'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace',
                fontSize: 13,
                lineHeight: 1.7,
                maxHeight: 460,
                overflow: 'auto',
              }}
            >
              {record.rendered_text}
            </pre>
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="这条记录还没有正文（草稿尚未生成 / 未提交）。"
            />
          )}

          <Collapse
            style={{ marginTop: 16 }}
            items={[
              {
                key: 'body',
                label: `结构化答案（body，共 ${Object.keys(record.body ?? {}).length} 项）`,
                children: (
                  <>
                    <Descriptions column={1} size="small" bordered>
                      {Object.entries(record.body ?? {}).map(([key, value]) => (
                        <Descriptions.Item key={key} label={key}>
                          {bodyValueText(value)}
                        </Descriptions.Item>
                      ))}
                    </Descriptions>
                    <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 8 }}>
                      这里是模板字段的原始取值，键名即模板里的字段 <code>key</code>；
                      字段定义在仓库的 <code>templates/&lt;大类&gt;/&lt;形态&gt;.json</code>。
                      界面**以正文为准**，本区块只用于排查。
                    </Typography.Paragraph>
                  </>
                ),
              },
            ]}
          />
        </>
      ) : null}
    </Drawer>
  )
}
