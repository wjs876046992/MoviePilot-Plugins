<template>
  <div class="plugin-page" style="padding: 18px 22px !important; box-sizing: border-box; width: 100%;">
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
        <div class="action-strip rounded-xl pa-3 mb-4">
          <div class="d-flex align-center justify-space-between flex-wrap ga-2">
            <div class="d-flex align-center ga-2">
              <v-btn color="primary" variant="flat" size="small" rounded="lg" @click="triggerSync" :loading="syncing" :disabled="statusData.is_running">
                <v-icon start size="16">mdi-play</v-icon>
                同步已就绪媒体
              </v-btn>
              <v-btn color="warning" variant="tonal" size="small" rounded="lg" @click="triggerRetry" :loading="retrying" :disabled="statusData.is_running || (!statusData.last_status?.missing_files?.length && !statusData.last_status?.corrupt_files?.length)">
                <v-icon start size="16">mdi-refresh</v-icon>
                定向重试失败文件
              </v-btn>
            </div>
            <div class="d-flex align-center ga-2">
              <div v-if="actionMsg" class="text-caption font-weight-bold text-primary mr-1">{{ actionMsg }}</div>
              <!-- 批量选择模式开关 -->
              <v-btn
                v-if="currentTab !== 'ignored'"
                size="small"
                variant="tonal"
                :color="selectMode ? 'error' : 'secondary'"
                rounded="lg"
                @click="toggleSelectMode"
              >
                <v-icon start size="16">{{ selectMode ? 'mdi-close' : 'mdi-checkbox-multiple-marked-outline' }}</v-icon>
                {{ selectMode ? '退出批量' : '批量选择' }}
              </v-btn>
              <v-btn
                v-if="selectMode"
                size="small"
                variant="flat"
                color="primary"
                rounded="lg"
                :loading="batchSyncing"
                :disabled="!selectedKeys.length || statusData.is_running"
                @click="batchSyncSelected"
              >
                <v-icon start size="16">mdi-cloud-upload-outline</v-icon>
                同步选中 ({{ selectedKeys.length }})
              </v-btn>
            </div>
          </div>

          <!-- 批量操作辅助条 -->
          <div v-if="selectMode" class="d-flex align-center flex-wrap ga-3 mt-2 pt-2 batch-bar">
            <v-checkbox
              :model-value="allSelected"
              :indeterminate="selectedKeys.length > 0 && !allSelected"
              density="compact"
              hide-details
              color="primary"
              class="flex-shrink-0"
              @update:model-value="toggleSelectAll"
            >
              <template #label>
                <span class="text-caption font-weight-bold">全选本页 ({{ selectableItems.length }})</span>
              </template>
            </v-checkbox>
            <span class="text-caption text-medium-emphasis">已选 {{ selectedKeys.length }} 项 · 可跨分组勾选后一次性上传统一触发</span>
          </div>
        </div>

        <!-- 选项卡切换：冷却队列 vs 异常对账清单 vs 已忽略 -->
        <v-tabs v-model="currentTab" color="primary" density="compact" class="mb-3 border-b">
          <v-tab value="queue">
            <v-icon start size="16">mdi-timer-sand</v-icon>
            入库延迟冷却队列 ({{ queueList.length }})
          </v-tab>
          <v-tab value="failed">
            <v-icon start size="16">mdi-alert-circle-outline</v-icon>
            对账异常清单 ({{ failedCount }})
          </v-tab>
          <v-tab value="ignored">
            <v-icon start size="16">mdi-eye-off-outline</v-icon>
            已忽略 ({{ ignoredList.length }})
          </v-tab>
        </v-tabs>

        <!-- 标签 1：延迟冷却队列 -->
        <div v-if="currentTab === 'queue'">
          <div v-if="queueList.length" class="d-flex flex-column ga-2">
            <div v-for="(item, idx) in queueList" :key="'q-' + idx" class="queue-item-card d-flex align-center justify-space-between rounded-xl pa-3">
              <div class="d-flex align-center overflow-hidden mr-3">
                <v-checkbox
                  v-if="selectMode"
                  :model-value="selectedKeys.includes(item.key)"
                  density="compact"
                  hide-details
                  color="primary"
                  class="flex-shrink-0 mr-2"
                  @update:model-value="toggleSelect(item.key)"
                ></v-checkbox>
                <div class="overflow-hidden">
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
              </div>
              <div class="d-flex align-center ga-1 flex-shrink-0">
                <v-chip size="x-small" :color="item.is_ready ? 'success' : 'warning'" variant="tonal" class="font-weight-bold">
                  {{ item.is_ready ? '已就绪' : '缓冲中' }}
                </v-chip>
                <v-btn
                  size="x-small"
                  variant="tonal"
                  color="primary"
                  rounded="lg"
                  class="px-2"
                  :loading="itemLoading === item.key"
                  :disabled="statusData.is_running || (itemLoading && itemLoading !== item.key)"
                  @click="syncSingle(item.key)"
                >
                  <v-icon start size="14">mdi-cloud-upload-outline</v-icon>
                  立即同步
                  <v-tooltip activator="parent" location="top">
                    不等待冷却，立即定向同步此文件（会自动移出冷却队列）
                  </v-tooltip>
                </v-btn>
              </div>
            </div>
          </div>
          <div v-else class="empty-box d-flex flex-column align-center justify-center py-10 px-4 rounded-xl text-center">
            <v-icon size="32" color="primary" class="mb-2">mdi-check-circle-outline</v-icon>
            <div class="text-caption font-weight-bold text-medium-emphasis">暂无正在冷却中的媒体文件</div>
          </div>
        </div>

        <!-- 标签 2：对账异常与失败清单 -->
        <div v-if="currentTab === 'failed'">
          <div v-if="failedCount" class="d-flex flex-column ga-2">
            <!-- 缺失未同步 -->
            <div v-for="(file, idx) in statusData.last_status?.missing_files || []" :key="'m-' + idx" class="failed-item-card d-flex align-center justify-space-between rounded-xl pa-3">
              <div class="d-flex align-center overflow-hidden mr-3">
                <v-checkbox
                  v-if="selectMode"
                  :model-value="selectedKeys.includes(file)"
                  density="compact"
                  hide-details
                  color="primary"
                  class="flex-shrink-0 mr-2"
                  @update:model-value="toggleSelect(file)"
                ></v-checkbox>
                <div class="overflow-hidden">
                  <div class="font-weight-bold text-body-2 text-error text-truncate">{{ file }}</div>
                  <div class="text-caption text-medium-emphasis mt-0.5">本地已入库，但 115 网盘端尚未同步到位</div>
                </div>
              </div>
              <div class="d-flex align-center ga-1 flex-shrink-0">
                <v-chip size="x-small" color="error" variant="flat" class="font-weight-bold">待同步</v-chip>
                <v-btn
                  size="x-small"
                  variant="tonal"
                  color="primary"
                  rounded="lg"
                  class="px-2"
                  :loading="itemLoading === file"
                  :disabled="statusData.is_running || (itemLoading && itemLoading !== file)"
                  @click="syncSingle(file)"
                >
                  <v-icon start size="14">mdi-refresh</v-icon>
                  重试
                  <v-tooltip activator="parent" location="top">立即定向重传此文件</v-tooltip>
                </v-btn>
                <v-btn icon size="x-small" variant="text" color="primary" @click="ignoreFile(file, 'exact')">
                  <v-icon size="16">mdi-eye-off-outline</v-icon>
                  <v-tooltip activator="parent" location="top">忽略此项（不再报警）</v-tooltip>
                </v-btn>
              </div>
            </div>
            <!-- 大小残缺 -->
            <div v-for="(file, idx) in statusData.last_status?.corrupt_files || []" :key="'c-' + idx" class="failed-item-card d-flex align-center justify-space-between rounded-xl pa-3">
              <div class="d-flex align-center overflow-hidden mr-3">
                <v-checkbox
                  v-if="selectMode"
                  :model-value="selectedKeys.includes(file)"
                  density="compact"
                  hide-details
                  color="primary"
                  class="flex-shrink-0 mr-2"
                  @update:model-value="toggleSelect(file)"
                ></v-checkbox>
                <div class="overflow-hidden">
                  <div class="font-weight-bold text-body-2 text-warning text-truncate">{{ file }}</div>
                  <div class="text-caption text-medium-emphasis mt-0.5">目标端大小不一致，传输中途断流</div>
                </div>
              </div>
              <div class="d-flex align-center ga-1 flex-shrink-0">
                <v-chip size="x-small" color="warning" variant="flat" class="font-weight-bold">文件残缺</v-chip>
                <v-btn
                  size="x-small"
                  variant="tonal"
                  color="primary"
                  rounded="lg"
                  class="px-2"
                  :loading="itemLoading === file"
                  :disabled="statusData.is_running || (itemLoading && itemLoading !== file)"
                  @click="syncSingle(file)"
                >
                  <v-icon start size="14">mdi-refresh</v-icon>
                  重试
                  <v-tooltip activator="parent" location="top">先清理目标端残缺文件，再重新上传</v-tooltip>
                </v-btn>
                <v-btn icon size="x-small" variant="text" color="primary" @click="ignoreFile(file, 'exact')">
                  <v-icon size="16">mdi-eye-off-outline</v-icon>
                  <v-tooltip activator="parent" location="top">忽略此项（不再报警）</v-tooltip>
                </v-btn>
              </div>
            </div>
          </div>
          <div v-else class="empty-box d-flex flex-column align-center justify-center py-10 px-4 rounded-xl text-center">
            <v-icon size="32" color="success" class="mb-2">mdi-shield-check</v-icon>
            <div class="text-caption font-weight-bold text-medium-emphasis">冷却队列与待重试文件经对账全部一致，零缺失零残缺！</div>
          </div>
        </div>

        <!-- 标签 3：已忽略清单 -->
        <div v-if="currentTab === 'ignored'">
          <div v-if="ignoredList.length" class="d-flex flex-column ga-2">
            <div v-for="(rule, idx) in ignoredList" :key="'i-' + idx" class="queue-item-card d-flex align-center justify-space-between rounded-xl pa-3">
              <div class="overflow-hidden mr-3">
                <div class="font-weight-bold text-body-2 text-truncate">{{ rule.rule }}</div>
                <div class="text-caption text-medium-emphasis mt-0.5">
                  {{ rule.match === 'exact' ? '精确匹配' : '包含匹配' }}
                  · 加入于 {{ rule.created_at }}
                  <span v-if="rule.created_by"> · 操作人 {{ rule.created_by }}</span>
                </div>
              </div>
              <div class="d-flex align-center ga-1 flex-shrink-0">
                <v-chip size="x-small" color="secondary" variant="tonal" class="font-weight-bold">已忽略</v-chip>
                <v-btn icon size="x-small" variant="text" color="success" @click="removeIgnore(idx)">
                  <v-icon size="16">mdi-restore</v-icon>
                  <v-tooltip activator="parent" location="top">恢复对账</v-tooltip>
                </v-btn>
              </div>
            </div>
          </div>
          <div v-else class="empty-box d-flex flex-column align-center justify-center py-10 px-4 rounded-xl text-center">
            <v-icon size="32" color="primary" class="mb-2">mdi-eye-off-outline</v-icon>
            <div class="text-caption font-weight-bold text-medium-emphasis">当前没有忽略任何文件</div>
          </div>
        </div>
      </v-card-text>
    </v-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  model: { type: Object, default: () => ({}) },
  api: { type: Object, required: true },
})

const emit = defineEmits(['close', 'switch'])

const loading = ref(false)
const syncing = ref(false)
const retrying = ref(false)
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

const ignoredList = ref([])

// 批量选择 / 单条手动触发
const selectMode = ref(false)
const selectedKeys = ref([])
const itemLoading = ref('')
const batchSyncing = ref(false)

const failedCount = computed(() =>
  (statusData.value.last_status?.missing_files?.length || 0) +
  (statusData.value.last_status?.corrupt_files?.length || 0)
)

const queueList = ref([])
let timer = null

// 当前标签页可被勾选的条目 key 列表
const selectableItems = computed(() => {
  if (currentTab.value === 'queue') {
    return queueList.value.map((it) => it.key)
  }
  if (currentTab.value === 'failed') {
    return [
      ...(statusData.value.last_status?.missing_files || []),
      ...(statusData.value.last_status?.corrupt_files || []),
    ]
  }
  return []
})

const allSelected = computed(
  () =>
    selectableItems.value.length > 0 &&
    selectableItems.value.every((k) => selectedKeys.value.includes(k))
)

function toggleSelectMode() {
  selectMode.value = !selectMode.value
  if (!selectMode.value) selectedKeys.value = []
}

function toggleSelect(key) {
  const i = selectedKeys.value.indexOf(key)
  if (i >= 0) selectedKeys.value.splice(i, 1)
  else selectedKeys.value.push(key)
}

// 全选/取消全选：仅作用于当前标签页的条目，不影响其它标签页已勾选的内容
function toggleSelectAll(val) {
  const current = selectableItems.value
  if (val) {
    const merged = new Set([...selectedKeys.value, ...current])
    selectedKeys.value = Array.from(merged)
  } else {
    selectedKeys.value = selectedKeys.value.filter((k) => !current.includes(k))
  }
}

// 单条手动触发同步（不等冷却，立即定向上传）
async function syncSingle(key) {
  if (!key || statusData.value.is_running) return
  itemLoading.value = key
  actionMsg.value = `正在触发同步: ${key}`
  try {
    const res = await props.api.post('plugin/Rsync115Sync/sync_item', { key })
    if (res && res.success) {
      actionMsg.value = res.message || `已触发同步: ${key}`
      // 从选中列表移除，避免重复提交
      const i = selectedKeys.value.indexOf(key)
      if (i >= 0) selectedKeys.value.splice(i, 1)
    } else {
      actionMsg.value = res?.message || '触发同步失败'
    }
    await fetchStatus()
  } catch (e) {
    actionMsg.value = '触发同步出错: ' + e.message
  } finally {
    itemLoading.value = ''
  }
}

// 批量触发选中条目
async function batchSyncSelected() {
  if (!selectedKeys.value.length || statusData.value.is_running) return
  batchSyncing.value = true
  actionMsg.value = `正在批量触发 ${selectedKeys.value.length} 个文件...`
  try {
    const res = await props.api.post('plugin/Rsync115Sync/sync_item', { keys: [...selectedKeys.value] })
    if (res && res.success) {
      actionMsg.value = res.message || '已批量触发同步'
      selectedKeys.value = []
    } else {
      actionMsg.value = res?.message || '批量触发失败'
    }
    await fetchStatus()
  } catch (e) {
    actionMsg.value = '批量触发出错: ' + e.message
  } finally {
    batchSyncing.value = false
  }
}

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
    const iRes = await props.api.get('plugin/Rsync115Sync/ignored')
    if (iRes && iRes.success && iRes.data) {
      ignoredList.value = iRes.data
    }
    // 清理已不存在条目的勾选状态，避免提交到已消失的文件
    if (selectedKeys.value.length) {
      const alive = new Set([
        ...queueList.value.map((it) => it.key),
        ...(statusData.value.last_status?.missing_files || []),
        ...(statusData.value.last_status?.corrupt_files || []),
      ])
      selectedKeys.value = selectedKeys.value.filter((k) => alive.has(k))
    }
  } catch (e) {
    console.error('获取状态失败:', e)
  } finally {
    loading.value = false
  }
}

async function ignoreFile(file, match = 'exact') {
  try {
    const res = await props.api.post('plugin/Rsync115Sync/ignore', { rule: file, match })
    actionMsg.value = res?.message || '已加入忽略清单'
    fetchStatus()
  } catch (e) {
    actionMsg.value = '忽略失败: ' + e.message
  }
}

async function removeIgnore(index) {
  try {
    const res = await props.api.post('plugin/Rsync115Sync/unignore', { index })
    actionMsg.value = res?.message || '已恢复对账'
    fetchStatus()
  } catch (e) {
    actionMsg.value = '恢复失败: ' + e.message
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

onMounted(() => {
  fetchStatus()
  timer = setInterval(fetchStatus, 30000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.plugin-page {
  width: 100%;
  box-sizing: border-box;
  padding: 16px 20px !important;
}
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
.batch-bar {
  border-top: 1px dashed rgba(var(--v-theme-on-surface, 0, 0, 0), 0.14);
}
.failed-item-card {
  background: rgba(var(--v-theme-error, 176, 0, 32), 0.04);
  border: 1px solid rgba(var(--v-theme-error, 176, 0, 32), 0.18);
}
.empty-box {
  border: 1px dashed rgba(var(--v-theme-on-surface, 0, 0, 0), 0.16);
}
</style>
