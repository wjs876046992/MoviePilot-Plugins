<template>
  <div class="plugin-page">
    <v-card class="d-flex flex-column h-100 radius-lg overflow-hidden page-main-card" elevation="0" variant="outlined">

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
            <v-btn icon variant="tonal" color="primary" size="small" class="radius-sm mr-1" @click="fetchStatus" :loading="loading">
              <v-icon size="18">mdi-refresh</v-icon>
              <v-tooltip activator="parent" location="bottom">刷新状态</v-tooltip>
            </v-btn>
            <v-btn color="primary" radius-sm variant="outlined" size="small" class="px-3 font-weight-medium mr-1" @click="notifySwitch">
              <v-icon start size="16">mdi-cog-outline</v-icon>
              配置
            </v-btn>
            <v-btn icon variant="text" size="small" class="radius-sm close-btn text-medium-emphasis" @click="notifyClose">
              <v-icon size="18">mdi-close</v-icon>
              <v-tooltip activator="parent" location="bottom">关闭</v-tooltip>
            </v-btn>
          </div>
        </template>
      </v-card-item>

      <!-- 主体内容 -->
      <v-card-text class="pa-4 flex-grow-1 overflow-y-auto body-surface">
        <!-- 核心指标卡片（两行，共 7 个统计数字）
             ⚠️ 第一行三个卡片有承重的布局约束（border-top 曾整条不可见），
             见样式区 .strm-stat-row 的说明与 test_dashboard_stat_row_border.py。
             第一行**必须保持是这一行**（它是滚动容器顶边对齐的那一行）。 -->
        <v-row class="mb-2 strm-stat-row">
          <v-col cols="12" sm="4" class="pa-1">
            <div class="stat-card stat-info radius-lg pa-3 text-center">
              <div class="text-h5 font-weight-black text-info">{{ statusData.cooling_count || 0 }}</div>
              <div class="text-caption text-medium-emphasis mt-1">冷却缓冲中 (设定 {{ statusData.delay_hours || 4 }}h)</div>
            </div>
          </v-col>
          <v-col cols="12" sm="4" class="pa-1">
            <div class="stat-card stat-primary radius-lg pa-3 text-center">
              <div class="text-h5 font-weight-black text-primary">{{ statusData.ready_count || 0 }}</div>
              <div class="text-caption text-medium-emphasis mt-1">冷却就绪待传输</div>
            </div>
          </v-col>
          <v-col cols="12" sm="4" class="pa-1">
            <div class="stat-card stat-error radius-lg pa-3 text-center">
              <div class="text-h5 font-weight-black text-error">
                {{ (statusData.last_status?.missing_files?.length || 0) + (statusData.last_status?.corrupt_files?.length || 0) }}
              </div>
              <div class="text-caption text-medium-emphasis mt-1">待重试缺失/残缺文件</div>
            </div>
          </v-col>
        </v-row>

        <!-- 第二行：把"入库发现"与"上传进度"这两件此前只能在提示条里读到的事
             也做成数字 —— 与上面那行同一个视觉语言，扫一眼就够，不必读句子。
             刻意选的都是**用户会拿来判断"还要不要做什么"**的量：
               · 扫描游标是否在走 → 发现层活着没有（不流动 = 新文件不会被发现）
               · 待观察 / 疑似 → strm 交叉验证要不要我处理
               · 补传剩余 → 还有多少存量在排队
               · 窗口用量 → 是不是被限流卡住了（到上限就只剩等待） -->
        <v-row class="mb-3 stat-row-secondary">
          <v-col cols="6" sm="3" class="pa-1">
            <div class="stat-card stat-muted radius-lg pa-2 text-center">
              <div class="text-subtitle-1 font-weight-black">
                {{ sourceScanAgoShort }}
              </div>
              <div class="text-caption text-medium-emphasis">上次源端扫描</div>
            </div>
          </v-col>
          <v-col cols="6" sm="3" class="pa-1">
            <div class="stat-card stat-warning radius-lg pa-2 text-center">
              <div class="text-subtitle-1 font-weight-black text-warning">{{ statusData.strm_watching || 0 }}</div>
              <div class="text-caption text-medium-emphasis">strm 观察中</div>
            </div>
          </v-col>
          <v-col cols="6" sm="3" class="pa-1">
            <div class="stat-card stat-warning radius-lg pa-2 text-center">
              <div class="text-subtitle-1 font-weight-black text-warning">{{ strmSuspectCount }}</div>
              <div class="text-caption text-medium-emphasis">strm 疑似异常</div>
            </div>
          </v-col>
          <v-col cols="6" sm="3" class="pa-1">
            <div class="stat-card stat-muted radius-lg pa-2 text-center">
              <div class="text-subtitle-1 font-weight-black">
                {{ statusData.backfill_remaining || 0 }}<span
                  v-if="statusData.backfill_total" class="text-caption text-medium-emphasis">/{{ statusData.backfill_total }}</span>
              </div>
              <div class="text-caption text-medium-emphasis">存量补传剩余</div>
            </div>
          </v-col>
        </v-row>

        <!-- 补传 / 限流 / 源端扫描提示：用通俗文字说明“为什么慢、还要多久” -->
        <v-alert
          v-if="statusData.backfill_remaining || isThrottled || statusData.stale_count || statusData.strm_watching || sourceScanProblem"
          :type="isThrottled || sourceScanProblem ? 'warning' : 'info'"
          variant="tonal"
          density="compact"
          class="radius-sm mb-3 text-body-2"
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
          <!-- 源端扫描是入库发现的**主通道**，它停摆 = 新文件不会被发现。
               因此这里显示的不是"进度"而是"健康状况"：游标落后多久。
               一行数字就能区分「扫描没跑」与「扫描跑了但没新文件」。 -->
          <div v-if="sourceScanProblem" class="font-weight-medium">
            🔍 源端扫描已 <strong>{{ sourceScanAgoText }}</strong> 未推进 ——
            新入库的文件不会被发现。请检查「源端扫描入库」开关是否开启、映射源目录是否可读，
            或查看日志中最近一条「源端扫描」记录。
          </div>
          <div v-if="statusData.strm_watching">
            📺 strm 交叉验证进行中：<strong>{{ statusData.strm_watching }}</strong> 个文件处于观察期，
            {{ statusData.strm_grace_minutes }} 分钟内未生成对应 .strm 才会被标记为「疑似上传异常」，
            属正常等待，无需处理。
          </div>
        </v-alert>

        <!-- Webhook 入库运行态（第二来源）：只在**收到过请求**时才出现。
             平时不占位 —— 绝大多数用户走的是宿主的整理事件，给他们看一块永远
             是 0 的面板只会让人怀疑自己配错了什么。

             「收到 / 入队 / 平台解析入口到达 / 被拒 / 未识别」这组数字本身就是诊断结论：
             全为 0 说明请求没到；claimed>0 而 received 少说明到了但没认领；
             received>0 而入队=0 且未识别>0 说明字段名对不上。
             与「last_payload_shape」配合，用户不必翻日志、不必来回问。

             注：此处曾有一块「最近报文（含值）」的样本区，按要求移除（连带后端采集）。
             完整报文值属于开发期对齐字段用的信息，不该常驻看板并持续落盘。 -->
        <v-alert
          v-if="webhookVisible"
          :type="webhookStat.rejected > 0 ? 'warning' : 'info'"
          variant="tonal"
          density="compact"
          class="radius-sm mb-3 text-body-2"
        >
          <div class="font-weight-medium">
            🪝 Webhook 入库：
            <template v-if="webhookStat.received > 0 || webhookStat.claimed > 0">
              收到 <strong>{{ webhookStat.received }}</strong> 条 ·
              入队 <strong>{{ webhookStat.ingested }}</strong> 个文件 ·
              🎯 平台解析入口到达 <strong>{{ webhookStat.claimed }}</strong> 条
            </template>
            <template v-else>
              暂无请求
            </template>
          </div>
          <!-- 三行诊断各对应一种「静默无反应」，数字自己就能指出断点在哪：
               · claimed>0 而 received 少 → 到了解析入口却没认领（路径不在映射内 / 未启用）
               · rejected>0          → 报文不合入库类事件，或路径不在任何映射内
               · unrecognized>0      → 到了、字段名没对上，需要扩展候选字段表
               原先这层解释由下方「最近报文」样本承担，样本已按要求移除 —— 因此
               未识别时保留字段结构摘要：它是缩小范围用的最小线索，而样本的完整
               值形态属于开发期对齐字段用的信息，不该常驻看板。 -->
          <div v-if="webhookStat.rejected > 0" class="mt-1">
            ⛔ 被拒 <strong>{{ webhookStat.rejected }}</strong> 条（报文不合入库类事件、
            或路径不在任何映射内，插件未认领），具体是哪一条见日志。
          </div>
          <div v-if="webhookStat.unrecognized > 0" class="mt-1">
            ⚠️ 有 <strong>{{ webhookStat.unrecognized }}</strong> 条取不到入库路径 ——
            说明请求到了、但字段名没对齐，需要扩展候选字段表。
            <template v-if="webhookStat.last_payload_shape">
              最近报文的字段结构：<code>{{ webhookStat.last_payload_shape }}</code>
            </template>
          </div>
        </v-alert>

        <!-- 入库闸门丢弃分布：**只在真的丢过东西时出现**。
             这一块是补上一个此前的盲区 —— 被扩展名白名单挡下的文件原先只写
             debug 日志，看板上完全没有痕迹，于是「某一类文件 100% 被丢弃」
             可以潜伏多个版本（音频就是这样全丢的）。
             显示的是累计值，不随重载清零，否则问题会再次隐形。 -->
        <v-alert
          v-if="skippedExtRows.length"
          type="warning"
          variant="tonal"
          density="compact"
          class="radius-sm mb-3 text-body-2"
        >
          <div class="font-weight-medium">
            ⏭ 有文件因<b>扩展名不在同步白名单</b>被跳过（累计）
          </div>
          <div class="mt-1">
            <span v-for="(row, i) in skippedExtRows" :key="row.ext">
              <template v-if="i > 0"> · </template>
              <code>{{ row.label }}</code> {{ row.count }} 个
            </span>
          </div>
          <div class="mt-1">
            如需同步这些类型，请到配置页把它们加入「同步的扩展名」；
            若确实不需要（如 .nfo、.jpg），忽略本提示即可。
          </div>
        </v-alert>

        <!-- 快捷操作工具条 -->
        <div class="action-strip radius-lg pa-3 mb-4">
          <div class="action-strip-row d-flex flex-column flex-sm-row align-stretch align-sm-center justify-sm-space-between ga-2">
            <div class="action-group d-flex align-center flex-wrap ga-2">
              <!-- 「立即运行一次」= 不等两个 cron：立刻扫一次源端 + 跑一轮就绪同步。
                   刻意**不**绕过冷却/限流/批次上限 —— 冷却期的现职是"等文件写完"，
                   绕过它会把半截文件传给 115（§3.10 的云端残留）。
                   要立刻传某个已冷却的文件，用列表里的单条「立即同步」。 -->
              <v-btn color="success" variant="flat" size="small" radius-sm @click="runNow" :loading="runningNow" :disabled="statusData.is_running">
                <v-icon start size="16">mdi-flash</v-icon>
                立即运行一次
                <v-tooltip activator="parent" location="top">
                  不等扫描与同步的 cron，立刻扫一次源端并跑一轮就绪同步。<br>
                  冷却时长、限流与批次上限照常生效 —— 冷却中的文件不会被提前上传。
                </v-tooltip>
              </v-btn>
              <v-btn color="primary" variant="tonal" size="small" radius-sm @click="triggerSync" :loading="syncing" :disabled="statusData.is_running">
                <v-icon start size="16">mdi-play</v-icon>
                同步已就绪媒体
              </v-btn>
              <v-btn color="warning" variant="tonal" size="small" radius-sm @click="triggerRetry" :loading="retrying" :disabled="statusData.is_running || (!statusData.last_status?.missing_files?.length && !statusData.last_status?.corrupt_files?.length)">
                <v-icon start size="16">mdi-refresh</v-icon>
                定向重试失败文件
              </v-btn>
              <v-btn color="info" variant="tonal" size="small" radius-sm @click="scanBackfill" :loading="backfillScanning" :disabled="statusData.is_running">
                <v-icon start size="16">mdi-database-arrow-up-outline</v-icon>
                补传存量媒体
                <v-tooltip activator="parent" location="top">
                  扫描本地存量媒体（含同名字幕）并分批补传；只读源端目录，不遍历 115
                </v-tooltip>
              </v-btn>
              <v-btn v-if="statusData.backfill_remaining" color="error" variant="text" size="small" radius-sm @click="clearBackfill" :disabled="statusData.is_running">
                <v-icon start size="16">mdi-cancel</v-icon>
                取消补传
              </v-btn>
            </div>
            <div class="action-group d-flex align-center flex-wrap ga-2">
              <!-- ⚠️ 走 plainText + pre-wrap：后端文案是**纯文本**（同一字符串也发到
                   聊天渠道，因此不能用 Markdown），但换行必须显式保留 ——
                   否则窗口内探测、删除拦截这类多段说明会被浏览器折叠成一整行，
                   用户看到的就是「…传不上去）：• 9KG:… 也就是说云端很可能是好的…」
                   这种挤成一坨的文本。Vue 的 {{ }} 是文本插值，自动转义，无注入风险。 -->
              <div
                v-if="actionMsg"
                class="text-caption font-weight-bold text-primary mr-1 action-msg"
                style="white-space: pre-wrap"
              >{{ plainText(actionMsg) }}</div>
              <!-- 批量选择模式开关 -->
              <v-btn
                v-if="currentTab !== 'ignored'"
                size="small"
                variant="tonal"
                :color="selectMode ? 'error' : 'secondary'"
                radius-sm
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
                radius-sm
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
              <v-btn
                v-if="selectMode && strmSelectedCount"
                size="small"
                variant="tonal"
                color="secondary"
                radius-sm
                :loading="batchSyncing"
                :disabled="!selectedKeys.length || statusData.is_running"
                @click="ignoreStrmSuspects(selectedKeys.filter((k) => k in (statusData.strm_suspects || {})))"
              >
                <v-icon start size="16">mdi-eye-off-outline</v-icon>
                忽略选中 ({{ strmSelectedCount }})
                <v-tooltip activator="parent" location="top" max-width="320">
                  将选中的 strm 疑似条目以「精确匹配」加入忽略规则并移出清单，
                  之后不再报告。恢复方式：到「已忽略」清单删除对应规则。
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
          <v-tab value="strm">
            <v-icon start size="16">mdi-television-classic-off</v-icon>
            strm 疑似异常 ({{ strmSuspectCount }})
          </v-tab>
          <v-tab value="ignored">
            <v-icon start size="16">mdi-eye-off-outline</v-icon>
            已忽略 ({{ ignoredList.length }})
          </v-tab>
        </v-tabs>

        <!-- 标签 1：延迟冷却队列 -->
        <div v-if="currentTab === 'queue'">
          <div v-if="queueList.length" class="d-flex flex-column ga-2">
            <div v-for="item in queuePaged.slice" :key="item.key" class="queue-item-card d-flex flex-column flex-sm-row align-stretch align-sm-center justify-sm-space-between radius-lg pa-3 ga-2">
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
                  radius-sm
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
              size="small" variant="text" radius-sm class="pager-btn"
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
              size="small" variant="text" radius-sm class="pager-btn"
              :disabled="paged.page >= paged.pages"
              @click="paged.pageRef.value = paged.page + 1"
            >
              下一页<v-icon end size="16">mdi-chevron-right</v-icon>
            </v-btn>
          </div>
          <!-- 空态显式绑定清单长度：不要用 v-else 挂在分页条上 —— 那会让
               「单页数据」时同时显示条目与空态（已忽略标签曾因此自相矛盾） -->
          <div v-if="!queueList.length" class="empty-box d-flex flex-column align-center justify-center py-10 px-4 radius-lg text-center">
            <v-icon size="32" color="primary" class="mb-2">mdi-check-circle-outline</v-icon>
            <div class="text-caption font-weight-bold text-medium-emphasis">暂无正在冷却中的媒体文件</div>
          </div>
        </div>

        <!-- 标签 2：对账异常与失败清单 -->
        <div v-if="currentTab === 'failed'">
          <div v-if="failedCount" class="d-flex flex-column ga-2">
            <!-- 缺失未同步 + 大小残缺：合并为一个列表以便统一分页 -->
            <div v-for="entry in failedPaged.slice" :key="entry.kind + ':' + entry.file" class="failed-item-card d-flex flex-column flex-sm-row align-stretch align-sm-center justify-sm-space-between radius-lg pa-3 ga-2">
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
                  radius-sm
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
              size="small" variant="text" radius-sm class="pager-btn"
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
              size="small" variant="text" radius-sm class="pager-btn"
              :disabled="paged.page >= paged.pages"
              @click="paged.pageRef.value = paged.page + 1"
            >
              下一页<v-icon end size="16">mdi-chevron-right</v-icon>
            </v-btn>
          </div>
          <div v-if="!failedCount" class="empty-box d-flex flex-column align-center justify-center py-10 px-4 radius-lg text-center">
            <v-icon size="32" color="success" class="mb-2">mdi-shield-check</v-icon>
            <div class="text-caption font-weight-bold text-medium-emphasis">冷却队列与待重试文件经对账全部一致，零缺失零残缺！</div>
          </div>

        </div>

        <!-- 标签 3：strm 疑似上传异常（判据与对账完全不同：来源是 strm 插件的视角，
             处理方式也不同 —— 前者走普通重传，这里必须删旧重传） -->
        <div v-if="currentTab === 'strm'">
<!-- 有配置 strm 目录就渲染本区（即使清单为空）—— 否则用户找不到「主动扫描」
               入口，而扫描正是清单为空时最需要的功能（发现从未被观察过的坏文件） -->
          <div v-if="strmConfigured" class="mt-4">
            <div class="d-flex align-center flex-wrap ga-2 mb-2">
              <v-icon size="18" color="warning">mdi-television-classic-off</v-icon>
              <span class="font-weight-bold text-body-2">strm 疑似上传异常 ({{ strmSuspectCount }})</span>
              <span class="text-caption text-medium-emphasis">
                观察期 {{ statusData.strm_grace_minutes }} 分钟内未生成对应 strm；处理前请确认 strm 生成侧本身正常。
                仅视频文件参与（字幕/图片/元数据不会有 strm，不纳入监控）
              </span>
              <!-- 依赖标注：本区绝大多数能力自包含，只有「先尝试生成」要外部助手。
                   不标出来，用户会误以为整个 strm 功能都依赖 P115StrmHelper。 -->
              <v-chip size="x-small" variant="tonal" color="success" class="font-weight-bold">
                观察/扫描/重传 不依赖插件
              </v-chip>
              <v-spacer></v-spacer>
              <!-- 主动扫描：从**源端**出发反查缺 strm 的文件，因此不依赖「插件曾认为它
                   同步成功」—— 补上「历史上传失败、从未被观察过」的盲区。纯本地比对 -->
              <v-btn
                size="x-small"
                variant="tonal"
                color="primary"
                radius-sm
                :loading="strmScanning"
                :disabled="!statusData.strm_check_enabled"
                @click="scanStrm"
              >
                <v-icon start size="14">mdi-magnify-scan</v-icon>
                扫描缺 strm 的文件
              </v-btn>
              <!-- 清理无效条目：非视频 / 已忽略 / 源端已删 / 映射取消验证。
                   历史版本产生过一批永远处理不掉的脏条目（例如 jpg/nfo 被判成疑似），
                   靠它一次性清掉，不必手工改插件数据文件 -->
              <v-btn
                v-if="strmSuspectCount"
                size="x-small"
                variant="text"
                color="secondary"
                radius-sm
                :loading="itemLoading === 'strm:prune'"
                @click="pruneStrmSuspects"
              >
                <v-icon start size="14">mdi-broom</v-icon>
                清理无效项
                <v-tooltip activator="parent" location="top">
                  移除已不可能恢复正常的条目：非视频文件（字幕/图片不会生成 strm）、
                  已命中忽略规则、源端文件已删除、所属映射已取消 strm 验证
                </v-tooltip>
              </v-btn>
              <!-- 先尝试补生成 strm：疑似有两种成因，处理成本差好几个数量级 ——
                   strm 助手漏生成（重新生成指针即可）与 CD2 假成功（必须删旧重传）。
                   两者在插件视角完全无法区分，但花一次助手侧目录遍历就能判别，
                   大概率直接免掉整轮删除重传。因此它排在「删旧重传」**之前**。
                   ⚠️ 不可用时的原因**不能只放 tooltip**：Vuetify 的 disabled 元素
                   不派发鼠标事件，tooltip 永远不会弹出 —— 用户只能看到一个灰按钮，
                   完全不知道要配什么。原因必须直接显示在按钮旁边。 -->
              <v-btn
                v-if="strmSuspectCount"
                size="x-small"
                variant="tonal"
                color="success"
                radius-sm
                :loading="itemLoading === 'strm:gen'"
                :disabled="statusData.is_running || !helperReady"
                @click="generateStrm"
              >
                <v-icon start size="14">mdi-file-refresh-outline</v-icon>
                先尝试生成 strm ({{ strmSuspectCount }})
                <v-tooltip v-if="helperReady" activator="parent" location="top" max-width="360">
                  请 115 网盘 STRM 助手按这些文件所在的网盘目录重新生成一次 .strm。<br>
                  成功后说明此前只是助手漏生成，<b>无需删旧重传</b>；<br>
                  若生成后仍无 strm，则云端确实缺该文件，再做删除重传。<br>
                  比直接删旧重传安全，成本也低得多。<br>
                  <b>本插件唯一依赖 P115StrmHelper 的功能</b>；右侧「删旧重传」不依赖它。
                </v-tooltip>
                <!-- 依赖标记常驻显示：让用户不点也知道这一项与旁边那些不同 -->
                <v-icon size="12" class="ml-1" color="info">mdi-link-variant</v-icon>
              </v-btn>
              <!-- 一键处理全部：清单规模小时最实用，避免逐条点击确认 -->
              <v-btn
                v-if="strmSuspectCount"
                size="x-small"
                variant="tonal"
                color="warning"
                radius-sm
                :loading="itemLoading === 'strm:all'"
                :disabled="statusData.is_running"
                @click="retryAllStrmSuspects"
              >
                <v-icon start size="14">mdi-delete-restore</v-icon>
                全部删旧重传 ({{ strmSuspectCount }})
              </v-btn>
            </div>

            <!-- 补生成不可用时的说明。
                 必须是**常驻可见**的文案而不是 tooltip：disabled 按钮不响应鼠标，
                 tooltip 弹不出来；而用户最需要的恰恰是「为什么点不了、我该配什么」。
                 同时给出可复制的配置指引，避免只报「不可用」让人无从下手。 -->
            <v-alert
              v-if="strmSuspectCount && !helperReady"
              type="warning"
              variant="tonal"
              density="compact"
              class="radius-sm mb-2 text-body-2"
            >
              <div class="font-weight-medium mb-1">
                「先尝试生成 strm」当前不可用：{{ helperReason }}
              </div>
              <div class="text-caption">
                配好即可用它免掉整轮删除重传（生成成功 ⇒ 只是助手漏生成，无需重传）：
                <br>① 在本插件<b>配置页</b>为该映射填写「<b>网盘目录</b>」——
                115 网盘里的真实路径（如 <code>/HomeTheater/TV</code>），不是 CD2 挂载路径；
                <br>② 该路径还需已配在 P115StrmHelper 的「<b>全量同步路径</b>」里
                （助手只接受它这个列表中的路径）。
                <br>这只是<b>可选的增强</b>：不配也不影响其它任何能力 ——
                「扫描缺 strm 的文件」「清理无效项」「删旧重传」以及整条交叉验证链路
                都由本插件独立完成，不依赖任何外部插件。
              </div>
            </v-alert>

            <!-- 扫描结果提示（含截断警告与两种成因的说明） -->
            <v-alert
              v-if="strmScanMsg"
              type="info"
              variant="tonal"
              density="compact"
              class="radius-sm mb-2 text-body-2"
            >
              <div class="font-weight-medium" style="white-space: pre-wrap">{{ plainText(strmScanMsg) }}</div>
            </v-alert>

            <!-- 观察期明细：这些文件刚同步成功、还在等 strm 生成（宽限期内），
                 属正常等待 —— 展示出来是为了让用户知道「谁在等、还要等多久」。

                 观察期里有两类条目，来源不同、等的对象也不同：
                   · 刚同步成功 → 等刮削/入库传播，窗口 = 宽限期配置值
                   · 已请求助手补生成 → 等助手遍历云端目录，窗口 = 补生成窗口
                 两者的「还要等多久」必须按各自的窗口算（entry.clock 决定），
                 否则同一批条目会显示成互相矛盾的剩余时间。

                 ⚠️ 只放**只读**的「检查」按钮，不放删旧重传：后者会诱导用户删掉
                 刚传好的文件、白耗一次删除 API 与重传配额。当初拒绝在观察期放
                 操作按钮，拒的正是这类破坏性操作；「检查一下 strm 出来没有」
                 纯本地读取、零副作用，没有这个风险，而且用户常常**已经知道**
                 strm 出来了（刚跑完生成任务），却只能干等下一轮巡检（最长 30 分钟）。
                 补生成之后的等待尤其需要这个按钮：助手是异步长任务，用户想知道
                 「到底出来了没」只能靠它。 -->
            <div v-if="strmWatchingEntries.length" class="d-flex align-center flex-wrap ga-2 mb-2">
              <span class="text-caption text-medium-emphasis">
                观察期 {{ strmWatchingEntries.length }} 个文件
              </span>
              <v-btn
                size="x-small"
                variant="text"
                color="primary"
                radius-sm
                :loading="itemLoading === 'strmchk:all'"
                @click="checkAllWatching"
              >
                <v-icon start size="14">mdi-refresh</v-icon>
                立即检查全部
                <v-tooltip activator="parent" location="top" max-width="320">
                  立刻比对这 {{ strmWatchingEntries.length }} 个文件的 .strm 是否已生成，
                  不必等下一轮巡检（最长 30 分钟）。纯本地读取，不访问 115。
                  已生成的会即时解除观察；宽限期已过的会转入疑似清单。
                </v-tooltip>
              </v-btn>
            </div>
            <div v-if="strmWatchingEntries.length" class="d-flex flex-column ga-2 mb-3">
              <div v-for="entry in strmWatchingEntries" :key="'w-' + entry.key" class="queue-item-card d-flex flex-column flex-sm-row align-stretch align-sm-center justify-sm-space-between radius-lg pa-3 ga-2">
                <div class="list-row-main d-flex align-center overflow-hidden mr-sm-3 mr-0">
                  <div class="overflow-hidden">
                    <div class="font-weight-bold text-body-2 text-truncate">{{ entry.key }}</div>
                    <div class="text-caption text-medium-emphasis mt-0.5">
                      <template v-if="entry.clock === 'gen'">
                        已请 strm 助手补生成，等待新生成的 .strm 出现
                        （窗口 {{ statusData.strm_regrace_hours }}h） · {{ entry.remainingText }}
                      </template>
                      <template v-else>
                        同步成功，等待 strm 生成（宽限期 {{ statusData.strm_grace_minutes }} 分钟） · {{ entry.remainingText }}
                      </template>
                    </div>
                  </div>
                </div>
                <div class="list-row-actions d-flex align-center flex-wrap ga-1 flex-shrink-0">
                  <v-chip
                    size="x-small"
                    :color="entry.clock === 'gen' ? 'primary' : 'info'"
                    variant="tonal"
                    class="font-weight-bold"
                  >
                    {{ entry.clock === 'gen' ? '已请求生成' : '观察中' }}
                  </v-chip>
                  <v-btn
                    size="x-small"
                    variant="tonal"
                    color="primary"
                    radius-sm
                    class="px-2"
                    :loading="itemLoading === 'strmchk:' + entry.key"
                    @click="checkWatching(entry.key)"
                  >
                    <v-icon start size="14">mdi-refresh</v-icon>
                    检查 strm
                    <v-tooltip activator="parent" location="top" max-width="320">
                      立即比对，不等窗口、不等巡检。<br>
                      已生成 ⇒ 立刻解除观察；仍未生成 ⇒ 到期后转入待处理清单。<br>
                      判据只看 .strm 有没有生成，不读 CD2 挂载视图。<br>
                      纯本地读取，不访问 115、不消耗配额。
                    </v-tooltip>
                  </v-btn>
                </div>
              </div>
            </div>

            <div v-if="!strmSuspectCount" class="text-caption text-medium-emphasis mb-2">
              当前无疑似异常。若怀疑有文件上传失败但从未被观察过，点上方「扫描缺 strm 的文件」主动反查。
            </div>
            <div class="d-flex flex-column ga-2">
              <div v-for="key in strmPaged.slice" :key="'s-' + key" class="failed-item-card d-flex flex-column flex-sm-row align-stretch align-sm-center justify-sm-space-between radius-lg pa-3 ga-2">
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
                      <!-- 走到这条分支说明补生成**请求过**且重新计时的窗口也走完了，
                           亦即「生成动作做过而指针文件仍不出现」。但依然不能写成
                           「补生成无效 ⇒ 云端缺文件」：助手可能压根没执行（路径不在
                           它的全量列表里就直接拒绝），那种情况下 strm 当然不会出现，
                           而云端文件是好的。只陈述已发生的事实，判断留给用户。 -->
                      <template v-if="genRequested[key]">
                        已请求 strm 助手补生成，窗口内仍未看到 .strm ——
                        请到助手侧确认它是真的生成了（可能漏生成），还是报了「匹配目录失败」
                      </template>
                      <template v-else>
                        同步已报告成功，但宽限期内未见 strm 生成 —— 可能上传未真正完成
                      </template>
                    </div>
                  </div>
                </div>
                <div class="list-row-actions d-flex align-center flex-wrap ga-1 flex-shrink-0">
                  <!-- 已请求过的条目换个标记。
                       ⚠️ 不能写成「补生成无效 ⇒ 云端缺文件」：助手可能压根没执行
                       （路径不在它的全量列表里就直接拒绝），那种情况下 strm 当然不会
                       出现，但云端文件是好的。把「命令发出」当成「生成失败」会误导
                       用户去删一个完好的云端文件。 -->
                  <v-chip v-if="genRequested[key]" size="x-small" color="info" variant="tonal" class="font-weight-bold">
                    补生成后仍无
                  </v-chip>
                  <v-chip v-else size="x-small" color="warning" variant="flat" class="font-weight-bold">疑似异常</v-chip>
                  <v-btn
                    size="x-small"
                    variant="tonal"
                    color="success"
                    radius-sm
                    class="px-2"
                    :loading="itemLoading === 'strmgen:' + key"
                    :disabled="statusData.is_running || !helperReady"
                    @click="generateStrmForKey(key)"
                  >
                    <v-icon start size="14">mdi-file-refresh-outline</v-icon>
                    {{ genRequested[key] ? '再试生成' : '尝试生成 strm' }}
                    <!-- tooltip 仅在可用时挂载：disabled 元素不派发鼠标事件，
                         挂上去也弹不出来（原因见区块上方那条常驻说明） -->
                    <v-tooltip v-if="helperReady" activator="parent" location="top" max-width="340">
                      请 strm 助手重新生成该文件所在网盘目录的 .strm。
                      成功 ⇒ 无需删旧重传；仍无 ⇒ 云端确实缺文件，再删旧重传。
                    </v-tooltip>
                  </v-btn>
                  <v-btn
                    size="x-small"
                    variant="tonal"
                    color="warning"
                    radius-sm
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
                  <v-btn
                    size="x-small"
                    variant="tonal"
                    color="secondary"
                    radius-sm
                    class="px-2"
                    :loading="itemLoading === 'strmign:' + key"
                    @click="ignoreStrmSuspects([key])"
                  >
                    <v-icon start size="14">mdi-eye-off-outline</v-icon>
                    忽略
                    <v-tooltip activator="parent" location="top" max-width="320">
                      以「精确匹配」加入忽略规则并移出疑似清单，<br>
                      之后同步/巡检不再报告该文件。<br>
                      恢复方式：到「已忽略」清单删除对应规则。<br>
                      适用于确认是误报、且不想再被提醒的条目。
                    </v-tooltip>
                  </v-btn>
                </div>
              </div>
            </div>
            <!-- 通用分页条：strm 独立成标签后与其它三个标签共用 paged 的绑定 -->
            <div v-if="paged.pages > 1" class="pager-bar d-flex align-center justify-center flex-wrap ga-2 mt-3">
              <v-btn
                size="small" variant="text" radius-sm class="pager-btn"
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
                size="small" variant="text" radius-sm class="pager-btn"
                :disabled="paged.page >= paged.pages"
                @click="paged.pageRef.value = paged.page + 1"
              >
                下一页<v-icon end size="16">mdi-chevron-right</v-icon>
              </v-btn>
            </div>
          </div>
        </div>

<!-- 标签 4：已忽略清单 -->
        <div v-if="currentTab === 'ignored'">
          <div v-if="ignoredList.length" class="d-flex flex-column ga-2">
            <div v-for="(rule, idx) in ignoredPaged.slice" :key="'i-' + idx" class="queue-item-card d-flex flex-column flex-sm-row align-stretch align-sm-center justify-sm-space-between radius-lg pa-3 ga-2">
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
              size="small" variant="text" radius-sm class="pager-btn"
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
              size="small" variant="text" radius-sm class="pager-btn"
              :disabled="paged.page >= paged.pages"
              @click="paged.pageRef.value = paged.page + 1"
            >
              下一页<v-icon end size="16">mdi-chevron-right</v-icon>
            </v-btn>
          </div>
          <div v-if="!ignoredList.length" class="empty-box d-flex flex-column align-center justify-center py-10 px-4 radius-lg text-center">
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
const runningNow = ref(false)
const retrying = ref(false)
const currentTab = ref('queue')
const actionMsg = ref('')

const statusData = ref({
  is_running: false,
  ready_count: 0,
  cooling_count: 0,
  delay_hours: 4.0,
  last_status: {},
  sync_pairs_count: 0,
  backfill_remaining: 0,
  stale_count: 0,
  // 源端扫描（主入库通道）：游标 = 映射名 → 上次成功推进的时刻；
  // source_scan_last 是全局最近一次推进。看板据此判断发现层是否还在工作。
  source_cursor: {},
  source_scan_last: 0,
  source_scan_enabled: true,
  source_scan_cron: '*/30 * * * *',
  // 入库闸门挡下的扩展名分布（累计）：扩展名 → 次数。
  ingest_skipped_by_ext: {},
  strm_suspects: {},
  strm_watch_detail: {},
  // key → 'sync' | 'gen'：该观察条目的计时基准。补生成移回观察期的条目用的是
  // 「请求时刻 + strm_regrace_hours」，不是宽限期配置值。
  strm_watch_clocks: {},
  strm_regrace_hours: 1,
  strm_watching: 0,
  strm_grace_minutes: 5,
  // 已请 strm 助手补生成过的 key → 时间戳；以及助手就绪状态（含不可用原因）
  strm_gen_requested: {},
  strm_gen_dir_limit: 20,
  strm_helper_ok: { ready: false, reason: '' },
  backfill_total: 0,
  rate_limit_enabled: true,
  upload_window_count: 0,
  upload_max_per_window: 500,
  upload_window_secs: 1800,
  upload_blocked_until: 0,
  // webhook 运行态：计数 + 最近一次报文的字段结构摘要（不含路径值）
  webhook: {},
})

// webhook 运行态。可见性判据刻意选「曾经收到过任何一条请求」——
// 而不是「webhook 功能已启用」：渠道默认就是 emby，用后者判断会让这块面板
// 对每个用户都常驻显示，等于没做门控。
const webhookStat = computed(() => statusData.value.webhook || {})

const webhookVisible = computed(() =>
  (Number(webhookStat.value.received) || 0) > 0
  // `claimed` 必须一并作为显示条件：只用 received 的话，**认领失败**的用户
  // 恰恰看不到这块面板 —— 而认领失败正是最需要看这块面板的情况。
  || (Number(webhookStat.value.claimed) || 0) > 0
)

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

// 源端扫描健康度：它停摆 = 新文件不会被发现，是**主通道**失效。
// 只在「开关开着、却明显落后于自己的节奏」时报警；开关主动关掉不报警
// （那是用户的选择，不是故障）。
// 阈值取 3 倍间隔且至少 30 分钟：避开宿主重启后的首个周期、也避开偶发的
// 单次调度延迟，只在真的连续几轮没跑时提示。
// ⚠️ 阈值不能直接按"间隔 × 3"算 —— 间隔现在是 **cron 表达式**。
//
// 做法：**只认 `*/N * * * *` 这一种形态**（它是默认值与旧配置换算后的形态，
// 覆盖绝大多数用户），由它推出间隔；其它任何写法（`0 * * * *`、`0 3 * * *`、
// `*/5 2-6 * * *` …）**一律退回一个保守的固定阈值**。
//
// 为什么不去写一个完整的 cron 解析器：解析器要跟后端 APScheduler 的语义保持
// 一致（步长、范围、列表、月份/星期名的别名……），一处不一致就是**假警报** ——
// 而假警报的代价比漏报高得多：用户会被训练成无视这块提示。退回固定阈值最坏
// 只是"发现得晚一点"，而扫描停摆本身不会造成数据丢失（游标没走，文件还在原地，
// 恢复后下一轮就补回来）。
const SOURCE_SCAN_FALLBACK_STALE = 6 * 3600   // 认不出表达式时的兜底：6 小时
const sourceScanStaleSecs = computed(() => {
  const cron = String(statusData.value.source_scan_cron || '').trim()
  const simple = /^\*\/(\d+)\s+\*\s+\*\s+\*\s+\*$/.exec(cron)
  if (!simple) return SOURCE_SCAN_FALLBACK_STALE
  const minutes = Math.max(1, parseInt(simple[1], 10) || 10)
  // 认出来时也留出宽裕：连续 3 轮没跑才算停摆
  return Math.max(minutes * 60 * 3, 1800)
})
const sourceScanProblem = computed(() => {
  if (statusData.value.source_scan_enabled === false) return false
  const last = Number(statusData.value.source_scan_last) || 0
  // 从未跑过（0）不算问题：插件刚装/刚重载，等第一轮即可。
  if (!last) return false
  return Date.now() / 1000 - last > sourceScanStaleSecs.value
})
// 卡片里用的极短版本（"3 分钟前" → "3 分钟"）。卡片宽度有限，且标签已经
// 写明是"上次源端扫描"，重复"前"字只会挤掉数字本身的视觉权重。
const sourceScanAgoShort = computed(() => {
  const last = Number(statusData.value.source_scan_last) || 0
  if (!last) return '尚未'
  const mins = Math.floor((Date.now() / 1000 - last) / 60)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时`
  return `${Math.floor(hours / 24)} 天`
})
const sourceScanAgoText = computed(() => {
  const last = Number(statusData.value.source_scan_last) || 0
  if (!last) return '从未'
  const mins = Math.floor((Date.now() / 1000 - last) / 60)
  if (mins < 60) return `${mins} 分钟`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时`
  return `${Math.floor(hours / 24)} 天`
})
// 闸门丢弃分布 → 表格行。按次数降序（最该关注的排最前）。
const skippedExtRows = computed(() => {
  const raw = statusData.value.ingest_skipped_by_ext || {}
  return Object.keys(raw)
    .map((ext) => ({
      ext,
      label: ext === '(无扩展名)' ? '无扩展名' : `.${ext}`,
      count: Number(raw[ext]) || 0,
    }))
    .filter((row) => row.count > 0)
    .sort((a, b) => b.count - a.count)
})

const failedCount = computed(() =>
  (statusData.value.last_status?.missing_files?.length || 0) +
  (statusData.value.last_status?.corrupt_files?.length || 0)
)

// strm 疑似异常数量与 key 列表（交叉验证发现的上传可疑文件）
const strmSuspectCount = computed(() => Object.keys(statusData.value.strm_suspects || {}).length)

// 观察期条目明细：显示在疑似清单上方，带「观察中」tag、不可操作。
// 宽限期从同步成功时刻起算，这里换算出剩余时间让用户对「还要等多久」有预期；
// 剩余时间只在每次 fetchStatus（30 秒轮询）时刷新，精度足够。
//
// ⚠️ 计时窗口**按基准分两种**，与后端 strm.watch_state_of 一一对应：
//   基准 sync：宽限期配置值（刮削/入库传播延迟）
//   基准 gen ：补生成窗口 strm_regrace_hours（等待助手遍历云端目录）
// 后端用哪把尺子判到期，这里就必须用哪把尺子算剩余；否则会出现「看板说还剩
// 5 小时、下一轮巡检却已判到期转疑似」—— 两边各自都自洽，用户完全无从判断
// 该信谁，而这正是双钟问题最难排查的地方。
const strmWatchingEntries = computed(() => {
  const detail = statusData.value.strm_watch_detail || {}
  const clocks = statusData.value.strm_watch_clocks || {}
  const graceSync = (Number(statusData.value.strm_grace_minutes) || 5) * 60
  const graceGen = (Number(statusData.value.strm_regrace_hours) || 1) * 3600
  const now = Date.now() / 1000
  return Object.entries(detail)
    .map(([key, syncedTs]) => {
      const clock = clocks[key] === 'gen' ? 'gen' : 'sync'
      const grace = clock === 'gen' ? graceGen : graceSync
      const remainingSec = Math.max(0, grace - (now - Number(syncedTs)))
      const remainingMin = Math.ceil(remainingSec / 60)
      let remainingText
      if (remainingSec <= 0) {
        remainingText = '即将在下轮巡检判定'
      } else if (remainingMin >= 60) {
        remainingText = `约 ${Math.ceil(remainingMin / 60)} 小时后判定`
      } else {
        remainingText = `约 ${remainingMin} 分钟后判定`
      }
      return { key, clock, remainingText }
    })
    .sort((a, b) => a.key.localeCompare(b.key))
})

// 是否已为某个映射配置了 strm 目录。后端 /status 未返回 sync_pairs，故用
// 「开关开启」近似判定 —— 没配 strm_dir 时扫描会返回明确的失败提示，
// 比整个区块都不显示更容易让用户明白该怎么配置。
const strmConfigured = computed(() => statusData.value.strm_check_enabled !== false)
const strmSuspectKeys = computed(() => Object.keys(statusData.value.strm_suspects || {}))

// strm 助手是否就绪（运行中 + 至少一个映射配了网盘目录）。
// 不可用时按钮置灰**并在区块内常驻说明原因** —— tooltip 在 disabled 元素上
// 根本不会弹出（不派发鼠标事件），只放 tooltip 等于没有提示。
const helperReady = computed(() => statusData.value.strm_helper_ok?.ready === true)
const helperReason = computed(
  () => statusData.value.strm_helper_ok?.reason || 'strm 助手未就绪'
)
// 已请求过补生成的 key。
//
// ⚠️ 这里**不能**推论成「补生成无效 ⇒ 云端确实缺文件」。助手可能压根没执行
// （路径不在它的「全量同步路径」里就被它直接拒绝），而拒绝提示只发给助手侧、
// 本插件收不到 —— 那种情况下 strm 不会出现，但云端文件是完好的。
// 把「命令已发出」当成「生成已失败」，会诱导用户去删掉一个好文件。
// 因此标记只表达「已请求、等结果」，按钮改成「再试生成」提示可重复发起。
const genRequested = computed(() => statusData.value.strm_gen_requested || {})

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
  if (currentTab.value === 'strm') return strmPaged.value
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
    return failedPaged.value.slice.map((it) => it.file)
  }
  if (currentTab.value === 'strm') {
    // strm 独立成标签后，本页可勾选集合只含 strm 条目。
    // 勾选状态仍跨标签保留 —— 用户可以在 strm 标签勾选后切到别处，
    // 因此批量按钮的分流逻辑（按选中项成分）保持不变。
    return strmPaged.value.slice
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


// 删旧重传的唯一提交入口（单条 / 批量勾选 / 「全部删旧重传」共用）。
//
// ⚠️ 这里曾经有一层二次确认：后端复探 CD2 挂载后若判成「可见且大小一致」，
// 会返回 `needs_force`，前端把那段探测原文弹给用户、再点一次才带 `force` 重发。
// 那道守卫已随「云端可见性」整套删除 —— 它在 CD2 改名失败这个主成因上必然
// 判成「文件是好的」，于是把唯一能修复的动作挡在门外（详见后端 _api_strm_retry）。
// 现在请求一次即执行，判据是「待处理清单里没有对应 strm」。
//
// ⚠️ 保留 plainText：后端的文案同时面向聊天渠道（渲染 Markdown）与看板
// （纯文本区块，不渲染）。显示在前者之外的地方都要先规整掉 `**` 与行内代码
// 标记，否则用户看到的就是一堆星号。
async function postStrmRetry(keys) {
  return props.api.post('plugin/Rsync115Sync/strm_retry', { keys })
}

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
    const res = await postStrmRetry([key])
    actionMsg.value = res?.message || (res?.success ? '已开始删旧重传' : '操作失败')
    await fetchStatus()
  } catch (e) {
    actionMsg.value = '重传出错: ' + e.message
  } finally {
    itemLoading.value = ''
  }
}

// 忽略疑似条目（单条与批量共用同一函数，避免两处文案/状态处理漂移）。
//
// 语义：以**精确匹配**加入忽略规则并移出疑似清单 —— 只删清单的话下一轮
// 同步又会把同一文件报回来，用户的操作等于没做；忽略规则才是持久判定。
// 恢复方式：到「已忽略」清单删除对应规则。
async function ignoreStrmSuspects(keys) {
  if (!keys || !keys.length) return
  const label = keys.length === 1 ? keys[0] : `${keys.length} 个文件`
  const ok = window.confirm(
    `将忽略 ${label}：\n\n` +
    `1. 以「精确匹配」加入忽略规则（只忽略这一个文件，不波及同名其它集数）\n` +
    `2. 立即从疑似清单移除，之后同步/巡检不再报告\n\n` +
    `⚠️ 忽略后本插件将不再为它做任何 strm 提醒。若之后想恢复对账，\n` +
    `请到「已忽略」清单删除对应规则。\n\n确定继续吗？`
  )
  if (!ok) return
  const loadingKey = keys.length === 1 ? 'strmign:' + keys[0] : 'strmign:batch'
  if (keys.length === 1) itemLoading.value = loadingKey
  else batchSyncing.value = true
  try {
    const res = await props.api.post('plugin/Rsync115Sync/strm_ignore', { keys })
    if (res && res.success) {
      strmScanMsg.value = res.message || '已忽略'
      // 被忽略的条目已离场，勾选状态一并清掉，避免后续批量操作对着不存在的条目提交
      const gone = new Set(res.data?.ignored || [])
      if (gone.size) selectedKeys.value = selectedKeys.value.filter((k) => !gone.has(k))
    } else {
      strmScanMsg.value = res?.message || '忽略失败'
    }
    await fetchStatus()
  } catch (e) {
    strmScanMsg.value = '忽略出错: ' + e.message
  } finally {
    itemLoading.value = ''
    batchSyncing.value = false
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
      const res = await postStrmRetry(strmKeys)
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

// 立即检查观察期条目的 strm 是否已生成（不等下一轮巡检，最长要等 30 分钟）。
//
// 纯本地文件读取：不访问 115、不占配额、不与同步冲突，因此**不做运行中拦截** ——
// 用户在同步跑着的时候照样可以查。检查结果会即时反映在看板上：
// 已生成的解除观察，宽限期已过的转入疑似清单。
async function checkWatching(key) {
  if (itemLoading.value.startsWith('strmchk')) return
  await postStrmCheck([key], 'strmchk:' + key)
}

async function checkAllWatching() {
  if (itemLoading.value.startsWith('strmchk')) return
  const keys = strmWatchingEntries.value.map((e) => e.key)
  if (!keys.length) return
  await postStrmCheck(keys, 'strmchk:all')
}

// 单条与全量共用，避免两条路径的提示文案与状态处理漂移
async function postStrmCheck(keys, loadingKey) {
  itemLoading.value = loadingKey
  try {
    const res = await props.api.post('plugin/Rsync115Sync/strm_check', { keys })
    if (res && res.success) {
      strmScanMsg.value = res.message || '已检查'
      // 被检查的条目若已离场（生成成功或转疑似），勾选状态要一并清掉，
      // 否则它们会留在 selectedKeys 里，让后续「批量操作」对着不存在的条目提交
      const gone = new Set([
        ...(res.data?.settled || []),
        ...(res.data?.suspects || []),
        ...(res.data?.removed || []),
      ])
      if (gone.size) selectedKeys.value = selectedKeys.value.filter((k) => !gone.has(k))
    } else {
      strmScanMsg.value = res?.message || '检查失败'
    }
    await fetchStatus()
  } catch (e) {
    strmScanMsg.value = '检查出错: ' + e.message
  } finally {
    itemLoading.value = ''
  }
}

// 请 strm 助手补生成 .strm —— 删旧重传**之前**该先试的一步。
//
// 为什么值得：疑似清单的两种成因（助手漏生成 / CD2 假成功）在插件本地视角完全
// 无法区分，但处理成本差好几个数量级 —— 前者重新生成指针文件即可，后者要删掉
// 云端文件再完整重传。花一次助手侧目录遍历换取「大概率免掉整轮重传」明显划算，
// 而且它顺带给出判别结果。因此这一步不是「多试一次」，而是**判据的补充**。
//
// 不做无确认的自动触发：助手会对每个参数遍历整个云端子树，属于对 115 的访问。
// 清单有几十条时自动触发就等于自动打出几十次遍历，与插件整体的风控保守取向相悖。
async function generateStrm() {
  const keys = [...strmSuspectKeys.value]
  if (!keys.length || statusData.value.is_running) return
  const ok = window.confirm(
    `将请 strm 助手按这些文件所在的网盘目录重新生成 .strm：\n\n` +
    `${keys.length} 个文件\n\n` +
    `• 生成成功 ⇒ 此前只是助手漏生成，**无需删旧重传**（省下一整轮删除与上传）\n` +
    `• 生成后仍无 ⇒ 云端确实缺该文件，届时再执行「删旧重传」\n\n` +
    `这些文件会移回「观察中」，按 ${statusData.value.strm_regrace_hours}h 窗口重新计时，` +
    `期间可用「检查 strm」立即查看结果（不必干等）。\n` +
    `助手按目录遍历云端（不是只处理单个文件），最多涉及 ` +
    `${statusData.value.strm_gen_dir_limit} 个目录，超过会整批拒绝。\n\n确定继续吗？`
  )
  if (!ok) return
  await postStrmGenerate(keys, 'strm:gen')
}

// 单条：与批量同一后端入口，只是 keys 只有一个
async function generateStrmForKey(key) {
  if (statusData.value.is_running) return
  await postStrmGenerate([key], 'strmgen:' + key)
}

// 批量与单条共用的提交逻辑，避免两条路径的提示文案与状态处理漂移
async function postStrmGenerate(keys, loadingKey) {
  itemLoading.value = loadingKey
  try {
    const res = await props.api.post('plugin/Rsync115Sync/strm_generate', { keys })
    if (res && res.success) {
      strmScanMsg.value = res.message || `已请助手补生成 ${keys.length} 个文件`
    } else {
      // 失败时保留后端原文：上限整批拒绝、助手未就绪、无法反查网盘目录
      // 都是**不同原因**，笼统覆盖会让用户无从处置
      strmScanMsg.value = res?.message || '补生成请求失败'
    }
    await fetchStatus()
  } catch (e) {
    strmScanMsg.value = '补生成请求出错: ' + e.message
  } finally {
    itemLoading.value = ''
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
      // ⚠️ 「缺 N 个」与「新增 M 个」对不上时必须解释差额，否则用户看到的
      // 是一句自相矛盾的结论（实测反馈：「检测到两个，却没有出现在疑似列表里」）。
      // 差额的三个去向各占一句，漏掉任何一句都会重新变成「数字对不上」。
      const skippedIgnored = d.skipped_ignored || 0
      const skippedWatching = d.skipped_watching || 0
      if (skippedIgnored) {
        msg += `\n🚫 其中 ${skippedIgnored} 个已命中「忽略」规则，按你的要求不再报警，因此不进疑似清单。`
      }
      if (skippedWatching) {
        msg += `\n⏳ 其中 ${skippedWatching} 个正在观察期（刚同步成功或已请求补生成），交给观察窗口自行判定。`
      }
      const unexplained = (d.found || 0) - (d.added || 0) - skippedIgnored - skippedWatching
      if (unexplained > 0) {
        msg += `\nℹ️ 另有 ${unexplained} 个已在疑似清单中（本次未重复计入新增）。`
      }
      // 「缺哪几个」是用户最需要的一条：只给计数等于让他自己去源端找。
      const candidates = d.candidates || []
      if (candidates.length) {
        const shown = candidates.slice(0, 10)
        msg += `\n\n缺 strm 的文件：\n` + shown.map((k) => `· ${k}`).join('\n')
        if (candidates.length > shown.length) {
          msg += `\n…（共 ${candidates.length} 个）`
        }
      }
      if (d.truncated) {
        msg += `\n⚠️ 已达到单次上限，结果被截断 —— 数量这么大通常说明 strm 插件本身没在工作，请先确认它的开关与媒体识别是否正常。`
      }
      msg += `\n\n💡 缺 strm 有三种可能，处理方式不同：\n` +
        `• 从未上传的存量文件 → 用 /rsync_backfill 补传\n` +
        `• strm 助手漏生成 → 点「先尝试生成 strm」，成本最低，多半能直接解决\n` +
        `• 上传了但 CD2 假成功 → 补生成后仍无 strm，才需要「删旧重传」`
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

// 清理无效的 strm 疑似条目（非视频 / 已忽略 / 源端已删 / 映射取消验证）。
// 与「清空」不同：它只删那些**结构上已不可能恢复正常**的条目，保留真问题。
async function pruneStrmSuspects() {
  if (itemLoading.value === 'strm:prune') return
  itemLoading.value = 'strm:prune'
  try {
    const res = await props.api.post('plugin/Rsync115Sync/strm_prune', {})
    strmScanMsg.value = res?.message || (res?.success ? '已清理无效条目' : '清理失败')
    await fetchStatus()
  } catch (e) {
    strmScanMsg.value = '清理出错: ' + e.message
  } finally {
    itemLoading.value = ''
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
    const res = await postStrmRetry(keys)
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

// 「立即运行一次」：后端会先扫源端、再跑一轮 ready，并如实回报排队情况
// （有多少在冷却、最快还需多久）—— 否则用户会以为按钮没生效。
async function runNow() {
  runningNow.value = true
  actionMsg.value = ''
  try {
    const res = await props.api.post('plugin/Rsync115Sync/run_now')
    if (res && res.success) {
      actionMsg.value = res.message || '已立即执行一次'
      // 扫描与入队是同步完成的（在后端线程池里），因此这里刷新能立刻看到新条目；
      // 传输是后台线程，下一轮 30 秒轮询会自然带上进度。
      fetchStatus()
    } else {
      actionMsg.value = res?.message || '执行失败'
    }
  } catch (e) {
    actionMsg.value = '执行失败：' + (e?.message || e)
  } finally {
    runningNow.value = false
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
/* ---- 圆角：本组件自己定义，不用框架的 rounded-* ----
   ⚠️ 为什么不覆盖 `.rounded-xl` / `.rounded-lg`：它们是 Vuetify 的全局实用类
   **且带 `!important`**（xs2px / sm4px / md6px / lg8px / xl24px / 0）。
   联邦插件与宿主共用同一个文档，覆盖它们会波及其它插件的界面，而且属于
   "用 !important 改别人的东西"。改用本组件自己的类名表达自己的意图：
     用户要求「圆角弧度减少一半」→ 24px 的卡片类收成 12px、8px 的按钮/块类收成 4px。 */
.radius-lg {
  border-radius: 12px !important;
}
.radius-sm {
  border-radius: 4px !important;
}

.plugin-page {
  width: 100%;
  box-sizing: border-box;
  /* 桌面端外边距。原为内联 style 且带 !important，
     导致媒体查询无法覆盖；现收敛到此处作为唯一来源，便于移动端收窄 */
  padding: 18px 22px !important;
}
.page-main-card {
  background: rgb(var(--v-theme-surface));
  width: 100%;
}
.header-surface {
  background: linear-gradient(135deg, rgba(var(--v-theme-primary), 0.08) 0%, rgba(var(--v-theme-primary), 0.02) 100%);
}
/* 顶栏标题与副标题：仅调整外边距，不覆盖 text-caption 的小字号行高，
   保证 12px 中文文本的可读性 */
.header-card-item .header-subtitle {
  margin-top: 6px;
}
/* PopUp 内 Title 与下方 Content 的间距必须用 margin 实现：
   宿主默认给 .v-card-item + .v-card-text 设置了 padding-block-start: 0 !important，
   内容区顶部内边距被强制归零。
   故此处：间距由 margin-top 提供（margin 不受该 padding !important 约束，是稳定生效的方案）。 */
.header-card-item + .v-card-text {
  margin-top: 16px;
}
.header-icon-box {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(var(--v-theme-primary), 0.12);
}
.stat-card {
  border: 1px solid rgba(var(--v-theme-on-surface), 0.08);
}
/* 首行三个数据卡片的 border-top 曾整条不可见（实测于真实宿主，勿凭理论回退）。
   成因：宿主把内容区顶部内边距归零（见上方 .header-card-item + .v-card-text 注释），
   而 .v-row 自带 margin: -12px，上下各外扩 12px；内容区又没有 padding-top，
   于是整行的顶边落在滚动容器（v-card-text 有 overflow-y:auto，即滚动裁剪框）之外
   —— 卡片的上边框与上圆角都被裁掉。实测卡片顶边相对容器顶边为 -8px。
   现有写法在页面无法滚动时会更严重：scrollHeight 恰等于 clientHeight，
   滚动区域没有可滚动内容，用户连滚动补救都做不到，只能一直看缺一条边的卡片。

   修法取「不依赖滚动容器内边距」的一步：把本行的负上边距归零，
   使内容顶边与容器顶边重合（实测 -8px → +4px，即列内边距，边框完整露出）。
   刻意不去覆写 .v-card-text 的顶部内边距 —— 那需要穿过宿主样式表并加 !important，
   宿主改版即失效；而归零负边距与宿主改版无关，重装依赖也不会被冲掉。 */
.strm-stat-row {
  margin-top: 0 !important;
  margin-bottom: 12px !important;
}
.stat-info { background: rgba(var(--v-theme-info), 0.06); }
.stat-primary { background: rgba(var(--v-theme-primary), 0.06); }
.stat-error { background: rgba(var(--v-theme-error), 0.06); }
.stat-warning { background: rgba(var(--v-theme-warning), 0.06); }
/* 中性色卡片（"上次源端扫描""补传剩余"）。刻意不用彩色：它们不是**问题指标**，
   而是两种"进度读数"—— 用彩色会让看板在一切正常时也显得刺眼，
   而这类常年常驻的数字一旦刺眼，用户就会开始无视整行。 */
.stat-muted { background: rgba(var(--v-theme-on-surface), 0.03); }
/* 第二行不受首行那条 border-top 约束（它不在滚动容器顶边），
   但上边距要压掉 Vuetify 的 -12px，否则两行会贴在一起。 */
.stat-row-secondary {
  margin-top: 0 !important;
  margin-bottom: 12px !important;
}

.action-strip {
  background: rgba(var(--v-theme-on-surface), 0.025);
  border: 1px solid rgba(var(--v-theme-on-surface), 0.06);
}
.queue-item-card {
  background: rgb(var(--v-theme-surface));
  border: 1px solid rgba(var(--v-theme-on-surface), 0.07);
}
.batch-bar {
  border-top: 1px dashed rgba(var(--v-theme-on-surface), 0.14);
}
.failed-item-card {
  background: rgba(var(--v-theme-error), 0.04);
  border: 1px solid rgba(var(--v-theme-error), 0.18);
}
.empty-box {
  border: 1px dashed rgba(var(--v-theme-on-surface), 0.16);
}
/* 分页条：与列表用虚线分隔，弱化存在感，避免抢占内容注意力 */
.pager-bar {
  border-top: 1px dashed rgba(var(--v-theme-on-surface), 0.14);
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
