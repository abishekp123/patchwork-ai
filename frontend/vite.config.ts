import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv } from 'vite'

const envDir = fileURLToPath(new URL('..', import.meta.url))

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, envDir, 'PATCHWORK_')
  const proxy = {
    '/api': {
      target: env.PATCHWORK_API_PROXY_TARGET || 'http://127.0.0.1:8000',
      rewrite: (path: string) => path.replace(/^\/api/, ''),
    },
  }
  return {
    envDir,
    plugins: [react(), tailwindcss()],
    server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy },
    preview: { host: '127.0.0.1', port: 4173, strictPort: true, proxy },
  }
})
