<template>
  <div class="plugin-page h-100">
    <v-card class="d-flex flex-column h-100 rounded-xl overflow-hidden page-main-card" elevation="0" variant="outlined">

      <!-- 优雅顶栏（与配置页设计语言保持一致） -->
      <v-card-item class="header-surface px-5 py-3 border-b">
        <template #prepend>
          <div class="header-icon-box mr-3">
            <v-icon color="primary" size="22">mdi-history</v-icon>
          </div>
        </template>

        <div>
          <v-card-title class="text-subtitle-1 font-weight-bold pa-0 d-flex align-center flex-wrap ga-2">
            <span>{{ title }}</span>
            <v-chip
              v-if="pagination.total > 0"
              size="x-small"
              variant="tonal"
              color="primary"
              class="font-weight-bold"
            >
              {{ pagination.total }} 条同步记录
            </v-chip>
          </v-card-title>
          <div class="text-caption text-medium-emphasis">实时查看跨媒体服务器播放进度、收藏与标记同步流水</div>
        </div>

        <template #append>
          <div class="d-flex align-center ga-1">
            <!-- 刷新按钮 -->
            <v-btn
              icon
              variant="tonal"
              color="primary"
              size="small"
              class="rounded-lg mr-1"
              @click="refreshData"
              :loading="loading"
            >
              <v-icon size="18">mdi-refresh</v-icon>
              <v-tooltip activator="parent" location="bottom">刷新记录</v-tooltip>
            </v-btn>

            <!-- 更多操作下拉菜单（清理、导出） -->
            <v-menu location="bottom end">
              <template v-slot:activator="{ props: menuProps }">
                <v-btn
                  icon
                  variant="text"
                  size="small"
                  class="rounded-lg mr-1 text-medium-emphasis"
                  v-bind="menuProps"
                >
                  <v-icon size="18">mdi-dots-vertical</v-icon>
                  <v-tooltip activator="parent" location="bottom">清理与导出</v-tooltip>
                </v-btn>
              </template>
              <v-list density="compact" class="rounded-lg shadow-elevation py-1">
                <v-list-subheader class="text-caption font-weight-bold">清理历史日志</v-list-subheader>
                <v-list-item
                  @click="clearOldRecords(7)"
                  :disabled="clearing"
                  prepend-icon="mdi-calendar-clock"
                  title="清理 7 天前记录"
                ></v-list-item>
                <v-list-item
                  @click="clearOldRecords(30)"
                  :disabled="clearing"
                  prepend-icon="mdi-calendar-month"
                  title="清理 30 天前记录"
                ></v-list-item>
                <v-list-item
                  @click="clearOldRecords(90)"
                  :disabled="clearing"
                  prepend-icon="mdi-calendar-alert"
                  title="清理 90 天前记录"
                ></v-list-item>
                <v-divider class="my-1"></v-divider>
                <v-list-item
                  @click="clearOldRecords(0)"
                  :disabled="clearing"
                  prepend-icon="mdi-delete-forever"
                  title="清理全部记录"
                  base-color="error"
                ></v-list-item>
                <v-divider class="my-1"></v-divider>
                <v-list-item
                  @click="exportLogs"
                  prepend-icon="mdi-download"
                  title="导出记录数据"
                ></v-list-item>
              </v-list>
            </v-menu>

            <!-- 前往配置 -->
            <v-btn
              color="primary"
              rounded="lg"
              variant="outlined"
              size="small"
              class="px-3 font-weight-medium mr-1"
              @click="notifySwitch"
            >
              <v-icon start size="16">mdi-cog-outline</v-icon>
              配置
            </v-btn>

            <!-- 关闭窗口 -->
            <v-btn
              icon
              variant="text"
              size="small"
              class="rounded-lg close-btn text-medium-emphasis"
              @click="notifyClose"
            >
              <v-icon size="18">mdi-close</v-icon>
              <v-tooltip activator="parent" location="bottom">关闭</v-tooltip>
            </v-btn>
          </div>
        </template>
      </v-card-item>

      <!-- 主体滚动区 -->
      <v-card-text class="pa-4 flex-grow-1 overflow-y-auto body-surface">
        <!-- 错误提示条 -->
        <v-alert
          v-if="error"
          type="error"
          variant="tonal"
          class="mb-4 rounded-xl border-opacity-25"
          closable
          @click:close="error = null"
        >
          {{ error }}
        </v-alert>

        <!-- 加载中骨架屏 -->
        <div v-if="loading" class="d-flex flex-column ga-3 py-2">
          <div v-for="i in 4" :key="i" class="skeleton-card pa-4 rounded-xl">
            <div class="d-flex align-center justify-space-between mb-3">
              <div class="d-flex align-center ga-2">
                <v-skeleton-loader type="avatar" size="32"></v-skeleton-loader>
                <v-skeleton-loader type="text" width="180"></v-skeleton-loader>
              </div>
              <v-skeleton-loader type="text" width="70"></v-skeleton-loader>
            </div>
            <v-skeleton-loader type="text" width="60%"></v-skeleton-loader>
          </div>
        </div>

        <!-- 记录流内容区 -->
        <div v-else>
          <div v-if="groupedSyncRecords && groupedSyncRecords.length" class="d-flex flex-column ga-3">
            <div
              v-for="(group, index) in groupedSyncRecords"
              :key="index"
              class="record-stream-card rounded-xl pa-3 pa-sm-4 transition-fast"
              :class="group.status === 'error' ? 'stream-card-error' : 'stream-card-success'"
            >
              <!-- 顶部信息行：状态指示点 + 媒体主信息 + 进度与时间 -->
              <div class="d-flex align-start justify-space-between flex-wrap ga-2 mb-2">
                <div class="d-flex align-center ga-3 flex-grow-1 overflow-hidden">
                  <!-- 状态徽章 -->
                  <div
                    class="status-indicator-box flex-shrink-0"
                    :class="`indicator-${group.status === 'error' ? 'error' : 'success'}`"
                  >
                    <v-icon size="16" :color="getItemColor(group.status)">
                      {{ getItemIcon(group.status) }}
                    </v-icon>
                  </div>

                  <!-- 媒体名称与标签 -->
                  <div class="overflow-hidden">
                    <div class="d-flex align-center flex-wrap ga-2">
                      <span class="text-body-2 font-weight-bold text-truncate media-title">
                        {{ group.media_name || '未命名媒体' }}
                      </span>

                      <!-- 媒体类型徽章 -->
                      <v-chip
                        size="x-small"
                        variant="flat"
                        :color="getMediaTypeColor(group.media_type)"
                        class="font-weight-medium px-2 media-chip"
                      >
                        {{ group.media_type || '媒体' }}
                      </v-chip>

                      <!-- 同步动作徽章 -->
                      <v-chip
                        size="x-small"
                        variant="tonal"
                        :color="getSyncTypeColor(group.sync_type)"
                        class="font-weight-medium px-2 sync-type-chip"
                      >
                        <v-icon start size="12">{{ getSyncTypeIcon(group.sync_type) }}</v-icon>
                        {{ getEventDescription(group.sync_type) || group.sync_type }}
                      </v-chip>
                    </div>
                  </div>
                </div>

                <!-- 进度与相对时间 -->
                <div class="d-flex align-center ga-2 flex-shrink-0 ml-auto">
                  <!-- 播放进度时间胶囊 -->
                  <div
                    v-if="group.position_ticks"
                    class="progress-pill d-flex align-center px-2 py-1 rounded-pill"
                  >
                    <v-icon size="12" class="mr-1" color="primary">mdi-progress-clock</v-icon>
                    <span class="text-caption font-weight-bold">{{ formatProgress(group.position_ticks) }}</span>
                  </div>

                  <!-- 发生时间 -->
                  <div class="time-label text-caption text-medium-emphasis">
                    {{ formatTime(group.timestamp || group.created_at) }}
                  </div>
                </div>
              </div>

              <!-- 节点流向展示条 (From 源节点 -> To 目标节点) -->
              <div class="flow-container d-flex align-center flex-wrap ga-2 rounded-lg px-3 py-2 mt-2">
                <!-- 源端 -->
                <div class="flow-node d-flex align-center">
                  <v-icon size="14" color="primary" class="mr-1">mdi-server-network</v-icon>
                  <span class="text-caption text-medium-emphasis mr-1 font-weight-medium">{{ group.source_server || '源服务器' }}</span>
                  <span class="node-user text-caption font-weight-bold">{{ group.source_user }}</span>
                </div>

                <!-- 流向指示箭头 -->
                <div class="flow-arrow d-flex align-center justify-center">
                  <v-icon size="14" color="primary">mdi-arrow-right-thin</v-icon>
                </div>

                <!-- 目标端用户列表 -->
                <div class="flow-targets d-flex align-center flex-wrap ga-1">
                  <div
                    v-for="(target_user, idx) in group.target_users"
                    :key="idx"
                    class="flow-node target-node d-flex align-center"
                  >
                    <v-icon size="14" :color="group.status === 'error' ? 'error' : 'success'" class="mr-1">mdi-account-check-outline</v-icon>
                    <span v-if="group.target_server" class="text-caption text-medium-emphasis mr-1">{{ group.target_server }}:</span>
                    <span class="node-user text-caption font-weight-bold">{{ target_user }}</span>
                  </div>
                </div>
              </div>

              <!-- 描述备注 -->
              <div v-if="group.description" class="desc-box text-caption d-flex align-center rounded-lg pa-2 mt-2">
                <v-icon size="14" class="mr-2 flex-shrink-0" color="info">mdi-information-outline</v-icon>
                <span>{{ group.description }}</span>
              </div>

              <!-- 异常错误报告条 -->
              <div
                v-if="group.error_message"
                class="error-box text-caption d-flex align-start rounded-lg pa-2 mt-2"
              >
                <v-icon size="15" class="mr-2 flex-shrink-0 mt-0.5" color="error">mdi-alert-circle-outline</v-icon>
                <span class="text-break">{{ group.error_message }}</span>
              </div>
            </div>

            <!-- 分页加载更多 -->
            <div v-if="pagination.hasMore" class="text-center mt-3 mb-1">
              <v-btn
                color="primary"
                variant="tonal"
                rounded="lg"
                class="px-6 font-weight-medium load-more-btn"
                @click="loadMoreRecords"
                :loading="pagination.loading"
              >
                <v-icon start size="16">mdi-chevron-double-down</v-icon>
                加载更多历史记录
              </v-btn>
            </div>

            <!-- 分页统计 -->
            <div v-if="pagination.total > 0" class="text-center text-caption text-medium-emphasis pb-2">
              已加载 {{ syncRecords.length }} / 共 {{ pagination.total }} 条记录
            </div>
          </div>

          <!-- 空状态 -->
          <div v-else class="empty-box d-flex flex-column align-center justify-center py-12 px-4 rounded-xl text-center">
            <div class="empty-icon mb-3">
              <v-icon size="32" color="primary">mdi-sync-off</v-icon>
            </div>
            <div class="text-subtitle-2 font-weight-bold text-medium-emphasis">暂无同步流水记录</div>
            <div class="text-caption text-disabled mt-1" style="max-width: 320px;">
              当配置保存生效并在受支持的多端播放、标记时，所有自动同步的历史状态将在此处实时归档。
            </div>
            <v-btn
              color="primary"
              variant="tonal"
              size="small"
              rounded="lg"
              class="mt-4 px-4"
              @click="notifySwitch"
            >
              <v-icon start size="16">mdi-cog-outline</v-icon>
              前往检查同步配置
            </v-btn>
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
/* 容器宽度与配置页对齐：100% 撑满 host 弹窗，不设人为限制 */
.plugin-page {
  width: 100%;
}

/* 主卡片外观 */
.page-main-card {
  background: rgb(var(--v-theme-surface, 255, 255, 255));
  border-color: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.08) !important;
}

/* 优雅渐变顶栏 (对齐 Config 页面风格) */
.header-surface {
  background: linear-gradient(
    135deg,
    rgba(var(--v-theme-primary, 24, 103, 192), 0.08) 0%,
    rgba(var(--v-theme-primary, 24, 103, 192), 0.02) 100%
  );
}

.header-icon-box {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: rgba(var(--v-theme-primary, 24, 103, 192), 0.12);
}

.close-btn {
  transition: transform 0.2s ease, background 0.2s ease;
}
.close-btn:hover {
  transform: rotate(90deg);
  background: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.06);
}

.body-surface {
  background: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.015);
}

/* 骨架屏卡片 */
.skeleton-card {
  background: rgb(var(--v-theme-surface, 255, 255, 255));
  border: 1px solid rgba(var(--v-theme-on-surface, 0, 0, 0), 0.06);
}

/* 同步流水卡片 (优雅扁平流式) */
.record-stream-card {
  background: rgb(var(--v-theme-surface, 255, 255, 255));
  border: 1px solid rgba(var(--v-theme-on-surface, 0, 0, 0), 0.07);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
  transition: all 0.2s ease;
}

.record-stream-card:hover {
  border-color: rgba(var(--v-theme-primary, 24, 103, 192), 0.3);
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.05);
  transform: translateY(-1px);
}

.stream-card-success {
  border-left: 3px solid rgb(var(--v-theme-success, 76, 175, 80));
}

.stream-card-error {
  border-left: 3px solid rgb(var(--v-theme-error, 176, 0, 32));
}

/* 状态指示框 */
.status-indicator-box {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
}
.indicator-success {
  background: rgba(var(--v-theme-success, 76, 175, 80), 0.12);
}
.indicator-error {
  background: rgba(var(--v-theme-error, 176, 0, 32), 0.12);
}

/* 媒体名称 */
.media-title {
  color: rgb(var(--v-theme-on-surface, 0, 0, 0));
  max-width: 480px;
}
@media (min-width: 960px) {
  .media-title {
    max-width: 620px;
  }
}
@media (min-width: 1280px) {
  .media-title {
    max-width: 760px;
  }
}

/* 标签圆角 */
.media-chip, .sync-type-chip {
  border-radius: 6px;
}

/* 播放进度微胶囊 */
.progress-pill {
  background: rgba(var(--v-theme-primary, 24, 103, 192), 0.08);
  border: 1px solid rgba(var(--v-theme-primary, 24, 103, 192), 0.18);
  color: rgb(var(--v-theme-primary, 24, 103, 192));
}

/* 节点流向容器 (对齐配置页用户映射节点风格) */
.flow-container {
  background: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.025);
  border: 1px solid rgba(var(--v-theme-on-surface, 0, 0, 0), 0.05);
}

.flow-node {
  padding: 2px 6px;
  border-radius: 6px;
  background: rgba(var(--v-theme-surface, 255, 255, 255), 0.7);
  border: 1px solid rgba(var(--v-theme-on-surface, 0, 0, 0), 0.06);
}

.target-node {
  background: rgba(var(--v-theme-primary, 24, 103, 192), 0.04);
}

.node-user {
  color: rgb(var(--v-theme-on-surface, 0, 0, 0));
}

.flow-arrow {
  width: 20px;
}

/* 描述与错误消息条 */
.desc-box {
  background: rgba(var(--v-theme-info, 33, 150, 243), 0.06);
  border: 1px solid rgba(var(--v-theme-info, 33, 150, 243), 0.18);
  color: rgb(var(--v-theme-info, 33, 150, 243));
}

.error-box {
  background: rgba(var(--v-theme-error, 176, 0, 32), 0.06);
  border: 1px solid rgba(var(--v-theme-error, 176, 0, 32), 0.18);
  color: rgb(var(--v-theme-error, 176, 0, 32));
}

/* 加载更多 */
.load-more-btn {
  border: 1px solid rgba(var(--v-theme-primary, 24, 103, 192), 0.2);
}

/* 空状态 */
.empty-box {
  background: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.02);
  border: 1px dashed rgba(var(--v-theme-on-surface, 0, 0, 0), 0.16);
}
.empty-icon {
  width: 60px;
  height: 60px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(var(--v-theme-primary, 24, 103, 192), 0.1);
}

.shadow-elevation {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
}
</style>
