<template>
  <div class="p115-section-stack">
    <div class="p115-callout p115-callout--info">
      <v-icon size="18" color="primary" icon="mdi-folder-sync-outline" class="mt-0.5 flex-shrink-0" />
      <div>
        <div class="mb-1">
          <strong>统一媒体库目录映射：</strong>在此维护「本地 STRM 目录 ↔ 115 网盘媒体库目录」的完整对应关系。
        </div>
        <div>
          每行勾选生效场景后，被勾选的场景会自动继承本表，无需在各自子页签里重复填写；未勾选的场景仍可打开该页签的「独立自定义路径」单独配置。
        </div>
        <div v-if="cd2Enabled" class="mt-1">
          • 已开启 CloudDrive2 储存监控：可在对应行填写 CD2 挂载前缀，仅「监控 MP 整理」使用。
        </div>
      </div>
    </div>

    <AppleSettingsGroup
      title="媒体库目录映射"
      subtitle="一行 = 一条本地目录与网盘目录的对应关系"
      icon="mdi-folder-swap-outline"
      padded
    >
      <PathMappingComposer
        mode="dual"
        key-prefix="unified"
        :items="unifiedPaths"
        :show-cd2-prefix="cd2Enabled"
        add-label="添加媒体库目录映射"
        @add="addPath('unified')"
        @remove="(i) => removePath(i, 'unified')"
        @browse-local="(i) => openDirSelector(i, 'local', 'unified')"
        @browse-remote="(i) => openDirSelector(i, 'remote', 'unified')"
      >
        <template #row-footer="{ item }">
          <div class="p115-scene-row">
            <span class="p115-scene-label">生效场景</span>
            <div class="p115-scene-chips">
              <button
                v-for="scene in scenes"
                :key="scene.key"
                type="button"
                class="p115-scene-chip"
                :class="item[scene.key] ? 'p115-scene-chip--on' : ''"
                @click="item[scene.key] = !item[scene.key]"
              >
                <v-icon size="14" :icon="item[scene.key] ? 'mdi-check' : scene.icon" />
                <span>{{ scene.label }}</span>
              </button>
            </div>
          </div>
        </template>
      </PathMappingComposer>

      <div class="p115-callout p115-callout--info mt-3">
        <v-icon size="16" color="primary" icon="mdi-information-outline" class="mt-0.5 flex-shrink-0" />
        <div>
          <div>• <strong>本地 STRM 目录：</strong>本地 STRM 文件生成路径</div>
          <div>• <strong>网盘媒体库目录：</strong>需要生成本地 STRM 文件的网盘媒体库路径</div>
          <div v-if="cd2Enabled">• <strong>CD2 挂载前缀：</strong>仅 CloudDrive2 储存时填写，会与此行网盘路径拼接</div>
          <div>• 单侧留空的映射行不会写入任何场景配置</div>
        </div>
      </div>
    </AppleSettingsGroup>

    <AppleSettingsGroup
      title="媒体服务器路径转换"
      subtitle="Emby / Jellyfin 刷新与信息提取使用；两端挂载一致时留空"
      icon="mdi-swap-horizontal-circle-outline"
      padded
    >
      <PathMappingComposer
        mode="dual"
        key-prefix="unified-mp"
        :items="unifiedMpPaths"
        local-label="媒体服务器映射目录"
        local-placeholder="/data/strm"
        local-icon="mdi-television-play"
        remote-label="MoviePilot 映射目录"
        remote-placeholder="/mnt/strm"
        remote-icon="mdi-folder-home-outline"
        :allow-local-browse="false"
        :allow-remote-browse="false"
        add-label="添加转换规则"
        @add="addPath('unified-mp')"
        @remove="(i) => removePath(i, 'unified-mp')"
      />
      <div class="p115-callout p115-callout--info mt-3">
        <v-icon size="16" color="primary" icon="mdi-information-outline" class="mt-0.5 flex-shrink-0" />
        <div>
          <div>• 媒体服务器映射路径与 MoviePilot 映射路径不一致时必须配置，否则刷新与 Emby 提取媒体信息会失败。</div>
          <div>• 未开启对应场景「独立自定义路径」时，本表会自动分发到该场景。</div>
        </div>
      </div>
    </AppleSettingsGroup>
  </div>
</template>

<script setup>
import { computed, inject } from 'vue';
import AppleSettingsGroup from '../ui/AppleSettingsGroup.vue';
import PathMappingComposer from '../ui/PathMappingComposer.vue';

const config = inject('config');
const unifiedPaths = inject('unifiedPaths');
const unifiedMpPaths = inject('unifiedMpPaths');
const addPath = inject('addPath');
const removePath = inject('removePath');
const openDirSelector = inject('openDirSelector');

/** 统一表支持的四类生效场景，key 与 usePathManagement 的数据字段一一对应。 */
const scenes = [
  { key: 'enable_transfer', label: '监控MP整理', icon: 'mdi-file-move-outline' },
  { key: 'enable_full', label: '全量同步', icon: 'mdi-sync' },
  { key: 'enable_inc', label: '增量同步', icon: 'mdi-book-sync-outline' },
  { key: 'enable_life', label: '生活事件', icon: 'mdi-calendar-heart' },
];

const cd2Enabled = computed(() => {
  const c = config?.value ?? config;
  return Boolean(c?.transfer_monitor_clouddrive2_enabled);
});
</script>

<style scoped>
.p115-section-stack {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
  max-width: 100%;
}

.p115-scene-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--p115-border-hairline);
  min-width: 0;
}

.p115-scene-label {
  font-size: 0.73rem;
  font-weight: 620;
  color: var(--p115-text-tertiary);
  white-space: nowrap;
  flex-shrink: 0;
}

.p115-scene-chips {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
  min-width: 0;
}

.p115-scene-chip {
  appearance: none;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 11px;
  min-height: 28px;
  border-radius: var(--p115-r-pill);
  border: 1px solid var(--p115-border-hairline);
  background: var(--p115-bg-card);
  color: var(--p115-text-tertiary);
  font-size: 0.75rem;
  font-weight: 560;
  font-family: var(--p115-font-sans);
  white-space: nowrap;
  cursor: pointer;
  transition:
    transform 0.12s var(--p115-press),
    background-color 0.2s ease,
    border-color 0.2s ease,
    color 0.2s ease;
}

.p115-scene-chip:active {
  transform: scale(0.96);
}

.p115-scene-chip--on {
  background: rgba(91, 207, 250, 0.16);
  border-color: rgba(91, 207, 250, 0.32);
  color: var(--p115-blue-ink);
  font-weight: 620;
}

@media (max-width: 600px) {
  .p115-scene-row {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
}
</style>
