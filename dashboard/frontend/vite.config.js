import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
    plugins: [react()],
    server: {
        port: 5173,
        proxy: {
            // Dashboard data API
            '/api': {
                target: 'http://localhost:8050',
                changeOrigin: true,
            },
            // Chainlit API + WebSocket (single prefix to avoid CORS in dev)
            '/chainlit': {
                target: 'http://localhost:8000',
                changeOrigin: true,
                ws: true,
                rewrite: (path) => path.replace(/^\/chainlit/, ''),
            },
        },
    },
    build: {
        outDir: 'dist',
        emptyOutDir: true,
    },
});
