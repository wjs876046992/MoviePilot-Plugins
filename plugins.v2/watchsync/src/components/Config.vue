<template>
  <div class="plugin-config">
    <v-card class="d-flex flex-column h-100 rounded-lg shadow-sm" elevation="0" variant="outlined">
      
      <!-- 顶栏区域 -->
      <v-card-item class="bg-primary text-white pa-4">
        <template #prepend>
          <v-icon size="x-large" class="mr-2">mdi-cogs</v-icon>
        </template>
        <v-card-title class="font-weight-bold">观看记录同步配置</v-card-title>
        <template #append>
          <v-btn icon color="white" variant="text" size="small" @click="notifyClose" class="bg-white bg-opacity-20 ml-2">
            <v-icon>mdi-close</v-icon>
          </v-btn>
        </template>
      </v-card-item>
      
      <v-alert v-if="successMessage" type="success" elevation="2" class="ma-4 rounded-lg font-weight-medium">
        {{ successMessage }}
      </v-alert>
      <v-alert v-if="error" type="error" variant="tonal" class="ma-4 border border-error rounded-lg">
        {{ error }}
      </v-alert>

      <v-card-text class="overflow-y-auto pa-5 bg-grey-lighten-5 flex-grow-1" style="max-height: 70vh;">
        <v-form ref="form" v-model="isFormValid" @submit.prevent="saveConfig">
          
          <!-- 基本设置区域 -->
          <div class="d-flex align-center mt-2 mb-3 text-primary">
            <v-avatar color="primary-lighten-4" class="mr-3 text-primary" size="36">
              <v-icon>mdi-tune</v-icon>
            </v-avatar>
            <span class="text-subtitle-1 font-weight-bold">基本设置</span>
          </div>
          
          <v-card variant="outlined" class="mb-8 rounded-lg bg-white border-opacity-50">
            <v-card-text class="pa-5">
              <v-row>
                <v-col cols="12">
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
                </v-col>
              </v-row>
            </v-card-text>
          </v-card>

          <!-- 同步设置区域 -->
          <div class="d-flex align-center mt-4 mb-3 text-info">
            <v-avatar color="info-lighten-4" class="mr-3 text-info" size="36">
              <v-icon>mdi-sync-circle</v-icon>
            </v-avatar>
            <span class="text-subtitle-1 font-weight-bold">媒体类型与阈值</span>
          </div>

          <v-card variant="outlined" class="mb-8 rounded-lg bg-white border-opacity-50">
            <v-card-text class="pa-5">
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

          <!-- 极影视设置区域 (智能展开) -->
          <v-expand-transition>
            <div v-if="hasZspaceInGroups">
              <div class="d-flex align-center mt-4 mb-3 text-warning">
                <v-avatar color="warning-lighten-4" class="mr-3 text-warning-darken-2" size="36">
                  <v-icon>mdi-television-classic</v-icon>
                </v-avatar>
                <span class="text-subtitle-1 font-weight-bold">极影视同步强化</span>
              </div>
              
              <v-alert type="warning" variant="tonal" class="mb-4 border-warning border-opacity-50 font-weight-medium bg-white">
                检测到配置中包含极影视服务端。开启以下轮询可有效捕获极影视独立产生的主动进度变化。
              </v-alert>

              <v-card variant="outlined" class="mb-8 rounded-lg bg-white border-opacity-50">
                <v-card-text class="pa-5">
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

          <!-- 同步组配置区域 -->
          <div class="d-flex align-center mt-6 mb-3 text-success">
             <v-avatar color="success-lighten-4" class="mr-3 text-success-darken-1" size="36">
              <v-icon>mdi-account-group</v-icon>
            </v-avatar>
            <span class="text-subtitle-1 font-weight-bold">同步组配置 (联络网)</span>
            <v-spacer></v-spacer>
            <v-btn color="success" size="small" variant="flat" rounded="pill" class="px-4 shadow-sm" @click="addSyncGroup">
              <v-icon left size="small" class="mr-1">mdi-plus-circle</v-icon>
              建立新同步组
            </v-btn>
          </div>

          <v-alert v-if="config.sync_groups.length === 0" type="info" variant="tonal" class="mb-6 border border-info border-opacity-50 bg-info-lighten-5 text-indigo-darken-3">
            <template #prepend><v-icon>mdi-information-outline</v-icon></template>
            当前无已添加的同步组。请添加并建立联系组，将多端的账号绑定在一起进行数据互通。
          </v-alert>

          <!-- 具体组渲染 -->
          <v-card v-for="(group, groupIndex) in config.sync_groups" :key="groupIndex" class="mb-5 rounded-lg border-opacity-50 border-success bg-white shadow-sm" variant="outlined">
            
            <v-toolbar density="compact" color="success" variant="tonal" class="px-2">
              <v-icon size="small" class="ml-2 mr-3" color="success">mdi-account-network</v-icon>
              <v-toolbar-title class="text-subtitle-2 font-weight-bold text-success-darken-3">
                {{ group.name || `未命名组合 ${groupIndex + 1}` }}
              </v-toolbar-title>
              <v-spacer></v-spacer>
              
              <v-switch
                v-model="group.enabled"
                color="success"
                density="compact"
                hide-details
                label="联通开关"
                class="mr-4 text-caption font-weight-medium"
              ></v-switch>

              <v-btn icon variant="flat" color="error-lighten-1" size="x-small" @click="removeSyncGroup(groupIndex)" class="elevation-1 bg-white">
                <v-icon size="small">mdi-delete</v-icon>
                <v-tooltip activator="parent" location="top">删除此组</v-tooltip>
              </v-btn>
            </v-toolbar>

            <v-card-text class="pt-5 pb-3">
              <v-row class="mb-4">
                <v-col cols="12" md="12">
                  <v-text-field
                    v-model="group.name"
                    label="同步组名称标注"
                    variant="outlined"
                    density="comfortable"
                    color="success"
                    prepend-inner-icon="mdi-pencil-outline"
                    placeholder="如：极空间TV客厅组 & 卧室Emby账号"
                    hide-details="auto"
                  ></v-text-field>
                </v-col>
              </v-row>

              <!-- 组内用户列表 -->
              <v-divider class="mb-4 border-dashed"></v-divider>
              <div class="d-flex align-center justify-space-between mb-3 text-secondary">
                <span class="text-subtitle-2 font-weight-medium">组内关联账号 ({{ group.users?.length || 0 }} 人)</span>
                <v-btn
                  color="info"
                  variant="text"
                  size="small"
                  class="bg-info-lighten-5 border-info border-opacity-25"
                  rounded="lg"
                  @click="addGroupUser(groupIndex)"
                >
                  <v-icon left size="small">mdi-account-plus</v-icon>关联新账号
                </v-btn>
              </div>

              <div v-if="group.users && group.users.length">
                <v-row v-for="(user, userIndex) in group.users" :key="userIndex" class="mb-2 align-center bg-grey-lighten-5 rounded mx-0 pa-2 border">
                  
                  <v-col cols="12" md="1" class="text-center pa-1">
                    <v-avatar size="32" color="blue-grey-lighten-4" class="text-blue-grey-darken-2 font-weight-bold">
                      {{ userIndex + 1 }}
                    </v-avatar>
                  </v-col>

                  <v-col cols="12" md="5" class="py-1 px-2">
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
                  </v-col>

                  <v-col cols="12" md="5" class="py-1 px-2">
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
                  </v-col>
                  
                  <v-col cols="12" md="1" class="d-flex align-center justify-center pa-1 text-center">
                    <v-btn color="grey" variant="text" size="small" icon @click="removeGroupUser(groupIndex, userIndex)">
                      <v-icon>mdi-close</v-icon>
                      <v-tooltip activator="parent" location="left">移除这个账号对象</v-tooltip>
                    </v-btn>
                  </v-col>
                </v-row>
              </div>
              <div v-else class="text-center text-medium-emphasis py-6 bg-grey-lighten-4 rounded-lg border-dashed">
                <v-icon size="40" color="grey-lighten-1" class="mb-2">mdi-account-multiple-remove-outline</v-icon>
                <div class="text-body-2">当前组尚未绑定任何账号角色</div>
              </div>
            </v-card-text>
          </v-card>
        </v-form>
      </v-card-text>

      <!-- 底部操作栏 -->
      <v-card-actions class="px-5 py-3 border-t bg-white">
        <v-btn color="primary" variant="flat" rounded="pill" class="px-6 font-weight-bold shadow-sm" @click="saveConfig" :loading="saving">
          <v-icon left>mdi-content-save-check</v-icon>保存总体应用
        </v-btn>
        
        <v-btn color="blue-grey-darken-1" variant="tonal" rounded="pill" class="px-5 mx-2 font-weight-medium" @click="resetForm">
          <v-icon left>mdi-undo-variant</v-icon>重置默认
        </v-btn>
        
        <v-spacer></v-spacer>
        
        <v-btn color="info" variant="text" rounded="pill" class="font-weight-medium px-4" @click="notifySwitch">
          查看统计面板 <v-icon right>mdi-arrow-right-top</v-icon>
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
.shadow-sm {
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.05);
}
.border-dashed {
  border-style: dashed !important;
}
</style>
