import { createApp } from 'vue'
import Page from './components/Page.vue'

// 仅用于本地 `npm run dev` 预览。
// 线上由宿主加载 dist/assets/remoteEntry.js 并挂载 ./Page、./Config、./Dashboard，
// Vuetify 实例与全局样式均由宿主提供，插件侧不做重复引入。
createApp(Page).mount('#app')
