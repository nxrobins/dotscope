import { defineConfig } from 'vite';

export default defineConfig({
  build: {
    outDir: '../dotscope/assets/ui',
    emptyOutDir: true,
    assetsInlineLimit: 100000000, 
    rollupOptions: {
      output: {
        entryFileNames: 'bundle.js',
        assetFileNames: 'styles.css'
      }
    }
  }
});
