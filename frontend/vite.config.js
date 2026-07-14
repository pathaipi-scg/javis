import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server proxies /api -> FastAPI backend (demo/app.py) on :5000
export default defineConfig({
  plugins: [react()],
  // onnxruntime-web (คำปลุก offline) โหลด wasm เอง — กัน Vite pre-bundle ทำ path เพี้ยน
  optimizeDeps: { exclude: ['onnxruntime-web'] },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
    },
  },
})
