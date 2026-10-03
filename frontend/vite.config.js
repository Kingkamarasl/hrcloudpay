import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  // In dev (`npm run dev`) assets are served from Vite's own server at
  // the site root. In a production build (`npm run build`), assets are
  // prefixed with /static/ to match Django's STATIC_URL, since Django
  // serves the built JS/CSS as static files from backend/frontend_dist.
  base: mode === 'production' ? '/static/' : '/',
  server: {
    port: 5173,
  },
  build: {
    // Build straight into Django's STATICFILES_DIRS so `npm run build`
    // + `python manage.py runserver` is all you need for single-server
    // mode. See backend/hrcloudpay/settings.py and urls.py.
    outDir: path.resolve(__dirname, '../backend/frontend_dist'),
    emptyOutDir: true,
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/tests/setup.js',
    css: false,
    exclude: ['**/tests/**/*.mjs', '**/node_modules/**'], // Exclude Node test files and node_modules
  },
}))
