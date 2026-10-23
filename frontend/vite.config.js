import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8788',
        // Keep the browser's Host aligned with Origin for backend CSRF checks.
        changeOrigin: false,
      },
    },
  },
})
