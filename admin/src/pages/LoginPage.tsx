/** 登录页。 */
import { useState } from 'react'
import { Button, Card, Form, Input, Typography } from 'antd'
import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { errorMessage } from '../api/client'
import { notify } from '../components/notify'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [loading, setLoading] = useState(false)

  const from = (location.state as { from?: string } | null)?.from ?? '/'

  const handleSubmit = async (values: { employee_no: string; password: string }) => {
    setLoading(true)
    try {
      const user = await login(values.employee_no, values.password)
      notify.success(`欢迎，${user.name}`)
      navigate(from, { replace: true })
    } catch (error) {
      notify.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg,#eef2f7 0%,#dfe7f1 100%)',
      }}
    >
      <Card style={{ width: 380 }} styles={{ body: { padding: 32 } }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <Typography.Title level={4} style={{ marginBottom: 4 }}>
            康复科管理后台
          </Typography.Title>
          <Typography.Text type="secondary">治疗过程记录系统</Typography.Text>
        </div>

        <Form layout="vertical" onFinish={handleSubmit} autoComplete="on">
          <Form.Item
            name="employee_no"
            label="工号"
            rules={[{ required: true, message: '请输入工号' }]}
          >
            <Input
              prefix={<UserOutlined />}
              placeholder="请输入工号"
              size="large"
              autoComplete="username"
            />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="请输入密码"
              size="large"
              autoComplete="current-password"
            />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0, marginTop: 8 }}>
            <Button type="primary" htmlType="submit" size="large" block loading={loading}>
              登录
            </Button>
          </Form.Item>
        </Form>

        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 16, marginBottom: 0 }}>
          仅限本科室工作人员使用。账号由管理员创建，忘记密码请联系管理员重置。
        </Typography.Paragraph>
      </Card>
    </div>
  )
}
