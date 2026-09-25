import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import federation from '@originjs/vite-plugin-federation'

export default defineConfig({
  plugins: [
    vue(),
    federation({
      name: 'Rsync115Sync',
      filename: 'remoteEntry.js',
      // ⚠️ 只显式暴露两个入口，**不要**写成 '.'（它会按目录匹配、把 src 下
      // 所有组件都当成可被宿主加载的入口，且会与预构建同步门禁的检查口径冲突）。
      // 共享的 CollapsibleNote 由 Config.vue 直接 import，不需要单独暴露。
      exposes: {
        './Page': './src/components/Page.vue',
        './Config': './src/components/Config.vue',
      },
      shared: {
        vue: {
          generate: false,
        },
        vuetify: {
          generate: false,
        },
      },
    }),
  ],
  build: {
    target: 'esnext',
    minify: false,
    cssCodeSplit: true,
  },
})
