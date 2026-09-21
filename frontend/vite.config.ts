import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The SPA is served under a path prefix in production (/flow/ behind the
// shared nginx), while local development stays at the root. Vite exposes the
// resolved value as import.meta.env.BASE_URL, which the router reuses as its
// basename.
const base = process.env.VITE_BASE_PATH ?? '/'

// Dev server runs on 3000 to match the backend's default CORS origin and
// frontend_base_url. Override with `--port` if you change CORS_ORIGINS.
export default defineConfig({
  base,
  plugins: [react(), tailwindcss()],
  server: {
    port: 3000,
    strictPort: true,
  },
  preview: {
    port: 3000,
    strictPort: true,
  },
})
