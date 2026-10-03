/** 修改自己的密码。改动后后端会吊销全部会话，因此这里要引导重新登录。 */
import { Form, Input, Modal, Typography } from 'antd'
import { useState } from 'react'
import { authApi } from '../api/endpoints'
import { errorMessage } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { notify } from '../components/notify'

interface Props {
  open: boolean
  onClose: () => void
}

export function ChangePasswordModal({ open, onClose }: Props) {
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)
  const { logout } = useAuth()

  const handleOk = async () => {
    const values = await form.validateFields()
    setSubmitting(true)
    try {
      await authApi.changePassword(values.old_password, values.new_password)
      notify.success('密码已修改，请重新登录')
      onClose()
      form.resetFields()
      // 后端已吊销全部会话，本地也要清干净，避免带着失效 token 继续点
      await logout()
      window.location.href = '/login'
    } catch (error) {
      notify.error(errorMessage(error))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title="修改密码"
      open={open}
      onOk={handleOk}
      onCancel={() => {
        onClose()
        form.resetFields()
      }}
      confirmLoading={submitting}
      okText="确认修改"
      cancelText="取消"
      destroyOnHidden
    >
      <Typography.Paragraph type="warning" style={{ marginBottom: 16 }}>
        修改成功后，本账号在所有设备上的登录都会失效，需要重新登录。
      </Typography.Paragraph>
      <Form form={form} layout="vertical">
        <Form.Item name="old_password" label="当前密码" rules={[{ required: true, message: '请输入当前密码' }]}>
          <Input.Password autoComplete="current-password" />
        </Form.Item>
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
