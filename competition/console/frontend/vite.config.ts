import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// The page lives under '/console/' because the entry keeps '/api/*' and
// '/session*' for itself, and the console's own calls are under the same prefix,
// so one rule at the door is enough.  In development the calls are proxied to a
// console started with ``python -m competition.console``.
export default defineConfig({
  base: '/console/',
  plugins: [vue()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    port: 5174,
    proxy: {
      '/console/api': 'http://127.0.0.1:8100',
      '/console/healthz': 'http://127.0.0.1:8100',
    },
  },
})
