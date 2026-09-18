<template>
  <div class="dashboard-widget h-100">
    <v-card
      :flat="!config?.attrs?.border"
      :variant="config?.attrs?.border ? 'outlined' : 'flat'"
      class="rounded-xl h-100 overflow-hidden dashboard-card"
      :class="config?.attrs?.border ? 'border-opacity-25' : ''"
    >
      <!-- 卡片头：渐变图标 + 标题 + 实时状态脉冲点 -->
      <v-card-item v-if="config?.attrs?.border" class="px-4 py-3 border-b header-surface">
        <template #prepend>
          <div class="header-icon-box mr-3">
            <v-icon color="primary" size="20">mdi-chart-timeline-variant-shimmer</v-icon>
          </div>
        </template>
        <v-card-title class="text-subtitle-1 font-weight-bold d-flex align-center">
          {{ config?.attrs?.title || '观看状态仪表盘' }}
          <span class="status-dot ml-2" :class="`dot-${serviceStatus}`"></span>
        </v-card-title>
        <template #append>
          <v-btn
            icon
            variant="tonal"
            color="primary"
            size="small"
            rounded="lg"
            @click="refreshData"
            :loading="loading"
          >
            <v-icon size="18">mdi-refresh</v-icon>
            <v-tooltip activator="parent" location="bottom">刷新数据</v-tooltip>
          </v-btn>
        </template>
      </v-card-item>

      <!-- 主要内容区域 -->
      <v-card-text :class="config?.attrs?.border ? 'pa-4' : 'pa-0'" style="height: 100%;">
        <div class="dashboard-content d-flex flex-column h-100">

          <!-- 加载中状态 -->
          <div v-if="loading" class="d-flex flex-column justify-center align-center flex-grow-1 py-11">
            <v-progress-circular indeterminate color="primary" :size="40" :width="3.5" class="mb-3"></v-progress-circular>
            <span class="text-caption text-medium-emphasis">正在汇总同步数据…</span>
          </div>

          <!-- 数据内容 -->
          <div v-else class="flex-grow-1 d-flex flex-column">

            <!-- 服务状态条 -->
            <div class="status-strip d-flex align-center px-3 py-2 mb-3 rounded-lg" :class="`strip-${serviceStatusColor}`">
              <v-icon :color="serviceStatusColor" size="18" class="mr-2">{{ serviceStatusIcon }}</v-icon>
              <span class="text-caption font-weight-bold" :class="`text-${serviceStatusColor}-darken-2`">
                {{ serviceStatusText }}
              </span>
              <v-spacer></v-spacer>
              <div class="rate-pill d-flex align-center px-2 py-1 rounded-pill" :class="rateTone">
                <v-icon size="12" class="mr-1">mdi-shield-check-outline</v-icon>
                <span class="text-caption font-weight-black">{{ stats.successRate }}%</span>
              </div>
            </div>

            <!-- 核心指标卡 -->
            <v-row class="mb-3 mx-0 align-stretch">
              <v-col cols="4" class="pa-1">
                <div class="stat-card stat-primary rounded-lg text-center py-3 px-1 h-100">
                  <div class="text-h5 font-weight-black text-primary stat-value">{{ stats.todayCount }}</div>
                  <div class="text-caption text-medium-emphasis font-weight-medium mt-1">今日指令</div>
                </div>
              </v-col>
              <v-col cols="4" class="pa-1">
                <div class="stat-card stat-info rounded-lg text-center py-3 px-1 h-100">
                  <div class="text-h5 font-weight-black text-info stat-value">{{ stats.activeUsers }}</div>
                  <div class="text-caption text-medium-emphasis font-weight-medium mt-1">24H 用户</div>
                </div>
              </v-col>
              <v-col cols="4" class="pa-1">
                <div class="stat-card stat-secondary rounded-lg text-center py-3 px-1 h-100">
                  <div class="text-h5 font-weight-black text-secondary stat-value">{{ stats.syncTypes.length }}</div>
                  <div class="text-caption text-medium-emphasis font-weight-medium mt-1">涉及类型</div>
                </div>
              </v-col>
            </v-row>

            <!-- 最近动向标题 -->
            <div class="d-flex align-center justify-space-between mb-2 px-1">
              <span class="text-caption font-weight-bold text-medium-emphasis d-flex align-center">
                <v-icon size="14" class="mr-1 text-primary">mdi-history</v-icon>
                最近动向
              </span>
              <span v-if="recentRecords.length" class="text-caption text-disabled">最新 {{ recentRecords.length }} 条</span>
            </div>

            <!-- 最近同步记录 -->
            <div v-if="recentRecords.length" class="flex-grow-1">
              <div
                v-for="(record, index) in recentRecords"
                :key="index"
                class="record-item d-flex align-center py-2 px-3 mb-2 rounded-lg"
              >
                <!-- 状态图标 -->
                <div class="record-badge mr-3" :class="`badge-${getStatusColor(record.status)}`">
                  <v-icon size="16" :color="getStatusColor(record.status)">
                    {{ getStatusIcon(record.status) }}
                  </v-icon>
                </div>

                <!-- 媒体与流向 -->
                <div class="flex-grow-1 overflow-hidden mr-2">
                  <div class="record-title text-caption font-weight-bold text-truncate">
                    {{ record.media_name || '未命名媒体' }}
                  </div>
                  <div class="text-caption text-disabled d-flex align-center text-truncate mt-1">
                    <v-icon size="12" :color="getSyncTypeColor(record.sync_type)" class="mr-1 flex-shrink-0">
                      {{ getSyncTypeIcon(record.sync_type) }}
                    </v-icon>
                    <span class="text-truncate">{{ record.source_user }}</span>
                    <v-icon size="10" class="mx-1 flex-shrink-0 text-grey">mdi-arrow-right</v-icon>
                    <span class="text-truncate">{{ record.target_user }}</span>
                  </div>
                </div>

                <!-- 时间 -->
                <div class="text-right flex-shrink-0">
                  <span class="text-caption text-disabled text-no-wrap">{{ formatTime(record.timestamp || record.created_at) }}</span>
                </div>
              </div>
            </div>

            <!-- 空状态 -->
            <div v-else class="empty-box d-flex flex-column align-center justify-center flex-grow-1 py-7 px-4 rounded-lg text-center">
              <div class="empty-icon mb-2">
                <v-icon size="26" color="primary">mdi-sync-off</v-icon>
              </div>
              <div class="text-caption font-weight-bold text-medium-emphasis">这里还是一片荒芜</div>
              <div class="text-caption text-disabled mt-1">暂无有效同步记录</div>
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
const recentRecords = ref([])
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

// 成功率徽章配色
const rateTone = computed(() => {
  if (stats.value.successRate >= 90) return 'rate-success'
  if (stats.value.successRate >= 70) return 'rate-warning'
  return 'rate-error'
})

// 格式化时间
function formatTime(timestamp) {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  if (isNaN(date.getTime())) return ''
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
      recentRecords.value = result.data || []
    } else {
      recentRecords.value = []
    }
  } catch (error) {
    console.error('获取同步记录失败:', error)
    recentRecords.value = []
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
/* 卡片整体 */
.dashboard-card {
  background: rgb(var(--v-theme-surface, 255, 255, 255));
  transition: box-shadow 0.25s ease;
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

/* 状态脉冲点 */
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}
.dot-running {
  background-color: rgb(var(--v-theme-success, 76, 175, 80));
  animation: pulse-success 2s infinite;
}
.dot-stopped {
  background-color: rgb(var(--v-theme-warning, 251, 140, 0));
}
.dot-error {
  background-color: rgb(var(--v-theme-error, 176, 0, 32));
  animation: pulse-error 1.4s infinite;
}

@keyframes pulse-success {
  0%   { box-shadow: 0 0 0 0 rgba(var(--v-theme-success, 76, 175, 80), 0.6); }
  70%  { box-shadow: 0 0 0 6px rgba(var(--v-theme-success, 76, 175, 80), 0); }
  100% { box-shadow: 0 0 0 0 rgba(var(--v-theme-success, 76, 175, 80), 0); }
}
@keyframes pulse-error {
  0%   { box-shadow: 0 0 0 0 rgba(var(--v-theme-error, 176, 0, 32), 0.6); }
  70%  { box-shadow: 0 0 0 6px rgba(var(--v-theme-error, 176, 0, 32), 0); }
  100% { box-shadow: 0 0 0 0 rgba(var(--v-theme-error, 176, 0, 32), 0); }
}

/* 服务状态条 */
.status-strip {
  border: 1px solid transparent;
}
.strip-success {
  background: rgba(var(--v-theme-success, 76, 175, 80), 0.08);
  border-color: rgba(var(--v-theme-success, 76, 175, 80), 0.22);
}
.strip-warning {
  background: rgba(var(--v-theme-warning, 251, 140, 0), 0.08);
  border-color: rgba(var(--v-theme-warning, 251, 140, 0), 0.22);
}
.strip-error {
  background: rgba(var(--v-theme-error, 176, 0, 32), 0.08);
  border-color: rgba(var(--v-theme-error, 176, 0, 32), 0.22);
}
.strip-grey {
  background: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.05);
  border-color: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.12);
}

/* 成功率胶囊 */
.rate-pill {
  background: rgba(var(--v-theme-surface, 255, 255, 255), 0.85);
  border: 1px solid rgba(var(--v-theme-on-surface, 0, 0, 0), 0.08);
}
.rate-success { color: rgb(var(--v-theme-success, 76, 175, 80)); }
.rate-warning { color: rgb(var(--v-theme-warning, 251, 140, 0)); }
.rate-error   { color: rgb(var(--v-theme-error, 176, 0, 32)); }

/* 指标卡 */
.stat-card {
  border: 1px solid rgba(var(--v-theme-on-surface, 0, 0, 0), 0.07);
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}
.stat-card:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
}
.stat-primary {
  background: linear-gradient(180deg, rgba(var(--v-theme-primary, 24, 103, 192), 0.09) 0%, rgba(var(--v-theme-primary, 24, 103, 192), 0.02) 100%);
}
.stat-info {
  background: linear-gradient(180deg, rgba(var(--v-theme-info, 33, 150, 243), 0.09) 0%, rgba(var(--v-theme-info, 33, 150, 243), 0.02) 100%);
}
.stat-secondary {
  background: linear-gradient(180deg, rgba(var(--v-theme-secondary, 92, 187, 246), 0.09) 0%, rgba(var(--v-theme-secondary, 92, 187, 246), 0.02) 100%);
}
.stat-value {
  line-height: 1.15;
}

/* 记录条目 */
.record-item {
  background: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.025);
  border: 1px solid rgba(var(--v-theme-on-surface, 0, 0, 0), 0.07);
  transition: background 0.18s ease, border-color 0.18s ease;
}
.record-item:hover {
  background: rgba(var(--v-theme-primary, 24, 103, 192), 0.05);
  border-color: rgba(var(--v-theme-primary, 24, 103, 192), 0.22);
}

.record-badge {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.badge-success { background: rgba(var(--v-theme-success, 76, 175, 80), 0.12); }
.badge-error   { background: rgba(var(--v-theme-error, 176, 0, 32), 0.12); }
.badge-warning { background: rgba(var(--v-theme-warning, 251, 140, 0), 0.14); }
.badge-grey    { background: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.08); }

.record-title {
  color: rgb(var(--v-theme-on-surface, 0, 0, 0));
}

/* 空状态 */
.empty-box {
  background: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.02);
  border: 1px dashed rgba(var(--v-theme-on-surface, 0, 0, 0), 0.18);
}
.empty-icon {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(var(--v-theme-primary, 24, 103, 192), 0.1);
}
</style>
