<template>
  <div class="plugin-page">
    <v-card class="rounded-xl overflow-hidden page-card" elevation="0" variant="outlined">
      <!-- 顶栏 -->
      <v-card-item class="px-4 py-3 border-b header-surface">
        <template #prepend>
          <div class="header-icon-box mr-3">
            <v-icon color="primary" size="20">mdi-history</v-icon>
          </div>
        </template>

        <v-card-title class="d-flex align-center flex-wrap">
          <span class="text-subtitle-1 font-weight-bold">{{ title }}</span>
          <v-chip
            v-if="pagination.total > 0"
            size="x-small"
            variant="tonal"
            color="primary"
            class="ml-3 font-weight-medium"
          >
            {{ pagination.total }} 条记录
          </v-chip>
        </v-card-title>

        <template #append>
          <div class="d-flex align-center gap-2">
            <v-btn
              color="primary"
              rounded="lg"
              variant="flat"
              size="small"
              class="px-3 font-weight-medium"
              :loading="loading"
              @click="refreshData"
            >
              <v-icon start size="18">mdi-refresh</v-icon>
              刷新
            </v-btn>

            <v-menu>
              <template v-slot:activator="{ props }">
                <v-btn
                  v-bind="props"
                  color="secondary"
                  rounded="lg"
                  variant="tonal"
                  size="small"
                  class="px-3 font-weight-medium"
                  :loading="clearing"
                >
                  <v-icon start size="18">mdi-delete-sweep</v-icon>
                  清理
                </v-btn>
              </template>
              <v-list rounded="lg" elevation="3" class="mt-1 py-1" density="compact" min-width="180">
                <v-list-item @click="clearOldRecords(7)" rounded="lg">
                  <template v-slot:prepend><v-icon size="18" class="mr-2" color="warning">mdi-calendar-alert</v-icon></template>
                  <v-list-item-title class="text-body-2 font-weight-medium">清理 7 天前</v-list-item-title>
                </v-list-item>
                <v-list-item @click="clearOldRecords(30)" rounded="lg">
                  <template v-slot:prepend><v-icon size="18" class="mr-2" color="error">mdi-calendar-remove</v-icon></template>
                  <v-list-item-title class="text-body-2 font-weight-medium">清理 30 天前</v-list-item-title>
                </v-list-item>
                <v-list-item @click="clearOldRecords(90)" rounded="lg">
                  <template v-slot:prepend><v-icon size="18" class="mr-2" color="grey">mdi-delete-forever</v-icon></template>
                  <v-list-item-title class="text-body-2 font-weight-medium">清理 90 天前</v-list-item-title>
                </v-list-item>
              </v-list>
            </v-menu>

            <v-btn
              color="info"
              rounded="lg"
              variant="tonal"
              size="small"
              class="px-3 font-weight-medium"
              @click="exportLogs"
            >
              <v-icon start size="18">mdi-download</v-icon>
              导出
            </v-btn>

            <v-btn
              color="primary"
              rounded="lg"
              variant="outlined"
              size="small"
              class="px-3 font-weight-medium config-btn"
              @click="notifySwitch"
            >
              <v-icon start size="18">mdi-cog</v-icon>
              配置
            </v-btn>

            <v-btn
              icon
              variant="text"
              size="small"
              class="rounded-lg close-btn ml-1"
              @click="notifyClose"
            >
              <v-icon size="18">mdi-close</v-icon>
              <v-tooltip activator="parent" location="bottom">关闭</v-tooltip>
            </v-btn>
          </div>
        </template>
      </v-card-item>

      <!-- 内容区 -->
      <v-card-text class="pa-4 body-surface" style="max-height: 75vh; overflow-y: auto;">
        <v-alert
          v-if="error"
          type="error"
          variant="tonal"
          class="mb-4 rounded-lg"
          closable
          @click:close="error = null"
        >
          {{ error }}
        </v-alert>

        <!-- 骨架屏 -->
        <div v-if="loading" class="pa-2">
          <v-skeleton-loader
            type="list-item-avatar-two-line, list-item-avatar-two-line, list-item-avatar-two-line"
            class="rounded-lg"
          ></v-skeleton-loader>
        </div>

        <div v-else>
          <!-- 带时间线的同步记录 -->
          <div v-if="groupedSyncRecords && groupedSyncRecords.length">
            <v-timeline density="compact" side="end" align="start">
              <v-timeline-item
                v-for="(group, index) in groupedSyncRecords"
                :key="index"
                size="small"
                :dot-color="getItemColor(group.status)"
                fill-dot
              >
                <template #icon>
                  <v-icon size="14" color="white">{{ getItemIcon(group.status) }}</v-icon>
                </template>

                <v-card
                  variant="outlined"
                  class="record-card rounded-lg pa-3 ml-2"
                  :class="group.status === 'error' ? 'record-card-error' : 'record-card-success'"
                >
                  <!-- 头部：媒体类型 + 同步类型 + 媒体名 + 时间 -->
                  <div class="d-flex justify-space-between align-center flex-wrap gap-2 mb-2">
                    <div class="d-flex align-center overflow-hidden">
                      <div class="media-badge mr-2" :class="`media-badge-${getMediaTypeColor(group.media_type)}`">
                        <v-icon size="15" :color="getMediaTypeColor(group.media_type)">
                          {{ getMediaTypeIcon(group.media_type) }}
                        </v-icon>
                      </div>
                      <span class="font-weight-bold text-body-2 text-truncate record-title">{{ group.media_name }}</span>
                      <v-icon
                        size="16"
                        :color="getSyncTypeColor(group.sync_type)"
                        class="ml-2 flex-shrink-0"
                      >
                        {{ getSyncTypeIcon(group.sync_type) }}
                      </v-icon>
                    </div>
                    <span class="text-caption text-disabled text-no-wrap time-chip px-2 py-1 rounded-pill">
                      {{ formatTime(group.timestamp) }}
                    </span>
                  </div>

                  <!-- 用户流向 -->
                  <div class="d-flex align-center flex-wrap gap-1 mb-2">
                    <v-chip size="x-small" variant="tonal" color="blue-grey" class="font-weight-medium">
                      <v-icon start size="12">mdi-account-arrow-right</v-icon>
                      {{ group.source_user }}
                    </v-chip>
                    <v-icon size="12" color="grey" class="mx-1">mdi-arrow-right-bold</v-icon>
                    <v-chip
                      v-for="(target_user, idx) in group.target_users"
                      :key="idx"
                      size="x-small"
                      variant="tonal"
                      :color="group.status === 'error' ? 'error' : 'success'"
                      class="font-weight-medium"
                    >
                      {{ target_user }}
                    </v-chip>
                  </div>

                  <!-- 描述 -->
                  <div v-if="group.description" class="desc-box text-caption d-flex align-center rounded pa-2">
                    <v-icon size="14" class="mr-2 flex-shrink-0" color="indigo">mdi-information-outline</v-icon>
                    <span>{{ group.description }}</span>
                  </div>

                  <!-- 错误信息 -->
                  <div
                    v-if="group.error_message"
                    class="error-box text-caption d-flex align-start rounded pa-2 mt-2"
                  >
                    <v-icon size="14" class="mr-2 flex-shrink-0 mt-1" color="error">mdi-alert-circle</v-icon>
                    <span class="text-break">{{ group.error_message }}</span>
                  </div>
                </v-card>
              </v-timeline-item>
            </v-timeline>

            <!-- 加载更多 -->
            <div v-if="pagination.hasMore" class="text-center mt-4 mb-2">
              <v-btn
                color="primary"
                variant="tonal"
                rounded="pill"
                class="px-6 font-weight-medium"
                @click="loadMoreRecords"
                :loading="pagination.loading"
              >
                <v-icon start size="18">mdi-chevron-down</v-icon>
                加载更多历史记录
              </v-btn>
            </div>

            <!-- 分页信息 -->
            <div v-if="pagination.total > 0" class="text-center mt-3 text-caption text-disabled">
              当前展示 {{ syncRecords.length }} / {{ pagination.total }} 条记录
            </div>
          </div>

          <!-- 空状态 -->
          <div v-else class="empty-box d-flex flex-column align-center justify-center py-10 px-4 rounded-lg text-center">
            <div class="empty-icon mb-3">
              <v-icon size="34" color="primary">mdi-history</v-icon>
            </div>
            <div class="text-subtitle-2 font-weight-bold text-medium-emphasis">暂无同步记录</div>
            <div class="text-caption text-disabled mt-1">当配置生效且触发同步后，相关的记录会展示在此处</div>
          </div>
        </div>
      </v-card-text>
    </v-card>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'

// 接收初始配置
const props = defineProps({
  model: {
    type: Object,
    default: () => {},
  },
  api: {
    type: Object,
    default: () => {},
  },
})

// 组件状态
const title = ref('观看记录同步')
const loading = ref(true)
const error = ref(null)
const syncRecords = ref([])
const groupedSyncRecords = ref([])
const clearing = ref(false)
// 分页相关状态
const pagination = ref({
  offset: 0,
  limit: 20,
  total: 0,
  hasMore: false,
  loading: false
})

// 自定义事件，用于通知主应用刷新数据
const emit = defineEmits(['action', 'switch', 'close'])

// 获取状态图标
function getItemIcon(status) {
  const icons = {
    'success': 'mdi-check',
    'error': 'mdi-alert',
    'pending': 'mdi-clock-outline',
  }
  return icons[status] || 'mdi-information'
}

// 获取状态颜色
function getItemColor(status) {
  const colors = {
    'success': 'success',
    'error': 'error',
    'pending': 'warning',
  }
  return colors[status] || 'grey'
}

// 获取媒体类型图标
function getMediaTypeIcon(mediaType) {
  const icons = {
    'Movie': 'mdi-movie',
    'Episode': 'mdi-television',
    'Series': 'mdi-television-box',
  }
  return icons[mediaType] || 'mdi-play-circle'
}

// 获取同步类型图标
function getSyncTypeIcon(syncType) {
  const icons = {
    'playback': 'mdi-play',
    'favorite': 'mdi-heart',
    'not_favorite': 'mdi-heart-outline',
    'played_status': 'mdi-eye',
    'mark_played': 'mdi-eye',
    'mark_unplayed': 'mdi-eye-off-outline'
  }
  return icons[syncType] || 'mdi-sync'
}

// 获取同步类型颜色
function getSyncTypeColor(syncType) {
  const colors = {
    'playback': 'primary',
    'favorite': 'pink',
    'not_favorite': 'grey',
    'played_status': 'grey',
    'mark_played': 'grey',
    'mark_unplayed': 'grey'
  }
  return colors[syncType] || 'grey'
}

// 获取媒体类型颜色
function getMediaTypeColor(mediaType) {
  const colors = {
    'Movie': 'blue',
    'Episode': 'green',
    'Series': 'purple',
  }
  return colors[mediaType] || 'grey'
}

// 获取事件描述
function getEventDescription(syncType) {
  const descriptions = {
    'favorite': '收藏了媒体',
    'not_favorite': '取消收藏媒体',
    'mark_played': '标记为已看',
    'mark_unplayed': '标记为未看'
  }
  return descriptions[syncType]
}

// 格式化时间
function formatTime(timestamp) {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  const now = new Date()
  const diff = now - date

  if (diff < 60000) { // 1分钟内
    return '刚刚'
  } else if (diff < 3600000) { // 1小时内
    return Math.floor(diff / 60000) + '分钟前'
  } else if (diff < 86400000) { // 1天内
    return Math.floor(diff / 3600000) + '小时前'
  } else {
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString()
  }
}

// 格式化播放进度 (始终显示 hh:mm:ss 格式)
function formatProgress(positionTicks) {
  if (!positionTicks) return ''

  // 将ticks转换为秒 (1 tick = 100 nanoseconds, 10,000,000 ticks = 1 second)
  const totalSeconds = Math.floor(positionTicks / 10000000)

  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60

  // 始终显示 hh:mm:ss 格式
  return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`
}

// 获取和刷新数据
async function refreshData() {
  loading.value = true
  error.value = null

  try {
    // 获取同步记录
    await loadSyncRecords()
  } catch (err) {
    console.error('获取数据失败:', err)
    error.value = err.message || '获取数据失败'
  } finally {
    loading.value = false
    // 通知主应用组件已更新
    emit('action')
  }
}

// 加载同步记录（初始加载）
async function loadSyncRecords() {
  try {
    // 重置分页状态
    pagination.value.offset = 0

    // 使用props.api进行API调用，它已经包含了认证信息
    const result = await props.api.get(`plugin/WatchSync/records?limit=${pagination.value.limit}&offset=${pagination.value.offset}`)

    if (result && result.success) {
      syncRecords.value = result.data || []

      // 更新分页信息
      if (result.pagination) {
        pagination.value.total = result.pagination.total
        pagination.value.hasMore = result.pagination.has_more
      }

      // 对同步记录进行分组
      groupSyncRecords()
      return
    } else {
      console.warn('获取同步记录失败:', result?.message || '未知错误')
    }
  } catch (err) {
    console.error('获取同步记录失败:', err)
  }
  // 设置空数组作为默认值
  syncRecords.value = []
  groupedSyncRecords.value = []
}

// 加载更多记录
async function loadMoreRecords() {
  if (pagination.value.loading || !pagination.value.hasMore) {
    return
  }

  pagination.value.loading = true

  try {
    // 计算下一页的offset
    const nextOffset = pagination.value.offset + pagination.value.limit

    const result = await props.api.get(`plugin/WatchSync/records?limit=${pagination.value.limit}&offset=${nextOffset}`)

    if (result && result.success) {
      // 追加新记录到现有记录
      syncRecords.value.push(...(result.data || []))

      // 更新分页信息
      if (result.pagination) {
        pagination.value.offset = nextOffset
        pagination.value.total = result.pagination.total
        pagination.value.hasMore = result.pagination.has_more
      }

      // 重新分组记录
      groupSyncRecords()
    } else {
      console.warn('加载更多记录失败:', result?.message || '未知错误')
    }
  } catch (err) {
    console.error('加载更多记录失败:', err)
  } finally {
    pagination.value.loading = false
  }
}

// 分组同步记录
function groupSyncRecords() {
  const groups = new Map()

  syncRecords.value.forEach(record => {
    const timestamp = new Date(record.timestamp || record.created_at)
    // 使用1分钟的时间窗口来聚合由单个操作触发的多个同步事件
    const timeWindow = Math.floor(timestamp.getTime() / (1 * 60 * 1000))

    // 分组键由源用户、媒体、操作类型和时间窗口共同决定
    const groupKey = `${record.source_user}_${record.media_name}_${record.sync_type}_${timeWindow}`

    if (!groups.has(groupKey)) {
      groups.set(groupKey, {
        ...record,
        target_users: [record.target_user] // 初始化目标用户列表
      })
    } else {
      const group = groups.get(groupKey)
      // 将新的目标用户添加到现有组中
      if (!group.target_users.includes(record.target_user)) {
        group.target_users.push(record.target_user)
      }

      // 确保使用最新的时间戳
      if (timestamp > new Date(group.timestamp)) {
        group.timestamp = record.timestamp
      }

      // 对于播放事件，始终更新到最新的进度
      if (record.sync_type === 'playback' && record.position_ticks > (group.position_ticks || 0)) {
          group.position_ticks = record.position_ticks;
      }

      // 如果有任何一个同步失败，整个组标记为失败
      if (record.status === 'error' || record.status === 'failed') {
        group.status = 'error'
      }
    }
  })

  // 转换为数组并按时间排序
  groupedSyncRecords.value = Array.from(groups.values())
    .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
    .map(group => {
      // 添加描述
      if (group.sync_type === 'playback') {
        group.description = `播放进度: ${formatProgress(group.position_ticks)}`;
      } else {
        group.description = getEventDescription(group.sync_type);
      }

      return group
    })
}

// 清理旧记录
async function clearOldRecords(days = 30) {
  clearing.value = true
  try {
    const result = await props.api.delete(`plugin/WatchSync/records/old?days=${days}`)
    if (result && result.success) {
      console.log('清理记录成功:', result.message)
      // 重新加载数据
      await loadSyncRecords()
    } else {
      console.warn('清理记录失败:', result?.message || '未知错误')
    }
  } catch (err) {
    console.error('清理记录失败:', err)
  } finally {
    clearing.value = false
  }
}

// 导出日志
function exportLogs() {
  try {
    const data = {
      exportTime: new Date().toISOString(),
      records: syncRecords.value
    }

    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `watchsync-logs-${new Date().toISOString().split('T')[0]}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)

    console.log('日志导出成功')
  } catch (err) {
    console.error('导出日志失败:', err)
  }
}

// 通知主应用切换到配置页面
function notifySwitch() {
  emit('switch')
}

// 通知主应用关闭组件
function notifyClose() {
  emit('close')
}

// 组件挂载时加载数据
onMounted(() => {
  refreshData()
})
</script>
<style scoped>
/* 卡片 */
.page-card {
  background: rgb(var(--v-theme-surface, 255, 255, 255));
}

/* 头部微渐变 */
.header-surface {
  background: linear-gradient(
    135deg,
    rgba(var(--v-theme-primary, 24, 103, 192), 0.07) 0%,
    rgba(var(--v-theme-primary, 24, 103, 192), 0.02) 100%
  );
}

.header-icon-box {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 9px;
  background: rgba(var(--v-theme-primary, 24, 103, 192), 0.12);
}

.config-btn {
  background: rgb(var(--v-theme-surface, 255, 255, 255));
}

.close-btn {
  color: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.6);
  border: 1px solid rgba(var(--v-theme-on-surface, 0, 0, 0), 0.12);
}

/* 内容背景 */
.body-surface {
  background: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.015);
}

/* 记录卡片 */
.record-card {
  background: rgb(var(--v-theme-surface, 255, 255, 255));
  transition: box-shadow 0.2s ease, border-color 0.2s ease;
}
.record-card:hover {
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.07);
}
.record-card-success {
  border-color: rgba(var(--v-theme-success, 76, 175, 80), 0.28);
}
.record-card-error {
  border-color: rgba(var(--v-theme-error, 176, 0, 32), 0.35);
}

.record-title {
  color: rgb(var(--v-theme-on-surface, 0, 0, 0));
}

/* 媒体类型徽章 */
.media-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  flex-shrink: 0;
}
.media-badge-blue   { background: rgba(33, 150, 243, 0.12); }
.media-badge-green  { background: rgba(76, 175, 80, 0.12); }
.media-badge-purple { background: rgba(156, 39, 176, 0.12); }
.media-badge-grey   { background: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.08); }

/* 时间胶囊 */
.time-chip {
  background: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.05);
}

/* 描述块 */
.desc-box {
  background: rgba(var(--v-theme-info, 33, 150, 243), 0.08);
  border: 1px solid rgba(var(--v-theme-info, 33, 150, 243), 0.18);
  color: rgb(var(--v-theme-on-surface, 0, 0, 0));
}

/* 错误块 */
.error-box {
  background: rgba(var(--v-theme-error, 176, 0, 32), 0.08);
  border: 1px solid rgba(var(--v-theme-error, 176, 0, 32), 0.25);
  color: rgb(var(--v-theme-error, 176, 0, 32));
}

/* 空状态 */
.empty-box {
  background: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.02);
  border: 1px dashed rgba(var(--v-theme-on-surface, 0, 0, 0), 0.16);
}
.empty-icon {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(var(--v-theme-primary, 24, 103, 192), 0.1);
}

.gap-1 {
  gap: 4px;
}
.gap-2 {
  gap: 8px;
}
</style>
