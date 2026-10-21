import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Geliştirmede backend'e (uvicorn, port 8000) proxy; CORS gerekmez.
const BACKEND = 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/chat': BACKEND,
      '/health': BACKEND,
    },
  },
})
