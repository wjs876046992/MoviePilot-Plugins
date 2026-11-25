<template>
  <div
    class="p115-inherit-banner"
    :class="inherit ? 'p115-inherit-banner--on' : 'p115-inherit-banner--off'"
  >
    <div class="p115-inherit-main">
      <div class="p115-inherit-text">
        <span class="p115-inherit-icon">
          <v-icon size="18" :icon="inherit ? 'mdi-check-circle-outline' : 'mdi-alert-circle-outline'" />
        </span>
        <span class="p115-inherit-title">
          <template v-if="inherit">已继承统一媒体库目录映射</template>
          <template v-else>已开启本场景独立路径配置</template>
        </span>
        <span class="p115-inherit-desc">
          <template v-if="inherit">当前生效 {{ count }} 条，点击右侧开关可改为本场景单独配置</template>
          <template v-else>不继承统一映射，本页配置仅对「{{ sceneLabel }}」生效</template>
        </span>
      </div>

      <div class="p115-inherit-actions">
        <button
          v-if="inherit"
          type="button"
          class="p115-btn p115-btn--sm p115-btn--tonal"
          @click="$emit('locate')"
        >
          <v-icon size="15" icon="mdi-arrow-top-right" />
          <span>去修改</span>
        </button>
        <v-switch
          :model-value="!inherit"
          color="warning"
          density="compact"
          hide-details
          inset
          class="p115-inherit-switch"
          @update:model-value="$emit('update:custom', $event)"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  inherit: {
    type: Boolean,
    default: true,
  },
  count: {
    type: Number,
    default: 0,
  },
  sceneLabel: {
    type: String,
    default: '当前场景',
  },
});

defineEmits(['locate', 'update:custom']);
</script>

<style scoped>
.p115-inherit-banner {
  border-radius: 13px;
  border: 1px solid var(--p115-border-hairline);
  padding: 11px 14px;
  min-width: 0;
}

.p115-inherit-banner--on {
  background: rgba(52, 199, 89, 0.08);
  border-color: rgba(52, 199, 89, 0.24);
}

.p115-inherit-banner--off {
  background: rgba(255, 159, 10, 0.09);
  border-color: rgba(255, 159, 10, 0.26);
}

.p115-inherit-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  min-width: 0;
}

.p115-inherit-text {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
  flex: 1 1 260px;
}

.p115-inherit-icon {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
}

.p115-inherit-banner--on .p115-inherit-icon {
  color: var(--p115-green-ink);
}

.p115-inherit-banner--off .p115-inherit-icon {
  color: var(--p115-amber-ink);
}

.p115-inherit-title {
  font-size: 0.81rem;
  font-weight: 620;
  color: var(--p115-text-primary);
  white-space: nowrap;
}

.p115-inherit-desc {
  font-size: 0.75rem;
  color: var(--p115-text-tertiary);
  min-width: 0;
}

.p115-inherit-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
  margin-left: auto;
}

.p115-inherit-switch {
  flex: 0 0 auto;
}

@media (max-width: 600px) {
  .p115-inherit-main {
    flex-direction: column;
    align-items: stretch;
  }

  .p115-inherit-actions {
    justify-content: space-between;
    margin-left: 0;
  }

  .p115-inherit-title {
    white-space: normal;
  }
}
</style>
