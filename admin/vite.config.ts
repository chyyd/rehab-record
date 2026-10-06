import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 后端地址：开发期由 Vite 代理到本地 FastAPI（默认 8000）。
// 生产由 Nginx 托管本构建产物并反代 /api，前端代码里不写死后端地址。
const API_TARGET = process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000'

// 监听地址：默认**只绑回环**；`start.ps1 -Lan` 会设 `KB_LAN=1` 改成全接口。
//
// 为什么绑 `0.0.0.0` 而不是 `::`（IPv6 的"全部接口"）：用户明确要求
// **禁止 IPv6 连接**。`0.0.0.0` 只覆盖 IPv4。
const HOST = process.env.KB_LAN === '1' ? '0.0.0.0' : '127.0.0.1'

export default defineConfig({
  plugins: [react()],
  server: {
    // ★ 显式写 `host`，两个坑都踩过（2026-10-06）：
    //
    // 1. **不写 `host` 时 Vite 只监听 `[::1]`**（实测 `netstat` 是
    //    `TCP [::1]:5173 LISTENING`），于是 `http://127.0.0.1:5173` **连不上** ——
    //    而 127.0.0.1 恰恰是脚本、文档、各种工具最常用的写法，
    //    很容易被误判成"服务没起来"。
    // 2. **写死 `host: '127.0.0.1'` 会把内网其它客户端挡在外面** ——
    //    这个后台是要在科室局域网里用的。
    //
    // 所以由 [HOST] 决定：默认回环，`-Lan` 时全 IPv4 接口。
    //
    // ⚠ **不要通过 `npm run dev -- --host …` 传**：npm 会把 `--host`/`--port`
    //   当成自己的参数吞掉（实测报 `Unused args: 5173`），真正生效的只有这里。
    host: HOST,
    port: 5173,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        // 必须保留 Cookie（refresh token 走 httpOnly Cookie）
        cookieDomainRewrite: '',
      },
    },
  },
  build: {
    outDir: 'dist',
    rollupOptions: {
      output: {
        // 用函数形式而不是对象映射：Vite 8 / Rollup 4 的类型只接受函数或数组，
        // 传对象会在 tsc 下报 "No overload matches this call"。
        // 目的只是把体积大的依赖单独切出来，便于排查加载问题。
        manualChunks(id: string) {
          if (id.includes('node_modules')) {
            if (id.includes('antd') || id.includes('@ant-design')) return 'antd'
            if (id.includes('react')) return 'react'
            return 'vendor'
          }
          return undefined
        },
      },
    },
  },
})
