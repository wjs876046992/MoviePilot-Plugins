<template>
  <div class="plugin-config">
    <v-card class="d-flex flex-column h-100 rounded-xl overflow-hidden config-main-card" elevation="0" variant="outlined">

      <!-- 优雅顶栏 -->
      <v-card-item class="header-surface px-5 py-4">
        <template #prepend>
          <div class="header-icon-box mr-3">
            <v-icon color="primary" size="22">mdi-sync-circle</v-icon>
          </div>
        </template>
        <div>
          <v-card-title class="text-subtitle-1 font-weight-bold pa-0 text-slate-800 d-flex align-center">
            观看记录同步配置
            <v-chip size="x-small" color="primary" variant="tonal" class="ml-2 font-weight-bold">v3.0.2</v-chip>
          </v-card-title>
          <div class="text-caption text-medium-emphasis">设定全局同步策略与多端设备用户映射网络</div>
        </div>
        <template #append>
          <v-btn icon variant="text" size="small" class="rounded-lg close-btn" @click="notifyClose">
            <v-icon size="18">mdi-close</v-icon>
            <v-tooltip activator="parent" location="bottom">关闭配置</v-tooltip>
          </v-btn>
        </template>
      </v-card-item>

      <!-- 提示信息 -->
      <v-expand-transition>
        <div v-if="successMessage || error" class="px-5 pt-3">
          <v-alert
            v-if="successMessage"
            type="success"
            variant="tonal"
            class="rounded-lg font-weight-medium"
            closable
            @click:close="successMessage = null"
          >
            {{ successMessage }}
          </v-alert>
          <v-alert
            v-if="error"
            type="error"
            variant="tonal"
            class="rounded-lg"
            closable
            @click:close="error = null"
          >
            {{ error }}
          </v-alert>
        </div>
      </v-expand-transition>

      <!-- 配置主体 -->
      <v-card-text class="config-body overflow-y-auto px-5 py-4 flex-grow-1">
        <v-form ref="form" v-model="isFormValid" @submit.prevent="saveConfig">

          <!-- 全局同步策略卡片 -->
          <div class="section-label d-flex align-center mb-2">
            <v-icon size="16" color="primary" class="mr-1">mdi-tune-variant</v-icon>
            <span class="text-caption font-weight-bold text-uppercase text-medium-emphasis tracking-wider">全局同步策略</span>
          </div>

          <v-card variant="outlined" class="settings-group-card rounded-xl mb-5">
            <!-- 插件主开关行 -->
            <div class="setting-row d-flex align-center justify-space-between px-4 py-3">
              <div class="d-flex align-center mr-3">
                <div class="setting-icon-box mr-3 setting-icon-primary">
                  <v-icon size="18" color="primary">mdi-power</v-icon>
                </div>
                <div>
                  <div class="font-weight-bold text-body-2">同步引擎主开关</div>
                  <div class="text-caption text-medium-emphasis">开启后将自动监听并双向同步多服务器间的播放进度与已看状态</div>
                </div>
              </div>
              <v-switch
                v-model="config.enabled"
                color="primary"
                inset
                hide-details
                density="compact"
                class="flex-shrink-0"
              ></v-switch>
            </div>

            <v-divider class="row-divider"></v-divider>

            <!-- 媒体类型行 -->
            <div class="px-4 py-3">
              <v-row align="center">
                <v-col cols="12" sm="6" class="py-1">
                  <div class="d-flex align-center justify-space-between">
                    <div class="d-flex align-center mr-2">
                      <v-icon size="18" color="info" class="mr-2">mdi-movie-outline</v-icon>
                      <span class="text-body-2 font-weight-medium">同步电影记录</span>
                    </div>
                    <v-switch
                      v-model="config.sync_movies"
                      color="info"
                      inset
                      hide-details
                      density="compact"
                    ></v-switch>
                  </div>
                </v-col>
                <v-col cols="12" sm="6" class="py-1">
                  <div class="d-flex align-center justify-space-between">
                    <div class="d-flex align-center mr-2">
                      <v-icon size="18" color="info" class="mr-2">mdi-television-box</v-icon>
                      <span class="text-body-2 font-weight-medium">同步电视剧记录</span>
                    </div>
                    <v-switch
                      v-model="config.sync_tv"
                      color="info"
                      inset
                      hide-details
                      density="compact"
                    ></v-switch>
                  </div>
                </v-col>
              </v-row>
            </div>

            <v-divider class="row-divider"></v-divider>

            <!-- 观看门槛行 -->
            <div class="px-4 py-3">
              <v-row align="center">
                <v-col cols="12" md="7">
                  <div class="text-body-2 font-weight-medium">有效观看时长门槛</div>
                  <div class="text-caption text-medium-emphasis">播放时间超过此阈值才触发自动同步，防止误点触发，推荐 300 秒</div>
                </v-col>
                <v-col cols="12" md="5">
                  <v-text-field
                    v-model.number="config.min_watch_time"
                    variant="outlined"
                    density="compact"
                    type="number"
                    min="0"
                    suffix="秒"
                    hide-details
                    color="primary"
                    prepend-inner-icon="mdi-timer-outline"
                    class="rounded-lg"
                  ></v-text-field>
                </v-col>
              </v-row>
            </div>
          </v-card>

          <!-- 极空间/极影视强化 (智能联动展开) -->
          <v-expand-transition>
            <div v-if="hasZspaceInGroups" class="mb-5">
              <div class="section-label d-flex align-center mb-2">
                <v-icon size="16" color="warning" class="mr-1">mdi-television-classic</v-icon>
                <span class="text-caption font-weight-bold text-uppercase text-medium-emphasis tracking-wider">极空间专属扩展</span>
                <v-chip size="x-small" color="warning" variant="tonal" class="ml-2 font-weight-bold">已检测到极影视</v-chip>
              </div>

              <v-card variant="outlined" class="settings-group-card rounded-xl zspace-card">
                <div class="setting-row d-flex align-center justify-space-between px-4 py-3">
                  <div class="d-flex align-center mr-3">
                    <div class="setting-icon-box mr-3 setting-icon-warning">
                      <v-icon size="18" color="warning">mdi-timer-sync-outline</v-icon>
                    </div>
                    <div>
                      <div class="font-weight-bold text-body-2">从极影视主动轮询进度</div>
                      <div class="text-caption text-medium-emphasis">极影视无被动 Webhook，开启定时轮询可捕获其独立产生的进度同步至 Emby</div>
                    </div>
                  </div>
                  <v-switch
                    v-model="config.zspace_poll_enabled"
                    color="warning"
                    inset
                    hide-details
                    density="compact"
                    class="flex-shrink-0"
                  ></v-switch>
                </div>

                <v-expand-transition>
                  <div v-if="config.zspace_poll_enabled">
                    <v-divider class="row-divider"></v-divider>
                    <div class="px-4 py-3">
                      <v-row align="center">
                        <v-col cols="12" md="7">
                          <div class="text-body-2 font-weight-medium">轮询探测间隔</div>
                          <div class="text-caption text-medium-emphasis">数值越小同步越及时，建议设为 30 秒</div>
                        </v-col>
                        <v-col cols="12" md="5">
                          <v-text-field
                            v-model.number="config.zspace_poll_interval"
                            variant="outlined"
                            density="compact"
                            type="number"
                            min="10"
                            step="5"
                            suffix="秒"
                            hide-details
                            color="warning"
                            prepend-inner-icon="mdi-av-timer"
                            class="rounded-lg"
                          ></v-text-field>
                        </v-col>
                      </v-row>
                    </div>
                  </div>
                </v-expand-transition>
              </v-card>
            </div>
          </v-expand-transition>

          <!-- 同步组互通网络 -->
          <div class="d-flex align-center justify-space-between mb-3">
            <div class="section-label d-flex align-center">
              <v-icon size="16" color="success" class="mr-1">mdi-lan-connect</v-icon>
              <span class="text-caption font-weight-bold text-uppercase text-medium-emphasis tracking-wider">同步互联组网络</span>
              <v-chip size="x-small" color="success" variant="tonal" class="ml-2 font-weight-bold">
                {{ config.sync_groups.length }} 组
              </v-chip>
            </div>
            <v-btn
              color="primary"
              size="small"
              variant="tonal"
              rounded="lg"
              class="font-weight-medium"
              @click="addSyncGroup"
            >
              <v-icon start size="16">mdi-plus</v-icon>
              添加同步组
            </v-btn>
          </div>

          <!-- 同步组列表为空时 -->
          <div v-if="config.sync_groups.length === 0" class="empty-sync-box rounded-xl pa-8 text-center mb-4">
            <div class="empty-icon-wrapper mb-3">
              <v-icon size="36" color="primary">mdi-account-network-outline</v-icon>
            </div>
            <div class="text-subtitle-2 font-weight-bold text-medium-emphasis">暂未创建同步组</div>
            <div class="text-caption text-disabled mt-1 mb-4">创建同步组后，可将不同服务端的多个账号绑定为一个互通群组</div>
            <v-btn color="primary" variant="flat" size="small" rounded="lg" @click="addSyncGroup">
              <v-icon start size="16">mdi-plus</v-icon>
              创建第一个同步组
            </v-btn>
          </div>

          <!-- 同步组卡片列表 -->
          <div v-else class="sync-groups-list">
            <v-card
              v-for="(group, groupIndex) in config.sync_groups"
              :key="groupIndex"
              variant="outlined"
              class="group-panel-card rounded-xl mb-4 overflow-hidden"
            >
              <!-- 组卡片顶部工具栏 -->
              <div class="group-header d-flex align-center justify-space-between px-4 py-3">
                <div class="d-flex align-center flex-grow-1 mr-3 overflow-hidden">
                  <div class="group-header-badge mr-2">
                    <v-icon size="16" color="primary">mdi-folder-network-outline</v-icon>
                  </div>
                  <span class="font-weight-bold text-body-2 text-truncate">
                    {{ group.name || `未命名同步组 ${groupIndex + 1}` }}
                  </span>
                  <v-chip size="x-small" variant="tonal" color="primary" class="ml-2 flex-shrink-0 font-weight-medium">
                    {{ group.users?.length || 0 }} 个端点
                  </v-chip>
                </div>

                <div class="d-flex align-center flex-shrink-0">
                  <v-switch
                    v-model="group.enabled"
                    color="primary"
                    density="compact"
                    hide-details
                    label="启用"
                    class="mr-3 font-weight-medium text-caption"
                  ></v-switch>
                  <v-btn
                    icon
                    variant="text"
                    color="error"
                    size="small"
                    class="rounded-lg"
                    @click="removeSyncGroup(groupIndex)"
                  >
                    <v-icon size="18">mdi-delete-outline</v-icon>
                    <v-tooltip activator="parent" location="top">删除此组</v-tooltip>
                  </v-btn>
                </div>
              </div>

              <v-divider class="row-divider"></v-divider>

              <!-- 组详情内容 -->
              <div class="pa-4">
                <!-- 组名称编辑框 -->
                <v-text-field
                  v-model="group.name"
                  label="同步组名称"
                  placeholder="例如：客厅极空间TV 与 卧室Emby互通"
                  variant="outlined"
                  density="compact"
                  color="primary"
                  prepend-inner-icon="mdi-tag-outline"
                  hide-details="auto"
                  class="mb-4 rounded-lg"
                ></v-text-field>

                <!-- 组内成员列表标题与添加按钮 -->
                <div class="d-flex align-center justify-space-between mb-3">
                  <span class="text-caption font-weight-bold text-medium-emphasis d-flex align-center">
                    <v-icon size="15" class="mr-1 text-primary">mdi-account-multiple</v-icon>
                    组内互通账号节点
                  </span>
                  <v-btn
                    color="primary"
                    variant="text"
                    size="small"
                    class="font-weight-medium px-2"
                    @click="addGroupUser(groupIndex)"
                  >
                    <v-icon start size="16">mdi-account-plus-outline</v-icon>
                    添加账号节点
                  </v-btn>
                </div>

                <!-- 组内用户节点 -->
                <div v-if="group.users && group.users.length" class="endpoint-nodes-container">
                  <div
                    v-for="(user, userIndex) in group.users"
                    :key="userIndex"
                    class="endpoint-node-card d-flex align-center flex-wrap ga-2 rounded-lg pa-3 mb-2"
                  >
                    <!-- 序号与图标 -->
                    <div class="d-flex align-center flex-shrink-0 mr-1">
                      <div class="node-number-badge font-weight-bold">
                        {{ userIndex + 1 }}
                      </div>
                    </div>

                    <!-- 服务端选择 -->
                    <div class="flex-grow-1 node-field-box">
                      <v-select
                        v-model="user.server"
                        :items="embyServers"
                        item-title="name"
                        item-value="name"
                        label="选择服务端"
                        variant="outlined"
                        density="compact"
                        color="primary"
                        hide-details="auto"
                        prepend-inner-icon="mdi-server-network"
                        @update:model-value="onGroupUserServerChange(groupIndex, userIndex)"
                      ></v-select>
                    </div>

                    <!-- 互通指示图标 -->
                    <div class="node-sync-indicator d-none d-sm-flex align-center justify-center flex-shrink-0">
                      <v-icon size="16" color="primary">mdi-swap-horizontal</v-icon>
                    </div>

                    <!-- 用户名选择 -->
                    <div class="flex-grow-1 node-field-box">
                      <v-select
                        v-model="user.username"
                        :items="getServerUsers(user.server)"
                        item-title="name"
                        item-value="name"
                        label="选择对应用户"
                        variant="outlined"
                        density="compact"
                        color="primary"
                        prepend-inner-icon="mdi-account-outline"
                        :loading="loadingUsers[user.server]"
                        :hint="user.server ? `${getServerUsers(user.server).length} 个可用用户` : '请先在左侧选择服务端'"
                        persistent-hint
                      ></v-select>
                    </div>

                    <!-- 移除按钮 -->
                    <div class="flex-shrink-0">
                      <v-btn
                        color="error"
                        variant="text"
                        size="small"
                        icon
                        class="rounded-lg"
                        @click="removeGroupUser(groupIndex, userIndex)"
                      >
                        <v-icon size="18">mdi-close-circle-outline</v-icon>
                        <v-tooltip activator="parent" location="left">移除此节点</v-tooltip>
                      </v-btn>
                    </div>
                  </div>
                </div>

                <!-- 组内暂无节点时的虚线添加块 -->
                <div
                  v-else
                  class="node-empty-dashed-box d-flex align-center justify-center py-4 rounded-lg cursor-pointer"
                  @click="addGroupUser(groupIndex)"
                >
                  <v-icon size="18" color="primary" class="mr-2">mdi-plus-circle-outline</v-icon>
                  <span class="text-caption font-weight-medium text-primary">点击添加组内第一个关联端点</span>
                </div>
              </div>
            </v-card>
          </div>
        </v-form>
      </v-card-text>

      <!-- 底部控制栏 -->
      <v-card-actions class="footer-surface px-5 py-3">
        <v-btn
          color="primary"
          variant="flat"
          rounded="lg"
          class="px-5 font-weight-bold save-btn"
          @click="saveConfig"
          :loading="saving"
        >
          <v-icon start size="18">mdi-content-save-check</v-icon>
          保存配置
        </v-btn>

        <v-btn
          color="secondary"
          variant="tonal"
          rounded="lg"
          class="px-4 ml-2 font-weight-medium"
          @click="resetForm"
        >
          <v-icon start size="18">mdi-undo-variant</v-icon>
          重置
        </v-btn>

        <v-spacer></v-spacer>

        <v-btn
          color="primary"
          variant="text"
          rounded="lg"
          class="font-weight-medium px-3"
          @click="notifySwitch"
        >
          查看统计面板
          <v-icon end size="16">mdi-arrow-right</v-icon>
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
/* 主卡片容器 */
.config-main-card {
  background: rgb(var(--v-theme-surface, 255, 255, 255));
}

/* 顶部标题栏渐变 */
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
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: rgba(var(--v-theme-primary, 24, 103, 192), 0.12);
}

.close-btn {
  color: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.6);
}

/* 配置内容区域 */
.config-body {
  background: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.015);
  max-height: 72vh;
}

/* 区域小标签 */
.section-label {
  letter-spacing: 0.05em;
}

/* 设置统一卡片 */
.settings-group-card {
  background: rgb(var(--v-theme-surface, 255, 255, 255));
  border: 1px solid rgba(var(--v-theme-on-surface, 0, 0, 0), 0.09) !important;
  transition: box-shadow 0.2s ease, border-color 0.2s ease;
}
.settings-group-card:hover {
  border-color: rgba(var(--v-theme-primary, 24, 103, 192), 0.25) !important;
}

.zspace-card {
  border-color: rgba(var(--v-theme-warning, 251, 140, 0), 0.25) !important;
}
.zspace-card:hover {
  border-color: rgba(var(--v-theme-warning, 251, 140, 0), 0.45) !important;
}

/* 行间分割线 */
.row-divider {
  border-color: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.06) !important;
}

/* 行图标 */
.setting-icon-box {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  flex-shrink: 0;
}
.setting-icon-primary {
  background: rgba(var(--v-theme-primary, 24, 103, 192), 0.1);
}
.setting-icon-warning {
  background: rgba(var(--v-theme-warning, 251, 140, 0), 0.12);
}

/* 同步组卡片 */
.group-panel-card {
  background: rgb(var(--v-theme-surface, 255, 255, 255));
  border: 1px solid rgba(var(--v-theme-on-surface, 0, 0, 0), 0.1) !important;
  transition: all 0.2s ease;
}
.group-panel-card:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
}

.group-header {
  background: rgba(var(--v-theme-primary, 24, 103, 192), 0.03);
}

.group-header-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: rgba(var(--v-theme-primary, 24, 103, 192), 0.1);
  flex-shrink: 0;
}

/* 节点卡片容器 */
.endpoint-node-card {
  background: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.025);
  border: 1px solid rgba(var(--v-theme-on-surface, 0, 0, 0), 0.08);
  transition: all 0.18s ease;
}
.endpoint-node-card:hover {
  background: rgba(var(--v-theme-primary, 24, 103, 192), 0.035);
  border-color: rgba(var(--v-theme-primary, 24, 103, 192), 0.25);
}

.node-number-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  font-size: 0.75rem;
  background: rgba(var(--v-theme-primary, 24, 103, 192), 0.12);
  color: rgb(var(--v-theme-primary, 24, 103, 192));
}

.node-field-box {
  min-width: 180px;
}

.node-sync-indicator {
  width: 24px;
  height: 24px;
  opacity: 0.6;
}

/* 节点空状态 */
.node-empty-dashed-box {
  border: 1px dashed rgba(var(--v-theme-primary, 24, 103, 192), 0.35);
  background: rgba(var(--v-theme-primary, 24, 103, 192), 0.02);
  transition: all 0.2s ease;
}
.node-empty-dashed-box:hover {
  background: rgba(var(--v-theme-primary, 24, 103, 192), 0.06);
  border-color: rgba(var(--v-theme-primary, 24, 103, 192), 0.6);
}

/* 暂无同步组空状态 */
.empty-sync-box {
  background: rgba(var(--v-theme-on-surface, 0, 0, 0), 0.02);
  border: 1px dashed rgba(var(--v-theme-on-surface, 0, 0, 0), 0.15);
}
.empty-icon-wrapper {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: rgba(var(--v-theme-primary, 24, 103, 192), 0.1);
}

/* 底部操作条 */
.footer-surface {
  background: rgb(var(--v-theme-surface, 255, 255, 255));
  border-top: 1px solid rgba(var(--v-theme-on-surface, 0, 0, 0), 0.08);
}

.save-btn {
  letter-spacing: 0.03em;
}

.cursor-pointer {
  cursor: pointer;
}

.ga-2 {
  gap: 8px;
}
</style>
