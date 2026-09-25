<template>
  <!--
    可折叠的说明块。

    ## 为什么需要它

    配置页有 6 段较长的说明（168~718 字符）。桌面端宽屏下它们只占几行，问题不大；
    但手机屏幕窄，同样的文字要占十几行 —— 一屏放不下一个设置项，用户得不停滚动
    才能找到真正要改的开关。用户反馈：「手机屏幕小，配置页面描述长，占篇幅大，
    默认做成隐藏起来，点击再展开」。

    ## 为什么不用 v-expansion-panels

    那会引入一套**新的视觉语言**（面板边框、标题行样式、多个面板互斥/联动的语义），
    而这里的每一段说明都**依附于它上面的那个设置项**，不是一组并列的可展开面板。
    本组件保留 `v-alert type="info" variant="tonal"` 的既有外观（与页面其它说明块
    一致 —— 用户此前专门要求过统一），只把正文折叠起来。

    ## 行为

    - **默认折叠**：标题之外不占高度，一屏能看到更多设置项。
    - 标题整行可点、可键盘操作（Enter/Space），带 `aria-expanded`。
    - 展开状态**不持久化**：它是阅读辅助，不是设置；记住它反而会让"我上次展开过"
      变成一种隐形状态，下次打开页面时看到的内容不一致。
  -->
  <!-- ⚠️ `:icon="false"` 是必需的：`type="info"` 会让 Vuetify 自动挂一个
       **28px 的 `mdi-information`**（源码 `icon.value = props.icon ?? '$'+type`，
       且 `.v-alert__prepend` 并未被隐藏）。那个图标纯装饰 —— 标题已经说明这是
       什么块了，而它在手机窄屏上实打实地吃掉一块横向空间。
       折叠箭头（16px）保留：它是**唯一**提示"这行可以点开"的线索。 -->
  <v-alert
    type="info"
    variant="tonal"
    density="compact"
    :icon="false"
    class="rounded-lg text-body-2 collapsible-note"
  >
    <div
      class="note-head d-flex align-center"
      role="button"
      tabindex="0"
      :aria-expanded="open ? 'true' : 'false'"
      @click="toggle"
      @keydown.enter.prevent="toggle"
      @keydown.space.prevent="toggle"
    >
      <v-icon size="16" class="mr-1 flex-shrink-0">{{ open ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
      <span class="font-weight-bold">{{ title }}</span>
      <span v-if="!open" class="text-medium-emphasis note-hint">（点击展开）</span>
    </div>
    <div v-show="open" class="mt-1"><slot /></div>
  </v-alert>
</template>

<script setup>
import { ref } from 'vue'

defineProps({
  title: { type: String, required: true },
})

const open = ref(false)
function toggle() { open.value = !open.value }
</script>

<style scoped>
.note-head {
  cursor: pointer;
  /* 点击热区上下各留一点，手机上更好按 */
  padding: 2px 0;
  user-select: none;
}
.note-head:hover .note-hint {
  opacity: 1;
}
.note-hint {
  font-weight: normal;
  opacity: 0.75;
  /* ③ 推到同一行最右端。用 margin-left:auto 而不是给标题行 justify-space-between：
     后者在标题很长时会把它也一起推走，读起来像两个并列元素；
     这里标题固定靠左跟随箭头，「（点击展开）」单独吸右。 */
  margin-left: auto;
  padding-left: 8px;
  white-space: nowrap;
}
/* 折叠时标题行是唯一的抓手，给它一个明确的焦点样式（键盘用户） */
.note-head:focus-visible {
  outline: 2px solid rgb(var(--v-theme-primary));
  outline-offset: 2px;
  border-radius: 4px;
}
</style>
