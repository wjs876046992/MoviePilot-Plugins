<template>
  <div class="plugin-page">
    <v-card class="d-flex flex-column h-100 rounded-xl overflow-hidden page-main-card" elevation="0" variant="outlined">

      <!-- 优雅顶栏 -->
      <v-card-item class="header-surface px-5 py-3 border-b">
        <template #prepend>
          <div class="header-icon-box mr-3">
            <v-icon color="primary" size="22">mdi-cloud-sync</v-icon>
          </div>
        </template>
        <div>
          <v-card-title class="text-subtitle-1 font-weight-bold pa-0 d-flex align-center flex-wrap ga-2">
            <span>115 网盘同步监控</span>
            <v-chip
              size="x-small"
              variant="tonal"
              :color="statusData.is_running ? 'warning' : (statusData.last_status?.success ? 'success' : 'error')"
              class="font-weight-bold"
            >
              {{ statusData.is_running ? '正在同步 ⏳' : (statusData.last_status?.success ? '空闲中 ✅' : '有异常待重试 ⚠️') }}
            </v-chip>
          </v-card-title>
          <div class="text-caption text-medium-emphasis">监控入库延迟冷却进度、双向对账异常与一键快速定向重试</div>
        </div>
        <template #append>
          <div class="d-flex align-center ga-1">
            <v-btn icon variant="tonal" color="primary" size="small" class="rounded-lg mr-1" @click="fetchStatus" :loading="loading">
              <v-icon size="18">mdi-refresh</v-icon>
              <v-tooltip activator="parent" location="bottom">刷新状态</v-tooltip>
            </v-btn>
            <v-btn color="primary" rounded="lg" variant="outlined" size="small" class="px-3 font-weight-medium mr-1" @click="notifySwitch">
              <v-icon start size="16">mdi-cog-outline</v-icon>
              配置
            </v-btn>
            <v-btn icon variant="text" size="small" class="rounded-lg close-btn text-medium-emphasis" @click="notifyClose">
              <v-icon size="18">mdi-close</v-icon>
              <v-tooltip activator="parent" location="bottom">关闭</v-tooltip>
            </v-btn>
          </div>
        </template>
      </v-card-item>

      <!-- 主体内容 -->
      <v-card-text class="pa-4 flex-grow-1 overflow-y-auto body-surface">
        <!-- 核心指标卡片 -->
        <v-row class="mb-3 mx-0">
          <v-col cols="12" sm="4" class="pa-1">
            <div class="stat-card stat-info rounded-xl pa-3 text-center">
              <div class="text-h5 font-weight-black text-info">{{ statusData.cooling_count || 0 }}</div>
              <div class="text-caption text-medium-emphasis mt-1">冷却缓冲中 (设定 {{ statusData.delay_hours || 2 }}h)</div>
            </div>
          </v-col>
          <v-col cols="12" sm="4" class="pa-1">
            <div class="stat-card stat-primary rounded-xl pa-3 text-center">
              <div class="text-h5 font-weight-black text-primary">{{ statusData.ready_count || 0 }}</div>
              <div class="text-caption text-medium-emphasis mt-1">冷却就绪待传输</div>
            </div>
          </v-col>
          <v-col cols="12" sm="4" class="pa-1">
            <div class="stat-card stat-error rounded-xl pa-3 text-center">
              <div class="text-h5 font-weight-black text-error">
                {{ (statusData.last_status?.missing_files?.length || 0) + (statusData.last_status?.corrupt_files?.length || 0) }}
              </div>
              <div class="text-caption text-medium-emphasis mt-1">待重试缺失/残缺文件</div>
            </div>
          </v-col>
        </v-row>

        <!-- 快捷操作工具条 -->
        <div class="action-strip d-flex align-center justify-space-between flex-wrap ga-2 rounded-xl pa-3 mb-4">
          <div class="d-flex align-center ga-2">
            <v-btn color="primary" variant="flat" size="small" rounded="lg" @click="triggerSync" :loading="syncing" :disabled="statusData.is_running">
              <v-icon start size="16">mdi-play</v-icon>
              同步已就绪媒体
            </v-btn>
            <v-btn color="warning" variant="tonal" size="small" rounded="lg" @click="triggerRetry" :loading="retrying" :disabled="statusData.is_running || (!statusData.last_status?.missing_files?.length && !statusData.last_status?.corrupt_files?.length)">
              <v-icon start size="16">mdi-refresh</v-icon>
              定向重试失败文件
            </v-btn>
            <v-btn color="secondary" variant="tonal" size="small" rounded="lg" @click="triggerClean" :loading="cleaning" :disabled="statusData.is_running">
              <v-icon start size="16">mdi-broom</v-icon>
              清理网盘 ..* 幽灵文件
            </v-btn>
          </div>
          <div v-if="actionMsg" class="text-caption font-weight-bold text-primary">{{ actionMsg }}</div>
        </div>

        <!-- 选项卡切换：冷却队列 vs 异常对账清单 -->
        <v-tabs v-model="currentTab" color="primary" density="compact" class="mb-3 border-b">
          <v-tab value="queue">
            <v-icon start size="16">mdi-timer-sand</v-icon>
            入库延迟冷却队列 ({{ queueList.length }})
          </v-tab>
          <v-tab value="failed">
            <v-icon start size="16">mdi-alert-circle-outline</v-icon>
            对账异常清单 ({{ (statusData.last_status?.missing_files?.length || 0) + (statusData.last_status?.corrupt_files?.length || 0) }})
          </v-tab>
        </v-tabs>

        <!-- 标签 1：延迟冷却队列 -->
        <div v-if="currentTab === 'queue'">
          <div v-if="queueList.length" class="d-flex flex-column ga-2">
            <div v-for="(item, idx) in queueList" :key="idx" class="queue-item-card d-flex align-center justify-space-between rounded-xl pa-3">
              <div class="overflow-hidden mr-3">
                <div class="font-weight-bold text-body-2 text-truncate">{{ item.key }}</div>
                <div class="text-caption text-medium-emphasis mt-0.5">
                  入库时间: {{ item.enter_time }}
                  <span v-if="!item.is_ready" class="ml-2 text-warning font-weight-medium">
                    (还需冷却等待 {{ Math.ceil(item.remaining_seconds / 60) }} 分钟)
                  </span>
                  <span v-else class="ml-2 text-success font-weight-medium">
                    (已达到冷却时间，随时可同步)
                  </span>
                </div>
              </div>
              <v-chip size="x-small" :color="item.is_ready ? 'success' : 'warning'" variant="tonal" class="font-weight-bold flex-shrink-0">
                {{ item.is_ready ? '已就绪' : '缓冲中' }}
              </v-chip>
            </div>
          </div>
          <div v-else class="empty-box d-flex flex-column align-center justify-center py-10 px-4 rounded-xl text-center">
            <v-icon size="32" color="primary" class="mb-2">mdi-check-circle-outline</v-icon>
            <div class="text-caption font-weight-bold text-medium-emphasis">暂无正在冷却中的媒体文件</div>
          </div>
        </div>

        <!-- 标签 2：对账异常与失败清单 -->
        <div v-if="currentTab === 'failed'">
          <div v-if="(statusData.last_status?.missing_files?.length || 0) + (statusData.last_status?.corrupt_files?.length || 0)" class="d-flex flex-column ga-2">
            <!-- 彻底缺失 -->
            <div v-for="(file, idx) in statusData.last_status?.missing_files || []" :key="'m-' + idx" class="failed-item-card d-flex align-center justify-space-between rounded-xl pa-3">
              <div class="overflow-hidden mr-3">
                <div class="font-weight-bold text-body-2 text-error text-truncate">{{ file }}</div>
                <div class="text-caption text-medium-emphasis mt-0.5">两端均无对应文件或目标端未创建成功</div>
              </div>
              <v-chip size="x-small" color="error" variant="flat" class="font-weight-bold flex-shrink-0">彻底缺失</v-chip>
            </div>
            <!-- 大小残缺 -->
            <div v-for="(file, idx) in statusData.last_status?.corrupt_files || []" :key="'c-' + idx" class="failed-item-card d-flex align-center justify-space-between rounded-xl pa-3">
              <div class="overflow-hidden mr-3">
                <div class="font-weight-bold text-body-2 text-warning text-truncate">{{ file }}</div>
                <div class="text-caption text-medium-emphasis mt-0.5">目标端大小不一致，传输中途断流</div>
              </div>
              <v-chip size="x-small" color="warning" variant="flat" class="font-weight-bold flex-shrink-0">文件残缺</v-chip>
            </div>
          </div>
          <div v-else class="empty-box d-flex flex-column align-center justify-center py-10 px-4 rounded-xl text-center">
            <v-icon size="32" color="success" class="mb-2">mdi-shield-check</v-icon>
            <div class="text-caption font-weight-bold text-medium-emphasis">两端文件经对账完全一致，零缺失零残缺！</div>
          </div>
        </div>
      </v-card-text>
    </v-card>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  model: { type: Object, default: () => ({}) },
  api: { type: Object, required: true },
})

const emit = defineEmits(['close', 'switch'])

const loading = ref(false)
const syncing = ref(false)
const retrying = ref(false)
const cleaning = ref(false)
const currentTab = ref('queue')
const actionMsg = ref('')

const statusData = ref({
  is_running: false,
  ready_count: 0,
  cooling_count: 0,
  delay_hours: 2.0,
  last_status: {},
  sync_pairs_count: 0,
})

const queueList = ref([])
let timer = null

function notifyClose() {
  emit('close')
}

function notifySwitch() {
  emit('switch')
}

async function fetchStatus() {
  loading.value = true
  try {
    const res = await props.api.get('plugin/Rsync115Sync/status')
    if (res && res.success && res.data) {
      statusData.value = res.data
    }
    const qRes = await props.api.get('plugin/Rsync115Sync/queue')
    if (qRes && qRes.success && qRes.data) {
      queueList.value = qRes.data
    }
  } catch (e) {
    console.error('获取状态失败:', e)
  } finally {
    loading.value = false
  }
}

async function triggerSync() {
  syncing.value = true
  actionMsg.value = '正在启动同步任务...'
  try {
    const res = await props.api.post('plugin/Rsync115Sync/sync')
    actionMsg.value = res?.message || '已触发同步'
    fetchStatus()
  } catch (e) {
    actionMsg.value = '启动同步出错: ' + e.message
  } finally {
    syncing.value = false
  }
}

async function triggerRetry() {
  retrying.value = true
  actionMsg.value = '正在启动定向重试...'
  try {
    const res = await props.api.post('plugin/Rsync115Sync/retry')
    actionMsg.value = res?.message || '已触发重试'
    fetchStatus()
  } catch (e) {
    actionMsg.value = '启动重试出错: ' + e.message
  } finally {
    retrying.value = false
  }
}

async function triggerClean() {
  cleaning.value = true
  actionMsg.value = '正在扫描并清理幽灵文件...'
  try {
    const res = await props.api.post('plugin/Rsync115Sync/clean')
    actionMsg.value = `已清理 ${res?.cleaned_count || 0} 个 ..* 幽灵临时文件！`
    fetchStatus()
  } catch (e) {
    actionMsg.value = '清理出错: ' + e.message
  } finally {
    cleaning.value = false
  }
}

onMounted(() => {
  fetchStatus()
  timer = setInterval(fetchStatus, 30000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.page-main-card {
  background: rgb(var(--v-theme-surface, 255, 255, 255));
  width: 100%;
}
.header-surface {
  background: linear-gradient(135deg, rgba(var(--v-theme-primary, 24, 103, 192), 0.08) 0%, rgba(var(--v-theme-primary, 24, 103, 192), 0.02) 100%);
}
.header-icon-box {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(var(--v-theme-primary, 24, 103, 192), 0.12);
}
.stat-card {
  border: 1px solid rgba(var(--v-theme-on-surface, 0, 0, 0), 0.08);
}
.stat-info { background: rgba(var(--v-theme-info, 33, 150, 243), 0.06); }
.stat-primary { background: rgba(var(--v-theme-primary, 24, 103, 192), 0.06); }
.stat-error { background: rgba(var(--v-theme-error, 176, 0, 32), 0.06); }

.action-strip {
  background: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.025);
  border: 1px solid rgba(var(--v-theme-on-surface, 0, 0, 0), 0.06);
}
.queue-item-card {
  background: rgb(var(--v-theme-surface, 255, 255, 255));
  border: 1px solid rgba(var(--v-theme-on-surface, 0, 0, 0), 0.07);
}
.failed-item-card {
  background: rgba(var(--v-theme-error, 176, 0, 32), 0.04);
  border: 1px solid rgba(var(--v-theme-error, 176, 0, 32), 0.18);
}
.empty-box {
  border: 1px dashed rgba(var(--v-theme-on-surface, 0, 0, 0), 0.16);
}
</style>
