import {defineConfig} from 'vite';
export default defineConfig({
  build: {outDir: '../src/coc_bot/web/static', emptyOutDir: true},
  server: {proxy: {'/api': {target: 'http://127.0.0.1:8765', ws: true}}}
});
