import { defineConfig } from 'vite'; import preact from '@preact/preset-vite';
export default defineConfig({plugins:[preact()],base:'/',build:{outDir:'app/static',emptyOutDir:true,assetsDir:'assets',rollupOptions:{output:{entryFileNames:'assets/[name]-[hash].js',chunkFileNames:'assets/[name]-[hash].js',assetFileNames:'assets/[name]-[hash][extname]'}}}});
