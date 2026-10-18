import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// The dev server talks to the observation gateway, which carries the four read
// routes and holds the observer credential.  The page never holds one, so there
// is nothing to configure here but where that gateway is listening.
const gateway = process.env.ZJJ_VIEWER || 'http://127.0.0.1:8008'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: { '/api': { target: gateway, changeOrigin: false } },
  },
  build: {
    // Element Plus is imported whole, which is the right trade for a kiosk page
    // that is never on a slow link; the default 500 kB warning is noise here.
    chunkSizeWarningLimit: 1200,
  },
})
