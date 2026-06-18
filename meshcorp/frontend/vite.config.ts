import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte()],
  server: {
    proxy: {
      '/api': 'http://localhost:8150',
      '/ws': {
        target: 'ws://localhost:8150',
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
