/** 汇总与打印（M10）：按日期 / 按患者汇总 + 三套 PDF 下载。 */
import { useState } from 'react'
import {
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Radio,
  Row,
  Segmented,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd'
import { FilePdfOutlined, PrinterOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import { patientsApi, summaryApi, type TotalsOut } from '../api/endpoints'
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

function TotalsCards({ totals }: { totals: TotalsOut }) {
  return (
    <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
      <Col xs={12} md={6}>
        <Card size="small">
          <Statistic title="治疗次数" value={totals.record_count} suffix="次" />
        </Card>
      </Col>
      <Col xs={12} md={6}>
        <Card size="small">
          <Statistic title="总时长" value={totals.total_duration_min} suffix="分钟" />
        </Card>
      </Col>
      <Col xs={12} md={6}>
        <Card size="small">
          <Statistic title="子项目条目" value={totals.item_count} suffix="条" />
        </Card>
      </Col>
      <Col xs={12} md={6}>
        <Card size="small">
          <Statistic title="涉及患者" value={totals.patient_count} suffix="人" />
        </Card>
      </Col>
    </Row>
  )
}

function FrequencyTags({ title, counts }: { title: string; counts: Record<string, number> }) {
  const entries = Object.entries(counts ?? {})
  if (entries.length === 0) return null
  return (
    <Descriptions.Item label={title}>
      <Space size={4} wrap>
        {entries.map(([name, count]) => (
          <Tag key={name}>
            {name} × {count}
          </Tag>
        ))}
      </Space>
    </Descriptions.Item>
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

  const totals = data?.totals as TotalsOut | undefined

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
          onClick={() =>
            downloadPdf(
              summaryApi.printDateUrl(day, groupBy),
              `按日期汇总-${day}.pdf`,
            )
          }
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

          {totals ? (
            <Descriptions size="small" column={1} bordered style={{ marginBottom: 16 }}>
              <FrequencyTags title="主项目频次" counts={totals.main_item_counts} />
              <FrequencyTags title="子项目频次" counts={totals.sub_item_counts} />
              <FrequencyTags title="治疗师分布" counts={totals.therapist_counts} />
            </Descriptions>
          ) : null}

          {(data?.groups as { key: string; totals: TotalsOut; rows: Record<string, unknown>[] }[] | undefined)
            ?.length === 0 ? (
            <Card>
              <Typography.Text type="secondary">当日没有已提交的治疗记录。</Typography.Text>
            </Card>
          ) : (
            (data?.groups as { key: string; totals: TotalsOut; rows: Record<string, unknown>[] }[])?.map(
              (group) => (
                <Card
                  key={group.key}
                  size="small"
                  title={`${group.key}（${group.totals.record_count} 次 / ${group.totals.total_duration_min} 分钟）`}
                  style={{ marginBottom: 16 }}
                >
                  <Table
                    rowKey={(r) => String((r as { record_id: number }).record_id)}
                    size="small"
                    pagination={false}
                    dataSource={group.rows}
                    scroll={{ x: 900 }}
                    columns={[
                      {
                        title: '患者',
                        key: 'patient',
                        width: 150,
                        render: (_: unknown, r: Record<string, unknown>) =>
                          `${r.patient_name ?? ''}（${r.patient_no ?? ''}）`,
                      },
                      {
                        title: '半日',
                        dataIndex: 'session_period',
                        width: 70,
                        render: (v: string) => (v === 'am' ? '上午' : v === 'pm' ? '下午' : '—'),
                      },
                      { title: '主项目', dataIndex: 'main_item_name', width: 160 },
                      { title: '子项目', dataIndex: 'sub_item_name_snapshot', width: 150 },
                      { title: '参数', dataIndex: 'params_digest', ellipsis: true },
                      { title: '患者反应', dataIndex: 'response_digest', width: 140 },
                      {
                        title: '时长',
                        dataIndex: 'duration_min',
                        width: 80,
                        render: (v: number) => `${v ?? 0} 分`,
                      },
                    ]}
                  />
                </Card>
              ),
            )
          )}
        </>
      )}
    </>
  )
}

/** 按患者汇总 */
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
        : Promise.resolve(null),
    [patientNo, range?.[0]?.valueOf(), range?.[1]?.valueOf()],
  )

  const totals = (data as { totals?: TotalsOut } | null)?.totals
  const days =
    (data as { days?: Record<string, unknown>[] } | null)?.days ?? []

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
            patientNo &&
            downloadPdf(summaryApi.printPatientUrl(patientNo), `患者汇总-${patientNo}.pdf`)
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
          {totals ? <TotalsCards totals={totals} /> : null}
          <Table
            rowKey="record_date"
            size="small"
            dataSource={days}
            pagination={false}
            scroll={{ x: 1000 }}
            columns={[
              { title: '日期', dataIndex: 'record_date', width: 110 },
              {
                title: '半日',
                dataIndex: 'session_periods',
                width: 90,
                render: (v: string[]) =>
                  (v ?? []).map((p) => (p === 'am' ? '上午' : p === 'pm' ? '下午' : p)).join('、') || '—',
              },
              {
                title: '治疗师',
                dataIndex: 'therapists',
                width: 110,
                render: (v: string[], r: Record<string, unknown>) =>
                  `${(v ?? []).join('、')}${r.temporary ? '（临时）' : ''}`,
              },
              {
                title: '主项目',
                dataIndex: 'main_items',
                width: 170,
                render: (v: string[]) => (v ?? []).join('、') || '—',
              },
              {
                title: '子项目',
                dataIndex: 'sub_items',
                width: 170,
                render: (v: string[]) => (v ?? []).join('、') || '—',
              },
              {
                title: '参数',
                dataIndex: 'params',
                ellipsis: true,
                render: (v: string[]) => (v ?? []).join('；') || '—',
              },
              {
                title: '患者反应',
                dataIndex: 'responses',
                width: 140,
                render: (v: string[]) => (v ?? []).join('；') || '—',
              },
              {
                title: '时长',
                dataIndex: 'duration_min',
                width: 80,
                render: (v: number) => `${v ?? 0} 分`,
              },
            ]}
          />
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
        description="统计只计已提交与已锁定的记录（草稿不计入），导出为中文 PDF。"
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
