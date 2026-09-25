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
            <v-chip size="x-small" color="primary" variant="tonal" class="ml-2 font-weight-bold">v0.2.7</v-chip>
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
              <div class="text-caption text-medium-emphasis">总控主开关，开启后生效定时轮询与入库监听</div>
            </div>
            <v-switch v-model="config.enabled" color="primary" inset hide-details density="compact"></v-switch>
          </div>

          <!-- ⚠️ 这三个 setting-row 的说明必须保持**一两行**。
               它们与右侧控件同处一个 space-between 横排，而文字列若长到拒绝收缩，
               就会把控件挤成一条缝甚至挤出可视区（此前「源端扫描 Cron」那条四行说明
               就是这么把输入框挡住的）。详细语义写在模块顶部的 alert 里 ——
               卡片内只留"这一项是干什么的"一句话。详见 §4.0g ②/⑤。 -->
          <div class="setting-row d-flex align-center justify-space-between px-4 py-3">
            <div>
              <div class="font-weight-bold text-body-2">启用入库监听</div>
              <div class="text-caption text-medium-emphasis">Webhook 与源端扫描共用的总闸</div>
            </div>
            <v-switch v-model="config.listen_transfer" color="primary" inset hide-details density="compact"></v-switch>
          </div>

          <!-- Webhook 接入说明：**挂在「启用入库监听」这一项下面** ——
               那个开关管的就是这条来源能不能进来，接入方式紧跟着它读才顺。

               ⚠️ 样式必须与页面其它说明块**完全一致**（v-alert type="info" variant="tonal"）。
               这里曾用过自制的 `.sub-note`（灰底 + 左侧竖线）来表达"从属关系"，
               代价是它在一片蓝色说明块里显得像是另一种东西 —— 用户直接指出
               「样式和其它描述模块不一样，其他是蓝色的」。层级已经由**位置**
               表达（紧跟在所属开关之后），不需要再靠换一套配色去强调。 -->
          <div class="px-4 pb-3">
            <v-alert type="info" variant="tonal" density="compact" class="rounded-lg text-body-2 mb-0">
              <div class="font-weight-bold mb-1">怎么把入库推给本插件（Webhook）</div>
              在发送端（自建脚本、下载器回调等）把地址指向平台 webhook 入口，并带上本插件的收件人标识：
              <br>
              <!-- ⚠️ 这个地址必须允许换行，否则它是**整页最长的一串不可断字符**
                   （约 80 字符无空格），会把所在行撑出卡片宽度，而卡片是
                   overflow-hidden —— 右侧内容（含同一模块里 cron 输入框那一列）
                   会被整条裁掉。`word-break: break-all` 让它在任意字符处折行。 -->
              <code class="wrap-anywhere">http://&lt;moviepilot地址&gt;:3001/api/v1/webhook/?token=&lt;API_TOKEN&gt;&amp;source=rsync115sync</code>
              <br>
              也可以改用请求头 <code>X-Webhook-Target: rsync115sync</code>。
              <b>这个值必须是 <code>rsync115sync</code></b> —— 填成别的（包括 <code>emby</code>）
              本插件都不会处理，那些报文归平台自己的解析器管。
              <br>
              本插件没有任何需要在这里配置的项：只认上面这个标识，其余来源一概不监听
              （这是<b>有意的设计</b>，不是待办 —— 媒体服务器自己的入库归平台处理）。
              <br>
              推送内容支持单个文件路径或目录（目录会自动展开），事件请用<b>入库类</b>
              （如 <code>library.new</code>）—— 播放类事件会被自动忽略，填了也不会误触发上传。
            </v-alert>
          </div>

          <div class="setting-row d-flex align-center justify-space-between px-4 py-3 border-t">
            <div>
              <div class="font-weight-bold text-body-2">
                源端扫描入库
                <v-chip size="x-small" color="primary" variant="tonal" class="ml-1 font-weight-bold">主通道</v-chip>
              </div>
              <div class="text-caption text-medium-emphasis">遍历本地源目录发现新入库，不依赖任何外部通知</div>
            </div>
            <v-switch v-model="config.source_scan_enabled" color="primary" inset hide-details density="compact"></v-switch>
          </div>

          <!-- ⚠️ 这一行**刻意不用横排**（不加 justify-space-between / align-center）。
               它是「标签在上、输入框在下」的纵向排布 —— 因为没有横排，
               就不存在"文字把输入框挤掉"这件事，与文字多长、窗口多宽都无关。
               前三次我都在调 flex 宽度分配（减字数、加 wrap、加 basis），
               都没解决；改用不依赖 flex 计算的排布后，挤压在结构上不可能发生。 -->
          <div class="setting-row setting-row-stacked px-4 py-3">
            <div>
              <div class="font-weight-bold text-body-2">源端扫描 Cron 规则</div>
              <div class="text-caption text-medium-emphasis">多久扫一轮（默认 30 分钟）</div>
            </div>
            <v-text-field
              v-model="config.source_scan_cron"
              variant="outlined"
              density="compact"
              hide-details
              placeholder="*/30 * * * *"
              class="mt-2 max-field"
            ></v-text-field>
          </div>

          <!-- 入库发现的完整语义集中在这里（卡片内只留一句话，见上） -->
          <div class="px-4 pb-3">
            <v-alert type="info" variant="tonal" density="compact" class="rounded-lg text-body-2 mb-0">
              <div class="font-weight-bold mb-1">入库是怎么被发现的</div>
              本插件有<b>两条</b>入库来源，分工是刻意的：
              <div class="mt-1">
                <b>① 源端扫描 —— 主通道，完整性的唯一承担者。</b>
                按上面的 cron 遍历各映射的本地源目录，把「修改时间晚于上次成功扫描时刻」的文件纳入冷却队列。
                整理入库、手动放进媒体库、外部工具搬入，以及插件重载期间发生的入库，它都能看见。
                <b>每轮只做本地目录遍历，不访问 115 挂载点，不消耗上传配额、不触发风控。</b>
                扫得更勤<b>不会</b>让文件更早上传（进队列后还要等满冷却），只是让它更早进队列。
              </div>
              <div class="mt-1">
                <b>② Webhook —— 加速器，不承担完整性。</b>
                发送端主动通知（接入方式见上方「怎么把入库推给本插件」）。它让文件早一点进队列，
                但即使整条失效，扫描也会在下一轮把同一个文件捞回来（去重由队列幂等保证）。
              </div>
              <div class="mt-1">
                关闭「启用入库监听」= 两条来源一起停（分开成两个开关会让用户遇到
                「关了一个、另一个还在悄悄入队」）。仅关闭「源端扫描入库」则只剩 Webhook 一条路 ——
                那时手动放入、外部搬入，以及 webhook 配置出问题时的入库都会静默丢失。
              </div>
            </v-alert>
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

        <!-- 字段说明集中在本模块顶部。卡片内只留"这里填什么"的极短提示 ——
             说明散在每个输入框的 hint 里时，用户要滚动才能拼出完整语义，
             而且同一句话会在每个映射卡片里重复一遍（映射越多越乱）。 -->
        <v-alert type="info" variant="tonal" density="compact" class="rounded-lg mb-3 text-body-2">
          <div class="font-weight-bold mb-1">每个映射是一对路径：本地源目录 → CD2 挂载的 115 目录</div>
          插件只同步这些映射内的文件，不会扫描其它位置。
          <div class="mt-2"><b>任务备注名称</b>：会成为文件清单的前缀（如
            <code>电视剧:剧名/剧名 S01E01.mkv</code>）。改名不会导致重复同步，
            但会让旧的异常清单条目失去对应关系，建议一次定好。</div>
          <div class="mt-1"><b>本地源目录</b>：NAS 上的媒体目录，需在容器内可访问。</div>
          <div class="mt-1"><b>CD2 挂载 115 目录</b>：上面对应的网盘目标目录。</div>
          <div class="mt-1"><b>同步所有文件类型</b>：关闭时只传下方「同步的扩展名」白名单里的文件
            （推荐）；开启后该映射下的 nfo、图片等一律上传。开启后还有一个区别：
            收到「推来单个文件」的通知时，同目录下的其它文件会一并入队（不递归子目录）——
            否则「全都要上传」就变成了「只传被点到名的那一个」。</div>
          <div class="mt-1"><b>strm 目录</b>：可选。填了才对该映射启用上传结果交叉验证 ——
            同步成功后进入观察期，到期仍未生成对应 <code>.strm</code> 会标记为「疑似上传异常」。
            看板可先请 STRM 助手补生成（成本低、多半直接解决），确认无效后再删旧重传。
            观察与扫描全程纯本地，<b>零 115 API</b>。
            <b>不依赖 P115StrmHelper</b>：任何会生成 .strm 的插件都可以，
            甚至完全不用插件、只填一个目录也能工作。</div>
          <div class="mt-1"><b>网盘目录</b>：可选，<b>仅「先尝试生成 strm」</b>用得到。
            填该映射在 115 网盘里的目录（<b>不是</b> CD2 挂载路径）；本地 strm 目录与
            网盘目录是两棵独立的树，无法自动推导，所以要单独填。
            注意助手只接受它自己「全量同步路径」里配置过的网盘路径，填了但助手没配会被拒绝
            （提示路径匹配错误）。<b>依赖 P115StrmHelper</b>；留空只是该映射不能用补生成，
            不影响同步、对账、观察与删旧重传。</div>
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
                <v-checkbox v-model="pair.all_ext" label="同步所有文件类型（含 nfo、图片等）" density="compact" hide-details color="primary"></v-checkbox>
              </v-col>
              <v-col cols="12">
                <v-text-field
                  v-model="pair.strm_dir"
                  label="strm 目录（可选，启用上传结果交叉验证）"
                  variant="outlined"
                  density="compact"
                  placeholder="例如 /vol1/strm/TV —— 留空则不启用该映射的验证"
                ></v-text-field>
              </v-col>
              <v-col cols="12">
                <v-text-field
                  v-model="pair.pan_dir"
                  label="网盘目录（可选，仅「先尝试生成 strm」需要）"
                  variant="outlined"
                  density="compact"
                  placeholder="例如 /HomeTheater/TV —— 填 115 网盘里的真实路径，留空则该映射不支持补生成"
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
                hint="媒体入库后等待 N 小时再上传。它同时兜两件事：① 留足外挂字幕与刮削时间；② 等文件写完 —— 源端扫描没有「写完了」这个信号，而正在写入的文件修改时间恰好是最新的，冷却期是唯一挡住「传到一半源文件还在变」的机制。建议 4~6 小时。设为 0 可关闭等待"
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
                hint="多久巡检一次。到期文件会按上面的限流规则分批上传；本轮无到期文件时才续跑补传队列（新鲜入库优先于存量补传）"
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

        <!-- 模块 6：strm 交叉验证 -->
        <div class="font-weight-bold text-subtitle-2 d-flex align-center mb-2">
          <v-icon size="18" color="warning" class="mr-1">mdi-television-classic</v-icon>
          strm 交叉验证
          <v-chip size="x-small" variant="tonal" color="success" class="ml-2 font-weight-bold">
            不依赖任何插件
          </v-chip>
        </div>
        <v-alert type="info" variant="tonal" density="compact" class="rounded-lg mb-3 text-body-2">
          <b>它是用来发现「假成功」的</b>：CD2 改名失败时，挂载视图会显示目标文件
          「存在且大小正常」，而 115 云端其实只有一份改名失败的半成品。此时双向对账
          与 rsync 的 --size-only 都会被蒙蔽，插件从自身视角<b>结构上看不见</b>这种失败。
          <br>
          strm 类插件生成的 .strm 指针文件依据与 CD2 无关，是独立见证人。
          同步成功后文件进入观察期，到期仍未生成对应 .strm 即标记为「疑似上传异常」。
          观察、扫描与判定的全过程都是<b>纯本地文件检查，零 115 API 开销</b>。
          <br>
          <b>启用方式</b>：在上方目录映射中为需要验证的映射填写「strm 目录」，
          留空的映射不启用验证，<b>不影响任何现有行为</b>。
          <br><br>
          <b>发现疑似后怎么处理</b>：「缺 strm」有两种成因，处理成本差很多 ——
          <b>①</b> strm 插件自己漏生成（云端文件其实是好的）；<b>②</b> CD2 改名失败假成功
          （云端只有半成品，必须删旧重传）。插件<b>无法从本地视角区分</b>这两者。
        </v-alert>

        <!-- 依赖边界对照表：本模块是「核心不依赖、可选增强依赖」的典型，
             分开列出来，避免用户以为整个功能都要装 P115StrmHelper -->
        <div class="dep-split rounded-lg mb-3">
          <div class="dep-split-row">
            <v-chip size="x-small" color="success" variant="tonal" class="font-weight-bold flex-shrink-0">
              本插件独立完成
            </v-chip>
            <span>
              观察期、主动扫描（全量 / 关键字）、疑似清单、忽略规则、清理无效项、
              <b>删旧重传</b>、状态通知
            </span>
          </div>
          <div class="dep-split-row">
            <v-chip size="x-small" color="info" variant="tonal" class="font-weight-bold flex-shrink-0">
              需要 P115StrmHelper
            </v-chip>
            <span>
              仅「<b>先尝试生成 strm</b>」一项。它请助手按文件所在的网盘目录重新生成
              一次指针文件：生成成功 ⇒ 是情况 ①，<b>无需删旧重传</b>；
              生成后仍无 ⇒ 是情况 ②，此时再删旧重传。
            </span>
          </div>
        </div>

        <v-alert type="info" variant="tonal" density="compact" class="rounded-lg mb-3 text-body-2">
          <b>「先尝试生成 strm」的启用前提（两处都要配）</b>：
          <br><b>①</b> 上方目录映射里为该映射填写「<b>网盘目录</b>」
          （115 网盘里的真实路径，与本地 strm 目录是两棵独立的树，无法自动推导）；
          <br><b>②</b> 该网盘路径必须已在 P115StrmHelper 的<b>「全量同步路径」</b>里配置过 ——
          助手的 <code>/p115_strm</code> 只接受它自己这个列表里的路径，其它字段
          （如「监控生活路径」）里配的目录传过去会被拒绝。
          <br>
          注意这一步会<b>访问 115 网盘</b>（助手按目录遍历云端），因此看板上是手动触发、
          逐目录去重，且单次涉及目录数有上限（超过则整批拒绝，不会自动放大访问量）。
          <b>不配也不影响上面「本插件独立完成」的任何一项</b>。
        </v-alert>

        <div class="settings-group-card rounded-xl overflow-hidden">
          <div class="setting-row setting-row-stacked px-4 py-3 border-b">
            <div>
              <div class="font-weight-bold text-body-2">观察宽限期（分钟）</div>
              <div class="text-caption text-medium-emphasis">
                strm 生成并不实时（可能还在上传或刮削中），因此同步成功后先等待一段时间再判定，
                避免把「还没生成」误判为上传异常。最小 1 分钟。
                <b>单位此前是小时，已改为分钟</b> —— 老配置的值不会自动换算，
                请按分钟重设（启动日志里会提示）。
              </div>
            </div>
            <v-text-field
              v-model.number="config.strm_grace_minutes"
              type="number"
              step="1"
              min="1"
              variant="outlined"
              density="compact"
              class="mt-2 max-field"
              hide-details
            ></v-text-field>
          </div>
          <div class="setting-row d-flex align-center justify-space-between px-4 py-3">
            <div>
              <div class="font-weight-bold text-body-2">当前状态</div>
              <div class="text-caption text-medium-emphasis">
                处于观察期的文件数会在看板顶部提示，疑似异常清单在独立的「strm 疑似异常」标签页内。
              </div>
            </div>
            <v-chip size="small" variant="tonal" color="warning">
              {{ config.sync_pairs.filter((p) => (p.strm_dir || '').trim()).length }} / {{ config.sync_pairs.length }} 个映射已配置
            </v-chip>
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
  // 源端扫描（入库发现的主通道，2026-09-25 起取代宿主整理事件订阅）
  source_scan_enabled: true,
  // cron 表达式（与「定时检查」同一套写法）。旧版这里是「间隔秒数」，
  // 后端会把它换算成等价的 */N 表达式并保留，见 _read_source_scan_cron。
  source_scan_cron: '*/30 * * * *',
  notify: true,
  // 4h：源端扫描引入后，冷却期多了一层职责 —— 等文件写完（见上面的 hint）
  delay_hours: 4.0,
  cron: '0 */2 * * *',
  sync_pairs: [],
  // ⚠️ 必须与后端 constants.DEFAULT_MEDIA_EXTENSIONS **逐字一致**。
  // 这是同一份默认串的第 3 份拷贝（另两份在后端默认值与旧默认值迁移表），
  // 漏改这里会让「新装用户在表单里看到的值」与「后端实际生效的值」不同 ——
  // 用户点一次保存就会把窄白名单写回去，表现为「升级后音频又不传了」。
  // Keep byte-identical with the backend default (see DEVELOPMENT §4.0f).
  media_extensions: 'mp4,mkv,ts,iso,rmvb,avi,mov,mpeg,mpg,wmv,3gp,asf,m4v,flv,m2ts,tp,f4v,srt,ssa,ass,sup,sub,idx,vtt,mp3,flac,m4a,aac,opus,wav,mka,ape,wma',
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
  // ---- webhook（第二入库来源）----
  // **没有任何配置项**：入口只认 `source=rsync115sync`，其它来源归平台解析器。
  // （渠道白名单与自建端点的四条防护均已移除，见 __init__.py 的 webhook 配置节。）
  // strm 观察宽限期：与后端 DEFAULT 及 _api_get_config 的兜底值保持 6.0 一致。
  // 这里必须显式声明：/config 未返回该字段时（例如宿主配置里从未存过），
  // v-model.number 绑定 undefined 会让输入框空白并写回 NaN。
  strm_grace_minutes: 5,
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
    // 115 网盘侧的目录，供「先尝试生成 strm」拼参数用；与 strm_dir 是两棵独立的树
    pan_dir: '',
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

// 注：这里曾有一段「分钟 ↔ 秒」的单位换算（源端扫描间隔）。改为 cron 表达式后
// 不再需要 —— 前后端存的是同一个字符串，没有单位可错。
// 教训值得留着：那次换算的边界处理错一次就会表现成「保存 10 分钟、回来变成 0」，
// 而 0 和 10 在界面上都"像那么回事"。**能用一个自描述的类型就别用数值 + 单位换算。**
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
   内容区顶部内边距被强制归零，与看板同源，间距由 margin-top 提供。
   此处不能依赖相邻选择器：保存成功/失败提示条会插在两者之间，
   故直接按内容区类名设置，保证提示条出现时间距依然稳定。 */
.config-body {
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

/* 设置行的宽度分配：说明文字可收缩换行，右侧控件**不被挤压**。
   背景：设置行是 `justify-space-between` 的横排（左说明 + 右控件）。flex 子项
   默认 `min-width: auto`，即「不得窄于内容的最小可排布宽度」—— 长说明段落
   （如「源端补齐扫描」那四行）在窗口不够宽时拒绝收缩，于是把右侧的开关
   压成一条细缝甚至顶出卡片。给它 min-width:0 才允许折行，再让控件
   flex-shrink:0 保持自身尺寸，两者合起来才是「文字让位、控件不动」。
   Long description blocks cannot shrink by default (min-width:auto), so they
   squeeze the trailing control out of the card; allow the text to wrap instead. */
/* 设置行：文字列可收缩，控件不被压缩。
   ⚠️ `min-width: 0` 只解决"**允许**收缩"。line-breaking 仍可能不够 ——
   长英文、代码片段、cron 表达式这类"不可断词"会把文字列的 min-content 撑得很宽，
   于是控件被挤到只剩一条缝或整个溢出可视区（用户实测两次：「源端补齐扫描」
   挤压开关、「源端扫描 Cron」输入框看不见）。

   `flex-wrap: wrap` 是这里的关键：一行放不下时**整块换到下一行**，
   控件永远拿满整行宽度 —— 而不是跟文字列在同一行里互相挤压。
   这样"会不会被挤掉"就不再取决于文字多长、用户窗口多宽。 */
.setting-row {
  flex-wrap: wrap;
  gap: 8px;
  /* ⚠️ 纵容横向溢出会把控件"推到看不见的地方"。
     卡片是 overflow-hidden，而设置行是横排 —— 只要有一样东西把内容撑宽，
     右侧那一列（含输入框）就被裁掉，且**没有任何滚动条可救**。
     设置行的职责是"排布"，不该有横向溢出；内容太宽就靠换行解决（见下）。 */
  overflow: hidden;
}
/* 说明文字块：允许在**任意字符**处断行。
   默认的 `overflow-wrap` 只在"整词放不下"时断，而 cron 表达式、URL、路径这类
   不含空格的串在浏览器眼里是"一个超长的词"，放不下就直接溢出。
   `word-break: break-word` 对中文无影响（中文本来就可断），对超长英文串有效。 */
/* 给需要显式换行的长串（URL 等）用 */
.wrap-anywhere {
  word-break: break-all;
  overflow-wrap: anywhere;
}
/* ⚠️ 文字列的 `flex-basis` 决定**何时换行**，这里的取值是承重的。
   若写成 `flex: 1 1 auto; min-width: 0`（本文件的早期写法），文字列可以一路
   收缩到 0 —— 于是容器再窄也**永远不会触发换行**，控件就一直被挤在剩余的那点
   宽度里。`min-width: 0` 解决的是"文字能在列内折行"，不是"列本身该多窄"。
   给定一个基准宽度后：装得下就并排（文字占据剩余空间），装不下就整体换行。 */
.setting-row > div:first-child {
  flex: 1 1 20rem;
  min-width: 15rem;
  word-break: break-word;
  overflow-wrap: anywhere;
}
.setting-row > .v-switch,
.setting-row > .v-text-field,
.setting-row > .v-chip,
.setting-row > .v-btn {
  flex: 0 0 auto;
}
/* 控件本身也不得溢出容器 */
.setting-row > .v-text-field {
  max-width: 100%;
}
/* 「标签在上、输入框在下」的纵向设置行。
   为什么单独做一个类：横排本来就要依赖 flex 的收缩与换行计算，而那个计算
   在真实宿主里出过三次意外（开关被挤成缝、输入框消失 ×2）。
   含输入框的行干脆不参与这套计算 —— 纵排下"被旁边文字挤压"在结构上不存在。 */
.setting-row-stacked {
  display: block;
}
.setting-row-stacked > div:first-child {
  /* 覆盖横排时给文字列设的 flex 属性 —— 纵排下它们没有意义 */
  flex: none;
  min-width: 0;
}
.max-field {
  width: 100%;
  max-width: 240px;
}
/* ⚠️ 这里刻意**不**给控件加 `flex: 1 1 100%`。那会让每个输入框永远独占一行
   （即使宽屏有空间），把原本紧凑的"左说明 + 右输入框"布局改掉。
   已有的 `flex: 0 0 auto`（见上）配合父级 `flex-wrap: wrap` 已经足够：
   控件**不允许**收缩 → 一行放不下时只能换行 → 换行后它保持自己的宽度、完整可见。
   即"宽屏保持原样、窄屏自动换行"，不需要任何断点判断。 */

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

/* ---- 跨插件依赖标注 ----
   本插件绝大多数功能是自包含的，只有「先尝试生成 strm」需要 P115StrmHelper。
   用统一的视觉语言标出，避免用户把「可选的协作功能」误当成「必须装的前置依赖」，
   也避免反过来：不知道某个字段填了才会启用协作。
   两种底色刻意区分：绿=不依赖任何插件，蓝=需要特定插件。 */
.dep-note {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  font-size: 11px;
  line-height: 1.45;
  padding: 5px 8px;
  border-radius: 6px;
}
.dep-note .v-icon {
  margin-top: 1px;
  flex-shrink: 0;
}
.dep-free {
  color: rgb(var(--v-theme-success));
  background: rgba(var(--v-theme-success), 0.08);
}
.dep-needs-helper {
  color: rgb(var(--v-theme-info));
  background: rgba(var(--v-theme-info), 0.1);
}

/* 依赖边界对照表：一行「本插件独立完成」+ 一行「需要助手」。
   两行并列呈现而非只列依赖项，是因为用户真正要判断的是「我不装它会少什么」。 */
.dep-split {
  border: 1px solid rgba(var(--v-theme-on-surface), 0.12);
  overflow: hidden;
}
.dep-split-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.5;
}
.dep-split-row + .dep-split-row {
  border-top: 1px solid rgba(var(--v-theme-on-surface), 0.1);
}
</style>
