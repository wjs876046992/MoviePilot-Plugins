<template>
  <div class="plugin-config">
    <v-card class="d-flex flex-column h-100 rounded-xl overflow-hidden config-main-card" elevation="0" variant="outlined">

      <!-- 顶部标题栏 -->
      <v-card-item class="header-surface header-card-item px-5 py-4">
        <template #prepend>
          <div class="header-icon-box mr-3">
            <v-icon color="primary" size="22">mdi-cloud-sync</v-icon>
          </div>
        </template>
        <div>
          <v-card-title class="text-subtitle-1 font-weight-bold pa-0 d-flex align-center">
            115 网盘同步配置
            <v-chip size="x-small" color="primary" variant="tonal" class="ml-2 font-weight-bold">v0.1.5</v-chip>
          </v-card-title>
          <div class="header-subtitle text-caption text-medium-emphasis">设定 CD2 挂载目录映射、入库冷却缓冲策略与防假死参数</div>
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

          <!-- 源端补齐扫描：默认关闭，仅在确实频繁丢事件时才建议开启 -->
          <div class="setting-row d-flex align-center justify-space-between px-4 py-3">
            <div>
              <div class="font-weight-bold text-body-2">
                源端补齐扫描（默认关闭）
                <v-chip size="x-small" color="warning" variant="tonal" class="ml-1 font-weight-bold">谨慎</v-chip>
              </div>
              <div class="text-caption text-medium-emphasis">
                每轮同步前遍历本地源目录，把「插件忙时错过的入库事件」补回来。
                它靠文件修改时间判断新增，<strong>无法区分「真的新入库」和「老文件被重新写入」</strong>
                （刮削写 nfo、下载器续传、套件刷新时间戳都会命中），
                开启后可能把很久以前就入库的文件反复当成新文件补进队列，且这类补入不等待冷却。
                只有在确认经常丢事件时才开启。
              </div>
            </div>
            <v-switch v-model="config.missed_scan_enabled" color="warning" inset hide-details density="compact"></v-switch>
          </div>
        </div>

        <!-- 模块 2：同步目录映射列表 -->
        <div class="section-header d-flex align-center justify-space-between mb-2">
          <div class="font-weight-bold text-subtitle-2 d-flex align-center">
            <v-icon size="18" color="primary" class="mr-1">mdi-folder-swap-outline</v-icon>
            同步目录映射对 ({{ config.sync_pairs.length }})
          </div>
          <v-btn size="small" variant="tonal" color="primary" rounded="lg" @click="addPair">
            <v-icon start size="16">mdi-plus</v-icon>
            添加目录映射
          </v-btn>
        </div>

        <v-alert type="info" variant="tonal" density="compact" class="rounded-lg mb-3 text-body-2">
          为每个媒体库配置一对路径：<b>本地源目录</b> → <b>CD2 挂载的 115 目录</b>。
          插件只同步这些映射内的文件，不会扫描其它位置。
          <b>「同步所有文件类型」</b>关闭时只传视频与字幕（推荐），开启后连同 nfo、图片等一律上传；
          文件类型由下方「同步的扩展名」统一控制。
        </v-alert>

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
              <v-col cols="12">
                <v-text-field
                  v-model="pair.strm_dir"
                  label="strm 目录（可选，用于上传结果交叉验证）"
                  variant="outlined"
                  density="compact"
                  placeholder="例如 /vol1/strm/TV —— 留空则不启用该映射的验证"
                  hint="若你用 strm 类插件在本地生成指针文件，且 strm 文件名与整理后文件同名，填写其根目录。同步成功后进入观察期（默认 6 小时），到期仍未生成对应 .strm 会标记为「疑似上传异常」，可在看板一键删旧重传。纯本地检查，零 115 API。"
                  persistent-hint
                ></v-text-field>
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
                hint="媒体入库后等待 N 小时再上传，留足外挂字幕下载与刮削时间，避免抢先上传导致字幕丢失。设为 0 可关闭等待"
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
                hint="多久巡检一次。到期文件会按上面的限流规则分批上传。补传队列未完成时优先续跑"
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
              <v-textarea v-model="config.exclude_patterns" label="排除文件与目录规则 (每行一条，严格继承 sync_115.sh)" variant="outlined" density="compact" rows="3" hint="每行一条，命中即跳过。默认排除群晖元数据与系统临时文件；注意排除只作用于源端，无法清理 115 上已有的残留" persistent-hint></v-textarea>
            </v-col>
          </v-row>
        </div>

        <!-- 模块 5：上传限流与风控退避 -->
        <div class="font-weight-bold text-subtitle-2 d-flex align-center mb-2 mt-4">
          <v-icon size="18" color="primary" class="mr-1">mdi-speedometer-slow</v-icon>
          上传限流与风控退避
        </div>

        <!-- 通俗说明：为什么需要限流，用大白话讲清风控逻辑 -->
        <v-alert type="info" variant="tonal" density="compact" class="rounded-lg mb-2 text-body-2">
          <div class="font-weight-bold mb-1">为什么需要限流？</div>
          115 网盘会统计<b>单位时间内上传的文件个数</b>。大量小文件（尤其是字幕、样张）
          在短时间内集中上传最容易被判定为异常流量而触发风控，导致上传被拒绝甚至临时封禁。
          <br>
          本插件用两层限制来避免：<b>单批上限</b>控制一次传输提交多少文件，
          <b>窗口配额</b>控制一段时间内累计上传多少文件。超出的部分不会丢弃，
          会在下一个窗口自动继续，直到全部传完。
        </v-alert>

        <div class="settings-group-card rounded-xl overflow-hidden">
          <div class="setting-row d-flex align-center justify-space-between px-4 py-3 border-b">
            <div>
              <div class="font-weight-bold text-body-2">启用上传限流</div>
              <div class="text-caption text-medium-emphasis">按时间窗口限制上传文件数，防止小文件高频上传触发 115 风控</div>
            </div>
            <v-switch v-model="config.rate_limit_enabled" color="primary" inset hide-details density="compact"></v-switch>
          </div>

          <!-- 实时换算：把生硬的秒数/个数翻译成用户能直观判断的速率 -->
          <div v-if="config.rate_limit_enabled" class="px-4 py-2 batch-bar">
            <div class="d-flex align-center flex-wrap ga-2">
              <v-chip size="small" color="primary" variant="tonal" class="font-weight-bold">
                <v-icon start size="14">mdi-speedometer</v-icon>
                当前速率约 {{ effectiveRateText }}
              </v-chip>
              <span class="text-caption text-medium-emphasis">
                即每 {{ windowHumanText }} 最多上传
                {{ config.upload_max_per_window || 0 }} 个文件
              </span>
            </div>
            <div v-if="rateConfigWarnings.length" class="text-caption text-warning font-weight-medium mt-1">
              <div v-for="(w, i) in rateConfigWarnings" :key="i">⚠️ {{ w }}</div>
            </div>
          </div>
          <div class="px-4 py-3">
            <v-row density="compact">
              <v-col cols="12" sm="6">
                <v-text-field
                  v-model.number="config.upload_batch_size"
                  label="单批文件数上限"
                  type="number"
                  variant="outlined"
                  density="compact"
                  :disabled="!config.rate_limit_enabled"
                  hint="一次传输最多提交多少个文件。宁小勿大：小文件扎堆时，大批量最容易触发风控。超出部分自动留到下一轮，不会丢失"
                  persistent-hint
                ></v-text-field>
              </v-col>
              <v-col cols="12" sm="6">
                <v-text-field
                  v-model.number="config.upload_max_per_window"
                  label="单窗口上传文件数上限"
                  type="number"
                  variant="outlined"
                  density="compact"
                  :disabled="!config.rate_limit_enabled"
                  hint="一个窗口内累计最多上传多少个文件。这是防风控的主要闸门——115 按单位时间内的文件个数判定异常"
                  persistent-hint
                ></v-text-field>
              </v-col>
              <v-col cols="12" sm="6">
                <v-text-field
                  v-model.number="config.upload_window_secs"
                  label="限流窗口时长 (秒)"
                  type="number"
                  variant="outlined"
                  density="compact"
                  :disabled="!config.rate_limit_enabled"
                  hint="默认 1800 秒（30 分钟）。窗口结束后额度自动重置，未传完的继续。窗口越短、峰值越高，建议不要低于 300 秒"
                  persistent-hint
                ></v-text-field>
              </v-col>
              <v-col cols="12" sm="6">
                <v-text-field
                  v-model.number="config.backoff_secs"
                  label="命中风控后退避时长 (秒)"
                  type="number"
                  variant="outlined"
                  density="compact"
                  :disabled="!config.rate_limit_enabled"
                  hint="一旦命中风控特征，暂停上传这么久再恢复，给 115 侧缓冲时间。默认 3600 秒（1 小时）"
                  persistent-hint
                ></v-text-field>
              </v-col>
              <v-col cols="12">
                <v-textarea
                  v-model="config.rate_limit_keywords"
                  label="风控特征关键词 (每行一条，命中即退避)"
                  variant="outlined"
                  density="compact"
                  rows="3"
                  :disabled="!config.rate_limit_enabled"
                  hint="从 rsync / CD2 的错误输出里匹配这些关键词，命中即暂停上传并进入退避。每行一条，不区分大小写"
                  persistent-hint
                ></v-textarea>
              </v-col>
              <v-col cols="12" sm="6">
                <v-text-field
                  v-model.number="config.force_cooldown_days"
                  label="全量校验冷却 (天)"
                  type="number"
                  variant="outlined"
                  density="compact"
                  hint="全量校验会遍历 115 全部目录，请求量按媒体库文件数计算（可能上万次），因此限频。默认 7 天；0 表示不限制（不建议）"
                  persistent-hint
                ></v-text-field>
              </v-col>
            </v-row>
          </div>
        </div>
      </v-card-text>

      <!-- 底部操作按钮 -->
      <v-card-actions class="config-actions px-5 py-3 border-t bg-surface">
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
import { ref, computed, onMounted } from 'vue'

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
  // 与后端 _MISSED_SCAN_ENABLED_DEFAULT 保持一致：默认关闭
  missed_scan_enabled: false,
  notify: true,
  delay_hours: 2.0,
  cron: '0 */2 * * *',
  sync_pairs: [],
  media_extensions: 'mp4,mkv,ts,iso,rmvb,avi,mov,mpeg,mpg,wmv,3gp,asf,m4v,flv,m2ts,tp,f4v,srt,ssa,ass',
  exclude_patterns: '@eaDir/\n#recycle/\n@__thumb/\n.DS_Store\n..*',
  rsync_timeout: 600,
  task_timeout: 3600,
  rate_limit_enabled: true,
  upload_batch_size: 200,
  upload_max_per_window: 500,
  upload_window_secs: 1800,
  backoff_secs: 3600,
  rate_limit_keywords: 'too many requests\nrate limit\n429\ntoo frequent\n频繁\n操作过快\n请稍后',
  force_cooldown_days: 7,
})

// ---- 限流参数的实时可读化：把秒数/个数换算成用户能判断的速率与提示 ----

// 窗口时长的可读表述（秒 → 分钟/小时）
const windowHumanText = computed(() => {
  const s = Number(config.value.upload_window_secs) || 0
  if (s <= 0) return '（未设置）'
  if (s % 3600 === 0) return `${s / 3600} 小时`
  if (s % 60 === 0) return `${s / 60} 分钟`
  return `${s} 秒`
})

// 平均速率：每窗口配额 / 窗口时长，让用户直观看到“每分钟大概传几个”
const effectiveRateText = computed(() => {
  const n = Number(config.value.upload_max_per_window) || 0
  const s = Number(config.value.upload_window_secs) || 0
  if (n <= 0 || s <= 0) return '未启用'
  const perMin = (n * 60) / s
  if (perMin >= 10) return `${perMin.toFixed(0)} 个/分钟`
  if (perMin >= 1) return `${perMin.toFixed(1)} 个/分钟`
  return `${(perMin * 60).toFixed(0)} 个/小时`
})

// 参数合理性提醒：避免用户把限流调成“形同虚设”或“永远跑不完”
const rateConfigWarnings = computed(() => {
  const warns = []
  const batch = Number(config.value.upload_batch_size) || 0
  const quota = Number(config.value.upload_max_per_window) || 0
  const win = Number(config.value.upload_window_secs) || 0
  const backoff = Number(config.value.backoff_secs) || 0

  if (quota <= 0) {
    warns.push('单窗口配额为 0：限流将拦截全部上传，建议保持 500 或更高。')
  }
  if (batch <= 0) {
    warns.push('单批上限为 0：单次将不处理任何文件。')
  }
  if (batch > 0 && quota > 0 && batch > quota) {
    warns.push(
      `单批上限（${batch}）大于窗口配额（${quota}）：单批就会耗尽整个窗口额度，` +
      `建议把单批上限设为不高于窗口配额。`
    )
  }
  if (win <= 0) {
    warns.push('窗口时长需大于 0 秒，否则配额会立即失效。')
  }
  if (backoff > 0 && backoff < 60) {
    warns.push(`退避时长仅 ${backoff} 秒：过短可能来不及让 115 侧恢复，建议至少 300 秒。`)
  }
  // 速率过高告警：这是最容易触发风控的配置，必须显式提示
  if (quota > 0 && win > 0) {
    const perMin = (quota * 60) / win
    if (perMin > 60) {
      warns.push(
        `当前速率约 ${perMin.toFixed(0)} 个/分钟（超过每秒 1 个），触发 115 风控的风险很高。` +
        `建议降低「单窗口上传文件数上限」或延长「限流窗口时长」。`
      )
    }
  }
  return warns
})

// 目录映射新增与限流换算无关，以下是原有逻辑
function addPair() {
  config.value.sync_pairs.push({
    name: '',
    src: '',
    dest: '',
    all_ext: false,
    strm_dir: '',
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
  /* 桌面端外边距。原为内联 style 且带 !important，
     导致媒体查询无法覆盖；现收敛到此处作为唯一来源，便于移动端收窄 */
  padding: 18px 22px !important;
}
.config-main-card {
  background: rgb(var(--v-theme-surface, 255, 255, 255));
  width: 100%;
}
.header-surface {
  background: linear-gradient(135deg, rgba(var(--v-theme-primary, 24, 103, 192), 0.08) 0%, rgba(var(--v-theme-primary, 24, 103, 192), 0.02) 100%);
  border-bottom: 1px solid rgba(var(--v-theme-on-surface, 0, 0, 0), 0.08);
}
/* 顶栏标题与副标题：仅调整外边距，不覆盖 text-caption 的小字号行高，
   保证 12px 中文文本的可读性 */
.header-card-item .header-subtitle {
  margin-top: 6px;
}
/* PopUp 内 Title 与下方 Content 的间距必须用 margin 实现：
   宿主默认给 .v-card-item + .v-card-text 设置了 padding-block-start: 0 !important，
   内容区顶部内边距被强制归零，与看板同源，故同样归一化顶部内边距，
   间距由 margin-top 提供。
   !important 是必需的：宿主该声明本身即 !important，级联顺序为
   重要度 > 权重 > 源码顺序，普通声明权重再高也覆盖不了 !important。
   此处不能依赖相邻选择器：保存成功/失败提示条会插在两者之间，
   故直接按内容区类名设置，保证提示条出现时间距依然稳定。

   注意：padding-block-start: unset 系看板真实页面调试所得，同步到本页保持一致，勿凭理论删除。 */
.config-body {
  padding-block-start: unset !important;
  margin-top: 16px;
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

/* ===== 移动端适配 =====
   设置页每行都是「左说明 + 右控件（开关/按钮）」的 justify-space-between 横排，
   窄屏下右侧控件会被挤出卡片；底部操作条的两个按钮同理。
   断点沿用 Vuetify 的 sm（600px）。 */
@media (max-width: 599.98px) {
  /* 移动端收窄外层留白，把宽度还给表单内容 */
  .plugin-config {
    padding: 10px 12px !important;
  }
  /* 同看板：.v-card-item 的 append 列按 max-content 固定宽度、不会收缩，
     窄屏下关闭按钮会被顶出卡片并被 overflow-hidden 裁掉。
     改为 minmax(0, max-content)，允许在宽度不足时收缩。 */
  :deep(.v-card-item) {
    grid-template-columns: max-content minmax(0, auto) minmax(0, max-content);
  }
  :deep(.v-card-item__content) {
    min-width: 0;
  }
  /* 开关类设置行：改为纵向排列，控件左对齐，避免被挤出右边界 */
  .setting-row {
    flex-direction: column;
    align-items: flex-start !important;
    gap: 8px;
  }
  .setting-row > .v-switch {
    margin-left: -8px; /* 抵消 Vuetify 开关自带的左侧内缩，与说明文字左缘对齐 */
  }
  /* 模块标题行（标题 + 右侧操作按钮）：标题允许收缩换行，按钮不被迫溢出 */
  .section-header {
    flex-wrap: wrap;
    gap: 8px;
  }
  .section-header > div {
    min-width: 0;
  }
  /* 底部操作条：查看看板 / 保存配置 两个按钮在窄屏各占一行 */
  .config-actions {
    flex-wrap: wrap;
    gap: 8px;
  }
  .config-actions .v-btn {
    flex: 1 1 100%;
    margin-left: 0 !important;
  }
}
</style>
