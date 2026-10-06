import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 后端地址：开发期由 Vite 代理到本地 FastAPI（默认 8000）。
// 生产由 Nginx 托管本构建产物并反代 /api，前端代码里不写死后端地址。
const API_TARGET = process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    // ★ 显式绑 IPv4（2026-10-06）。
    //
    // 不写 `host` 时 Vite 只监听 `[::1]` —— 本机实测 `netstat` 是
    // `TCP [::1]:5173 LISTENING`，于是 `http://127.0.0.1:5173` **连不上**，
    // 而 127.0.0.1 恰恰是脚本、文档、各种工具最常用的写法，
    // 排查时很容易误判成"服务没起来"。
    host: '127.0.0.1',
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
