import federation from '@originjs/vite-plugin-federation';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const AUTH_REMOTE =
  process.env.VITE_AUTH_REMOTE ?? 'http://localhost:5001/assets/remoteEntry.js';
const CHAT_REMOTE =
  process.env.VITE_CHAT_REMOTE ?? 'http://localhost:5002/assets/remoteEntry.js';

export default defineConfig({
  plugins: [
    react(),
    federation({
      name: 'shell',
      remotes: {
        auth: AUTH_REMOTE,
        chat: CHAT_REMOTE,
      },
      shared: ['react', 'react-dom', 'react-router-dom'],
    }),
  ],
  build: {
    target: 'esnext',
    minify: false,
    cssCodeSplit: false,
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
});
