/**
 * 汇总与打印：按日期 / 按患者汇总 + 三套 PDF 下载。
 *
 * 2026-10-05（脊柱级改造后）：汇总**彻底不再有表格**。
 * 后端只输出记录落库时冻结的 `rendered_text`（SOAP 纯文本），
 * 所以这里也按"文本块"渲染 —— 一、保留换行；二、按日期分块；
 * 三、界面与 PDF 看到的是同一段文字（表格会把 A4 上的行文拆散，两者对不上）。
 *
 * 计数口径（用户明确要求）：
 * - 只算 `kind='daily'` 且 `status IN ('submitted','locked')`；
 * - 首评 / 阶段性复评 / 出院小结是**独立文书，不计治疗次数**，
 *   但它们的正文会出现在按患者的每日文本里 —— 于是"只写了出院小结的那天"
 *   会显示 `record_count: 0`。这是**预期行为**，UI 必须能读得通，
 *   所以下面刻意写成「本次计数 0 次 · 其中含 1 份文书」，而不是"没有记录"。
 */
import { useState } from 'react'
import {
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Empty,
  Radio,
  Row,
  Segmented,
  Select,
  Space,
  Statistic,
  Tag,
  Typography,
} from 'antd'
import { FilePdfOutlined, PrinterOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import {
  patientsApi,
  summaryApi,
  type DateSummaryOut,
  type PatientDailyRowOut,
  type PatientDailySummaryOut,
  type SummaryRowOut,
  type TotalsOut,
} from '../api/endpoints'
import { getAccessToken } from '../api/client'
import { ErrorBox, PageHeader, PageSkeleton, useAsync } from '../components/Feedback'
import { notify } from '../components/notify'

/**
 * 下载 PDF。
 *
 * 后端 PDF 接口需要 `Authorization` 头，而 `<a download>` 与 `window.open` 都带不上
 * 自定义头（只能带 Cookie）。因此这里用 fetch 拿 blob 再触发下载 ——
 * 否则会拿到 401。
 */
async function downloadPdf(url: string, filename: string) {
  const token = getAccessToken()
  const resp = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    credentials: 'include',
  })
  if (!resp.ok) {
    notify.error(`生成 PDF 失败（HTTP ${resp.status}）`)
    return
  }
  const blob = await resp.blob()
  const objectUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(objectUrl)
}

const DISCIPLINE_LABEL: Record<string, string> = {
  PT: '运动',
  OT: '生活技能',
  ST_SW: '吞咽',
  ST_SP: '言语',
}

const KIND_LABEL: Record<string, string> = {
  initial: '首评',
  daily: '日常',
  reassessment: '阶段性复评',
  discharge: '出院小结',
}

const STATUS_LABEL: Record<string, { text: string; color: string }> = {
  draft: { text: '草稿', color: 'default' },
  submitted: { text: '已提交', color: 'blue' },
  locked: { text: '已锁定', color: 'green' },
}

const disciplineText = (r: { discipline: string; discipline_name?: string | null }) =>
  r.discipline_name || DISCIPLINE_LABEL[r.discipline] || r.discipline

const kindText = (r: { kind: string; kind_label?: string | null }) =>
  r.kind_label || KIND_LABEL[r.kind] || r.kind

/** 汇总计数卡片。**没有"总时长"** —— 新口径里不存在时长字段。 */
function TotalsCards({ totals }: { totals: TotalsOut }) {
  const disciplines = Object.entries(totals.discipline_counts ?? {})
  return (
    <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
      <Col xs={12} md={6}>
        <Card size="small">
          <Statistic title="治疗次数（仅日常）" value={totals.record_count} suffix="次" />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            评估文书不计次数
          </Typography.Text>
        </Card>
      </Col>
      <Col xs={12} md={6}>
        <Card size="small">
          <Statistic title="涉及患者" value={totals.patient_count} suffix="人" />
        </Card>
      </Col>
      <Col xs={24} md={12}>
        <Card size="small" title="按大类分布（仅日常）">
          {disciplines.length === 0 ? (
            <Typography.Text type="secondary">没有日常记录。</Typography.Text>
          ) : (
            <Space size={4} wrap>
              {disciplines.map(([name, count]) => (
                <Tag key={name} color="blue">
                  {name} × {count}
                </Tag>
              ))}
            </Space>
          )}
        </Card>
      </Col>
    </Row>
  )
}

/** 治疗师分布（仅日常）。 */
function TherapistCounts({ counts }: { counts: Record<string, number> }) {
  const entries = Object.entries(counts ?? {})
  if (entries.length === 0) return null
  return (
    <Descriptions size="small" column={1} bordered style={{ marginBottom: 16 }}>
      <Descriptions.Item label="治疗师分布（仅日常）">
        <Space size={4} wrap>
          {entries.map(([name, count]) => (
            <Tag key={name}>
              {name} × {count}
            </Tag>
          ))}
        </Space>
      </Descriptions.Item>
    </Descriptions>
  )
}

/** 一段 SOAP 纯文本。保留换行、等宽字体、可滚动 —— 与 PDF 里看到的一致。 */
function SoapTextBlock({ text, caption }: { text: string; caption?: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      {caption ? (
        <div style={{ marginBottom: 4, fontSize: 12, color: 'rgba(0,0,0,0.65)' }}>{caption}</div>
      ) : null}
      <pre
        style={{
          background: '#fafafa',
          border: '1px solid #f0f0f0',
          borderLeft: '3px solid #1677ff',
          borderRadius: 6,
          padding: 12,
          margin: 0,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          fontFamily:
            'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace',
          fontSize: 13,
          lineHeight: 1.7,
        }}
      >
        {text}
      </pre>
    </div>
  )
}

/** 一条汇总记录的元信息（患者 / 大类 / 形态 / 治疗师 / 状态 / 序次）。 */
function RowMeta({ row, showPatient = true }: { row: SummaryRowOut; showPatient?: boolean }) {
  const status = STATUS_LABEL[row.status] ?? { text: row.status, color: 'default' }
  return (
    <Space size={4} wrap style={{ marginBottom: 6 }}>
      {showPatient ? (
        <Typography.Text strong>
          {`${row.patient_name ?? '—'}（${row.patient_no}）`}
        </Typography.Text>
      ) : null}
      <Tag>{disciplineText(row)}</Tag>
      <Tag color={row.kind === 'daily' ? 'default' : 'geekblue'}>{kindText(row)}</Tag>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {/* ★ 2026-10-06：这一段原来是 3 个并列子节点（治疗师名 + 条件"（临时）" +
            条件"第 N 次"），而 antd 的 Typography 内部会把 children **原样**塞进
            `<span>{node}</span>`（见 `typography/Base/index.js`：
            `node.length > 0 && … ? <span key="show-content">{node}</span> : node`）。
            于是"多个子节点"变成一个**没有 key 的数组**，React 报
            `Each child in a list should have a unique "key" prop …
             Check the render method of Card. It was passed a child from DateSummary.`
            —— 警告指向 Card / DateSummary，真正的原因却在这里，很难找。

            合并成**一个字符串**即可：警告消失，渲染结果完全一样。 */}
        {[
          row.therapist_name ?? '—',
          row.is_temporary ? '（临时）' : '',
          row.kind === 'daily' && row.seq_no ? ` · 第 ${row.seq_no} 次` : '',
        ].join('')}
      </Typography.Text>
      <Tag color={status.color}>{status.text}</Tag>
    </Space>
  )
}

/** 按日期汇总 */
function DateSummary() {
  const [date, setDate] = useState<Dayjs>(dayjs())
  const [groupBy, setGroupBy] = useState('therapist')
  const day = date.format('YYYY-MM-DD')

  const { data, loading, error, reload } = useAsync(
    () => summaryApi.byDate(day, groupBy),
    [day, groupBy],
  )

  const totals = data?.totals
  const groups = (data as DateSummaryOut | null)?.groups ?? []

  return (
    <>
      <Space style={{ marginBottom: 16 }} wrap>
        <DatePicker
          value={date}
          onChange={(v) => v && setDate(v)}
          allowClear={false}
          presets={[
            { label: '昨天', value: dayjs().subtract(1, 'day') },
            { label: '今天', value: dayjs() },
          ]}
        />
        <Radio.Group
          value={groupBy}
          onChange={(e) => setGroupBy(e.target.value)}
          optionType="button"
          options={[
            { value: 'therapist', label: '按治疗师' },
            { value: 'patient', label: '按患者' },
          ]}
        />
        <Button icon={<ReloadOutlined />} onClick={reload}>
          刷新
        </Button>
        <Button
          type="primary"
          icon={<FilePdfOutlined />}
          onClick={() => downloadPdf(summaryApi.printDateUrl(day, groupBy), `按日期汇总-${day}.pdf`)}
        >
          导出 PDF
        </Button>
      </Space>

      {error ? (
        <ErrorBox message={error} onRetry={reload} />
      ) : loading ? (
        <PageSkeleton />
      ) : (
        <>
          {totals ? <TotalsCards totals={totals} /> : null}
          {totals ? <TherapistCounts counts={totals.therapist_counts} /> : null}

          {groups.length === 0 ? (
            <Card>
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="当日没有已提交/已锁定的日常记录（首评、复评、出院小结不计入按日期汇总）。"
              />
            </Card>
          ) : (
            groups.map((group) => (
              <Card
                key={group.key}
                size="small"
                title={`${group.key}（本次计数 ${group.totals.record_count} 次 · ${group.rows.length} 份文书）`}
                style={{ marginBottom: 16 }}
              >
                {group.rows.map((row) => (
                  <SoapTextBlock
                    // ★ 2026-10-06：这里原来写 `key={row.id}`，而**汇总接口的行没有 `id`
                    //   字段**（只有 `record_id`）。`key={undefined}` 等于没给 key，于是
                    //   React 报：
                    //     `Each child in a list should have a unique "key" prop …
                    //      Check the render method of Card. It was passed a child from DateSummary.`
                    //   警告指向 Card / DateSummary，真正的原因是这里字段名写错了 ——
                    //   找它花了很久，故留此说明。
                    //
                    //   类型检查当时没拦住：`SummaryRowOut extends RecordListItemOut` 从基接口
                    //   **继承**了 `id: number`，但后端这个接口并不返回它
                    //（已把 `SummaryRowOut` 的 `id` 收紧成可选，编译器以后能拦）。
                    key={row.record_id}
                    caption={<RowMeta row={row} showPatient={groupBy !== 'patient'} />}
                    text={row.rendered_text || '（无正文）'}
                  />
                ))}
              </Card>
            ))
          )}
        </>
      )}
    </>
  )
}

/** 按患者汇总（逐日 SOAP 文本块） */
function PatientSummary() {
  const [patientNo, setPatientNo] = useState<string | undefined>()
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null)
  const [patients, setPatients] = useState<{ value: string; label: string }[]>([])

  const search = async (keyword: string) => {
    const r = await patientsApi.list({ page: 1, page_size: 30, keyword: keyword || undefined })
    setPatients(r.items.map((p) => ({ value: p.inpatient_no, label: `${p.name}（${p.inpatient_no}）` })))
  }

  const { data, loading, error, reload } = useAsync(
    () =>
      patientNo
        ? summaryApi.byPatient(patientNo, {
            from: range?.[0]?.format('YYYY-MM-DD'),
            to: range?.[1]?.format('YYYY-MM-DD'),
          })
        : Promise.resolve(null as PatientDailySummaryOut | null),
    [patientNo, range?.[0]?.valueOf(), range?.[1]?.valueOf()],
  )

  const totals = data?.totals
  const days = data?.days ?? []

  return (
    <>
      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          showSearch
          filterOption={false}
          placeholder="选择患者（输入编号或姓名搜索）"
          style={{ width: 280 }}
          value={patientNo}
          onChange={setPatientNo}
          onSearch={search}
          onDropdownVisibleChange={(open) => open && void search('')}
          options={patients}
        />
        <DatePicker.RangePicker
          value={range}
          onChange={(v) => setRange(v as [Dayjs, Dayjs] | null)}
          placeholder={['开始', '结束']}
        />
        <Button icon={<ReloadOutlined />} onClick={reload}>
          刷新
        </Button>
        <Button
          icon={<FilePdfOutlined />}
          disabled={!patientNo}
          onClick={() =>
            patientNo &&
            downloadPdf(
              summaryApi.printPatientDailyUrl(
                patientNo,
                range?.[0]?.format('YYYY-MM-DD'),
                range?.[1]?.format('YYYY-MM-DD'),
              ),
              `患者每日汇总-${patientNo}.pdf`,
            )
          }
        >
          每日汇总 PDF
        </Button>
        <Button
          type="primary"
          icon={<PrinterOutlined />}
          disabled={!patientNo}
          onClick={() =>
            patientNo && downloadPdf(summaryApi.printPatientUrl(patientNo), `患者汇总-${patientNo}.pdf`)
          }
        >
          单患者汇总 PDF
        </Button>
      </Space>

      {!patientNo ? (
        <Card>
          <Typography.Text type="secondary">请先选择一位患者。</Typography.Text>
        </Card>
      ) : error ? (
        <ErrorBox message={error} onRetry={reload} />
      ) : loading ? (
        <PageSkeleton />
      ) : (
        <>
          {data?.patient ? (
            <Descriptions size="small" column={2} bordered style={{ marginBottom: 16 }}>
              <Descriptions.Item label="患者">
                {data.patient.name}（{data.patient.inpatient_no}）
              </Descriptions.Item>
              <Descriptions.Item label="诊断">{data.patient.diagnosis || '—'}</Descriptions.Item>
            </Descriptions>
          ) : null}

          {totals ? <TotalsCards totals={totals} /> : null}
          {totals ? <TherapistCounts counts={totals.therapist_counts} /> : null}

          {days.length === 0 ? (
            <Card>
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="该患者在此区间内没有已提交/已锁定的文书。"
              />
            </Card>
          ) : (
            days.map((day: PatientDailyRowOut) => {
              // ⚠ 只含出院小结/首评的那天 record_count 就是 0 —— 预期行为，别写成"无记录"
              const assessmentCount = day.records.filter((r) => r.kind !== 'daily').length
              const countHint =
                day.record_count === 0 && assessmentCount > 0
                  ? `本次计数 0 次 · 当天只有 ${assessmentCount} 份评估文书（不计治疗次数）`
                  : `本次计数 ${day.record_count} 次 · ${day.records.length} 份文书`
              return (
                <Card
                  key={day.record_date}
                  size="small"
                  title={`${day.record_date}（${countHint}）`}
                  style={{ marginBottom: 16 }}
                >
                  <Space size={4} wrap style={{ marginBottom: 8 }}>
                    {day.therapists.length > 0 ? (
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {`治疗师：${day.therapists.join('、')}${day.temporary ? '（含临时）' : ''}`}
                      </Typography.Text>
                    ) : null}
                    {day.disciplines.map((d) => (
                      <Tag key={d}>{d}</Tag>
                    ))}
                  </Space>

                  {day.records.map((record) => {
                    const status = STATUS_LABEL[record.status] ?? {
                      text: record.status,
                      color: 'default',
                    }
                    return (
                      <SoapTextBlock
                        key={record.record_id}
                        caption={
                          <Space size={4} wrap>
                            <Tag>{disciplineText(record)}</Tag>
                            <Tag color={record.kind === 'daily' ? 'default' : 'geekblue'}>
                              {kindText(record)}
                            </Tag>
                            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                              {[
                                record.therapist_name ?? '—',
                                record.is_temporary ? '（临时）' : '',
                                record.kind === 'daily' && record.seq_no
                                  ? ` · 第 ${record.seq_no} 次`
                                  : '',
                              ].join('')}
                            </Typography.Text>
                            <Tag color={status.color}>{status.text}</Tag>
                          </Space>
                        }
                        text={record.rendered_text || '（无正文）'}
                      />
                    )
                  })}
                </Card>
              )
            })
          )}
        </>
      )}
    </>
  )
}

export function SummaryPage() {
  const [mode, setMode] = useState<string>('date')

  return (
    <>
      <PageHeader
        title="汇总与打印"
        description="只计已提交与已锁定的日常记录（草稿不计；首评/复评/出院小结是独立文书，不计治疗次数）。内容为 SOAP 纯文本，界面与 PDF 同源。"
        extra={
          <Segmented
            value={mode}
            onChange={(v) => setMode(String(v))}
            options={[
              { value: 'date', label: '按日期汇总' },
              { value: 'patient', label: '按患者汇总' },
            ]}
          />
        }
      />
      {mode === 'date' ? <DateSummary /> : <PatientSummary />}
    </>
  )
}
