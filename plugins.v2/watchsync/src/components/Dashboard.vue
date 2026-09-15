<template>
  <div class="dashboard-widget">
    <v-card v-if="!config?.attrs?.border" flat>
      <v-card-text class="pa-0">
        <div class="dashboard-content">
          <!-- 加载中状态 -->
          <div v-if="loading" class="d-flex justify-center align-center py-4">
            <v-progress-circular indeterminate color="primary"></v-progress-circular>
          </div>

          <!-- 数据内容 -->
          <div v-else>
            <!-- 服务状态指示器 -->
            <div class="d-flex align-center mb-2">
              <v-icon :color="serviceStatusColor" size="small" class="mr-2">
                {{ serviceStatusIcon }}
              </v-icon>
              <span class="text-body-2 font-weight-medium">{{ serviceStatusText }}</span>
              <v-spacer></v-spacer>
              <v-chip :color="stats.successRate >= 90 ? 'success' : stats.successRate >= 70 ? 'warning' : 'error'"
                      size="x-small" variant="flat">
                {{ stats.successRate }}%
              </v-chip>
            </div>

            <!-- 核心指标 -->
            <div class="d-flex justify-space-between align-center mb-3">
              <div class="text-center">
                <div class="text-h6 font-weight-bold text-primary">{{ stats.todayCount }}</div>
                <div class="text-caption">今日同步</div>
              </div>
              <div class="text-center">
                <div class="text-h6 font-weight-bold text-info">{{ stats.activeUsers }}</div>
                <div class="text-caption">活跃用户</div>
              </div>
              <div class="text-center">
                <div class="text-h6 font-weight-bold text-secondary">{{ stats.syncTypes.length }}</div>
                <div class="text-caption">同步类型</div>
              </div>
            </div>

            <!-- 最近同步记录（简化版） -->
            <v-list v-if="syncRecords.length" density="compact" class="py-0">
              <v-list-item v-for="(record, index) in syncRecords.slice(0, 3)" :key="index">
                <template v-slot:prepend>
                  <div class="d-flex align-center">
                    <v-icon :color="getSyncTypeColor(record.sync_type)" size="x-small" class="mr-1">
                      {{ getSyncTypeIcon(record.sync_type) }}
                    </v-icon>
                    <v-avatar :color="getStatusColor(record.status)" size="x-small">
                      <v-icon size="x-small" color="white">{{ getStatusIcon(record.status) }}</v-icon>
                    </v-avatar>
                  </div>
                </template>
                <v-list-item-title class="text-body-2">{{ record.media_name }}</v-list-item-title>
                <v-list-item-subtitle class="text-caption">
                  {{ record.source_user }} → {{ record.target_user }}
                </v-list-item-subtitle>
                <template v-slot:append>
                  <span class="text-caption">{{ formatTime(record.timestamp) }}</span>
                </template>
              </v-list-item>
            </v-list>

            <!-- 无数据提示 -->
            <div v-else class="text-center text-caption text-medium-emphasis py-2">
              暂无同步记录
            </div>
          </div>
        </div>
      </v-card-text>
    </v-card>

    <!-- 带边框的卡片 -->
    <v-card v-else>
      <v-card-item>
        <v-card-title class="text-subtitle-1">{{ config?.attrs?.title || '观看记录同步' }}</v-card-title>
        <template v-slot:append>
          <v-btn icon size="x-small" variant="text" @click="refreshData">
            <v-icon size="small">mdi-refresh</v-icon>
          </v-btn>
        </template>
      </v-card-item>

      <v-card-text class="pt-2">
        <!-- 加载中状态 -->
        <div v-if="loading" class="d-flex justify-center align-center py-2">
          <v-progress-circular indeterminate color="primary" size="small"></v-progress-circular>
        </div>

        <!-- 数据内容 -->
        <div v-else>
          <!-- 服务状态指示器 -->
          <div class="d-flex align-center mb-2">
            <v-icon :color="serviceStatusColor" size="small" class="mr-2">
              {{ serviceStatusIcon }}
            </v-icon>
            <span class="text-body-2 font-weight-medium">{{ serviceStatusText }}</span>
            <v-spacer></v-spacer>
            <v-chip :color="stats.successRate >= 90 ? 'success' : stats.successRate >= 70 ? 'warning' : 'error'"
                    size="x-small" variant="flat">
              {{ stats.successRate }}%
            </v-chip>
          </div>

          <!-- 核心指标 -->
          <div class="d-flex justify-space-between align-center mb-3">
            <div class="text-center">
              <div class="text-h6 font-weight-bold text-primary">{{ stats.todayCount }}</div>
              <div class="text-caption">今日同步</div>
            </div>
            <div class="text-center">
              <div class="text-h6 font-weight-bold text-info">{{ stats.activeUsers }}</div>
              <div class="text-caption">活跃用户</div>
            </div>
            <div class="text-center">
              <div class="text-h6 font-weight-bold text-secondary">{{ stats.syncTypes.length }}</div>
              <div class="text-caption">同步类型</div>
            </div>
          </div>

          <!-- 最近同步记录（简化版） -->
          <v-list v-if="syncRecords.length" density="compact" class="py-0">
            <v-list-item v-for="(record, index) in syncRecords.slice(0, 3)" :key="index">
              <template v-slot:prepend>
                <div class="d-flex align-center">
                  <v-icon :color="getSyncTypeColor(record.sync_type)" size="x-small" class="mr-1">
                    {{ getSyncTypeIcon(record.sync_type) }}
                  </v-icon>
                  <v-avatar :color="getStatusColor(record.status)" size="x-small">
                    <v-icon size="x-small" color="white">{{ getStatusIcon(record.status) }}</v-icon>
                  </v-avatar>
                </div>
              </template>
              <v-list-item-title class="text-body-2">{{ record.media_name }}</v-list-item-title>
              <v-list-item-subtitle class="text-caption">
                {{ record.source_user }} → {{ record.target_user }}
              </v-list-item-subtitle>
              <template v-slot:append>
                <span class="text-caption">{{ formatTime(record.timestamp) }}</span>
              </template>
            </v-list-item>
          </v-list>

          <!-- 无数据提示 -->
          <div v-else class="text-center text-caption text-medium-emphasis py-2">
            暂无同步记录
          </div>
        </div>
      </v-card-text>
    </v-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'

// 接收仪表板配置
const props = defineProps({
  config: {
    type: Object,
    default: () => ({}),
  },
  allowRefresh: {
    type: Boolean,
    default: true,
  },
  api: {
    type: Object,
    required: true,
  },
})

// 组件状态
const loading = ref(true)
const stats = ref({
  todayCount: 0,
  successRate: 0,
  activeUsers: 0,
  syncTypes: []
})
const syncRecords = ref([])
const serviceStatus = ref('running') // running, stopped, error
let refreshTimer = null

// 获取状态图标
function getStatusIcon(status) {
  const icons = {
    'success': 'mdi-check',
    'error': 'mdi-alert',
    'pending': 'mdi-clock-outline',
  }
  return icons[status] || 'mdi-help-circle'
}

// 获取状态颜色
function getStatusColor(status) {
  const colors = {
    'success': 'success',
    'error': 'error',
    'pending': 'warning',
  }
  return colors[status] || 'grey'
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

// 服务状态相关的计算属性
const serviceStatusIcon = computed(() => {
  const icons = {
    'running': 'mdi-check-circle',
    'stopped': 'mdi-stop-circle',
    'error': 'mdi-alert-circle'
  }
  return icons[serviceStatus.value] || 'mdi-help-circle'
})

const serviceStatusColor = computed(() => {
  const colors = {
    'running': 'success',
    'stopped': 'warning',
    'error': 'error'
  }
  return colors[serviceStatus.value] || 'grey'
})

const serviceStatusText = computed(() => {
  const texts = {
    'running': '同步服务运行中',
    'stopped': '同步服务已停止',
    'error': '同步服务异常'
  }
  return texts[serviceStatus.value] || '状态未知'
})

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

// 获取仪表板数据
async function fetchDashboardData() {
  if (!props.allowRefresh) return

  loading.value = true

  try {
    // 获取统计数据
    await loadDashboardStats()

    // 获取最近同步记录
    await loadDashboardRecords()

  } catch (error) {
    console.error('获取仪表板数据失败:', error)
  } finally {
    loading.value = false
  }
}

// 加载仪表板统计数据
async function loadDashboardStats() {
  try {
    const result = await props.api.get('plugin/WatchSync/stats')
    if (result && result.success) {
      const data = result.data
      stats.value = {
        todayCount: data['今日同步次数'] || 0,
        successRate: parseFloat(data['成功率']) || 0,
        activeUsers: data['活跃用户数'] || 0,
        syncTypes: data['同步类型'] || []
      }

      // 根据成功率判断服务状态
      if (stats.value.successRate >= 90) {
        serviceStatus.value = 'running'
      } else if (stats.value.successRate >= 50) {
        serviceStatus.value = 'stopped'
      } else {
        serviceStatus.value = 'error'
      }
    } else {
      // 设置默认值
      stats.value = {
        todayCount: 0,
        successRate: 0,
        activeUsers: 0,
        syncTypes: []
      }
      serviceStatus.value = 'stopped'
    }
  } catch (error) {
    console.error('获取统计数据失败:', error)
    // 设置默认值
    stats.value = {
      todayCount: 0,
      successRate: 0,
      activeUsers: 0,
      syncTypes: []
    }
    serviceStatus.value = 'error'
  }
}

// 加载仪表板同步记录
async function loadDashboardRecords() {
  try {
    const result = await props.api.get('plugin/WatchSync/records?limit=3')
    if (result && result.success) {
      syncRecords.value = result.data || []
    } else {
      syncRecords.value = []
    }
  } catch (error) {
    console.error('获取同步记录失败:', error)
    syncRecords.value = []
  }
}

// 手动刷新数据
async function refreshData() {
  await fetchDashboardData()
}

// 设置定时刷新
function setupRefreshTimer() {
  if (props.allowRefresh) {
    // 每30秒刷新一次
    refreshTimer = setInterval(() => {
      fetchDashboardData()
    }, 30000)
  }
}

// 初始化
onMounted(() => {
  fetchDashboardData()
  setupRefreshTimer()
})

// 清理
onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
  }
})
</script>