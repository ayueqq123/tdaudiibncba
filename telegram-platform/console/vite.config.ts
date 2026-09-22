import path from 'node:path'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/tg/',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
