<template>
  <div class="plugin-page">
    <v-card class="d-flex flex-column h-100 rounded-xl overflow-hidden page-main-card" elevation="0" variant="outlined">

      <!-- 优雅顶栏 -->
      <v-card-item class="header-surface header-card-item px-5 py-3 border-b">
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
          <div class="header-subtitle text-caption text-medium-emphasis">监控入库延迟冷却进度、双向对账异常与一键快速定向重试</div>
        </div>
        <template #append>
          <div class="d-flex align-center flex-wrap justify-end ga-1 header-append">
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

        <!-- 补传 / 限流 / 遗漏补齐提示：用通俗文字说明“为什么慢、还要多久” -->
        <v-alert
          v-if="statusData.backfill_remaining || isThrottled || statusData.missed_count || statusData.stale_count || statusData.strm_watching"
          :type="isThrottled ? 'warning' : 'info'"
          variant="tonal"
          density="compact"
          class="rounded-lg mb-3 text-body-2"
        >
          <div v-if="isThrottled" class="font-weight-medium">
            ⏸ 为避免触发 115 风控，上传已自动暂停，约 {{ blockedMinutes }} 分钟后恢复，无需手动操作。
          </div>
          <div v-if="statusData.backfill_remaining">
            存量补传进行中：剩余 <strong>{{ statusData.backfill_remaining }}</strong>
            <template v-if="statusData.backfill_total"> / 共 {{ statusData.backfill_total }}</template> 个。
            为防风控，每个时间窗口最多上传 {{ statusData.upload_max_per_window }} 个
            （本窗口已用 {{ statusData.upload_window_count }} 个），未传完的会自动继续。
          </div>
          <div v-if="statusData.stale_count">
            🗑️ <strong>{{ statusData.stale_count }}</strong> 个队列条目的源文件已从本地删除，
            将在下轮同步时自动移出（不计入上方「冷却中 / 就绪」数字）。
          </div>
          <div v-if="statusData.missed_count">
            🕳️ 检测到 <strong>{{ statusData.missed_count }}</strong> 个文件可能因插件重载错过了入库事件，
            已由源端扫描补回，将在下次同步时一并上传（这些文件不再等待冷却）。
          </div>
          <div v-if="statusData.strm_watching">
            📺 strm 交叉验证进行中：<strong>{{ statusData.strm_watching }}</strong> 个文件处于观察期，
            {{ statusData.strm_grace_hours }} 小时内未生成对应 .strm 才会被标记为「疑似上传异常」，
            属正常等待，无需处理。
          </div>
        </v-alert>

        <!-- 快捷操作工具条 -->
        <div class="action-strip rounded-xl pa-3 mb-4">
          <div class="action-strip-row d-flex flex-column flex-sm-row align-stretch align-sm-center justify-sm-space-between ga-2">
            <div class="action-group d-flex align-center flex-wrap ga-2">
              <v-btn color="primary" variant="flat" size="small" rounded="lg" @click="triggerSync" :loading="syncing" :disabled="statusData.is_running">
                <v-icon start size="16">mdi-play</v-icon>
                同步已就绪媒体
              </v-btn>
              <v-btn color="warning" variant="tonal" size="small" rounded="lg" @click="triggerRetry" :loading="retrying" :disabled="statusData.is_running || (!statusData.last_status?.missing_files?.length && !statusData.last_status?.corrupt_files?.length)">
                <v-icon start size="16">mdi-refresh</v-icon>
                定向重试失败文件
              </v-btn>
              <v-btn color="info" variant="tonal" size="small" rounded="lg" @click="scanBackfill" :loading="backfillScanning" :disabled="statusData.is_running">
                <v-icon start size="16">mdi-database-arrow-up-outline</v-icon>
                补传存量媒体
                <v-tooltip activator="parent" location="top">
                  扫描本地存量媒体（含同名字幕）并分批补传；只读源端目录，不遍历 115
                </v-tooltip>
              </v-btn>
              <v-btn v-if="statusData.backfill_remaining" color="error" variant="text" size="small" rounded="lg" @click="clearBackfill" :disabled="statusData.is_running">
                <v-icon start size="16">mdi-cancel</v-icon>
                取消补传
              </v-btn>
            </div>
            <div class="action-group d-flex align-center flex-wrap ga-2">
              <div v-if="actionMsg" class="text-caption font-weight-bold text-primary mr-1 action-msg">{{ actionMsg }}</div>
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
                :color="selectedStrmOnly ? 'warning' : 'primary'"
                rounded="lg"
                :loading="batchSyncing"
                :disabled="!selectedKeys.length || statusData.is_running"
                @click="batchSyncSelected"
              >
                <v-icon start size="16">{{ selectedStrmOnly ? 'mdi-delete-restore' : 'mdi-cloud-upload-outline' }}</v-icon>
                {{ selectedStrmOnly ? `删旧重传 (${selectedKeys.length})` : `同步选中 (${selectedKeys.length})` }}
                <v-tooltip v-if="selectedStrmOnly" activator="parent" location="top">
                  选中项全部来自 strm 疑似异常清单：先删除 115 端旧文件再重传，
                  以绕过 CD2 挂载视图「看起来正常」的假成功
                </v-tooltip>
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
            <span class="text-caption text-medium-emphasis batch-hint">
              已选 {{ selectedKeys.length }} 项 · 可跨分组勾选后一次性触发
              <template v-if="selectedStrmOnly">（全部为 strm 疑似异常，将执行「删旧重传」）</template>
              <template v-else-if="strmSelectedCount">
                （其中 {{ strmSelectedCount }} 项为 strm 疑似异常，提交时会自动分流）
              </template>
            </span>
          </div>
        </div>

        <!-- 选项卡切换：冷却队列 vs 异常对账清单 vs 已忽略 -->
        <v-tabs v-model="currentTab" color="primary" density="compact" show-arrows class="mb-3 border-b">
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
            <div v-for="item in queuePaged.slice" :key="item.key" class="queue-item-card d-flex flex-column flex-sm-row align-stretch align-sm-center justify-sm-space-between rounded-xl pa-3 ga-2">
              <div class="list-row-main d-flex align-center overflow-hidden mr-sm-3 mr-0">
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
              <div class="list-row-actions d-flex align-center flex-wrap ga-1 flex-shrink-0">
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
                  :disabled="statusData.is_running || (!!itemLoading && itemLoading !== item.key)"
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
          <!-- 分页条：三个标签共用，绑定各自页码 -->
          <div v-if="paged.pages > 1" class="pager-bar d-flex align-center justify-center flex-wrap ga-2 mt-3">
            <v-btn
              size="small" variant="text" rounded="lg" class="pager-btn"
              :disabled="paged.page <= 1"
              @click="paged.pageRef.value = paged.page - 1"
            >
              <v-icon start size="16">mdi-chevron-left</v-icon>上一页
            </v-btn>
            <span class="text-caption text-medium-emphasis">
              第 <strong>{{ paged.page }}</strong> / {{ paged.pages }} 页 ·
              共 {{ paged.total }} 条（每页 {{ PAGE_SIZE }} 条）
            </span>
            <v-btn
              size="small" variant="text" rounded="lg" class="pager-btn"
              :disabled="paged.page >= paged.pages"
              @click="paged.pageRef.value = paged.page + 1"
            >
              下一页<v-icon end size="16">mdi-chevron-right</v-icon>
            </v-btn>
          </div>
          <div v-else class="empty-box d-flex flex-column align-center justify-center py-10 px-4 rounded-xl text-center">
            <v-icon size="32" color="primary" class="mb-2">mdi-check-circle-outline</v-icon>
            <div class="text-caption font-weight-bold text-medium-emphasis">暂无正在冷却中的媒体文件</div>
          </div>
        </div>

        <!-- 标签 2：对账异常与失败清单 -->
        <div v-if="currentTab === 'failed'">
          <div v-if="failedCount" class="d-flex flex-column ga-2">
            <!-- 缺失未同步 + 大小残缺：合并为一个列表以便统一分页 -->
            <div v-for="entry in failedPaged.slice" :key="entry.kind + ':' + entry.file" class="failed-item-card d-flex flex-column flex-sm-row align-stretch align-sm-center justify-sm-space-between rounded-xl pa-3 ga-2">
              <div class="list-row-main d-flex align-center overflow-hidden mr-sm-3 mr-0">
                <v-checkbox
                  v-if="selectMode"
                  :model-value="selectedKeys.includes(entry.file)"
                  density="compact"
                  hide-details
                  color="primary"
                  class="flex-shrink-0 mr-2"
                  @update:model-value="toggleSelect(entry.file)"
                ></v-checkbox>
                <div class="overflow-hidden">
                  <div
                    class="font-weight-bold text-body-2 text-truncate"
                    :class="entry.kind === 'missing' ? 'text-error' : 'text-warning'"
                  >{{ entry.file }}</div>
                  <div class="text-caption text-medium-emphasis mt-0.5">
                    {{ entry.kind === 'missing' ? '本地已入库，但 115 网盘端尚未同步到位' : '目标端大小不一致，传输中途断流' }}
                  </div>
                </div>
              </div>
              <div class="list-row-actions d-flex align-center flex-wrap ga-1 flex-shrink-0">
                <v-chip
                  size="x-small"
                  :color="entry.kind === 'missing' ? 'error' : 'warning'"
                  variant="flat"
                  class="font-weight-bold"
                >{{ entry.kind === 'missing' ? '待同步' : '文件残缺' }}</v-chip>
                <v-btn
                  size="x-small"
                  variant="tonal"
                  color="primary"
                  rounded="lg"
                  class="px-2"
                  :loading="itemLoading === file"
                  :disabled="statusData.is_running || (!!itemLoading && itemLoading !== file)"
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
          </div>
          <!-- 分页条：三个标签共用，绑定各自页码 -->
          <div v-if="paged.pages > 1" class="pager-bar d-flex align-center justify-center flex-wrap ga-2 mt-3">
            <v-btn
              size="small" variant="text" rounded="lg" class="pager-btn"
              :disabled="paged.page <= 1"
              @click="paged.pageRef.value = paged.page - 1"
            >
              <v-icon start size="16">mdi-chevron-left</v-icon>上一页
            </v-btn>
            <span class="text-caption text-medium-emphasis">
              第 <strong>{{ paged.page }}</strong> / {{ paged.pages }} 页 ·
              共 {{ paged.total }} 条（每页 {{ PAGE_SIZE }} 条）
            </span>
            <v-btn
              size="small" variant="text" rounded="lg" class="pager-btn"
              :disabled="paged.page >= paged.pages"
              @click="paged.pageRef.value = paged.page + 1"
            >
              下一页<v-icon end size="16">mdi-chevron-right</v-icon>
            </v-btn>
          </div>
          <div v-else class="empty-box d-flex flex-column align-center justify-center py-10 px-4 rounded-xl text-center">
            <v-icon size="32" color="success" class="mb-2">mdi-shield-check</v-icon>
            <div class="text-caption font-weight-bold text-medium-emphasis">冷却队列与待重试文件经对账全部一致，零缺失零残缺！</div>
          </div>

          <!-- strm 交叉验证：疑似上传异常（独立于对账，来自 strm 插件视角） -->
          <!-- 有配置 strm 目录就渲染本区（即使清单为空）—— 否则用户找不到「主动扫描」
               入口，而扫描正是清单为空时最需要的功能（发现从未被观察过的坏文件） -->
          <div v-if="strmConfigured" class="mt-4">
            <div class="d-flex align-center flex-wrap ga-2 mb-2">
              <v-icon size="18" color="warning">mdi-television-classic-off</v-icon>
              <span class="font-weight-bold text-body-2">strm 疑似上传异常 ({{ strmSuspectCount }})</span>
              <span class="text-caption text-medium-emphasis">
                观察期 {{ statusData.strm_grace_hours }}h 内未生成对应 strm；处理前请确认 strm 插件本身正常
              </span>
              <v-spacer></v-spacer>
              <!-- 主动扫描：从**源端**出发反查缺 strm 的文件，因此不依赖「插件曾认为它
                   同步成功」—— 补上「历史上传失败、从未被观察过」的盲区。纯本地比对 -->
              <v-btn
                size="x-small"
                variant="tonal"
                color="primary"
                rounded="lg"
                :loading="strmScanning"
                :disabled="!statusData.strm_check_enabled"
                @click="scanStrm"
              >
                <v-icon start size="14">mdi-magnify-scan</v-icon>
                扫描缺 strm 的文件
              </v-btn>
              <!-- 一键处理全部：清单规模小时最实用，避免逐条点击确认 -->
              <v-btn
                v-if="strmSuspectCount"
                size="x-small"
                variant="tonal"
                color="warning"
                rounded="lg"
                :loading="itemLoading === 'strm:all'"
                :disabled="statusData.is_running"
                @click="retryAllStrmSuspects"
              >
                <v-icon start size="14">mdi-delete-restore</v-icon>
                全部删旧重传 ({{ strmSuspectCount }})
              </v-btn>
            </div>

            <!-- 扫描结果提示（含截断警告与两种成因的说明） -->
            <v-alert
              v-if="strmScanMsg"
              type="info"
              variant="tonal"
              density="compact"
              class="rounded-lg mb-2 text-body-2"
            >
              <div class="font-weight-medium" style="white-space: pre-line">{{ strmScanMsg }}</div>
            </v-alert>

            <div v-if="!strmSuspectCount" class="text-caption text-medium-emphasis mb-2">
              当前无疑似异常。若怀疑有文件上传失败但从未被观察过，点上方「扫描缺 strm 的文件」主动反查。
            </div>
            <div class="d-flex flex-column ga-2">
              <div v-for="key in strmPaged.slice" :key="'s-' + key" class="failed-item-card d-flex flex-column flex-sm-row align-stretch align-sm-center justify-sm-space-between rounded-xl pa-3 ga-2">
                <div class="list-row-main d-flex align-center overflow-hidden mr-sm-3 mr-0">
                  <v-checkbox
                    v-if="selectMode"
                    :model-value="selectedKeys.includes(key)"
                    density="compact"
                    hide-details
                    color="warning"
                    class="flex-shrink-0 mr-2"
                    @update:model-value="toggleSelect(key)"
                  ></v-checkbox>
                  <div class="overflow-hidden">
                    <div class="font-weight-bold text-body-2 text-warning text-truncate">{{ key }}</div>
                    <div class="text-caption text-medium-emphasis mt-0.5">
                      同步已报告成功，但宽限期内未见 strm 生成 —— 可能上传未真正完成
                    </div>
                  </div>
                </div>
                <div class="list-row-actions d-flex align-center flex-wrap ga-1 flex-shrink-0">
                  <v-chip size="x-small" color="warning" variant="flat" class="font-weight-bold">疑似异常</v-chip>
                  <v-btn
                    size="x-small"
                    variant="tonal"
                    color="warning"
                    rounded="lg"
                    class="px-2"
                    :loading="itemLoading === 'strm:' + key"
                    :disabled="statusData.is_running"
                    @click="retryStrmSuspect(key)"
                  >
                    <v-icon start size="14">mdi-delete-restore</v-icon>
                    删旧重传
                    <v-tooltip activator="parent" location="top">
                      删除 115 端该文件后立即重传（先删再传，绕过 CD2 视图假成功）
                    </v-tooltip>
                  </v-btn>
                </div>
              </div>
            </div>
            <!-- strm 疑似清单独立分页：与上方对账清单数据源不同、长度也不同，
                 共用页码会让两边互相串位，故单独维护 pageStrm -->
            <div v-if="strmPaged.pages > 1" class="pager-bar d-flex align-center justify-center flex-wrap ga-2 mt-3">
              <v-btn
                size="small" variant="text" rounded="lg" class="pager-btn"
                :disabled="strmPaged.page <= 1"
                @click="strmPaged.pageRef.value = strmPaged.page - 1"
              >
                <v-icon start size="16">mdi-chevron-left</v-icon>上一页
              </v-btn>
              <span class="text-caption text-medium-emphasis">
                第 <strong>{{ strmPaged.page }}</strong> / {{ strmPaged.pages }} 页 ·
                共 {{ strmPaged.total }} 条（每页 {{ PAGE_SIZE }} 条）
              </span>
              <v-btn
                size="small" variant="text" rounded="lg" class="pager-btn"
                :disabled="strmPaged.page >= strmPaged.pages"
                @click="strmPaged.pageRef.value = strmPaged.page + 1"
              >
                下一页<v-icon end size="16">mdi-chevron-right</v-icon>
              </v-btn>
            </div>
          </div>
        </div>

        <!-- 标签 3：已忽略清单 -->
        <div v-if="currentTab === 'ignored'">
          <div v-if="ignoredList.length" class="d-flex flex-column ga-2">
            <div v-for="(rule, idx) in ignoredPaged.slice" :key="'i-' + idx" class="queue-item-card d-flex flex-column flex-sm-row align-stretch align-sm-center justify-sm-space-between rounded-xl pa-3 ga-2">
              <div class="list-row-main overflow-hidden mr-sm-3 mr-0">
                <div class="font-weight-bold text-body-2 text-truncate">{{ rule.rule }}</div>
                <div class="text-caption text-medium-emphasis mt-0.5">
                  {{ rule.match === 'exact' ? '精确匹配' : '包含匹配' }}
                  · 加入于 {{ rule.created_at }}
                  <span v-if="rule.created_by"> · 操作人 {{ rule.created_by }}</span>
                </div>
              </div>
              <div class="list-row-actions d-flex align-center flex-wrap ga-1 flex-shrink-0">
                <v-chip size="x-small" color="secondary" variant="tonal" class="font-weight-bold">已忽略</v-chip>
                <v-btn icon size="x-small" variant="text" color="success" @click="removeIgnore(idx)">
                  <v-icon size="16">mdi-restore</v-icon>
                  <v-tooltip activator="parent" location="top">恢复对账</v-tooltip>
                </v-btn>
              </div>
            </div>
          </div>
          <!-- 分页条：三个标签共用，绑定各自页码 -->
          <div v-if="paged.pages > 1" class="pager-bar d-flex align-center justify-center flex-wrap ga-2 mt-3">
            <v-btn
              size="small" variant="text" rounded="lg" class="pager-btn"
              :disabled="paged.page <= 1"
              @click="paged.pageRef.value = paged.page - 1"
            >
              <v-icon start size="16">mdi-chevron-left</v-icon>上一页
            </v-btn>
            <span class="text-caption text-medium-emphasis">
              第 <strong>{{ paged.page }}</strong> / {{ paged.pages }} 页 ·
              共 {{ paged.total }} 条（每页 {{ PAGE_SIZE }} 条）
            </span>
            <v-btn
              size="small" variant="text" rounded="lg" class="pager-btn"
              :disabled="paged.page >= paged.pages"
              @click="paged.pageRef.value = paged.page + 1"
            >
              下一页<v-icon end size="16">mdi-chevron-right</v-icon>
            </v-btn>
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
  backfill_remaining: 0,
  missed_count: 0,
  missed_last_scan: 0,
  missed_scan_enabled: false,
  stale_count: 0,
  strm_suspects: {},
  strm_watching: 0,
  strm_grace_hours: 6,
  backfill_total: 0,
  rate_limit_enabled: true,
  upload_window_count: 0,
  upload_max_per_window: 500,
  upload_window_secs: 1800,
  upload_blocked_until: 0,
})

const ignoredList = ref([])

// 分页：每页固定条数。队列可能上百条，一次全渲染既卡顿又难浏览。
// 页码按标签分别记录，切换标签不会丢失各自的位置。
// Per-tab pagination state. The queue can hold hundreds of entries; rendering all
// of them hurts both performance and readability.
const PAGE_SIZE = 15
const pageQueue = ref(1)
const pageFailed = ref(1)
const pageIgnored = ref(1)
// strm 疑似清单与「对账异常」标签同屏，但数据源与长度都不同，页码必须独立
const pageStrm = ref(1)

// 批量选择 / 单条手动触发
const selectMode = ref(false)
const selectedKeys = ref([])
const itemLoading = ref('')
const batchSyncing = ref(false)
// 存量补传：扫描中状态
const backfillScanning = ref(false)
// strm 主动扫描：进度与结果提示
const strmScanning = ref(false)
const strmScanMsg = ref('')

const failedCount = computed(() =>
  (statusData.value.last_status?.missing_files?.length || 0) +
  (statusData.value.last_status?.corrupt_files?.length || 0)
)

// strm 疑似异常数量与 key 列表（交叉验证发现的上传可疑文件）
const strmSuspectCount = computed(() => Object.keys(statusData.value.strm_suspects || {}).length)

// 是否已为某个映射配置了 strm 目录。后端 /status 未返回 sync_pairs，故用
// 「开关开启」近似判定 —— 没配 strm_dir 时扫描会返回明确的失败提示，
// 比整个区块都不显示更容易让用户明白该怎么配置。
const strmConfigured = computed(() => statusData.value.strm_check_enabled !== false)
const strmSuspectKeys = computed(() => Object.keys(statusData.value.strm_suspects || {}))

// 选中项中有多少属于 strm 疑似清单。
// 用途：strm 项需要「先删旧再传」才能绕过 CD2 假成功，而普通条目绝不能删旧，
// 因此批量按钮必须按选中项的成分决定走哪条通道，不能只看当前在哪个标签页
// （勾选状态是跨分组保留的，用户可以在对账清单里勾选、再翻到别的分组）。
const strmSelectedCount = computed(
  () => selectedKeys.value.filter((k) => k in (statusData.value.strm_suspects || {})).length
)
const selectedStrmOnly = computed(
  () => selectedKeys.value.length > 0 && strmSelectedCount.value === selectedKeys.value.length
)

// 是否处于风控退避期（时间戳为未来时刻）
const isThrottled = computed(
  () => (statusData.value.upload_blocked_until || 0) * 1000 > Date.now()
)
const blockedMinutes = computed(() =>
  Math.max(1, Math.ceil(((statusData.value.upload_blocked_until || 0) * 1000 - Date.now()) / 60000))
)

const queueList = ref([])
let timer = null

// ---- 分页工具 ----
// 三个标签共用同一套切片/页码纠偏逻辑，只在外面绑定各自的页码 ref。
// Shared slicing helpers; each tab binds its own page ref.
function paginate(list, pageRef) {
  const total = list.length
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  // 数据变少（如同步成功后条目被移除）时页码可能越界，这里就地纠偏，
  // 否则用户会停留在空白页且无法自行返回
  const page = Math.min(Math.max(1, pageRef.value), pages)
  if (page !== pageRef.value) pageRef.value = page
  const start = (page - 1) * PAGE_SIZE
  // 一并带出 pageRef，模板里的翻页按钮才能作用于当前标签对应的页码
  return { total, pages, page, pageRef, slice: list.slice(start, start + PAGE_SIZE) }
}

// 对账异常标签的两类清单合成一个列表，才能让「每页 15 条」覆盖整体。
// missing/corrupt 用 kind 区分，渲染时按 kind 决定配色与按钮文案。
// Merge missing + corrupt into one list so the page size applies to the whole tab.
const failedEntries = computed(() => [
  ...(statusData.value.last_status?.missing_files || []).map((file) => ({ file, kind: 'missing' })),
  ...(statusData.value.last_status?.corrupt_files || []).map((file) => ({ file, kind: 'corrupt' })),
])

const queuePaged = computed(() => paginate(queueList.value, pageQueue))
const failedPaged = computed(() => paginate(failedEntries.value, pageFailed))
const ignoredPaged = computed(() => paginate(ignoredList.value, pageIgnored))
// strm 疑似清单不分页时列表可无限增长（strm 插件大面积漏生成时会成批出现），
// 与另外三个列表统一按 PAGE_SIZE 切片
const strmPaged = computed(() => paginate(strmSuspectKeys.value, pageStrm))

// 当前标签页的分页结果，供模板统一渲染底部页码条
const paged = computed(() => {
  if (currentTab.value === 'queue') return queuePaged.value
  if (currentTab.value === 'failed') return failedPaged.value
  return ignoredPaged.value
})

// 当前标签页可被勾选的条目 key 列表。
// ⚠️ 必须是**本页**条目而不是全部条目：批量选择以「页」为单位才符合直觉，
// 否则「全选本页」会选中用户看不见的条目，误同步风险很高。
const selectableItems = computed(() => {
  if (currentTab.value === 'queue') {
    return queuePaged.value.slice.map((it) => it.key)
  }
  if (currentTab.value === 'failed') {
    // strm 疑似清单与对账清单在同一个标签页内，故其 key 也算本页可勾选项，
    // 否则勾了 strm 条目却因不在集合里被「全选本页」清掉
    return [
      ...failedPaged.value.slice.map((it) => it.file),
      ...strmPaged.value.slice,
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

// 补传存量媒体：先本地扫描预览规模，用户确认后再启动
async function scanBackfill() {
  if (statusData.value.is_running) return
  backfillScanning.value = true
  actionMsg.value = '正在扫描本地存量媒体（不访问 115）...'
  try {
    const res = await props.api.get('plugin/Rsync115Sync/backfill_scan')
    if (!res || !res.success) {
      actionMsg.value = res?.message || '扫描失败'
      return
    }
    const { count, batch_size: batch, windows_needed: windows } = res.data || {}
    if (!count) {
      actionMsg.value = '没有需要补传的存量文件'
      return
    }
    // 明确告知代价：候选数 = 至少这么多次目标端 stat
    const ok = window.confirm(
      `发现 ${count} 个待补传文件（含同名字幕）。\n\n` +
      `补传将按每批 ${batch} 个、每个限流窗口分多轮自动推进，` +
      `预计需要约 ${windows} 个窗口（${windows} × ${Math.round((statusData.value.upload_window_secs || 1800) / 60)} 分钟）。\n\n` +
      `注意：每个候选文件至少产生一次 115 端校验请求，已存在的文件会被跳过而不会重传。\n\n` +
      `确定开始补传吗？`
    )
    if (!ok) {
      actionMsg.value = '已取消补传'
      return
    }
    const start = await props.api.post('plugin/Rsync115Sync/backfill_start', {})
    actionMsg.value = start?.message || '已启动补传'
    await fetchStatus()
  } catch (e) {
    actionMsg.value = '补传出错: ' + e.message
  } finally {
    backfillScanning.value = false
  }
}

// 清空补传队列
async function clearBackfill() {
  try {
    const res = await props.api.post('plugin/Rsync115Sync/backfill_clear', {})
    actionMsg.value = res?.message || '已取消补传'
    await fetchStatus()
  } catch (e) {
    actionMsg.value = '取消失败: ' + e.message
  }
}

// strm 疑似异常：确认后删旧重传（删除是破坏性操作，先弹确认框）
async function retryStrmSuspect(key) {
  const ok = window.confirm(
    `将对以下文件执行「删旧重传」：\n\n${key}\n\n` +
    `1. 先删除 115 端该文件（经挂载点删除，云端状态一并纠正）\n` +
    `2. 立即定向重传\n` +
    `3. 传完后自动复核 strm 是否生成\n\n` +
    `⚠️ 若是 strm 插件自身漏生成（误报），重传也是安全的：已同步的文件不会重复上传。\n\n确定继续吗？`
  )
  if (!ok) return
  itemLoading.value = 'strm:' + key
  try {
    const res = await props.api.post('plugin/Rsync115Sync/strm_retry', { keys: [key] })
    actionMsg.value = res?.message || (res?.success ? '已开始删旧重传' : '操作失败')
    await fetchStatus()
  } catch (e) {
    actionMsg.value = '重传出错: ' + e.message
  } finally {
    itemLoading.value = ''
  }
}

// 批量触发选中条目。
//
// 通道选择依据是「选中项的成分」而不是当前标签页：勾选状态跨分组保留，
// 用户在哪个标签页按下按钮都可能包含 strm 疑似项。两条后端通道的差异是：
//
//   /sync_item  不主动删旧。目标端缺失 → 直接补传；大小不符 → retry 分支
//               按大小条件清理残缺再传；大小一致且正常 → rsync --size-only
//               跳过（不传也不删）。**无法修复「大小一致但内容是坏的」**。
//   /strm_retry 主动删旧，且只要目标端存在就删（含大小一致的）。服务端另有
//               一道守卫，只接受已在 strm 疑似清单里的 key。
//
// 所以分流的实质不是「一个删一个不删」，而是「谁有权限删掉一个大小看起来
// 完全正常的文件」。这个判断系统只能从 strm 疑似清单得到 —— 纯看大小的话，
// 「坏得很彻底所以大小完全相同」与「好文件」无法区分。
async function batchSyncSelected() {
  if (!selectedKeys.value.length || statusData.value.is_running) return
  const keys = [...selectedKeys.value]
  const isStrm = selectedStrmOnly.value
  const isMixed = !isStrm && strmSelectedCount.value > 0

  // 混合选择时明确提示会被分流，避免用户以为「一个按钮一种行为」
  if (isMixed) {
    const ok = window.confirm(
      `选中 ${keys.length} 项中，有 ${strmSelectedCount.value} 项属于 strm 疑似异常。\n\n` +
      `提交后将自动分流：\n` +
      `• ${strmSelectedCount.value} 项走「删旧重传」：目标端那份「看起来正常」的文件\n` +
      `  实际是坏的（CD2 改名失败），只有先删掉才能让重传真正发生\n` +
      `• ${keys.length - strmSelectedCount.value} 项走普通定向重传：\n` +
      `  目标端缺失的直接补传，大小不符的先清理残缺再传，\n` +
      `  大小一致且正常的会由 rsync 自动跳过，不会被删除\n\n确定继续吗？`
    )
    if (!ok) return
  } else if (isStrm) {
    // 全部为 strm 项：删旧是破坏性操作，沿用单条操作的确认口径
    const ok = window.confirm(
      `将对选中的 ${keys.length} 个文件执行「删旧重传」：\n\n` +
      `1. 先删除 115 端这些文件（经挂载点删除，云端状态一并纠正）\n` +
      `2. 立即定向重传\n` +
      `3. 传完后自动复核 strm 是否生成\n\n` +
      `⚠️ 若是 strm 插件自身漏生成（误报），重传也是安全的：已同步的文件不会重复上传。\n\n确定继续吗？`
    )
    if (!ok) return
  }

  batchSyncing.value = true
  actionMsg.value = `正在批量触发 ${keys.length} 个文件...`
  try {
    // 路由分流：strm 疑似项走后端 /strm_retry（含删旧护栏），其余走 /sync_item。
    // 后端 /strm_retry 会对不在疑似清单内的 key 二次校验并忽略，这里有前端分流兜底。
    const strmKeys = keys.filter((k) => k in (statusData.value.strm_suspects || {}))
    const plainKeys = keys.filter((k) => !(k in (statusData.value.strm_suspects || {})))

    const messages = []
    if (strmKeys.length) {
      const res = await props.api.post('plugin/Rsync115Sync/strm_retry', { keys: strmKeys })
      messages.push(res?.message || (res?.success ? `已删旧重传 ${strmKeys.length} 个` : '删旧重传失败'))
    }
    if (plainKeys.length) {
      const res = await props.api.post('plugin/Rsync115Sync/sync_item', { keys: plainKeys })
      messages.push(res?.message || (res?.success ? `已触发 ${plainKeys.length} 个` : '批量触发失败'))
    }
    actionMsg.value = messages.join('；') || '未提交任何条目'
    selectedKeys.value = []
    await fetchStatus()
  } catch (e) {
    actionMsg.value = '批量触发出错: ' + e.message
  } finally {
    batchSyncing.value = false
  }
}

// 主动扫描缺 strm 的文件：从源端出发反查，不依赖「插件曾认为它同步成功」，
// 因此能发现历史上传失败、从未进入过观察期的盲区文件。
async function scanStrm() {
  if (strmScanning.value) return
  strmScanning.value = true
  strmScanMsg.value = '正在扫描源端并逐个比对 strm…'
  try {
    const res = await props.api.post('plugin/Rsync115Sync/strm_scan', {})
    if (res && res.success) {
      const d = res.data || {}
      let msg = `已检查 ${d.checked || 0} 个文件，缺 strm ${d.found || 0} 个，新增疑似 ${d.added || 0} 个。`
      if (d.truncated) {
        msg += `\n⚠️ 已达到单次上限，结果被截断 —— 数量这么大通常说明 strm 插件本身没在工作，请先确认它的开关与媒体识别是否正常。`
      }
      msg += `\n💡 缺 strm 可能是「从未上传的存量文件」（应走补传），也可能是「上传了但 CD2 假成功」（用删旧重传），请先判断再处理。`
      strmScanMsg.value = msg
    } else {
      strmScanMsg.value = res?.message || '扫描失败'
    }
    await fetchStatus()
  } catch (e) {
    strmScanMsg.value = '扫描出错: ' + e.message
  } finally {
    strmScanning.value = false
  }
}

// 一键处理全部 strm 疑似异常（清单规模小时最实用，省去逐条确认）
async function retryAllStrmSuspects() {
  const keys = [...strmSuspectKeys.value]
  if (!keys.length || statusData.value.is_running) return
  const ok = window.confirm(
    `将对全部 ${keys.length} 个 strm 疑似异常文件执行「删旧重传」：\n\n` +
    `1. 先删除 115 端这些文件（经挂载点删除，云端状态一并纠正）\n` +
    `2. 立即定向重传（仍受批次上限与限流配额约束，可能需要多轮）\n` +
    `3. 传完后自动复核 strm 是否生成\n\n` +
    `⚠️ 若是 strm 插件自身漏生成（误报），重传也是安全的：已同步的文件不会重复上传。\n\n确定继续吗？`
  )
  if (!ok) return
  itemLoading.value = 'strm:all'
  actionMsg.value = `正在对 ${keys.length} 个疑似异常执行删旧重传...`
  try {
    const res = await props.api.post('plugin/Rsync115Sync/strm_retry', { keys })
    if (res && res.success) {
      actionMsg.value = res.message || `已删除并开始重传 ${keys.length} 个文件`
    } else {
      // 失败时保留 actionMsg 原文（例如部分文件删不掉），不要笼统覆盖
      actionMsg.value = res?.message || '删旧重传失败'
    }
    await fetchStatus()
  } catch (e) {
    actionMsg.value = '删旧重传出错: ' + e.message
  } finally {
    itemLoading.value = ''
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
    // 清理已不存在条目的勾选状态，避免提交到已消失的文件。
    // strm 疑似清单也纳入存活集合：它同样是可勾选来源，漏掉会让用户
    // 勾选后一刷新（30 秒轮询）就被静默清除
    if (selectedKeys.value.length) {
      const alive = new Set([
        ...queueList.value.map((it) => it.key),
        ...(statusData.value.last_status?.missing_files || []),
        ...(statusData.value.last_status?.corrupt_files || []),
        ...Object.keys(statusData.value.strm_suspects || {}),
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
  /* 桌面端外边距。原为内联 style 且带 !important，
     导致媒体查询无法覆盖；现收敛到此处作为唯一来源，便于移动端收窄 */
  padding: 18px 22px !important;
}
.page-main-card {
  background: rgb(var(--v-theme-surface, 255, 255, 255));
  width: 100%;
}
.header-surface {
  background: linear-gradient(135deg, rgba(var(--v-theme-primary, 24, 103, 192), 0.08) 0%, rgba(var(--v-theme-primary, 24, 103, 192), 0.02) 100%);
}
/* 顶栏标题与副标题：仅调整外边距，不覆盖 text-caption 的小字号行高，
   保证 12px 中文文本的可读性 */
.header-card-item .header-subtitle {
  margin-top: 6px;
}
/* PopUp 内 Title 与下方 Content 的间距必须用 margin 实现：
   宿主默认给 .v-card-item + .v-card-text 设置了 padding-block-start: 0 !important，
   内容区顶部内边距被强制归零，看板首行三个数据卡片的顶部圆角因此被裁掉（实测缺 radius）。
   故此处：padding-block-start 显式归一化，间距则由 margin-top 提供。

   为什么必须带 !important：宿主该声明本身即 !important，级联顺序是
   重要度 > 权重 > 源码顺序，普通声明无论权重多高都赢不了 !important，
   必须同样以 !important + 更高权重才能覆盖。
   又因该属性非继承、unset 对非继承属性求值等同 initial(0px)，
   在本页显示效果上通常与宿主一致；但显式声明可避免宿主后续调整该值
   （如改成非 0）时圆角问题复现，属稳定性加固。
   经真实页面调试确认，勿凭「理论等价」删除。 */
.header-card-item + .v-card-text {
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
/* 分页条：与列表用虚线分隔，弱化存在感，避免抢占内容注意力 */
.pager-bar {
  border-top: 1px dashed rgba(var(--v-theme-on-surface, 0, 0, 0), 0.14);
  padding-top: 12px;
}
.pager-btn {
  /* 与说明文字基线对齐，避免按钮内图标把行高撑开 */
  letter-spacing: normal;
}

/* ===== 移动端适配 =====
   宿主移动端可用宽度很窄，且卡片内还有 pa-3/pa-4 内边距，
   原先一排横向按钮必然溢出到卡片外。以下按「窄屏纵向堆叠、宽屏恢复横排」处理，
   断点沿用 Vuetify 的 sm（600px），与模板里的 flex-sm-row 保持一致。 */
@media (max-width: 599.98px) {
  /* 移动端收窄外层留白，把宽度还给内容（外层 + 卡片内层共省下约 36px） */
  .plugin-page {
    padding: 10px 12px !important;
  }
  /* 顶栏按钮"超出范围"的根因在这里：
     Vuetify 的 .v-card-item 是 grid 布局，列宽为 max-content auto max-content，
     append 列固定按 max-content 计算、不会收缩，窄屏下右侧按钮组被顶出卡片，
     再由外层 .page-main-card 的 overflow-hidden 裁掉，看起来就是按钮超出了范围。
     把 append 列改成 minmax(0, max-content)：优先按内容宽度，宽度不足时允许收缩，
     收缩后按钮组依 .header-append 的 flex-wrap 换行，从而始终留在卡片内。
     必须用 :deep()：.v-card-item__append 由 Vuetify 组件渲染，scoped 选择器匹配不到 */
  :deep(.v-card-item) {
    grid-template-columns: max-content minmax(0, auto) minmax(0, max-content);
  }
  :deep(.v-card-item__content) {
    min-width: 0;
  }
  .body-surface {
    padding-left: 10px !important;
    padding-right: 10px !important;
  }
  /* 顶栏右侧按钮组：允许换行并右对齐，避免刷新/配置/关闭三个按钮挤出卡片 */
  .header-append {
    flex-wrap: wrap;
    justify-content: flex-end;
  }
  /* 操作工具条：按钮组纵向铺满，按钮本身在窄屏下占满整行更好点按 */
  .action-strip-row {
    align-items: stretch;
  }
  .action-group {
    width: 100%;
  }
  .action-group > .v-btn {
    flex: 1 1 auto;
  }
  /* 操作反馈文字可能很长（含文件数），允许换行而不是把同行按钮顶出去 */
  .action-msg {
    width: 100%;
    margin-right: 0 !important;
    white-space: normal;
    word-break: break-word;
  }
  /* 列表行在窄屏改为纵向堆叠后，左侧信息区需占满整行 */
  .list-row-main {
    width: 100%;
  }
  /* 右侧操作区占满整行并允许换行；
     注：flex-shrink 在纵向堆叠下作用于纵轴，此处无需覆盖，保持工具类的 flex-shrink-0 即可 */
  .list-row-actions {
    width: 100%;
    flex-wrap: wrap;
  }
  /* 批量辅助条说明文字：占满剩余宽度并允许折行 */
  .batch-hint {
    width: 100%;
    white-space: normal;
    word-break: break-word;
  }
}
</style>
