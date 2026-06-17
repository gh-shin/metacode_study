import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// dev: /api는 FastAPI(eddr serve-api, :8000)로 프록시 — prod는 FastAPI가
// web/dist를 직접 서빙하므로 동일 출처(CORS 불필요).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
