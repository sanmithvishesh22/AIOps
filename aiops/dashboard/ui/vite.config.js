import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// The UI dev server and its proxy are loopback-only, mirroring the read-API's
// deliberate localhost-only v1 posture (docs/CONTRACTS.md §E,
// SECURITY_AND_ACCESS.md §0). `/api` is proxied to the Express read-API default
// bind (aiops/dashboard/src/config.js: 127.0.0.1:8081) so live mode needs no CORS
// change on the API and no origin configuration in the app.
const API_TARGET = 'http://127.0.0.1:8081';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
    },
  },
  preview: {
    host: '127.0.0.1',
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.js'],
    // UI tests are *.test.jsx on purpose: the Express package's `npm test`
    // (node --test, run from aiops/dashboard) discovers `**/test/**/*.js` but
    // not .jsx, so it keeps running only its own suite.
    include: ['test/**/*.test.jsx'],
    unstubGlobals: true,
  },
});
