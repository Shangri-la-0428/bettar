import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'BETAR_');
  const webPort = Number(env.BETAR_WEB_PORT || 5173);
  const enginePort = Number(env.BETAR_ENGINE_PORT || 8765);
  return {
  server: {
    host: '127.0.0.1', port: webPort, strictPort: true,
    proxy: { '/api': `http://127.0.0.1:${enginePort}` },
  },
  preview: { port: 4173, proxy: { '/api': `http://127.0.0.1:${enginePort}` } },
  };
});
