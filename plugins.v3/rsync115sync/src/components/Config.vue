<template>
  <div class="plugin-config" style="padding: 18px 22px !important; box-sizing: border-box; width: 100%;">
    <v-card class="d-flex flex-column h-100 rounded-xl overflow-hidden config-main-card" elevation="0" variant="outlined">

      <!-- 顶部标题栏 -->
      <v-card-item class="header-surface px-5 py-4">
        <template #prepend>
          <div class="header-icon-box mr-3">
            <v-icon color="primary" size="22">mdi-cloud-sync</v-icon>
          </div>
        </template>
        <div>
          <v-card-title class="text-subtitle-1 font-weight-bold pa-0 d-flex align-center">
            115 网盘同步配置
            <v-chip size="x-small" color="primary" variant="tonal" class="ml-2 font-weight-bold">v0.0.1</v-chip>
          </v-card-title>
          <div class="text-caption text-medium-emphasis">设定 CD2 挂载目录映射、入库冷却缓冲策略与防假死参数</div>
        </div>
        <template #append>
          <v-btn icon variant="text" size="small" class="rounded-lg close-btn" @click="notifyClose">
            <v-icon size="18">mdi-close</v-icon>
            <v-tooltip activator="parent" location="bottom">关闭配置</v-tooltip>
          </v-btn>
        </template>
      </v-card-item>

      <!-- 状态提醒条 -->
      <div v-if="successMessage || error" class="px-5 pt-3">
        <v-alert v-if="successMessage" type="success" variant="tonal" class="rounded-lg mb-2" closable @click:close="successMessage = null">
          {{ successMessage }}
        </v-alert>
        <v-alert v-if="error" type="error" variant="tonal" class="rounded-lg mb-2" closable @click:close="error = null">
          {{ error }}
        </v-alert>
      </div>

      <!-- 表单主体滚动区 -->
      <v-card-text class="config-body px-5 py-4 overflow-y-auto">
        <!-- 模块 1：基础开关 -->
        <div class="settings-group-card rounded-xl overflow-hidden mb-4">
          <div class="setting-row d-flex align-center justify-space-between px-4 py-3 border-b">
            <div>
              <div class="font-weight-bold text-body-2">启用同步助手</div>
              <div class="text-caption text-medium-emphasis">总控主开关，开启后生效定时轮询与事件监听</div>
            </div>
            <v-switch v-model="config.enabled" color="primary" inset hide-details density="compact"></v-switch>
          </div>

          <div class="setting-row d-flex align-center justify-space-between px-4 py-3">
            <div>
              <div class="font-weight-bold text-body-2">监听媒体转移入库事件</div>
              <div class="text-caption text-medium-emphasis">下载与刮削转移完成后自动纳入延迟冷却队列</div>
            </div>
            <v-switch v-model="config.listen_transfer" color="primary" inset hide-details density="compact"></v-switch>
          </div>
        </div>

        <!-- 模块 2：同步目录映射列表 -->
        <div class="d-flex align-center justify-space-between mb-2">
          <div class="font-weight-bold text-subtitle-2 d-flex align-center">
            <v-icon size="18" color="primary" class="mr-1">mdi-folder-swap-outline</v-icon>
            同步目录映射对 ({{ config.sync_pairs.length }})
          </div>
          <v-btn size="small" variant="tonal" color="primary" rounded="lg" @click="addPair">
            <v-icon start size="16">mdi-plus</v-icon>
            添加目录映射
          </v-btn>
        </div>

        <div v-if="config.sync_pairs.length" class="d-flex flex-column ga-3 mb-4">
          <div v-for="(pair, idx) in config.sync_pairs" :key="idx" class="pair-card rounded-xl pa-4">
            <div class="d-flex align-center justify-space-between mb-3">
              <span class="font-weight-bold text-body-2 text-primary">映射任务 #{{ idx + 1 }}</span>
              <v-btn icon size="x-small" variant="text" color="error" @click="removePair(idx)">
                <v-icon size="18">mdi-trash-can-outline</v-icon>
              </v-btn>
            </div>
            <v-row density="compact">
              <v-col cols="12" sm="4">
                <v-text-field v-model="pair.name" label="任务备注名称" variant="outlined" density="compact" placeholder="例如：电影/电视剧"></v-text-field>
              </v-col>
              <v-col cols="12" sm="4">
                <v-text-field v-model="pair.src" label="本地源目录" variant="outlined" density="compact" placeholder="/volume3/HomeTheater/emby/TV"></v-text-field>
              </v-col>
              <v-col cols="12" sm="4">
                <v-text-field v-model="pair.dest" label="CD2 挂载 115 目录" variant="outlined" density="compact" placeholder="/volume2/CloudNAS/115/TV"></v-text-field>
              </v-col>
              <v-col cols="12">
                <v-checkbox v-model="pair.all_ext" label="同步所有文件类型 (默认仅同步视频，勾选后将同步字幕与元数据等全部格式)" density="compact" hide-details color="primary"></v-checkbox>
              </v-col>
            </v-row>
          </div>
        </div>
        <div v-else class="empty-hint-box text-center py-6 rounded-xl mb-4 text-caption text-disabled">
          暂未配置任何目录映射，点击上方按钮添加你的本地媒体目录与 CD2 挂载路径
        </div>

        <!-- 模块 3：入库冷却缓冲与定时策略 -->
        <div class="font-weight-bold text-subtitle-2 d-flex align-center mb-2">
          <v-icon size="18" color="primary" class="mr-1">mdi-timer-sand</v-icon>
          入库冷却缓冲与调度
        </div>
        <div class="settings-group-card rounded-xl overflow-hidden pa-4 mb-4">
          <v-row density="comfortable">
            <v-col cols="12" sm="6">
              <v-text-field
                v-model.number="config.delay_hours"
                label="入库冷却延迟时长 (小时)"
                type="number"
                step="0.5"
                min="0"
                variant="outlined"
                density="compact"
                suffix="小时"
                hint="媒体入库后等待 N 小时，留足外挂字幕下载与刮削时间，到期后才触发上传"
                persistent-hint
              ></v-text-field>
            </v-col>
            <v-col cols="12" sm="6">
              <v-text-field
                v-model="config.cron"
                label="定时检查 Cron 规则"
                variant="outlined"
                density="compact"
                placeholder="0 */2 * * *"
                hint="默认每 2 小时定时巡检一次达到冷却要求的就绪文件"
                persistent-hint
              ></v-text-field>
            </v-col>
          </v-row>
        </div>

        <!-- 模块 4：高级过滤与防假死参数 -->
        <div class="font-weight-bold text-subtitle-2 d-flex align-center mb-2">
          <v-icon size="18" color="primary" class="mr-1">mdi-shield-check-outline</v-icon>
          CD2 核心过滤与防假死参数
        </div>
        <div class="settings-group-card rounded-xl overflow-hidden pa-4">
          <v-row density="compact">
            <v-col cols="12" sm="6">
              <v-text-field v-model.number="config.rsync_timeout" label="rsync I/O 超时 (秒)" type="number" variant="outlined" density="compact" hint="网络异常中断时快速失败，防止 FUSE 挂起死锁" persistent-hint></v-text-field>
            </v-col>
            <v-col cols="12" sm="6">
              <v-text-field v-model.number="config.task_timeout" label="单次任务最大超时 (秒)" type="number" variant="outlined" density="compact" hint="进程超过此时长强制杀死，彻底避免进程僵死" persistent-hint></v-text-field>
            </v-col>
            <v-col cols="12">
              <v-textarea v-model="config.exclude_patterns" label="排除文件与目录规则 (每行一条，严格继承 sync_115.sh)" variant="outlined" density="compact" rows="3" hint="默认排除群晖元数据与系统废件" persistent-hint></v-textarea>
            </v-col>
          </v-row>
        </div>
      </v-card-text>

      <!-- 底部操作按钮 -->
      <v-card-actions class="px-5 py-3 border-t bg-surface">
        <v-btn variant="tonal" rounded="lg" color="primary" @click="notifySwitch">
          <v-icon start size="16">mdi-view-dashboard-outline</v-icon>
          查看监控看板
        </v-btn>
        <v-spacer></v-spacer>
        <v-btn variant="flat" color="primary" rounded="lg" class="px-6" @click="saveConfig" :loading="saving">
          <v-icon start size="16">mdi-content-save</v-icon>
          保存配置
        </v-btn>
      </v-card-actions>
    </v-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'

const props = defineProps({
  model: { type: Object, default: () => ({}) },
  api: { type: Object, required: true },
})

const emit = defineEmits(['close', 'switch'])

const saving = ref(false)
const error = ref(null)
const successMessage = ref(null)

const config = ref({
  enabled: false,
  listen_transfer: true,
  notify: true,
  delay_hours: 2.0,
  cron: '0 */2 * * *',
  sync_pairs: [],
  media_extensions: 'mp4,mkv,avi,mov,ts,m2ts,iso,wmv,flv,rmvb',
  exclude_patterns: '@eaDir/\n#recycle/\n@__thumb/\n.DS_Store',
  rsync_timeout: 60,
  task_timeout: 3600,
})

function addPair() {
  config.value.sync_pairs.push({
    name: '',
    src: '',
    dest: '',
    all_ext: false,
  })
}

function removePair(index) {
  config.value.sync_pairs.splice(index, 1)
}

function notifyClose() {
  emit('close')
}

function notifySwitch() {
  emit('switch')
}

async function loadConfig() {
  try {
    const res = await props.api.get('plugin/Rsync115Sync/config')
    if (res && res.success && res.data) {
      Object.assign(config.value, res.data)
    }
  } catch (e) {
    console.error('读取配置失败:', e)
  }
}

async function saveConfig() {
  saving.value = true
  error.value = null
  successMessage.value = null
  try {
    const res = await props.api.post('plugin/Rsync115Sync/config', config.value)
    if (res && res.success) {
      successMessage.value = '配置已成功保存！'
    } else {
      error.value = res?.message || '保存配置失败'
    }
  } catch (e) {
    error.value = e.message || '保存配置失败'
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadConfig()
})
</script>

<style scoped>
.plugin-config {
  width: 100%;
  box-sizing: border-box;
  padding: 16px 20px !important;
}
.config-main-card {
  background: rgb(var(--v-theme-surface, 255, 255, 255));
  width: 100%;
}
.header-surface {
  background: linear-gradient(135deg, rgba(var(--v-theme-primary, 24, 103, 192), 0.08) 0%, rgba(var(--v-theme-primary, 24, 103, 192), 0.02) 100%);
  border-bottom: 1px solid rgba(var(--v-theme-on-surface, 0, 0, 0), 0.08);
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
.settings-group-card {
  background: rgb(var(--v-theme-surface, 255, 255, 255));
  border: 1px solid rgba(var(--v-theme-on-surface, 0, 0, 0), 0.08);
}
.pair-card {
  background: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.02);
  border: 1px solid rgba(var(--v-theme-on-surface, 0, 0, 0), 0.07);
}
.empty-hint-box {
  border: 1px dashed rgba(var(--v-theme-on-surface, 0, 0, 0), 0.16);
}
</style>
