/**
 * SOAP 表单的**通用渲染器**（后台版）。
 *
 * 为什么通用而不是给每个大类写死界面：出院小结四大类各有 17–23 个字段、
 * 字段完全不同（PT 有 MMT/Ashworth，吞咽有洼田饮水试验…），而后端已经把
 * 字段定义（`soap[].fields[]`）连同**带入值**（`prefill`）一起下发了 ——
 * 与 App 用的是**同一份契约**，所以这里照着渲染即可，
 * 以后模板改了后台不用跟着改。
 *
 * 只处理 4 种类型 + 1 个"自动只读"：
 * - `single` → 单选（Select，允许清空）
 * - `multi`  → 多选（Select mode="multiple"）
 * - `number` → 数字输入（带 `unit` 后缀）
 * - `text`   → 文本
 * - `auto`   → 只读（服务端算好的，如出院小结的「治疗过程汇总」）
 */
import { Form, Input, InputNumber, Select, Tag, Typography } from 'antd'
import type { SoapField, SoapSection } from '../api/endpoints'

/** 空值判据：`undefined` / `null` / 空串 / 空数组 都算没填。 */
export function isBlank(value: unknown): boolean {
  if (value === undefined || value === null) return true
  if (typeof value === 'string') return value.trim() === ''
  if (Array.isArray(value)) return value.length === 0
  return false
}

/**
 * 校验必填，返回缺失字段的**中文标签**（与后端 422 的 `details.missing` 同口径）。
 *
 * 前端先拦一道是为了**即时反馈**：23 个字段的表单提交后才报错，
 * 用户还得自己找哪一项漏了。
 */
export function missingRequired(
  sections: SoapSection[],
  values: Record<string, unknown>,
): string[] {
  const missing: string[] = []
  for (const section of sections) {
    for (const field of section.fields) {
      if (!field.required || field.auto) continue
      if (isBlank(values[field.key])) missing.push(field.label)
    }
  }
  return missing
}

function FieldInput({ field, autoValue }: { field: SoapField; autoValue?: unknown }) {
  // 自动字段：服务端已经算好了（如出院小结的「治疗过程汇总」= "住院期间共治疗 20 次"）。
  // **要把值显示出来** —— 它就是这份小结的一部分，只写"无需填写"等于把它藏起来。
  // 不参与提交（提交了也会被服务端忽略并重算）。
  if (field.auto) {
    const text = isBlank(autoValue) ? '（系统将按该大类的记录自动生成）' : String(autoValue)
    return <Typography.Text type="secondary">{text}</Typography.Text>
  }
  const options = (field.options ?? []).map((v) => ({ label: v, value: v }))

  switch (field.type) {
    case 'single':
      return (
        <Select
          allowClear
          showSearch
          placeholder="请选择"
          options={options}
          // 选项多时（如疗法的 58 项）本地过滤，省得滚半天
          filterOption={(input, option) =>
            String(option?.label ?? '').toLowerCase().includes(input.toLowerCase())
          }
          style={{ maxWidth: 320 }}
        />
      )
    case 'multi':
      return (
        <Select
          mode="multiple"
          allowClear
          showSearch
          placeholder="可多选"
          options={options}
          filterOption={(input, option) =>
            String(option?.label ?? '').toLowerCase().includes(input.toLowerCase())
          }
          style={{ minWidth: 260 }}
        />
      )
    case 'number':
      return <InputNumber style={{ width: 140 }} addonAfter={field.unit ?? undefined} />
    default:
      return <Input placeholder={field.hint ?? undefined} />
  }
}

export function SoapFormFields({
  sections,
  prefill,
}: {
  sections: SoapSection[]
  /** 服务端带入的值（`prefill`）—— 自动字段要从这里取来**展示**。 */
  prefill?: Record<string, unknown>
}) {
  return (
    <>
      {sections.map((section) => (
        <div key={section.key} style={{ marginBottom: 8 }}>
          <Typography.Text strong>{section.heading}</Typography.Text>
          {section.fields.map((field) => (
            <Form.Item
              key={field.key}
              name={field.key}
              label={field.label}
              // 自动字段与后端一样不参与校验
              rules={
                field.required && !field.auto
                  ? [{ required: true, message: `请填写「${field.label}」` }]
                  : undefined
              }
              // 多选/单选都可能很长，标签太长会把输入框挤到看不见
              labelCol={{ flex: '0 0 190px' }}
              wrapperCol={{ flex: '1 1 auto' }}
              style={{ marginBottom: 10 }}
            >
              <FieldInput field={field} autoValue={prefill?.[field.key]} />
            </Form.Item>
          ))}
        </div>
      ))}
    </>
  )
}

/** 一行小字：这份表单共几个必填项（让用户对工作量有预期）。 */
export function RequiredHint({ sections }: { sections: SoapSection[] }) {
  const required = sections.flatMap((s) => s.fields).filter((f) => f.required && !f.auto)
  const auto = sections.flatMap((s) => s.fields).filter((f) => f.auto)
  return (
    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
      共 {required.length} 项必填
      {auto.length > 0 ? (
        <>
          ，其中 {auto.length} 项由系统自动汇总{' '}
          {auto.map((f) => (
            <Tag key={f.key}>{f.label}</Tag>
          ))}
        </>
      ) : null}
    </Typography.Text>
  )
}
