<template>
  <div class="dashboard-widget h-100">
    <v-card :flat="!config?.attrs?.border" :variant="config?.attrs?.border ? 'outlined' : 'flat'" class="rounded-lg h-100 border-opacity-50">
      
      <!-- 卡片头 -->
      <v-card-item v-if="config?.attrs?.border" class="border-b bg-grey-lighten-4 pa-3">
        <template v-slot:prepend>
          <v-icon color="primary" class="mr-2">mdi-chart-timeline-variant-shimmer</v-icon>
        </template>
        <v-card-title class="text-subtitle-1 font-weight-bold text-primary">{{ config?.attrs?.title || '观看状态仪表盘' }}</v-card-title>
        <template v-slot:append>
          <v-btn icon variant="tonal" color="primary" size="x-small" class="bg-white elevation-1" @click="refreshData" :loading="loading">
            <v-icon size="small">mdi-refresh</v-icon>
          </v-btn>
        </template>
      </v-card-item>

      <!-- 主要内容区域 -->
      <v-card-text :class="config?.attrs?.border ? 'pa-4 pb-2' : 'pa-0'" style="height: 100%;">
        <div class="dashboard-content d-flex flex-column h-100">
          
          <!-- 加载中状态 -->
          <div v-if="loading" class="d-flex justify-center align-center flex-grow-1 py-10">
            <v-progress-circular indeterminate color="primary" :size="36" :width="3"></v-progress-circular>
          </div>

          <!-- 数据内容 -->
          <div v-else class="flex-grow-1">
            
            <!-- 服务状态指示器 -->
            <div class="d-flex align-center px-4 py-2 mb-4 rounded-lg bg-surface-variant text-on-surface-variant shadow-sm border border-opacity-25" :class="`bg-${serviceStatusColor}-lighten-5 border-${serviceStatusColor}`">
              <v-icon :color="serviceStatusColor" size="small" class="mr-2">{{ serviceStatusIcon }}</v-icon>
              <span class="text-body-2 font-weight-bold" :class="`text-${serviceStatusColor}-darken-2`">{{ serviceStatusText }}</span>
              <v-spacer></v-spacer>
              <div class="d-flex align-center bg-white px-2 py-1 rounded-pill elevation-1" :class="`text-${stats.successRate >= 90 ? 'success' : stats.successRate >= 70 ? 'warning' : 'error'}`">
                <v-icon start size="x-small" class="mr-1">mdi-brightness-percent</v-icon>
                <span class="text-caption font-weight-bold">{{ stats.successRate }}% 成功率</span>
              </div>
            </div>

            <!-- 数据列 (Grid UI) -->
            <v-row class="mb-4 mt-2 mx-0 align-stretch">
              <v-col cols="4" class="text-center bg-grey-lighten-5 rounded-s-lg py-3">
                <div class="text-h5 font-weight-black text-primary">{{ stats.todayCount }}</div>
                <div class="text-caption font-weight-medium text-medium-emphasis mt-1">今日同步指令</div>
              </v-col>
              <v-col cols="4" class="text-center border-s border-e bg-blue-grey-lighten-5 py-3">
                <div class="text-h5 font-weight-black text-info">{{ stats.activeUsers }}</div>
                <div class="text-caption font-weight-medium text-medium-emphasis mt-1">24H 涉及用户</div>
              </v-col>
              <v-col cols="4" class="text-center bg-grey-lighten-5 rounded-e-lg py-3">
                <div class="text-h5 font-weight-black text-secondary">{{ stats.syncTypes.length }}</div>
                <div class="text-caption font-weight-medium text-medium-emphasis mt-1">同步涉及类型</div>
              </v-col>
            </v-row>

            <div class="text-subtitle-2 text-grey-darken-1 mb-2 d-flex align-center">
              <v-icon size="small" class="mr-1">mdi-history</v-icon>近期最新动向
            </div>

            <!-- 最近同步记录（简化卡片版） -->
            <v-list v-if="syncRecords.length" density="compact" class="py-0 rounded-lg border border-opacity-50">
              <v-list-item 
                v-for="(record, index) in syncRecords.slice(0, 3)" 
                :key="index" 
                :class="{'border-b': index < syncRecords.slice(0, 3).length - 1}"
                class="px-3"
              >
                <template v-slot:prepend>
                  <v-avatar :color="getStatusColor(record.status)" size="28" class="mr-3 mt-1 elevation-1">
                    <v-icon size="16" color="white">{{ getStatusIcon(record.status) }}</v-icon>
                  </v-avatar>
                </template>
                
                <v-list-item-title class="text-body-2 font-weight-bold text-primary-darken-1 pt-1 text-truncate">
                  {{ record.media_name || '未命名媒体' }}
                </v-list-item-title>
                
                <v-list-item-subtitle class="text-caption d-flex align-center mt-1 pb-1">
                  <v-icon size="x-small" :color="getSyncTypeColor(record.sync_type)" class="mr-1">
                    {{ getSyncTypeIcon(record.sync_type) }}
                  </v-icon>
                  <span class="text-truncate" style="max-width: 60%;">
                    <span class="font-weight-medium">{{ record.source_user }}</span> 
                    <v-icon size="x-small" class="mx-1 text-grey">mdi-arrow-right</v-icon> 
                    <span class="font-weight-medium">{{ record.target_user }}</span>
                  </span>
                </v-list-item-subtitle>
                
                <template v-slot:append>
                  <span class="text-caption text-medium-emphasis ml-2 bg-grey-lighten-4 px-2 py-1 rounded">
                    {{ formatTime(record.timestamp) }}
                  </span>
                </template>
              </v-list-item>
            </v-list>

            <!-- 无数据空状态呈现 -->
            <div v-else class="text-center text-caption text-blue-grey-darken-1 py-8 rounded-lg border-dashed bg-grey-lighten-5">
              <v-icon size="48" color="blue-grey-lighten-3" class="d-block mx-auto mb-2">mdi-cube-scan</v-icon>
              这里还是一片荒芜...<br/>暂无有效同步记录
            </div>
            
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
    'running': '核心服务正常运作中',
    'stopped': '服务状态已中断/停止',
    'error': '同步服务异常告警中'
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
    // 简短日期
    const m = (date.getMonth() + 1).toString().padStart(2, '0')
    const d = date.getDate().toString().padStart(2, '0')
    const t = date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})
    return `${m}-${d} ${t}`
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

<style scoped>
.shadow-sm {
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}
.border-dashed {
  border-style: dashed !important;
}
.text-truncate {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
