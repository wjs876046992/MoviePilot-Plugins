<template>
  <div class="plugin-page">
    <v-card>
      <v-card-item>
        <v-card-title>{{ title }}</v-card-title>
        <template #append>
          <div class="d-flex align-center gap-2">
            <v-btn color="primary" @click="refreshData" :loading="loading" text="刷新" variant="tonal">
              <template v-slot:prepend>
                <v-icon>mdi-refresh</v-icon>
              </template>
            </v-btn>

            <v-menu>
              <template v-slot:activator="{ props }">
                <v-btn v-bind="props" color="secondary" :loading="clearing" text="清理" variant="outlined">
                  <template v-slot:prepend>
                    <v-icon>mdi-delete-sweep</v-icon>
                  </template>
                </v-btn>
              </template>
              <v-list>
                <v-list-item @click="clearOldRecords(7)">
                  <v-list-item-title>清理7天前</v-list-item-title>
                </v-list-item>
                <v-list-item @click="clearOldRecords(30)">
                  <v-list-item-title>清理30天前</v-list-item-title>
                </v-list-item>
                <v-list-item @click="clearOldRecords(90)">
                  <v-list-item-title>清理90天前</v-list-item-title>
                </v-list-item>
              </v-list>
            </v-menu>

            <v-btn color="info" @click="exportLogs" text="导出" variant="outlined">
              <template v-slot:prepend>
                <v-icon>mdi-download</v-icon>
              </template>
            </v-btn>
            <v-btn color="primary" @click="notifySwitch" text="配置" variant="outlined">
              <template v-slot:prepend>
                <v-icon>mdi-cog</v-icon>
              </template>
            </v-btn>

            <v-btn icon color="primary" variant="text" @click="notifyClose">
              <v-icon>mdi-close</v-icon>
            </v-btn>
          </div>
        </template>
      </v-card-item>
      <v-card-text style="max-height: 75vh; overflow-y: auto;">
        <v-alert v-if="error" type="error" class="mb-4">{{ error }}</v-alert>
        <v-skeleton-loader v-if="loading" type="card"></v-skeleton-loader>
        <div v-else>
          <!-- 最近同步记录 -->
          <div v-if="groupedSyncRecords && groupedSyncRecords.length" class="mt-4">
            <v-timeline density="compact">
              <v-timeline-item
                v-for="(group, index) in groupedSyncRecords"
                :key="index"
                size="small"
              >
                <template #icon>
                  <v-avatar size="24" :color="getItemColor(group.status)">
                    <v-icon size="16" color="white">{{ getItemIcon(group.status) }}</v-icon>
                  </v-avatar>
                </template>
                <div class="d-flex align-center">
                  <v-icon :color="getMediaTypeColor(group.media_type)" size="small" class="mr-2">
                    {{ getMediaTypeIcon(group.media_type) }}
                  </v-icon>
                  <v-icon :color="getSyncTypeColor(group.sync_type)" size="small" class="mr-2">
                    {{ getSyncTypeIcon(group.sync_type) }}
                  </v-icon>
                  <span class="font-weight-medium">{{ group.media_name }}</span>
                </div>
                <div class="text-caption text-secondary">
                  <div>{{ group.source_user }} → {{ group.target_users.join(', ') }}</div>
                  <div v-if="group.description">{{ group.description }}</div>
                  <div v-if="group.error_message" class="text-error">错误: {{ group.error_message }}</div>
                  <div>{{ formatTime(group.timestamp) }}</div>
                </div>
              </v-timeline-item>
            </v-timeline>

            <!-- 加载更多按钮 -->
            <div v-if="pagination.hasMore" class="text-center mt-4">
              <v-btn
                color="primary"
                variant="outlined"
                @click="loadMoreRecords"
                :loading="pagination.loading"
              >
                <v-icon left>mdi-chevron-down</v-icon>
                加载更多历史记录
              </v-btn>
            </div>

            <!-- 分页信息 -->
            <div v-if="pagination.total > 0" class="text-center mt-2 text-caption text-secondary">
              已显示 {{ syncRecords.length }} / {{ pagination.total }} 条记录
            </div>
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