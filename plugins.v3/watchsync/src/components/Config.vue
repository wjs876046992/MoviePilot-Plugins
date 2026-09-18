<template>
  <div class="plugin-config">
    <v-card class="d-flex flex-column h-100 rounded-xl overflow-hidden config-card" elevation="0" variant="outlined">

      <!-- 顶栏 -->
      <v-card-item class="header-surface px-4 py-3">
        <template #prepend>
          <div class="header-icon-box mr-3">
            <v-icon color="primary" size="20">mdi-cogs</v-icon>
          </div>
        </template>
        <v-card-title class="text-subtitle-1 font-weight-bold">观看记录同步配置</v-card-title>
        <template #append>
          <v-btn icon variant="text" size="small" class="rounded-lg close-btn" @click="notifyClose">
            <v-icon size="18">mdi-close</v-icon>
            <v-tooltip activator="parent" location="bottom">关闭</v-tooltip>
          </v-btn>
        </template>
      </v-card-item>

      <v-expand-transition>
        <div v-if="successMessage || error">
          <v-alert
            v-if="successMessage"
            type="success"
            variant="tonal"
            class="mx-4 mt-4 rounded-lg font-weight-medium"
            closable
            @click:close="successMessage = null"
          >
            {{ successMessage }}
          </v-alert>
          <v-alert
            v-if="error"
            type="error"
            variant="tonal"
            class="mx-4 mt-4 rounded-lg"
            closable
            @click:close="error = null"
          >
            {{ error }}
          </v-alert>
        </div>
      </v-expand-transition>

      <v-card-text class="config-body overflow-y-auto pa-4 flex-grow-1">
        <v-form ref="form" v-model="isFormValid" @submit.prevent="saveConfig">

          <!-- 基本设置 -->
          <div class="section-title d-flex align-center mb-3">
            <div class="section-icon section-icon-primary">
              <v-icon size="18" color="primary">mdi-tune</v-icon>
            </div>
            <span class="text-subtitle-2 font-weight-bold ml-2">基本设置</span>
            <v-divider class="ml-3 opacity-25"></v-divider>
          </div>

          <v-card variant="outlined" class="section-card rounded-lg mb-6">
            <v-card-text class="pa-4">
              <v-switch
                v-model="config.enabled"
                label="启用当前插件 (观看记录同步)"
                color="primary"
                inset
                hide-details="auto"
                class="font-weight-medium"
                hint="全局开关。启用后将自动建立对应不同用户的事件监听与同步"
                persistent-hint
              ></v-switch>
            </v-card-text>
          </v-card>

          <!-- 媒体类型与阈值 -->
          <div class="section-title d-flex align-center mb-3">
            <div class="section-icon section-icon-info">
              <v-icon size="18" color="info">mdi-sync-circle</v-icon>
            </div>
            <span class="text-subtitle-2 font-weight-bold ml-2">媒体类型与阈值</span>
            <v-divider class="ml-3 opacity-25"></v-divider>
          </div>

          <v-card variant="outlined" class="section-card rounded-lg mb-6">
            <v-card-text class="pa-4">
              <v-row>
                <v-col cols="12" md="6" class="py-2">
                  <v-switch
                    v-model="config.sync_movies"
                    label="同步 电影 观看记录"
                    color="info"
                    inset
                    hide-details
                  ></v-switch>
                </v-col>
                <v-col cols="12" md="6" class="py-2">
                  <v-switch
                    v-model="config.sync_tv"
                    label="同步 电视剧 观看记录"
                    color="info"
                    inset
                    hide-details
                  ></v-switch>
                </v-col>
                <v-col cols="12" md="6" class="mt-2">
                  <v-text-field
                    v-model.number="config.min_watch_time"
                    label="最小观看时长阈值（秒）"
                    variant="outlined"
                    density="comfortable"
                    type="number"
                    min="0"
                    color="info"
                    prepend-inner-icon="mdi-clock-outline"
                    hint="有效观看超过此阈值才会触发自动同步"
                    persistent-hint
                  ></v-text-field>
                </v-col>
              </v-row>
            </v-card-text>
          </v-card>

          <!-- 极影视同步强化 (智能展开) -->
          <v-expand-transition>
            <div v-if="hasZspaceInGroups">
              <div class="section-title d-flex align-center mb-3">
                <div class="section-icon section-icon-warning">
                  <v-icon size="18" color="warning">mdi-television-classic</v-icon>
                </div>
                <span class="text-subtitle-2 font-weight-bold ml-2">极影视同步强化</span>
                <v-divider class="ml-3 opacity-25"></v-divider>
              </div>

              <v-alert
                type="warning"
                variant="tonal"
                class="mb-4 rounded-lg font-weight-medium"
                icon="mdi-information-outline"
              >
                检测到配置中包含极影视服务端。开启以下轮询可有效捕获极影视独立产生的主动进度变化。
              </v-alert>

              <v-card variant="outlined" class="section-card rounded-lg mb-6">
                <v-card-text class="pa-4">
                  <v-row>
                    <v-col cols="12" md="6">
                      <v-switch
                        v-model="config.zspace_poll_enabled"
                        label="从极影视读取最新进度同步至 Emby"
                        color="warning"
                        inset
                        hint="关闭此项不影响 Emby 同步至极影视"
                        persistent-hint
                      ></v-switch>
                    </v-col>
                    <v-col v-if="config.zspace_poll_enabled" cols="12" md="6">
                      <v-text-field
                        v-model.number="config.zspace_poll_interval"
                        label="极影视轮询间隔（秒）"
                        variant="outlined"
                        density="comfortable"
                        type="number"
                        min="10"
                        step="5"
                        color="warning"
                        prepend-inner-icon="mdi-timer-sync-outline"
                        hint="降低数值可提高进度响应速度，建议: 30"
                        persistent-hint
                      ></v-text-field>
                    </v-col>
                  </v-row>
                </v-card-text>
              </v-card>
            </div>
          </v-expand-transition>

          <!-- 同步组配置 -->
          <div class="section-title d-flex align-center mb-3">
            <div class="section-icon section-icon-success">
              <v-icon size="18" color="success">mdi-account-group</v-icon>
            </div>
            <span class="text-subtitle-2 font-weight-bold ml-2">同步组配置（联络网）</span>
            <v-divider class="ml-3 opacity-25 d-none d-sm-flex"></v-divider>
            <v-spacer class="d-none d-sm-flex"></v-spacer>
            <v-btn
              color="success"
              size="small"
              variant="flat"
              rounded="lg"
              class="px-3 font-weight-medium flex-shrink-0"
              @click="addSyncGroup"
            >
              <v-icon start size="18">mdi-plus-circle</v-icon>
              建立新同步组
            </v-btn>
          </div>

          <v-alert
            v-if="config.sync_groups.length === 0"
            type="info"
            variant="tonal"
            class="mb-5 rounded-lg"
            icon="mdi-information-outline"
          >
            当前无已添加的同步组。请添加并建立联系组，将多端的账号绑定在一起进行数据互通。
          </v-alert>

          <!-- 同步组列表 -->
          <v-card
            v-for="(group, groupIndex) in config.sync_groups"
            :key="groupIndex"
            class="group-card rounded-lg mb-4 overflow-hidden"
            variant="outlined"
          >
            <v-toolbar density="compact" color="success" variant="tonal" class="group-toolbar px-2">
              <div class="group-badge ml-2 mr-3">
                <v-icon size="15" color="success">mdi-account-network</v-icon>
              </div>
              <v-toolbar-title class="text-body-2 font-weight-bold text-truncate">
                {{ group.name || `未命名组合 ${groupIndex + 1}` }}
              </v-toolbar-title>
              <v-spacer></v-spacer>

              <v-switch
                v-model="group.enabled"
                color="success"
                density="compact"
                hide-details
                label="联通开关"
                class="mr-4 text-caption font-weight-medium flex-shrink-0"
              ></v-switch>

              <v-btn
                icon
                variant="text"
                color="error"
                size="x-small"
                class="rounded-lg flex-shrink-0"
                @click="removeSyncGroup(groupIndex)"
              >
                <v-icon size="16">mdi-delete</v-icon>
                <v-tooltip activator="parent" location="top">删除此组</v-tooltip>
              </v-btn>
            </v-toolbar>

            <v-card-text class="pa-4">
              <v-text-field
                v-model="group.name"
                label="同步组名称标注"
                variant="outlined"
                density="comfortable"
                color="success"
                prepend-inner-icon="mdi-pencil-outline"
                placeholder="如：极空间TV客厅组 & 卧室Emby账号"
                hide-details="auto"
                class="mb-4"
              ></v-text-field>

              <div class="d-flex align-center justify-space-between flex-wrap gap-2 mb-3">
                <span class="text-caption font-weight-medium text-medium-emphasis d-flex align-center">
                  <v-icon size="15" class="mr-1">mdi-account-multiple</v-icon>
                  组内关联账号
                  <v-chip size="x-small" variant="tonal" color="success" class="ml-2 font-weight-bold">
                    {{ group.users?.length || 0 }}
                  </v-chip>
                </span>
                <v-btn
                  color="info"
                  variant="tonal"
                  size="small"
                  class="px-3 font-weight-medium"
                  rounded="lg"
                  @click="addGroupUser(groupIndex)"
                >
                  <v-icon start size="16">mdi-account-plus</v-icon>
                  关联新账号
                </v-btn>
              </div>

              <v-divider class="mb-3 opacity-25"></v-divider>

              <!-- 组内用户 -->
              <div v-if="group.users && group.users.length">
                <div
                  v-for="(user, userIndex) in group.users"
                  :key="userIndex"
                  class="user-row d-flex align-center flex-wrap ga-2 rounded-lg pa-2 mb-2"
                >
                  <div class="user-index flex-shrink-0">
                    <v-avatar size="26" color="blue-grey-lighten-4" class="text-blue-grey-darken-3 font-weight-bold text-caption">
                      {{ userIndex + 1 }}
                    </v-avatar>
                  </div>

                  <div class="flex-grow-1" style="min-width: 200px;">
                    <v-select
                      v-model="user.server"
                      :items="embyServers"
                      item-title="name"
                      item-value="name"
                      label="归属服务端"
                      variant="outlined"
                      density="compact"
                      color="primary"
                      hide-details="auto"
                      bg-color="white"
                      prepend-inner-icon="mdi-server"
                      @update:model-value="onGroupUserServerChange(groupIndex, userIndex)"
                    ></v-select>
                  </div>

                  <div class="flex-grow-1" style="min-width: 200px;">
                    <v-select
                      v-model="user.username"
                      :items="getServerUsers(user.server)"
                      item-title="name"
                      item-value="name"
                      label="具体用户名"
                      variant="outlined"
                      density="compact"
                      color="primary"
                      bg-color="white"
                      prepend-inner-icon="mdi-account"
                      :loading="loadingUsers[user.server]"
                      :hint="user.server ? `${getServerUsers(user.server).length} 个可用识别目标` : '请先在左侧提供服务器'"
                      persistent-hint
                    ></v-select>
                  </div>

                  <div class="flex-shrink-0">
                    <v-btn
                      color="grey"
                      variant="text"
                      size="small"
                      icon
                      class="rounded-lg"
                      @click="removeGroupUser(groupIndex, userIndex)"
                    >
                      <v-icon size="18">mdi-close</v-icon>
                      <v-tooltip activator="parent" location="left">移除这个账号对象</v-tooltip>
                    </v-btn>
                  </div>
                </div>
              </div>

              <!-- 组内空状态 -->
              <div v-else class="group-empty d-flex flex-column align-center justify-center py-6 rounded-lg text-center">
                <v-icon size="34" color="grey-lighten-1" class="mb-2">mdi-account-multiple-remove-outline</v-icon>
                <div class="text-caption text-medium-emphasis">当前组尚未绑定任何账号角色</div>
              </div>
            </v-card-text>
          </v-card>
        </v-form>
      </v-card-text>

      <!-- 底部操作栏 -->
      <v-card-actions class="footer-surface px-4 py-3">
        <v-btn
          color="primary"
          variant="flat"
          rounded="lg"
          class="px-5 font-weight-bold"
          @click="saveConfig"
          :loading="saving"
        >
          <v-icon start>mdi-content-save-check</v-icon>
          保存配置
        </v-btn>

        <v-btn
          color="blue-grey-darken-1"
          variant="tonal"
          rounded="lg"
          class="px-4 ml-2 font-weight-medium"
          @click="resetForm"
        >
          <v-icon start>mdi-undo-variant</v-icon>
          重置默认
        </v-btn>

        <v-spacer></v-spacer>

        <v-btn
          color="info"
          variant="text"
          rounded="lg"
          class="font-weight-medium px-3"
          @click="notifySwitch"
        >
          查看统计面板
          <v-icon end size="18">mdi-arrow-right-top</v-icon>
        </v-btn>
      </v-card-actions>
    </v-card>
  </div>
</template>
<script setup>
import { ref, reactive, computed, onMounted } from 'vue'

// 接收初始配置
const props = defineProps({
  initialConfig: {
    type: Object,
    default: () => ({}),
  },
  api: {
    type: Object,
    default: () => {},
  },
})

// 表单状态
const form = ref(null)
const isFormValid = ref(true)
const error = ref(null)
const successMessage = ref(null)
const saving = ref(false)

// 数据状态
const embyServers = ref([])
const serverUsers = ref({})
const loadingUsers = ref({})


// 配置数据，使用默认值和初始配置合并
const defaultConfig = {
  enabled: true,
  sync_movies: true,
  sync_tv: true,
  min_watch_time: 300,
  zspace_poll_enabled: true,
  zspace_poll_interval: 30,
  sync_groups: [],
}

// 合并默认配置和初始配置
const config = reactive({ ...defaultConfig })

// 初始化配置
onMounted(async () => {
  // 加载初始配置
  if (props.initialConfig) {
    Object.keys(props.initialConfig).forEach(key => {
      if (key in config) {
        config[key] = props.initialConfig[key]
      }
    })
  }

  // 加载Emby服务器列表
  await loadEmbyServers()
})

// 自定义事件，用于保存配置
const emit = defineEmits(['save', 'close', 'switch'])

// 加载Emby服务器列表
async function loadEmbyServers() {
  try {
    // 检查props.api是否可用
    if (!props.api) {
      error.value = 'API对象不可用，请检查插件配置'
      return
    }

    if (typeof props.api.get !== 'function') {
      error.value = 'API调用方法不可用'
      return
    }

    const result = await props.api.get('plugin/WatchSync/servers')

    if (result && result.success) {
      embyServers.value = result.data || []

      // 清除之前的错误信息
      error.value = null

      if (embyServers.value.length === 0) {
        error.value = '没有找到可用的Emby服务器，请检查MoviePilot的媒体服务器配置'
      } else {
        // 预加载所有服务器的用户列表
        loadAllServerUsers()
      }
    } else {
      error.value = `加载服务器列表失败: ${result?.message || '未知错误'}`
    }
  } catch (err) {
    error.value = `加载服务器列表失败: ${err.message}`
  }
}

// 获取服务器用户列表
function getServerUsers(serverName) {
  return serverUsers.value[serverName] || []
}

const hasZspaceInGroups = computed(() => {
  return (config.sync_groups || []).some(group => {
    return (group.users || []).some(user => isZspaceServer(user.server))
  })
})

function isZspaceServer(serverName) {
  if (!serverName) {
    return false
  }
  const server = embyServers.value.find(item => item.name === serverName)
  if (server?.type === 'zspace') {
    return true
  }
  const normalized = String(serverName).toLowerCase()
  return ['zspace', 'zvideo', 'jiyingshi', 'qizhi', '极影视', '极空间'].some(alias => normalized.includes(alias))
}

// 加载所有服务器的用户列表
async function loadAllServerUsers() {
  try {
    // 检查props.api是否可用
    if (!props.api || typeof props.api.get !== 'function') {
      return
    }

    const result = await props.api.get('plugin/WatchSync/users')

    if (result && result.success) {
      const allUsersData = result.data || {}

      // 存储所有服务器的用户数据
      for (const [serverName, userData] of Object.entries(allUsersData)) {
        serverUsers.value[serverName] = userData || []
      }

      // 清除之前的错误信息
      error.value = null

    } else {
      error.value = `加载用户列表失败: ${result?.message || '未知错误'}`
    }
  } catch (err) {
    error.value = `加载用户列表失败: ${err.message}`
  }
}

// 加载服务器用户列表（兼容旧接口）
async function loadServerUsers(serverName) {
  if (!serverName) {
    return
  }

  if (serverUsers.value[serverName]) {
    return
  }

  loadingUsers.value[serverName] = true

  try {
    // 如果还没有加载过任何用户数据，先加载所有服务器的用户
    if (Object.keys(serverUsers.value).length === 0) {
      await loadAllServerUsers()
    }
  } catch (err) {
    console.error('加载用户列表失败:', err)
  } finally {
    loadingUsers.value[serverName] = false
  }
}

// 添加同步组
function addSyncGroup() {
  config.sync_groups.push({
    name: '',
    enabled: true,
    users: []
  })
}

// 删除同步组
function removeSyncGroup(index) {
  config.sync_groups.splice(index, 1)
}

// 添加组内用户
function addGroupUser(groupIndex) {
  if (!config.sync_groups[groupIndex].users) {
    config.sync_groups[groupIndex].users = []
  }
  config.sync_groups[groupIndex].users.push({
    server: '',
    username: ''
  })
}

// 删除组内用户
function removeGroupUser(groupIndex, userIndex) {
  config.sync_groups[groupIndex].users.splice(userIndex, 1)
}

// 组内用户服务器变更时的处理
function onGroupUserServerChange(groupIndex, userIndex) {
  const user = config.sync_groups[groupIndex].users[userIndex]

  // 清空用户名
  user.username = ''

  if (user.server) {
    // 检查是否已经有缓存的用户数据
    const cachedUsers = getServerUsers(user.server)

    if (cachedUsers.length === 0) {
      loadServerUsers(user.server)
    }
  }
}

// 保存配置
async function saveConfig() {
  if (!isFormValid.value) {
    error.value = '请修正表单错误'
    return
  }

  saving.value = true
  error.value = null
  successMessage.value = null

  try {
    // 发送保存事件
    emit('save', { ...config })
    successMessage.value = '配置保存成功，稍后生效配置即可。'
  } catch (err) {
    console.error('保存配置失败:', err)
    error.value = err.message || '保存配置失败'
  } finally {
    saving.value = false
  }
}

// 重置表单
function resetForm() {
  Object.keys(defaultConfig).forEach(key => {
    config[key] = defaultConfig[key]
  })

  if (form.value) {
    form.value.resetValidation()
  }
}

// 通知主应用关闭组件
function notifyClose() {
  emit('close')
}

// 通知主应用切换到统计页面
function notifySwitch() {
  emit('switch')
}
</script>
<style scoped>
/* 卡片 */
.config-card {
  background: rgb(var(--v-theme-surface, 255, 255, 255));
}

/* 顶栏微渐变 */
.header-surface {
  background: linear-gradient(
    135deg,
    rgba(var(--v-theme-primary, 24, 103, 192), 0.08) 0%,
    rgba(var(--v-theme-primary, 24, 103, 192), 0.02) 100%
  );
  border-bottom: 1px solid rgba(var(--v-theme-on-surface, 0, 0, 0), 0.08);
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

.close-btn {
  color: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.6);
}

/* 主体背景 */
.config-body {
  background: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.015);
  max-height: 70vh;
}

/* 分节标题 */
.section-title {
  margin-top: 8px;
}

.section-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 9px;
  flex-shrink: 0;
}
.section-icon-primary { background: rgba(var(--v-theme-primary, 24, 103, 192), 0.12); }
.section-icon-info    { background: rgba(var(--v-theme-info, 33, 150, 243), 0.12); }
.section-icon-warning { background: rgba(var(--v-theme-warning, 251, 140, 0), 0.14); }
.section-icon-success { background: rgba(var(--v-theme-success, 76, 175, 80), 0.12); }

/* 分节卡片 */
.section-card {
  background: rgb(var(--v-theme-surface, 255, 255, 255));
  border-color: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.1) !important;
}

/* 同步组卡片 */
.group-card {
  background: rgb(var(--v-theme-surface, 255, 255, 255));
  border-color: rgba(var(--v-theme-success, 76, 175, 80), 0.3) !important;
}

.group-toolbar {
  border-bottom: 1px solid rgba(var(--v-theme-success, 76, 175, 80), 0.18);
}

.group-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 7px;
  background: rgba(var(--v-theme-success, 76, 175, 80), 0.15);
  flex-shrink: 0;
}

/* 组内用户行 */
.user-row {
  background: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.03);
  border: 1px solid rgba(var(--v-theme-on-surface, 0, 0, 0), 0.08);
  transition: border-color 0.18s ease, background 0.18s ease;
}
.user-row:hover {
  background: rgba(var(--v-theme-primary, 24, 103, 192), 0.04);
  border-color: rgba(var(--v-theme-primary, 24, 103, 192), 0.2);
}

.user-index {
  padding-top: 4px;
}

/* 组内空状态 */
.group-empty {
  background: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.02);
  border: 1px dashed rgba(var(--v-theme-on-surface, 0, 0, 0), 0.16);
}

/* 底部操作栏 */
.footer-surface {
  background: rgb(var(--v-theme-surface, 255, 255, 255));
  border-top: 1px solid rgba(var(--v-theme-on-surface, 0, 0, 0), 0.08);
}

.gap-2 {
  gap: 8px;
}
</style>
