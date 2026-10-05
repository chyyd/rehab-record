/** 审计日志（M11）：按人 / 对象 / 时间范围查询 + 变更详情对比。只读。 */
import { useState } from 'react';
import {
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Drawer,
  Input,
  Row,
  Select,
  Table,
  Tag,
  Typography,
} from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import dayjs, { type Dayjs } from 'dayjs';
import { auditApi, usersApi, type AuditLogOut } from '../api/endpoints';
import { ErrorBox, PageHeader, PageSkeleton, useAsync } from '../components/Feedback';

/** 动作名转中文，便于管理员阅读。 */
const ACTION_LABEL: Record<string, string> = {
  create: '新建',
  update: '修改',
  delete: '删除',
  login: '登录',
  logout: '退出',
  submit: '提交',
  lock: '锁定',
  cancel: '取消',
  claim: '认领',
  release: '取消归属',
  assign: '分配',
  // 已出院患者改回在院/暂停时单独记这个动作，便于追溯谁做过恢复
  restore: '恢复（出院改回）',
  reset_password: '重置密码',
  change_password: '修改密码',
  revoke_sessions: '踢下线',
  record_modified_after_submit: '提交后修改',
  copy_schedule: '复制排期',
  upsert: '维护',
  disable: '停用',
  delete_draft: '删除草稿',
};

const TARGET_LABEL: Record<string, string> = {
  user: '用户',
  patient: '患者',
  appointment: '排期',
  treatment_record: '治疗记录',
  leave_record: '请假',
  rest_block: '休息块',
  option_set: '选项集',
  record_template: '模板',
  main_item: '主项目',
  sub_item: '子项目',
  sub_item_param_def: '参数定义',
};

export function AuditLogsPage() {
  const [page, setPage] = useState(1);
  const [userId, setUserId] = useState<number | undefined>();
  const [action, setAction] = useState<string | undefined>();
  const [targetType, setTargetType] = useState<string | undefined>();
  const [targetId, setTargetId] = useState('');
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [detail, setDetail] = useState<AuditLogOut | null>(null);

  const users = useAsync(async () => {
    const r = await usersApi.list({ page: 1, page_size: 200 });
    return r.items;
  }, []);
  const facets = useAsync(() => auditApi.facets(), []);

  const { data, loading, error, reload } = useAsync(
    () =>
      auditApi.list({
        page,
        page_size: 20,
        user_id: userId,
        action,
        target_type: targetType,
        target_id: targetId || undefined,
        from: range?.[0]?.format('YYYY-MM-DD'),
        to: range?.[1]?.format('YYYY-MM-DD'),
      }),
    [page, userId, action, targetType, targetId, range?.[0]?.valueOf(), range?.[1]?.valueOf()],
  );

  return (
    <>
      <PageHeader
        title="审计日志"
        description="只读。记录谁在什么时候对什么对象做了什么，含变更前后内容。"
        extra={
          <Button icon={<ReloadOutlined />} onClick={reload}>
            刷新
          </Button>
        }
      />

      <Card size="small" style={{ marginBottom: 16 }}>
        <Row gutter={[12, 12]}>
          <Col xs={12} md={5}>
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="操作人"
              style={{ width: '100%' }}
              value={userId}
              onChange={(v) => {
                setPage(1);
                setUserId(v);
              }}
              options={(users.data ?? []).map((u) => ({
                value: u.id,
                label: `${u.name}（${u.employee_no}）`,
              }))}
            />
          </Col>
          <Col xs={12} md={4}>
            <Select
              allowClear
              placeholder="动作"
              style={{ width: '100%' }}
              value={action}
              onChange={(v) => {
                setPage(1);
                setAction(v);
              }}
              options={(facets.data?.actions ?? []).map((a) => ({
                value: a,
                label: ACTION_LABEL[a] ?? a,
              }))}
            />
          </Col>
          <Col xs={12} md={4}>
            <Select
              allowClear
              placeholder="对象类型"
              style={{ width: '100%' }}
              value={targetType}
              onChange={(v) => {
                setPage(1);
                setTargetType(v);
              }}
              options={(facets.data?.target_types ?? []).map((t) => ({
                value: t,
                label: TARGET_LABEL[t] ?? t,
              }))}
            />
          </Col>
          <Col xs={12} md={4}>
            <Input
              placeholder="对象 ID"
              value={targetId}
              onChange={(e) => setTargetId(e.target.value)}
              onPressEnter={() => setPage(1)}
              allowClear
            />
          </Col>
          <Col xs={24} md={7}>
            <DatePicker.RangePicker
              style={{ width: '100%' }}
              value={range}
              onChange={(v) => {
                setPage(1);
                setRange(v as [Dayjs, Dayjs] | null);
              }}
              placeholder={['开始', '结束']}
            />
          </Col>
        </Row>
      </Card>

      {error ? (
        <ErrorBox message={error} onRetry={reload} />
      ) : loading ? (
        <PageSkeleton />
      ) : (
        <Table<AuditLogOut>
          rowKey="id"
          size="middle"
          dataSource={data?.items ?? []}
          pagination={{
            current: page,
            pageSize: 20,
            total: data?.total ?? 0,
            showSizeChanger: false,
            onChange: setPage,
            showTotal: (t) => `共 ${t} 条日志`,
          }}
          columns={[
            {
              title: '时间',
              dataIndex: 'created_at',
              width: 150,
              render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm:ss'),
            },
            {
              title: '操作人',
              key: 'user',
              width: 130,
              render: (_: unknown, r: AuditLogOut) =>
                r.user_name ? (
                  <span>
                    {r.user_name}
                    <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 4 }}>
                      {r.employee_no}
                    </Typography.Text>
                  </span>
                ) : (
                  <Typography.Text type="secondary">系统</Typography.Text>
                ),
            },
            {
              title: '动作',
              dataIndex: 'action',
              width: 120,
              render: (v: string) => (
                <Tag color={v === 'delete' ? 'red' : v === 'lock' ? 'green' : 'blue'}>
                  {ACTION_LABEL[v] ?? v}
                </Tag>
              ),
            },
            {
              title: '对象',
              key: 'target',
              width: 180,
              render: (_: unknown, r: AuditLogOut) => (
                <span>
                  {TARGET_LABEL[r.target_type] ?? r.target_type}
                  {r.target_id ? (
                    <Typography.Text type="secondary"> #{r.target_id}</Typography.Text>
                  ) : null}
                </span>
              ),
            },
            {
              title: '操作',
              key: 'a',
              width: 90,
              render: (_: unknown, r: AuditLogOut) => (
                <Button size="small" type="link" onClick={() => setDetail(r)}>
                  详情
                </Button>
              ),
            },
          ]}
        />
      )}

      <Drawer
        title="变更详情"
        size={640}
        open={detail !== null}
        onClose={() => setDetail(null)}
        destroyOnHidden
      >
        {detail ? (
          <>
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="时间">
                {dayjs(detail.created_at).format('YYYY-MM-DD HH:mm:ss')}
              </Descriptions.Item>
              <Descriptions.Item label="操作人">
                {detail.user_name ?? '系统'} {detail.employee_no ? `（${detail.employee_no}）` : ''}
              </Descriptions.Item>
              <Descriptions.Item label="动作">{ACTION_LABEL[detail.action] ?? detail.action}</Descriptions.Item>
              <Descriptions.Item label="对象">
                {TARGET_LABEL[detail.target_type] ?? detail.target_type} #{detail.target_id}
              </Descriptions.Item>
            </Descriptions>

            <Typography.Title level={5} style={{ marginTop: 20 }}>
              变更前
            </Typography.Title>
            <pre style={{ background: '#fafafa', padding: 12, borderRadius: 6, maxHeight: 260, overflow: 'auto' }}>
              {detail.before ? JSON.stringify(detail.before, null, 2) : '（无）'}
            </pre>

            <Typography.Title level={5} style={{ marginTop: 16 }}>
              变更后
            </Typography.Title>
            <pre style={{ background: '#fafafa', padding: 12, borderRadius: 6, maxHeight: 260, overflow: 'auto' }}>
              {detail.after ? JSON.stringify(detail.after, null, 2) : '（无）'}
            </pre>
          </>
        ) : null}
      </Drawer>
    </>
  );
}
