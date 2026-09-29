import federation from '@originjs/vite-plugin-federation'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [
    vue(),
    federation({
      name: 'BrushFlow',
      filename: 'remoteEntry.js',
      exposes: {
        './Page': './src/components/Page.vue',
        './Config': './src/components/Config.vue',
        './Dashboard': './src/components/Dashboard.vue',
        './AppPage': './src/components/AppPage.vue',
      },
      shared: {
        vue: {
          requiredVersion: false,
          generate: false,
          singleton: true,
        },
        vuetify: {
          requiredVersion: false,
          generate: false,
          singleton: true,
        },
        // ⚠️ 不要把 'vuetify/styles' 加进共享列表：源码并未显式 import 它，
        // 它只会让构建额外产出 dist/assets/__federation_shared_vuetify/styles-*.css。
        // 该文件既不被 remoteEntry 引用，又会被 .github/scripts/check_federation_css.py
        // 判为「不得发布 Vuetify 共享基础样式」，卡住发布门禁。
      },
      format: 'esm',
    }),
  ],
  build: {
    target: 'esnext',
    minify: false,
    cssCodeSplit: true,
  },
  css: {
    postcss: {
      plugins: [
        {
          postcssPlugin: 'internal:charset-removal',
          AtRule: {
            charset: atRule => {
              if (atRule.name === 'charset') atRule.remove()
            },
          },
        },
        {
          postcssPlugin: 'vuetify-filter',
          Root(root) {
            root.walkRules(rule => {
              if (rule.selector && (rule.selector.includes('.v-') || rule.selector.includes('.mdi-'))) {
                rule.remove()
              }
            })
          },
        },
      ],
    },
  },
})
