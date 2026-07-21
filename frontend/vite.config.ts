import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/admin': 'http://127.0.0.1:2100',
      '/auth': 'http://127.0.0.1:2100',
      '/v1': 'http://127.0.0.1:2100',
    },
  },
});
