import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import legacy from '@vitejs/plugin-legacy';
import path from 'path';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const apiTarget = env.VITE_DEV_API_TARGET || 'http://127.0.0.1:5173';

  return {
    plugins: [
      react(),
      legacy({
        targets: ['ie >= 11'],
        renderLegacyChunks: true,
        modernPolyfills: false,
        additionalLegacyPolyfills: [
          'whatwg-fetch',
          'regenerator-runtime/runtime',
          'core-js/stable/url-search-params',
        ],
      }),
    ],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, 'src'),
      },
    },
    server: {
      host: '0.0.0.0',
      port: 4173,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
    preview: {
      host: '0.0.0.0',
      port: 4173,
    },
    build: {},
  };
});
