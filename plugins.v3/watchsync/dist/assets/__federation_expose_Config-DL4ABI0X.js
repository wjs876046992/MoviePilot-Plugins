import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,toDisplayString:_toDisplayString,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createElementVNode:_createElementVNode,createElementBlock:_createElementBlock,renderList:_renderList,Fragment:_Fragment,withModifiers:_withModifiers} = await importShared('vue');


const _hoisted_1 = { class: "plugin-config" };
const _hoisted_2 = { class: "d-flex align-center mt-2 mb-3 text-primary" };
const _hoisted_3 = { class: "d-flex align-center mt-4 mb-3 text-info" };
const _hoisted_4 = { key: 0 };
const _hoisted_5 = { class: "d-flex align-center mt-4 mb-3 text-warning" };
const _hoisted_6 = { class: "d-flex align-center mt-6 mb-3 text-success" };
const _hoisted_7 = { class: "d-flex align-center justify-space-between mb-3 text-secondary" };
const _hoisted_8 = { class: "text-subtitle-2 font-weight-medium" };
const _hoisted_9 = { key: 0 };
const _hoisted_10 = {
  key: 1,
  class: "text-center text-medium-emphasis py-6 bg-grey-lighten-4 rounded-lg border-dashed"
};

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
  const _component_v_card_title = _resolveComponent("v-card-title");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_card_item = _resolveComponent("v-card-item");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_avatar = _resolveComponent("v-avatar");
  const _component_v_switch = _resolveComponent("v-switch");
  const _component_v_col = _resolveComponent("v-col");
  const _component_v_row = _resolveComponent("v-row");
  const _component_v_card_text = _resolveComponent("v-card-text");
  const _component_v_card = _resolveComponent("v-card");
  const _component_v_text_field = _resolveComponent("v-text-field");
  const _component_v_expand_transition = _resolveComponent("v-expand-transition");
  const _component_v_spacer = _resolveComponent("v-spacer");
  const _component_v_toolbar_title = _resolveComponent("v-toolbar-title");
  const _component_v_tooltip = _resolveComponent("v-tooltip");
  const _component_v_toolbar = _resolveComponent("v-toolbar");
  const _component_v_divider = _resolveComponent("v-divider");
  const _component_v_select = _resolveComponent("v-select");
  const _component_v_form = _resolveComponent("v-form");
  const _component_v_card_actions = _resolveComponent("v-card-actions");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_v_card, {
      class: "d-flex flex-column h-100 rounded-lg shadow-sm",
      elevation: "0",
      variant: "outlined"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_v_card_item, { class: "bg-primary text-white pa-4" }, {
          prepend: _withCtx(() => [
            _createVNode(_component_v_icon, {
              size: "x-large",
              class: "mr-2"
            }, {
              default: _withCtx(() => [...(_cache[7] || (_cache[7] = [
                _createTextVNode("mdi-cogs", -1)
              ]))]),
              _: 1
            })
          ]),
          append: _withCtx(() => [
            _createVNode(_component_v_btn, {
              icon: "",
              color: "white",
              variant: "text",
              size: "small",
              onClick: notifyClose,
              class: "bg-white bg-opacity-20 ml-2"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_icon, null, {
                  default: _withCtx(() => [...(_cache[9] || (_cache[9] = [
                    _createTextVNode("mdi-close", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          default: _withCtx(() => [
            _createVNode(_component_v_card_title, { class: "font-weight-bold" }, {
              default: _withCtx(() => [...(_cache[8] || (_cache[8] = [
                _createTextVNode("观看记录同步配置", -1)
              ]))]),
              _: 1
            })
          ]),
          _: 1
        }),
        (successMessage.value)
          ? (_openBlock(), _createBlock(_component_v_alert, {
              key: 0,
              type: "success",
              elevation: "2",
              class: "ma-4 rounded-lg font-weight-medium"
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
              class: "ma-4 border border-error rounded-lg"
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(error.value), 1)
              ]),
              _: 1
            }))
          : _createCommentVNode("", true),
        _createVNode(_component_v_card_text, {
          class: "overflow-y-auto pa-5 bg-grey-lighten-5 flex-grow-1",
          style: {"max-height":"70vh"}
        }, {
          default: _withCtx(() => [
            _createVNode(_component_v_form, {
              ref_key: "form",
              ref: form,
              modelValue: isFormValid.value,
              "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((isFormValid).value = $event)),
              onSubmit: _withModifiers(saveConfig, ["prevent"])
            }, {
              default: _withCtx(() => [
                _createElementVNode("div", _hoisted_2, [
                  _createVNode(_component_v_avatar, {
                    color: "primary-lighten-4",
                    class: "mr-3 text-primary",
                    size: "36"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_icon, null, {
                        default: _withCtx(() => [...(_cache[10] || (_cache[10] = [
                          _createTextVNode("mdi-tune", -1)
                        ]))]),
                        _: 1
                      })
                    ]),
                    _: 1
                  }),
                  _cache[11] || (_cache[11] = _createElementVNode("span", { class: "text-subtitle-1 font-weight-bold" }, "基本设置", -1))
                ]),
                _createVNode(_component_v_card, {
                  variant: "outlined",
                  class: "mb-8 rounded-lg bg-white border-opacity-50"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_card_text, { class: "pa-5" }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_row, null, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_col, { cols: "12" }, {
                              default: _withCtx(() => [
                                _createVNode(_component_v_switch, {
                                  modelValue: config.enabled,
                                  "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((config.enabled) = $event)),
                                  label: "启用当前插件 (观看记录同步)",
                                  color: "primary",
                                  inset: "",
                                  "hide-details": "auto",
                                  class: "font-weight-medium",
                                  hint: "全局开关。启用后将自动建立对应不同用户的事件监听与同步",
                                  "persistent-hint": ""
                                }, null, 8, ["modelValue"])
                              ]),
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
                }),
                _createElementVNode("div", _hoisted_3, [
                  _createVNode(_component_v_avatar, {
                    color: "info-lighten-4",
                    class: "mr-3 text-info",
                    size: "36"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_icon, null, {
                        default: _withCtx(() => [...(_cache[12] || (_cache[12] = [
                          _createTextVNode("mdi-sync-circle", -1)
                        ]))]),
                        _: 1
                      })
                    ]),
                    _: 1
                  }),
                  _cache[13] || (_cache[13] = _createElementVNode("span", { class: "text-subtitle-1 font-weight-bold" }, "媒体类型与阈值", -1))
                ]),
                _createVNode(_component_v_card, {
                  variant: "outlined",
                  class: "mb-8 rounded-lg bg-white border-opacity-50"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_card_text, { class: "pa-5" }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_row, null, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_col, {
                              cols: "12",
                              md: "6",
                              class: "py-2"
                            }, {
                              default: _withCtx(() => [
                                _createVNode(_component_v_switch, {
                                  modelValue: config.sync_movies,
                                  "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((config.sync_movies) = $event)),
                                  label: "同步 电影 观看记录",
                                  color: "info",
                                  inset: "",
                                  "hide-details": ""
                                }, null, 8, ["modelValue"])
                              ]),
                              _: 1
                            }),
                            _createVNode(_component_v_col, {
                              cols: "12",
                              md: "6",
                              class: "py-2"
                            }, {
                              default: _withCtx(() => [
                                _createVNode(_component_v_switch, {
                                  modelValue: config.sync_tv,
                                  "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((config.sync_tv) = $event)),
                                  label: "同步 电视剧 观看记录",
                                  color: "info",
                                  inset: "",
                                  "hide-details": ""
                                }, null, 8, ["modelValue"])
                              ]),
                              _: 1
                            }),
                            _createVNode(_component_v_col, {
                              cols: "12",
                              md: "6",
                              class: "mt-2"
                            }, {
                              default: _withCtx(() => [
                                _createVNode(_component_v_text_field, {
                                  modelValue: config.min_watch_time,
                                  "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((config.min_watch_time) = $event)),
                                  modelModifiers: { number: true },
                                  label: "最小观看时长阈值（秒）",
                                  variant: "outlined",
                                  density: "comfortable",
                                  type: "number",
                                  min: "0",
                                  color: "info",
                                  "prepend-inner-icon": "mdi-clock-outline",
                                  hint: "有效观看超过此阈值才会触发自动同步",
                                  "persistent-hint": ""
                                }, null, 8, ["modelValue"])
                              ]),
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
                }),
                _createVNode(_component_v_expand_transition, null, {
                  default: _withCtx(() => [
                    (hasZspaceInGroups.value)
                      ? (_openBlock(), _createElementBlock("div", _hoisted_4, [
                          _createElementVNode("div", _hoisted_5, [
                            _createVNode(_component_v_avatar, {
                              color: "warning-lighten-4",
                              class: "mr-3 text-warning-darken-2",
                              size: "36"
                            }, {
                              default: _withCtx(() => [
                                _createVNode(_component_v_icon, null, {
                                  default: _withCtx(() => [...(_cache[14] || (_cache[14] = [
                                    _createTextVNode("mdi-television-classic", -1)
                                  ]))]),
                                  _: 1
                                })
                              ]),
                              _: 1
                            }),
                            _cache[15] || (_cache[15] = _createElementVNode("span", { class: "text-subtitle-1 font-weight-bold" }, "极影视同步强化", -1))
                          ]),
                          _createVNode(_component_v_alert, {
                            type: "warning",
                            variant: "tonal",
                            class: "mb-4 border-warning border-opacity-50 font-weight-medium bg-white"
                          }, {
                            default: _withCtx(() => [...(_cache[16] || (_cache[16] = [
                              _createTextVNode(" 检测到配置中包含极影视服务端。开启以下轮询可有效捕获极影视独立产生的主动进度变化。 ", -1)
                            ]))]),
                            _: 1
                          }),
                          _createVNode(_component_v_card, {
                            variant: "outlined",
                            class: "mb-8 rounded-lg bg-white border-opacity-50"
                          }, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_card_text, { class: "pa-5" }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_row, null, {
                                    default: _withCtx(() => [
                                      _createVNode(_component_v_col, {
                                        cols: "12",
                                        md: "6"
                                      }, {
                                        default: _withCtx(() => [
                                          _createVNode(_component_v_switch, {
                                            modelValue: config.zspace_poll_enabled,
                                            "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((config.zspace_poll_enabled) = $event)),
                                            label: "从极影视读取最新进度同步至 Emby",
                                            color: "warning",
                                            inset: "",
                                            hint: "关闭此项不影响 Emby 同步至极影视",
                                            "persistent-hint": ""
                                          }, null, 8, ["modelValue"])
                                        ]),
                                        _: 1
                                      }),
                                      (config.zspace_poll_enabled)
                                        ? (_openBlock(), _createBlock(_component_v_col, {
                                            key: 0,
                                            cols: "12",
                                            md: "6"
                                          }, {
                                            default: _withCtx(() => [
                                              _createVNode(_component_v_text_field, {
                                                modelValue: config.zspace_poll_interval,
                                                "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((config.zspace_poll_interval) = $event)),
                                                modelModifiers: { number: true },
                                                label: "极影视轮询间隔（秒）",
                                                variant: "outlined",
                                                density: "comfortable",
                                                type: "number",
                                                min: "10",
                                                step: "5",
                                                color: "warning",
                                                "prepend-inner-icon": "mdi-timer-sync-outline",
                                                hint: "降低数值可提高进度响应速度，建议: 30",
                                                "persistent-hint": ""
                                              }, null, 8, ["modelValue"])
                                            ]),
                                            _: 1
                                          }))
                                        : _createCommentVNode("", true)
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
                      : _createCommentVNode("", true)
                  ]),
                  _: 1
                }),
                _createElementVNode("div", _hoisted_6, [
                  _createVNode(_component_v_avatar, {
                    color: "success-lighten-4",
                    class: "mr-3 text-success-darken-1",
                    size: "36"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_icon, null, {
                        default: _withCtx(() => [...(_cache[17] || (_cache[17] = [
                          _createTextVNode("mdi-account-group", -1)
                        ]))]),
                        _: 1
                      })
                    ]),
                    _: 1
                  }),
                  _cache[20] || (_cache[20] = _createElementVNode("span", { class: "text-subtitle-1 font-weight-bold" }, "同步组配置 (联络网)", -1)),
                  _createVNode(_component_v_spacer),
                  _createVNode(_component_v_btn, {
                    color: "success",
                    size: "small",
                    variant: "flat",
                    rounded: "pill",
                    class: "px-4 shadow-sm",
                    onClick: addSyncGroup
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_icon, {
                        left: "",
                        size: "small",
                        class: "mr-1"
                      }, {
                        default: _withCtx(() => [...(_cache[18] || (_cache[18] = [
                          _createTextVNode("mdi-plus-circle", -1)
                        ]))]),
                        _: 1
                      }),
                      _cache[19] || (_cache[19] = _createTextVNode(" 建立新同步组 ", -1))
                    ]),
                    _: 1
                  })
                ]),
                (config.sync_groups.length === 0)
                  ? (_openBlock(), _createBlock(_component_v_alert, {
                      key: 0,
                      type: "info",
                      variant: "tonal",
                      class: "mb-6 border border-info border-opacity-50 bg-info-lighten-5 text-indigo-darken-3"
                    }, {
                      prepend: _withCtx(() => [
                        _createVNode(_component_v_icon, null, {
                          default: _withCtx(() => [...(_cache[21] || (_cache[21] = [
                            _createTextVNode("mdi-information-outline", -1)
                          ]))]),
                          _: 1
                        })
                      ]),
                      default: _withCtx(() => [
                        _cache[22] || (_cache[22] = _createTextVNode(" 当前无已添加的同步组。请添加并建立联系组，将多端的账号绑定在一起进行数据互通。 ", -1))
                      ]),
                      _: 1
                    }))
                  : _createCommentVNode("", true),
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(config.sync_groups, (group, groupIndex) => {
                  return (_openBlock(), _createBlock(_component_v_card, {
                    key: groupIndex,
                    class: "mb-5 rounded-lg border-opacity-50 border-success bg-white shadow-sm",
                    variant: "outlined"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_toolbar, {
                        density: "compact",
                        color: "success",
                        variant: "tonal",
                        class: "px-2"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_icon, {
                            size: "small",
                            class: "ml-2 mr-3",
                            color: "success"
                          }, {
                            default: _withCtx(() => [...(_cache[23] || (_cache[23] = [
                              _createTextVNode("mdi-account-network", -1)
                            ]))]),
                            _: 1
                          }),
                          _createVNode(_component_v_toolbar_title, { class: "text-subtitle-2 font-weight-bold text-success-darken-3" }, {
                            default: _withCtx(() => [
                              _createTextVNode(_toDisplayString(group.name || `未命名组合 ${groupIndex + 1}`), 1)
                            ]),
                            _: 2
                          }, 1024),
                          _createVNode(_component_v_spacer),
                          _createVNode(_component_v_switch, {
                            modelValue: group.enabled,
                            "onUpdate:modelValue": $event => ((group.enabled) = $event),
                            color: "success",
                            density: "compact",
                            "hide-details": "",
                            label: "联通开关",
                            class: "mr-4 text-caption font-weight-medium"
                          }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                          _createVNode(_component_v_btn, {
                            icon: "",
                            variant: "flat",
                            color: "error-lighten-1",
                            size: "x-small",
                            onClick: $event => (removeSyncGroup(groupIndex)),
                            class: "elevation-1 bg-white"
                          }, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_icon, { size: "small" }, {
                                default: _withCtx(() => [...(_cache[24] || (_cache[24] = [
                                  _createTextVNode("mdi-delete", -1)
                                ]))]),
                                _: 1
                              }),
                              _createVNode(_component_v_tooltip, {
                                activator: "parent",
                                location: "top"
                              }, {
                                default: _withCtx(() => [...(_cache[25] || (_cache[25] = [
                                  _createTextVNode("删除此组", -1)
                                ]))]),
                                _: 1
                              })
                            ]),
                            _: 1
                          }, 8, ["onClick"])
                        ]),
                        _: 2
                      }, 1024),
                      _createVNode(_component_v_card_text, { class: "pt-5 pb-3" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_row, { class: "mb-4" }, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_col, {
                                cols: "12",
                                md: "12"
                              }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_text_field, {
                                    modelValue: group.name,
                                    "onUpdate:modelValue": $event => ((group.name) = $event),
                                    label: "同步组名称标注",
                                    variant: "outlined",
                                    density: "comfortable",
                                    color: "success",
                                    "prepend-inner-icon": "mdi-pencil-outline",
                                    placeholder: "如：极空间TV客厅组 & 卧室Emby账号",
                                    "hide-details": "auto"
                                  }, null, 8, ["modelValue", "onUpdate:modelValue"])
                                ]),
                                _: 2
                              }, 1024)
                            ]),
                            _: 2
                          }, 1024),
                          _createVNode(_component_v_divider, { class: "mb-4 border-dashed" }),
                          _createElementVNode("div", _hoisted_7, [
                            _createElementVNode("span", _hoisted_8, "组内关联账号 (" + _toDisplayString(group.users?.length || 0) + " 人)", 1),
                            _createVNode(_component_v_btn, {
                              color: "info",
                              variant: "text",
                              size: "small",
                              class: "bg-info-lighten-5 border-info border-opacity-25",
                              rounded: "lg",
                              onClick: $event => (addGroupUser(groupIndex))
                            }, {
                              default: _withCtx(() => [
                                _createVNode(_component_v_icon, {
                                  left: "",
                                  size: "small"
                                }, {
                                  default: _withCtx(() => [...(_cache[26] || (_cache[26] = [
                                    _createTextVNode("mdi-account-plus", -1)
                                  ]))]),
                                  _: 1
                                }),
                                _cache[27] || (_cache[27] = _createTextVNode("关联新账号 ", -1))
                              ]),
                              _: 1
                            }, 8, ["onClick"])
                          ]),
                          (group.users && group.users.length)
                            ? (_openBlock(), _createElementBlock("div", _hoisted_9, [
                                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(group.users, (user, userIndex) => {
                                  return (_openBlock(), _createBlock(_component_v_row, {
                                    key: userIndex,
                                    class: "mb-2 align-center bg-grey-lighten-5 rounded mx-0 pa-2 border"
                                  }, {
                                    default: _withCtx(() => [
                                      _createVNode(_component_v_col, {
                                        cols: "12",
                                        md: "1",
                                        class: "text-center pa-1"
                                      }, {
                                        default: _withCtx(() => [
                                          _createVNode(_component_v_avatar, {
                                            size: "32",
                                            color: "blue-grey-lighten-4",
                                            class: "text-blue-grey-darken-2 font-weight-bold"
                                          }, {
                                            default: _withCtx(() => [
                                              _createTextVNode(_toDisplayString(userIndex + 1), 1)
                                            ]),
                                            _: 2
                                          }, 1024)
                                        ]),
                                        _: 2
                                      }, 1024),
                                      _createVNode(_component_v_col, {
                                        cols: "12",
                                        md: "5",
                                        class: "py-1 px-2"
                                      }, {
                                        default: _withCtx(() => [
                                          _createVNode(_component_v_select, {
                                            modelValue: user.server,
                                            "onUpdate:modelValue": [$event => ((user.server) = $event), $event => (onGroupUserServerChange(groupIndex, userIndex))],
                                            items: embyServers.value,
                                            "item-title": "name",
                                            "item-value": "name",
                                            label: "归属服务端",
                                            variant: "outlined",
                                            density: "compact",
                                            color: "primary",
                                            "hide-details": "auto",
                                            "bg-color": "white",
                                            "prepend-inner-icon": "mdi-server"
                                          }, null, 8, ["modelValue", "onUpdate:modelValue", "items"])
                                        ]),
                                        _: 2
                                      }, 1024),
                                      _createVNode(_component_v_col, {
                                        cols: "12",
                                        md: "5",
                                        class: "py-1 px-2"
                                      }, {
                                        default: _withCtx(() => [
                                          _createVNode(_component_v_select, {
                                            modelValue: user.username,
                                            "onUpdate:modelValue": $event => ((user.username) = $event),
                                            items: getServerUsers(user.server),
                                            "item-title": "name",
                                            "item-value": "name",
                                            label: "具体用户名",
                                            variant: "outlined",
                                            density: "compact",
                                            color: "primary",
                                            "bg-color": "white",
                                            "prepend-inner-icon": "mdi-account",
                                            loading: loadingUsers.value[user.server],
                                            hint: user.server ? `${getServerUsers(user.server).length} 个可用识别目标` : '请先在左侧提供服务器',
                                            "persistent-hint": ""
                                          }, null, 8, ["modelValue", "onUpdate:modelValue", "items", "loading", "hint"])
                                        ]),
                                        _: 2
                                      }, 1024),
                                      _createVNode(_component_v_col, {
                                        cols: "12",
                                        md: "1",
                                        class: "d-flex align-center justify-center pa-1 text-center"
                                      }, {
                                        default: _withCtx(() => [
                                          _createVNode(_component_v_btn, {
                                            color: "grey",
                                            variant: "text",
                                            size: "small",
                                            icon: "",
                                            onClick: $event => (removeGroupUser(groupIndex, userIndex))
                                          }, {
                                            default: _withCtx(() => [
                                              _createVNode(_component_v_icon, null, {
                                                default: _withCtx(() => [...(_cache[28] || (_cache[28] = [
                                                  _createTextVNode("mdi-close", -1)
                                                ]))]),
                                                _: 1
                                              }),
                                              _createVNode(_component_v_tooltip, {
                                                activator: "parent",
                                                location: "left"
                                              }, {
                                                default: _withCtx(() => [...(_cache[29] || (_cache[29] = [
                                                  _createTextVNode("移除这个账号对象", -1)
                                                ]))]),
                                                _: 1
                                              })
                                            ]),
                                            _: 1
                                          }, 8, ["onClick"])
                                        ]),
                                        _: 2
                                      }, 1024)
                                    ]),
                                    _: 2
                                  }, 1024))
                                }), 128))
                              ]))
                            : (_openBlock(), _createElementBlock("div", _hoisted_10, [
                                _createVNode(_component_v_icon, {
                                  size: "40",
                                  color: "grey-lighten-1",
                                  class: "mb-2"
                                }, {
                                  default: _withCtx(() => [...(_cache[30] || (_cache[30] = [
                                    _createTextVNode("mdi-account-multiple-remove-outline", -1)
                                  ]))]),
                                  _: 1
                                }),
                                _cache[31] || (_cache[31] = _createElementVNode("div", { class: "text-body-2" }, "当前组尚未绑定任何账号角色", -1))
                              ]))
                        ]),
                        _: 2
                      }, 1024)
                    ]),
                    _: 2
                  }, 1024))
                }), 128))
              ]),
              _: 1
            }, 8, ["modelValue"])
          ]),
          _: 1
        }),
        _createVNode(_component_v_card_actions, { class: "px-5 py-3 border-t bg-white" }, {
          default: _withCtx(() => [
            _createVNode(_component_v_btn, {
              color: "primary",
              variant: "flat",
              rounded: "pill",
              class: "px-6 font-weight-bold shadow-sm",
              onClick: saveConfig,
              loading: saving.value
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_icon, { left: "" }, {
                  default: _withCtx(() => [...(_cache[32] || (_cache[32] = [
                    _createTextVNode("mdi-content-save-check", -1)
                  ]))]),
                  _: 1
                }),
                _cache[33] || (_cache[33] = _createTextVNode("保存总体应用 ", -1))
              ]),
              _: 1
            }, 8, ["loading"]),
            _createVNode(_component_v_btn, {
              color: "blue-grey-darken-1",
              variant: "tonal",
              rounded: "pill",
              class: "px-5 mx-2 font-weight-medium",
              onClick: resetForm
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_icon, { left: "" }, {
                  default: _withCtx(() => [...(_cache[34] || (_cache[34] = [
                    _createTextVNode("mdi-undo-variant", -1)
                  ]))]),
                  _: 1
                }),
                _cache[35] || (_cache[35] = _createTextVNode("重置默认 ", -1))
              ]),
              _: 1
            }),
            _createVNode(_component_v_spacer),
            _createVNode(_component_v_btn, {
              color: "info",
              variant: "text",
              rounded: "pill",
              class: "font-weight-medium px-4",
              onClick: notifySwitch
            }, {
              default: _withCtx(() => [
                _cache[37] || (_cache[37] = _createTextVNode(" 查看统计面板 ", -1)),
                _createVNode(_component_v_icon, { right: "" }, {
                  default: _withCtx(() => [...(_cache[36] || (_cache[36] = [
                    _createTextVNode("mdi-arrow-right-top", -1)
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
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-c03491a5"]]);

export { Config as default };
