import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// Geliştirmede backend'e (uvicorn) proxy; CORS gerekmez.
const DEFAULT_BACKEND = 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Önek '' : VITE_ önekli olmayan BACKEND_URL de okunur. Süreç ortamındaki değer
  // frontend/.env* dosyalarının önüne geçer. Değer yalnızca config'te kullanılır,
  // tarayıcı koduna gömülmez.
  const env = loadEnv(mode, process.cwd(), '')
  const backend = env.BACKEND_URL || DEFAULT_BACKEND

  return {
    plugins: [react()],
    server: {
      proxy: {
        '/chat': backend,
        '/health': backend,
        '/tools': backend,
      },
    },
  }
})
