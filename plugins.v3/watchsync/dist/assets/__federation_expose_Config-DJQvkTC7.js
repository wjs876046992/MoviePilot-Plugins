import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createElementBlock:_createElementBlock,renderList:_renderList,Fragment:_Fragment,withModifiers:_withModifiers} = await importShared('vue');


const _hoisted_1 = { class: "plugin-config" };
const _hoisted_2 = { class: "header-icon-box mr-3" };
const _hoisted_3 = {
  key: 0,
  class: "px-5 pt-3"
};
const _hoisted_4 = { class: "section-label d-flex align-center mb-2" };
const _hoisted_5 = { class: "setting-row d-flex align-center justify-space-between px-4 py-3" };
const _hoisted_6 = { class: "d-flex align-center mr-3" };
const _hoisted_7 = { class: "setting-icon-box mr-3 setting-icon-primary" };
const _hoisted_8 = { class: "px-4 py-3" };
const _hoisted_9 = { class: "d-flex align-center justify-space-between" };
const _hoisted_10 = { class: "d-flex align-center mr-2" };
const _hoisted_11 = { class: "d-flex align-center justify-space-between" };
const _hoisted_12 = { class: "d-flex align-center mr-2" };
const _hoisted_13 = { class: "px-4 py-3" };
const _hoisted_14 = {
  key: 0,
  class: "mb-5"
};
const _hoisted_15 = { class: "section-label d-flex align-center mb-2" };
const _hoisted_16 = { class: "setting-row d-flex align-center justify-space-between px-4 py-3" };
const _hoisted_17 = { class: "d-flex align-center mr-3" };
const _hoisted_18 = { class: "setting-icon-box mr-3 setting-icon-warning" };
const _hoisted_19 = { key: 0 };
const _hoisted_20 = { class: "px-4 py-3" };
const _hoisted_21 = { class: "d-flex align-center justify-space-between mb-3" };
const _hoisted_22 = { class: "section-label d-flex align-center" };
const _hoisted_23 = {
  key: 0,
  class: "empty-sync-box rounded-xl pa-8 text-center mb-4"
};
const _hoisted_24 = { class: "empty-icon-wrapper mb-3" };
const _hoisted_25 = {
  key: 1,
  class: "sync-groups-list"
};
const _hoisted_26 = { class: "group-header d-flex align-center justify-space-between px-4 py-3" };
const _hoisted_27 = { class: "d-flex align-center flex-grow-1 mr-3 overflow-hidden" };
const _hoisted_28 = { class: "group-header-badge mr-2" };
const _hoisted_29 = { class: "font-weight-bold text-body-2 text-truncate" };
const _hoisted_30 = { class: "d-flex align-center flex-shrink-0" };
const _hoisted_31 = { class: "pa-4" };
const _hoisted_32 = { class: "d-flex align-center justify-space-between mb-3" };
const _hoisted_33 = { class: "text-caption font-weight-bold text-medium-emphasis d-flex align-center" };
const _hoisted_34 = {
  key: 0,
  class: "endpoint-nodes-container"
};
const _hoisted_35 = { class: "d-flex align-center flex-shrink-0 mr-1" };
const _hoisted_36 = { class: "node-number-badge font-weight-bold" };
const _hoisted_37 = { class: "flex-grow-1 node-field-box" };
const _hoisted_38 = { class: "node-sync-indicator d-none d-sm-flex align-center justify-center flex-shrink-0" };
const _hoisted_39 = { class: "flex-grow-1 node-field-box" };
const _hoisted_40 = { class: "flex-shrink-0" };
const _hoisted_41 = ["onClick"];

const {ref,reactive,computed,onMounted} = await importShared('vue');


// 接收初始配置

const _sfc_main = {
  __name: 'Config',
  props: {
  initialConfig: {
    type: Object,
    default: () => ({}),
  },
  api: {
    type: Object,
    default: () => {},
  },
},
  emits: ['save', 'close', 'switch'],
  setup(__props, { emit: __emit }) {

const props = __props;

// 表单状态
const form = ref(null);
const isFormValid = ref(true);
const error = ref(null);
const successMessage = ref(null);
const saving = ref(false);

// 数据状态
const embyServers = ref([]);
const serverUsers = ref({});
const loadingUsers = ref({});


// 配置数据，使用默认值和初始配置合并
const defaultConfig = {
  enabled: true,
  sync_movies: true,
  sync_tv: true,
  min_watch_time: 300,
  zspace_poll_enabled: true,
  zspace_poll_interval: 30,
  sync_groups: [],
};

// 合并默认配置和初始配置
const config = reactive({ ...defaultConfig });

// 初始化配置
onMounted(async () => {
  // 加载初始配置
  if (props.initialConfig) {
    Object.keys(props.initialConfig).forEach(key => {
      if (key in config) {
        config[key] = props.initialConfig[key];
      }
    });
  }

  // 加载Emby服务器列表
  await loadEmbyServers();
});

// 自定义事件，用于保存配置
const emit = __emit;

// 加载Emby服务器列表
async function loadEmbyServers() {
  try {
    // 检查props.api是否可用
    if (!props.api) {
      error.value = 'API对象不可用，请检查插件配置';
      return
    }

    if (typeof props.api.get !== 'function') {
      error.value = 'API调用方法不可用';
      return
    }

    const result = await props.api.get('plugin/WatchSync/servers');

    if (result && result.success) {
      embyServers.value = result.data || [];

      // 清除之前的错误信息
      error.value = null;

      if (embyServers.value.length === 0) {
        error.value = '没有找到可用的Emby服务器，请检查MoviePilot的媒体服务器配置';
      } else {
        // 预加载所有服务器的用户列表
        loadAllServerUsers();
      }
    } else {
      error.value = `加载服务器列表失败: ${result?.message || '未知错误'}`;
    }
  } catch (err) {
    error.value = `加载服务器列表失败: ${err.message}`;
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
});

function isZspaceServer(serverName) {
  if (!serverName) {
    return false
  }
  const server = embyServers.value.find(item => item.name === serverName);
  if (server?.type === 'zspace') {
    return true
  }
  const normalized = String(serverName).toLowerCase();
  return ['zspace', 'zvideo', 'jiyingshi', 'qizhi', '极影视', '极空间'].some(alias => normalized.includes(alias))
}

// 加载所有服务器的用户列表
async function loadAllServerUsers() {
  try {
    // 检查props.api是否可用
    if (!props.api || typeof props.api.get !== 'function') {
      return
    }

    const result = await props.api.get('plugin/WatchSync/users');

    if (result && result.success) {
      const allUsersData = result.data || {};

      // 存储所有服务器的用户数据
      for (const [serverName, userData] of Object.entries(allUsersData)) {
        serverUsers.value[serverName] = userData || [];
      }

      // 清除之前的错误信息
      error.value = null;

    } else {
      error.value = `加载用户列表失败: ${result?.message || '未知错误'}`;
    }
  } catch (err) {
    error.value = `加载用户列表失败: ${err.message}`;
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

  loadingUsers.value[serverName] = true;

  try {
    // 如果还没有加载过任何用户数据，先加载所有服务器的用户
    if (Object.keys(serverUsers.value).length === 0) {
      await loadAllServerUsers();
    }
  } catch (err) {
    console.error('加载用户列表失败:', err);
  } finally {
    loadingUsers.value[serverName] = false;
  }
}

// 添加同步组
function addSyncGroup() {
  config.sync_groups.push({
    name: '',
    enabled: true,
    users: []
  });
}

// 删除同步组
function removeSyncGroup(index) {
  config.sync_groups.splice(index, 1);
}

// 添加组内用户
function addGroupUser(groupIndex) {
  if (!config.sync_groups[groupIndex].users) {
    config.sync_groups[groupIndex].users = [];
  }
  config.sync_groups[groupIndex].users.push({
    server: '',
    username: ''
  });
}

// 删除组内用户
function removeGroupUser(groupIndex, userIndex) {
  config.sync_groups[groupIndex].users.splice(userIndex, 1);
}

// 组内用户服务器变更时的处理
function onGroupUserServerChange(groupIndex, userIndex) {
  const user = config.sync_groups[groupIndex].users[userIndex];

  // 清空用户名
  user.username = '';

  if (user.server) {
    // 检查是否已经有缓存的用户数据
    const cachedUsers = getServerUsers(user.server);

    if (cachedUsers.length === 0) {
      loadServerUsers(user.server);
    }
  }
}

// 保存配置
async function saveConfig() {
  if (!isFormValid.value) {
    error.value = '请修正表单错误';
    return
  }

  saving.value = true;
  error.value = null;
  successMessage.value = null;

  try {
    // 发送保存事件
    emit('save', { ...config });
    successMessage.value = '配置保存成功，稍后生效配置即可。';
  } catch (err) {
    console.error('保存配置失败:', err);
    error.value = err.message || '保存配置失败';
  } finally {
    saving.value = false;
  }
}

// 重置表单
function resetForm() {
  Object.keys(defaultConfig).forEach(key => {
    config[key] = defaultConfig[key];
  });

  if (form.value) {
    form.value.resetValidation();
  }
}

// 通知主应用关闭组件
function notifyClose() {
  emit('close');
}

// 通知主应用切换到统计页面
function notifySwitch() {
  emit('switch');
}

return (_ctx, _cache) => {
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_chip = _resolveComponent("v-chip");
  const _component_v_card_title = _resolveComponent("v-card-title");
  const _component_v_tooltip = _resolveComponent("v-tooltip");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_card_item = _resolveComponent("v-card-item");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_expand_transition = _resolveComponent("v-expand-transition");
  const _component_v_switch = _resolveComponent("v-switch");
  const _component_v_divider = _resolveComponent("v-divider");
  const _component_v_col = _resolveComponent("v-col");
  const _component_v_row = _resolveComponent("v-row");
  const _component_v_text_field = _resolveComponent("v-text-field");
  const _component_v_card = _resolveComponent("v-card");
  const _component_v_select = _resolveComponent("v-select");
  const _component_v_form = _resolveComponent("v-form");
  const _component_v_card_text = _resolveComponent("v-card-text");
  const _component_v_spacer = _resolveComponent("v-spacer");
  const _component_v_card_actions = _resolveComponent("v-card-actions");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_v_card, {
      class: "d-flex flex-column h-100 rounded-xl overflow-hidden config-main-card",
      elevation: "0",
      variant: "outlined"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_v_card_item, { class: "header-surface px-5 py-4" }, {
          prepend: _withCtx(() => [
            _createElementVNode("div", _hoisted_2, [
              _createVNode(_component_v_icon, {
                color: "primary",
                size: "22"
              }, {
                default: _withCtx(() => [...(_cache[9] || (_cache[9] = [
                  _createTextVNode("mdi-sync-circle", -1)
                ]))]),
                _: 1
              })
            ])
          ]),
          append: _withCtx(() => [
            _createVNode(_component_v_btn, {
              icon: "",
              variant: "text",
              size: "small",
              class: "rounded-lg close-btn",
              onClick: notifyClose
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_icon, { size: "18" }, {
                  default: _withCtx(() => [...(_cache[13] || (_cache[13] = [
                    _createTextVNode("mdi-close", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_v_tooltip, {
                  activator: "parent",
                  location: "bottom"
                }, {
                  default: _withCtx(() => [...(_cache[14] || (_cache[14] = [
                    _createTextVNode("关闭配置", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          default: _withCtx(() => [
            _createElementVNode("div", null, [
              _createVNode(_component_v_card_title, { class: "text-subtitle-1 font-weight-bold pa-0 text-slate-800 d-flex align-center" }, {
                default: _withCtx(() => [
                  _cache[11] || (_cache[11] = _createTextVNode(" 观看记录同步配置 ", -1)),
                  _createVNode(_component_v_chip, {
                    size: "x-small",
                    color: "primary",
                    variant: "tonal",
                    class: "ml-2 font-weight-bold"
                  }, {
                    default: _withCtx(() => [...(_cache[10] || (_cache[10] = [
                      _createTextVNode("v3.0.2", -1)
                    ]))]),
                    _: 1
                  })
                ]),
                _: 1
              }),
              _cache[12] || (_cache[12] = _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "设定全局同步策略与多端设备用户映射网络", -1))
            ])
          ]),
          _: 1
        }),
        _createVNode(_component_v_expand_transition, null, {
          default: _withCtx(() => [
            (successMessage.value || error.value)
              ? (_openBlock(), _createElementBlock("div", _hoisted_3, [
                  (successMessage.value)
                    ? (_openBlock(), _createBlock(_component_v_alert, {
                        key: 0,
                        type: "success",
                        variant: "tonal",
                        class: "rounded-lg font-weight-medium",
                        closable: "",
                        "onClick:close": _cache[0] || (_cache[0] = $event => (successMessage.value = null))
                      }, {
                        default: _withCtx(() => [
                          _createTextVNode(_toDisplayString(successMessage.value), 1)
                        ]),
                        _: 1
                      }))
                    : _createCommentVNode("", true),
                  (error.value)
                    ? (_openBlock(), _createBlock(_component_v_alert, {
                        key: 1,
                        type: "error",
                        variant: "tonal",
                        class: "rounded-lg",
                        closable: "",
                        "onClick:close": _cache[1] || (_cache[1] = $event => (error.value = null))
                      }, {
                        default: _withCtx(() => [
                          _createTextVNode(_toDisplayString(error.value), 1)
                        ]),
                        _: 1
                      }))
                    : _createCommentVNode("", true)
                ]))
              : _createCommentVNode("", true)
          ]),
          _: 1
        }),
        _createVNode(_component_v_card_text, { class: "config-body overflow-y-auto px-5 py-4 flex-grow-1" }, {
          default: _withCtx(() => [
            _createVNode(_component_v_form, {
              ref_key: "form",
              ref: form,
              modelValue: isFormValid.value,
              "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((isFormValid).value = $event)),
              onSubmit: _withModifiers(saveConfig, ["prevent"])
            }, {
              default: _withCtx(() => [
                _createElementVNode("div", _hoisted_4, [
                  _createVNode(_component_v_icon, {
                    size: "16",
                    color: "primary",
                    class: "mr-1"
                  }, {
                    default: _withCtx(() => [...(_cache[15] || (_cache[15] = [
                      _createTextVNode("mdi-tune-variant", -1)
                    ]))]),
                    _: 1
                  }),
                  _cache[16] || (_cache[16] = _createElementVNode("span", { class: "text-caption font-weight-bold text-uppercase text-medium-emphasis tracking-wider" }, "全局同步策略", -1))
                ]),
                _createVNode(_component_v_card, {
                  variant: "outlined",
                  class: "settings-group-card rounded-xl mb-5"
                }, {
                  default: _withCtx(() => [
                    _createElementVNode("div", _hoisted_5, [
                      _createElementVNode("div", _hoisted_6, [
                        _createElementVNode("div", _hoisted_7, [
                          _createVNode(_component_v_icon, {
                            size: "18",
                            color: "primary"
                          }, {
                            default: _withCtx(() => [...(_cache[17] || (_cache[17] = [
                              _createTextVNode("mdi-power", -1)
                            ]))]),
                            _: 1
                          })
                        ]),
                        _cache[18] || (_cache[18] = _createElementVNode("div", null, [
                          _createElementVNode("div", { class: "font-weight-bold text-body-2" }, "同步引擎主开关"),
                          _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "开启后将自动监听并双向同步多服务器间的播放进度与已看状态")
                        ], -1))
                      ]),
                      _createVNode(_component_v_switch, {
                        modelValue: config.enabled,
                        "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((config.enabled) = $event)),
                        color: "primary",
                        inset: "",
                        "hide-details": "",
                        density: "compact",
                        class: "flex-shrink-0"
                      }, null, 8, ["modelValue"])
                    ]),
                    _createVNode(_component_v_divider, { class: "row-divider" }),
                    _createElementVNode("div", _hoisted_8, [
                      _createVNode(_component_v_row, { align: "center" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_col, {
                            cols: "12",
                            sm: "6",
                            class: "py-1"
                          }, {
                            default: _withCtx(() => [
                              _createElementVNode("div", _hoisted_9, [
                                _createElementVNode("div", _hoisted_10, [
                                  _createVNode(_component_v_icon, {
                                    size: "18",
                                    color: "info",
                                    class: "mr-2"
                                  }, {
                                    default: _withCtx(() => [...(_cache[19] || (_cache[19] = [
                                      _createTextVNode("mdi-movie-outline", -1)
                                    ]))]),
                                    _: 1
                                  }),
                                  _cache[20] || (_cache[20] = _createElementVNode("span", { class: "text-body-2 font-weight-medium" }, "同步电影记录", -1))
                                ]),
                                _createVNode(_component_v_switch, {
                                  modelValue: config.sync_movies,
                                  "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((config.sync_movies) = $event)),
                                  color: "info",
                                  inset: "",
                                  "hide-details": "",
                                  density: "compact"
                                }, null, 8, ["modelValue"])
                              ])
                            ]),
                            _: 1
                          }),
                          _createVNode(_component_v_col, {
                            cols: "12",
                            sm: "6",
                            class: "py-1"
                          }, {
                            default: _withCtx(() => [
                              _createElementVNode("div", _hoisted_11, [
                                _createElementVNode("div", _hoisted_12, [
                                  _createVNode(_component_v_icon, {
                                    size: "18",
                                    color: "info",
                                    class: "mr-2"
                                  }, {
                                    default: _withCtx(() => [...(_cache[21] || (_cache[21] = [
                                      _createTextVNode("mdi-television-box", -1)
                                    ]))]),
                                    _: 1
                                  }),
                                  _cache[22] || (_cache[22] = _createElementVNode("span", { class: "text-body-2 font-weight-medium" }, "同步电视剧记录", -1))
                                ]),
                                _createVNode(_component_v_switch, {
                                  modelValue: config.sync_tv,
                                  "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((config.sync_tv) = $event)),
                                  color: "info",
                                  inset: "",
                                  "hide-details": "",
                                  density: "compact"
                                }, null, 8, ["modelValue"])
                              ])
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      })
                    ]),
                    _createVNode(_component_v_divider, { class: "row-divider" }),
                    _createElementVNode("div", _hoisted_13, [
                      _createVNode(_component_v_row, { align: "center" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_col, {
                            cols: "12",
                            md: "7"
                          }, {
                            default: _withCtx(() => [...(_cache[23] || (_cache[23] = [
                              _createElementVNode("div", { class: "text-body-2 font-weight-medium" }, "有效观看时长门槛", -1),
                              _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "播放时间超过此阈值才触发自动同步，防止误点触发，推荐 300 秒", -1)
                            ]))]),
                            _: 1
                          }),
                          _createVNode(_component_v_col, {
                            cols: "12",
                            md: "5"
                          }, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_text_field, {
                                modelValue: config.min_watch_time,
                                "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((config.min_watch_time) = $event)),
                                modelModifiers: { number: true },
                                variant: "outlined",
                                density: "compact",
                                type: "number",
                                min: "0",
                                suffix: "秒",
                                "hide-details": "",
                                color: "primary",
                                "prepend-inner-icon": "mdi-timer-outline",
                                class: "rounded-lg"
                              }, null, 8, ["modelValue"])
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      })
                    ])
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_expand_transition, null, {
                  default: _withCtx(() => [
                    (hasZspaceInGroups.value)
                      ? (_openBlock(), _createElementBlock("div", _hoisted_14, [
                          _createElementVNode("div", _hoisted_15, [
                            _createVNode(_component_v_icon, {
                              size: "16",
                              color: "warning",
                              class: "mr-1"
                            }, {
                              default: _withCtx(() => [...(_cache[24] || (_cache[24] = [
                                _createTextVNode("mdi-television-classic", -1)
                              ]))]),
                              _: 1
                            }),
                            _cache[26] || (_cache[26] = _createElementVNode("span", { class: "text-caption font-weight-bold text-uppercase text-medium-emphasis tracking-wider" }, "极空间专属扩展", -1)),
                            _createVNode(_component_v_chip, {
                              size: "x-small",
                              color: "warning",
                              variant: "tonal",
                              class: "ml-2 font-weight-bold"
                            }, {
                              default: _withCtx(() => [...(_cache[25] || (_cache[25] = [
                                _createTextVNode("已检测到极影视", -1)
                              ]))]),
                              _: 1
                            })
                          ]),
                          _createVNode(_component_v_card, {
                            variant: "outlined",
                            class: "settings-group-card rounded-xl zspace-card"
                          }, {
                            default: _withCtx(() => [
                              _createElementVNode("div", _hoisted_16, [
                                _createElementVNode("div", _hoisted_17, [
                                  _createElementVNode("div", _hoisted_18, [
                                    _createVNode(_component_v_icon, {
                                      size: "18",
                                      color: "warning"
                                    }, {
                                      default: _withCtx(() => [...(_cache[27] || (_cache[27] = [
                                        _createTextVNode("mdi-timer-sync-outline", -1)
                                      ]))]),
                                      _: 1
                                    })
                                  ]),
                                  _cache[28] || (_cache[28] = _createElementVNode("div", null, [
                                    _createElementVNode("div", { class: "font-weight-bold text-body-2" }, "从极影视主动轮询进度"),
                                    _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "极影视无被动 Webhook，开启定时轮询可捕获其独立产生的进度同步至 Emby")
                                  ], -1))
                                ]),
                                _createVNode(_component_v_switch, {
                                  modelValue: config.zspace_poll_enabled,
                                  "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((config.zspace_poll_enabled) = $event)),
                                  color: "warning",
                                  inset: "",
                                  "hide-details": "",
                                  density: "compact",
                                  class: "flex-shrink-0"
                                }, null, 8, ["modelValue"])
                              ]),
                              _createVNode(_component_v_expand_transition, null, {
                                default: _withCtx(() => [
                                  (config.zspace_poll_enabled)
                                    ? (_openBlock(), _createElementBlock("div", _hoisted_19, [
                                        _createVNode(_component_v_divider, { class: "row-divider" }),
                                        _createElementVNode("div", _hoisted_20, [
                                          _createVNode(_component_v_row, { align: "center" }, {
                                            default: _withCtx(() => [
                                              _createVNode(_component_v_col, {
                                                cols: "12",
                                                md: "7"
                                              }, {
                                                default: _withCtx(() => [...(_cache[29] || (_cache[29] = [
                                                  _createElementVNode("div", { class: "text-body-2 font-weight-medium" }, "轮询探测间隔", -1),
                                                  _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "数值越小同步越及时，建议设为 30 秒", -1)
                                                ]))]),
                                                _: 1
                                              }),
                                              _createVNode(_component_v_col, {
                                                cols: "12",
                                                md: "5"
                                              }, {
                                                default: _withCtx(() => [
                                                  _createVNode(_component_v_text_field, {
                                                    modelValue: config.zspace_poll_interval,
                                                    "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((config.zspace_poll_interval) = $event)),
                                                    modelModifiers: { number: true },
                                                    variant: "outlined",
                                                    density: "compact",
                                                    type: "number",
                                                    min: "10",
                                                    step: "5",
                                                    suffix: "秒",
                                                    "hide-details": "",
                                                    color: "warning",
                                                    "prepend-inner-icon": "mdi-av-timer",
                                                    class: "rounded-lg"
                                                  }, null, 8, ["modelValue"])
                                                ]),
                                                _: 1
                                              })
                                            ]),
                                            _: 1
                                          })
                                        ])
                                      ]))
                                    : _createCommentVNode("", true)
                                ]),
                                _: 1
                              })
                            ]),
                            _: 1
                          })
                        ]))
                      : _createCommentVNode("", true)
                  ]),
                  _: 1
                }),
                _createElementVNode("div", _hoisted_21, [
                  _createElementVNode("div", _hoisted_22, [
                    _createVNode(_component_v_icon, {
                      size: "16",
                      color: "success",
                      class: "mr-1"
                    }, {
                      default: _withCtx(() => [...(_cache[30] || (_cache[30] = [
                        _createTextVNode("mdi-lan-connect", -1)
                      ]))]),
                      _: 1
                    }),
                    _cache[31] || (_cache[31] = _createElementVNode("span", { class: "text-caption font-weight-bold text-uppercase text-medium-emphasis tracking-wider" }, "同步互联组网络", -1)),
                    _createVNode(_component_v_chip, {
                      size: "x-small",
                      color: "success",
                      variant: "tonal",
                      class: "ml-2 font-weight-bold"
                    }, {
                      default: _withCtx(() => [
                        _createTextVNode(_toDisplayString(config.sync_groups.length) + " 组 ", 1)
                      ]),
                      _: 1
                    })
                  ]),
                  _createVNode(_component_v_btn, {
                    color: "primary",
                    size: "small",
                    variant: "tonal",
                    rounded: "lg",
                    class: "font-weight-medium",
                    onClick: addSyncGroup
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_icon, {
                        start: "",
                        size: "16"
                      }, {
                        default: _withCtx(() => [...(_cache[32] || (_cache[32] = [
                          _createTextVNode("mdi-plus", -1)
                        ]))]),
                        _: 1
                      }),
                      _cache[33] || (_cache[33] = _createTextVNode(" 添加同步组 ", -1))
                    ]),
                    _: 1
                  })
                ]),
                (config.sync_groups.length === 0)
                  ? (_openBlock(), _createElementBlock("div", _hoisted_23, [
                      _createElementVNode("div", _hoisted_24, [
                        _createVNode(_component_v_icon, {
                          size: "36",
                          color: "primary"
                        }, {
                          default: _withCtx(() => [...(_cache[34] || (_cache[34] = [
                            _createTextVNode("mdi-account-network-outline", -1)
                          ]))]),
                          _: 1
                        })
                      ]),
                      _cache[37] || (_cache[37] = _createElementVNode("div", { class: "text-subtitle-2 font-weight-bold text-medium-emphasis" }, "暂未创建同步组", -1)),
                      _cache[38] || (_cache[38] = _createElementVNode("div", { class: "text-caption text-disabled mt-1 mb-4" }, "创建同步组后，可将不同服务端的多个账号绑定为一个互通群组", -1)),
                      _createVNode(_component_v_btn, {
                        color: "primary",
                        variant: "flat",
                        size: "small",
                        rounded: "lg",
                        onClick: addSyncGroup
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_icon, {
                            start: "",
                            size: "16"
                          }, {
                            default: _withCtx(() => [...(_cache[35] || (_cache[35] = [
                              _createTextVNode("mdi-plus", -1)
                            ]))]),
                            _: 1
                          }),
                          _cache[36] || (_cache[36] = _createTextVNode(" 创建第一个同步组 ", -1))
                        ]),
                        _: 1
                      })
                    ]))
                  : (_openBlock(), _createElementBlock("div", _hoisted_25, [
                      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(config.sync_groups, (group, groupIndex) => {
                        return (_openBlock(), _createBlock(_component_v_card, {
                          key: groupIndex,
                          variant: "outlined",
                          class: "group-panel-card rounded-xl mb-4 overflow-hidden"
                        }, {
                          default: _withCtx(() => [
                            _createElementVNode("div", _hoisted_26, [
                              _createElementVNode("div", _hoisted_27, [
                                _createElementVNode("div", _hoisted_28, [
                                  _createVNode(_component_v_icon, {
                                    size: "16",
                                    color: "primary"
                                  }, {
                                    default: _withCtx(() => [...(_cache[39] || (_cache[39] = [
                                      _createTextVNode("mdi-folder-network-outline", -1)
                                    ]))]),
                                    _: 1
                                  })
                                ]),
                                _createElementVNode("span", _hoisted_29, _toDisplayString(group.name || `未命名同步组 ${groupIndex + 1}`), 1),
                                _createVNode(_component_v_chip, {
                                  size: "x-small",
                                  variant: "tonal",
                                  color: "primary",
                                  class: "ml-2 flex-shrink-0 font-weight-medium"
                                }, {
                                  default: _withCtx(() => [
                                    _createTextVNode(_toDisplayString(group.users?.length || 0) + " 个端点 ", 1)
                                  ]),
                                  _: 2
                                }, 1024)
                              ]),
                              _createElementVNode("div", _hoisted_30, [
                                _createVNode(_component_v_switch, {
                                  modelValue: group.enabled,
                                  "onUpdate:modelValue": $event => ((group.enabled) = $event),
                                  color: "primary",
                                  density: "compact",
                                  "hide-details": "",
                                  label: "启用",
                                  class: "mr-3 font-weight-medium text-caption"
                                }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                                _createVNode(_component_v_btn, {
                                  icon: "",
                                  variant: "text",
                                  color: "error",
                                  size: "small",
                                  class: "rounded-lg",
                                  onClick: $event => (removeSyncGroup(groupIndex))
                                }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_icon, { size: "18" }, {
                                      default: _withCtx(() => [...(_cache[40] || (_cache[40] = [
                                        _createTextVNode("mdi-delete-outline", -1)
                                      ]))]),
                                      _: 1
                                    }),
                                    _createVNode(_component_v_tooltip, {
                                      activator: "parent",
                                      location: "top"
                                    }, {
                                      default: _withCtx(() => [...(_cache[41] || (_cache[41] = [
                                        _createTextVNode("删除此组", -1)
                                      ]))]),
                                      _: 1
                                    })
                                  ]),
                                  _: 1
                                }, 8, ["onClick"])
                              ])
                            ]),
                            _createVNode(_component_v_divider, { class: "row-divider" }),
                            _createElementVNode("div", _hoisted_31, [
                              _createVNode(_component_v_text_field, {
                                modelValue: group.name,
                                "onUpdate:modelValue": $event => ((group.name) = $event),
                                label: "同步组名称",
                                placeholder: "例如：客厅极空间TV 与 卧室Emby互通",
                                variant: "outlined",
                                density: "compact",
                                color: "primary",
                                "prepend-inner-icon": "mdi-tag-outline",
                                "hide-details": "auto",
                                class: "mb-4 rounded-lg"
                              }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                              _createElementVNode("div", _hoisted_32, [
                                _createElementVNode("span", _hoisted_33, [
                                  _createVNode(_component_v_icon, {
                                    size: "15",
                                    class: "mr-1 text-primary"
                                  }, {
                                    default: _withCtx(() => [...(_cache[42] || (_cache[42] = [
                                      _createTextVNode("mdi-account-multiple", -1)
                                    ]))]),
                                    _: 1
                                  }),
                                  _cache[43] || (_cache[43] = _createTextVNode(" 组内互通账号节点 ", -1))
                                ]),
                                _createVNode(_component_v_btn, {
                                  color: "primary",
                                  variant: "text",
                                  size: "small",
                                  class: "font-weight-medium px-2",
                                  onClick: $event => (addGroupUser(groupIndex))
                                }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_icon, {
                                      start: "",
                                      size: "16"
                                    }, {
                                      default: _withCtx(() => [...(_cache[44] || (_cache[44] = [
                                        _createTextVNode("mdi-account-plus-outline", -1)
                                      ]))]),
                                      _: 1
                                    }),
                                    _cache[45] || (_cache[45] = _createTextVNode(" 添加账号节点 ", -1))
                                  ]),
                                  _: 1
                                }, 8, ["onClick"])
                              ]),
                              (group.users && group.users.length)
                                ? (_openBlock(), _createElementBlock("div", _hoisted_34, [
                                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(group.users, (user, userIndex) => {
                                      return (_openBlock(), _createElementBlock("div", {
                                        key: userIndex,
                                        class: "endpoint-node-card d-flex align-center flex-wrap ga-2 rounded-lg pa-3 mb-2"
                                      }, [
                                        _createElementVNode("div", _hoisted_35, [
                                          _createElementVNode("div", _hoisted_36, _toDisplayString(userIndex + 1), 1)
                                        ]),
                                        _createElementVNode("div", _hoisted_37, [
                                          _createVNode(_component_v_select, {
                                            modelValue: user.server,
                                            "onUpdate:modelValue": [$event => ((user.server) = $event), $event => (onGroupUserServerChange(groupIndex, userIndex))],
                                            items: embyServers.value,
                                            "item-title": "name",
                                            "item-value": "name",
                                            label: "选择服务端",
                                            variant: "outlined",
                                            density: "compact",
                                            color: "primary",
                                            "hide-details": "auto",
                                            "prepend-inner-icon": "mdi-server-network"
                                          }, null, 8, ["modelValue", "onUpdate:modelValue", "items"])
                                        ]),
                                        _createElementVNode("div", _hoisted_38, [
                                          _createVNode(_component_v_icon, {
                                            size: "16",
                                            color: "primary"
                                          }, {
                                            default: _withCtx(() => [...(_cache[46] || (_cache[46] = [
                                              _createTextVNode("mdi-swap-horizontal", -1)
                                            ]))]),
                                            _: 1
                                          })
                                        ]),
                                        _createElementVNode("div", _hoisted_39, [
                                          _createVNode(_component_v_select, {
                                            modelValue: user.username,
                                            "onUpdate:modelValue": $event => ((user.username) = $event),
                                            items: getServerUsers(user.server),
                                            "item-title": "name",
                                            "item-value": "name",
                                            label: "选择对应用户",
                                            variant: "outlined",
                                            density: "compact",
                                            color: "primary",
                                            "prepend-inner-icon": "mdi-account-outline",
                                            loading: loadingUsers.value[user.server],
                                            hint: user.server ? `${getServerUsers(user.server).length} 个可用用户` : '请先在左侧选择服务端',
                                            "persistent-hint": ""
                                          }, null, 8, ["modelValue", "onUpdate:modelValue", "items", "loading", "hint"])
                                        ]),
                                        _createElementVNode("div", _hoisted_40, [
                                          _createVNode(_component_v_btn, {
                                            color: "error",
                                            variant: "text",
                                            size: "small",
                                            icon: "",
                                            class: "rounded-lg",
                                            onClick: $event => (removeGroupUser(groupIndex, userIndex))
                                          }, {
                                            default: _withCtx(() => [
                                              _createVNode(_component_v_icon, { size: "18" }, {
                                                default: _withCtx(() => [...(_cache[47] || (_cache[47] = [
                                                  _createTextVNode("mdi-close-circle-outline", -1)
                                                ]))]),
                                                _: 1
                                              }),
                                              _createVNode(_component_v_tooltip, {
                                                activator: "parent",
                                                location: "left"
                                              }, {
                                                default: _withCtx(() => [...(_cache[48] || (_cache[48] = [
                                                  _createTextVNode("移除此节点", -1)
                                                ]))]),
                                                _: 1
                                              })
                                            ]),
                                            _: 1
                                          }, 8, ["onClick"])
                                        ])
                                      ]))
                                    }), 128))
                                  ]))
                                : (_openBlock(), _createElementBlock("div", {
                                    key: 1,
                                    class: "node-empty-dashed-box d-flex align-center justify-center py-4 rounded-lg cursor-pointer",
                                    onClick: $event => (addGroupUser(groupIndex))
                                  }, [
                                    _createVNode(_component_v_icon, {
                                      size: "18",
                                      color: "primary",
                                      class: "mr-2"
                                    }, {
                                      default: _withCtx(() => [...(_cache[49] || (_cache[49] = [
                                        _createTextVNode("mdi-plus-circle-outline", -1)
                                      ]))]),
                                      _: 1
                                    }),
                                    _cache[50] || (_cache[50] = _createElementVNode("span", { class: "text-caption font-weight-medium text-primary" }, "点击添加组内第一个关联端点", -1))
                                  ], 8, _hoisted_41))
                            ])
                          ]),
                          _: 2
                        }, 1024))
                      }), 128))
                    ]))
              ]),
              _: 1
            }, 8, ["modelValue"])
          ]),
          _: 1
        }),
        _createVNode(_component_v_card_actions, { class: "footer-surface px-5 py-3" }, {
          default: _withCtx(() => [
            _createVNode(_component_v_btn, {
              color: "primary",
              variant: "flat",
              rounded: "lg",
              class: "px-5 font-weight-bold save-btn",
              onClick: saveConfig,
              loading: saving.value
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_icon, {
                  start: "",
                  size: "18"
                }, {
                  default: _withCtx(() => [...(_cache[51] || (_cache[51] = [
                    _createTextVNode("mdi-content-save-check", -1)
                  ]))]),
                  _: 1
                }),
                _cache[52] || (_cache[52] = _createTextVNode(" 保存配置 ", -1))
              ]),
              _: 1
            }, 8, ["loading"]),
            _createVNode(_component_v_btn, {
              color: "secondary",
              variant: "tonal",
              rounded: "lg",
              class: "px-4 ml-2 font-weight-medium",
              onClick: resetForm
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_icon, {
                  start: "",
                  size: "18"
                }, {
                  default: _withCtx(() => [...(_cache[53] || (_cache[53] = [
                    _createTextVNode("mdi-undo-variant", -1)
                  ]))]),
                  _: 1
                }),
                _cache[54] || (_cache[54] = _createTextVNode(" 重置 ", -1))
              ]),
              _: 1
            }),
            _createVNode(_component_v_spacer),
            _createVNode(_component_v_btn, {
              color: "primary",
              variant: "text",
              rounded: "lg",
              class: "font-weight-medium px-3",
              onClick: notifySwitch
            }, {
              default: _withCtx(() => [
                _cache[56] || (_cache[56] = _createTextVNode(" 查看统计面板 ", -1)),
                _createVNode(_component_v_icon, {
                  end: "",
                  size: "16"
                }, {
                  default: _withCtx(() => [...(_cache[55] || (_cache[55] = [
                    _createTextVNode("mdi-arrow-right", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    })
  ]))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-c1daa538"]]);

export { Config as default };
