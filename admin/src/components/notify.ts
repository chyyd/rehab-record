/**
 * 统一的提示封装。
 *
 * ## 为什么要包一层
 *
 * antd 的**静态** `message.xxx()` 拿不到 `ConfigProvider` 的上下文，因此会打印
 * `Warning: [antd: message] Static function can not consume context like dynamic theme.`
 * 官方推荐用 `App` 组件提供的 `message` 实例（`App.useApp()`）。
 *
 * 但 `useApp()` 只能在组件内调用，而各处都是命令式地 `message.success(...)`。
 * 折中做法：在 `App.tsx` 挂载时把 `App` 提供的实例注册到模块级变量，
 * 各页面继续 `import { notify } from '../components/notify'` 调用，
 * 既拿到正确的主题上下文，也不必把每个页面都改成 hook 取用。
 */
import type { MessageInstance } from 'antd/es/message/interface'
import type { ModalStaticFunctions } from 'antd/es/modal/confirm'
import type { NotificationInstance } from 'antd/es/notification/interface'

interface NotifyApi {
  message: MessageInstance
  modal: Omit<ModalStaticFunctions, 'warn'>
  notification: NotificationInstance
}

let api: NotifyApi | null = null

/** 由 `App.tsx` 在挂载时调用，注入带上下文能力的实例。 */
export function registerNotify(instance: NotifyApi): void {
  api = instance
}

function fallback(): NotifyApi {
  if (!api) {
    // 理论上不会发生：registerNotify 在 App 挂载时就跑了。
    // 真发生时给出明确错误，而不是静默丢失提示（静默失败最难排查）。
    throw new Error('notify 尚未注册：请确认 App.tsx 里已调用 registerNotify')
  }
  return api
}

export const notify = {
  success: (content: string, duration?: number) => fallback().message.success(content, duration),
  error: (content: string, duration?: number) => fallback().message.error(content, duration),
  warning: (content: string, duration?: number) => fallback().message.warning(content, duration),
  info: (content: string, duration?: number) => fallback().message.info(content, duration),
  /** 需要"确认/取消"时用，替代 `Modal.confirm` 的静态调用。 */
  confirm: (config: Parameters<NotifyApi['modal']['confirm']>[0]) => fallback().modal.confirm(config),
  info_modal: (config: Parameters<NotifyApi['modal']['info']>[0]) => fallback().modal.info(config),
}

/** 供组件内需要 `message` 实例的场景使用（如 `App.useApp()` 的返回值）。 */
export type { NotifyApi }
