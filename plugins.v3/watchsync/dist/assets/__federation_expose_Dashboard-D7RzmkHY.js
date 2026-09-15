import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,toDisplayString:_toDisplayString,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createElementBlock:_createElementBlock,normalizeClass:_normalizeClass,createElementVNode:_createElementVNode,renderList:_renderList,Fragment:_Fragment} = await importShared('vue');


const _hoisted_1 = { class: "dashboard-widget h-100" };
const _hoisted_2 = { class: "dashboard-content d-flex flex-column h-100" };
const _hoisted_3 = {
  key: 0,
  class: "d-flex justify-center align-center flex-grow-1 py-10"
};
const _hoisted_4 = {
  key: 1,
  class: "flex-grow-1"
};
const _hoisted_5 = { class: "text-caption font-weight-bold" };
const _hoisted_6 = { class: "text-h5 font-weight-black text-primary" };
const _hoisted_7 = { class: "text-h5 font-weight-black text-info" };
const _hoisted_8 = { class: "text-h5 font-weight-black text-secondary" };
const _hoisted_9 = { class: "text-subtitle-2 text-grey-darken-1 mb-2 d-flex align-center" };
const _hoisted_10 = {
  class: "text-truncate",
  style: {"max-width":"60%"}
};
const _hoisted_11 = { class: "font-weight-medium" };
const _hoisted_12 = { class: "font-weight-medium" };
const _hoisted_13 = { class: "text-caption text-medium-emphasis ml-2 bg-grey-lighten-4 px-2 py-1 rounded" };
const _hoisted_14 = {
  key: 1,
  class: "text-center text-caption text-blue-grey-darken-1 py-8 rounded-lg border-dashed bg-grey-lighten-5"
};

const {ref,computed,onMounted,onUnmounted} = await importShared('vue');


// 接收仪表板配置

const _sfc_main = {
  __name: 'Dashboard',
  props: {
  config: {
    type: Object,
    default: () => ({}),
  },
  allowRefresh: {
    type: Boolean,
    default: true,
  },
  api: {
    type: Object,
    required: true,
  },
},
  setup(__props) {

const props = __props;

// 组件状态
const loading = ref(true);
const stats = ref({
  todayCount: 0,
  successRate: 0,
  activeUsers: 0,
  syncTypes: []
});
const syncRecords = ref([]);
const serviceStatus = ref('running'); // running, stopped, error
let refreshTimer = null;

// 获取状态图标
function getStatusIcon(status) {
  const icons = {
    'success': 'mdi-check',
    'error': 'mdi-alert',
    'pending': 'mdi-clock-outline',
  };
  return icons[status] || 'mdi-help-circle'
}

// 获取状态颜色
function getStatusColor(status) {
  const colors = {
    'success': 'success',
    'error': 'error',
    'pending': 'warning',
  };
  return colors[status] || 'grey'
}

// 获取同步类型图标
function getSyncTypeIcon(syncType) {
  const icons = {
    'playback': 'mdi-play',
    'favorite': 'mdi-heart',
    'not_favorite': 'mdi-heart-outline',
    'played_status': 'mdi-eye',
    'mark_played': 'mdi-eye',
    'mark_unplayed': 'mdi-eye-off-outline'
  };
  return icons[syncType] || 'mdi-sync'
}

// 获取同步类型颜色
function getSyncTypeColor(syncType) {
  const colors = {
    'playback': 'primary',
    'favorite': 'pink',
    'not_favorite': 'grey',
    'played_status': 'grey',
    'mark_played': 'grey',
    'mark_unplayed': 'grey'
  };
  return colors[syncType] || 'grey'
}

// 服务状态相关的计算属性
const serviceStatusIcon = computed(() => {
  const icons = {
    'running': 'mdi-check-circle',
    'stopped': 'mdi-stop-circle',
    'error': 'mdi-alert-circle'
  };
  return icons[serviceStatus.value] || 'mdi-help-circle'
});

const serviceStatusColor = computed(() => {
  const colors = {
    'running': 'success',
    'stopped': 'warning',
    'error': 'error'
  };
  return colors[serviceStatus.value] || 'grey'
});

const serviceStatusText = computed(() => {
  const texts = {
    'running': '核心服务正常运作中',
    'stopped': '服务状态已中断/停止',
    'error': '同步服务异常告警中'
  };
  return texts[serviceStatus.value] || '状态未知'
});

// 格式化时间
function formatTime(timestamp) {
  if (!timestamp) return ''
  const date = new Date(timestamp);
  const now = new Date();
  const diff = now - date;

  if (diff < 60000) { // 1分钟内
    return '刚刚'
  } else if (diff < 3600000) { // 1小时内
    return Math.floor(diff / 60000) + '分钟前'
  } else if (diff < 86400000) { // 1天内
    return Math.floor(diff / 3600000) + '小时前'
  } else {
    // 简短日期
    const m = (date.getMonth() + 1).toString().padStart(2, '0');
    const d = date.getDate().toString().padStart(2, '0');
    const t = date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
    return `${m}-${d} ${t}`
  }
}

// 获取仪表板数据
async function fetchDashboardData() {
  if (!props.allowRefresh) return

  loading.value = true;

  try {
    // 获取统计数据
    await loadDashboardStats();

    // 获取最近同步记录
    await loadDashboardRecords();

  } catch (error) {
    console.error('获取仪表板数据失败:', error);
  } finally {
    loading.value = false;
  }
}

// 加载仪表板统计数据
async function loadDashboardStats() {
  try {
    const result = await props.api.get('plugin/WatchSync/stats');
    if (result && result.success) {
      const data = result.data;
      stats.value = {
        todayCount: data['今日同步次数'] || 0,
        successRate: parseFloat(data['成功率']) || 0,
        activeUsers: data['活跃用户数'] || 0,
        syncTypes: data['同步类型'] || []
      };

      // 根据成功率判断服务状态
      if (stats.value.successRate >= 90) {
        serviceStatus.value = 'running';
      } else if (stats.value.successRate >= 50) {
        serviceStatus.value = 'stopped';
      } else {
        serviceStatus.value = 'error';
      }
    } else {
      // 设置默认值
      stats.value = {
        todayCount: 0,
        successRate: 0,
        activeUsers: 0,
        syncTypes: []
      };
      serviceStatus.value = 'stopped';
    }
  } catch (error) {
    console.error('获取统计数据失败:', error);
    // 设置默认值
    stats.value = {
      todayCount: 0,
      successRate: 0,
      activeUsers: 0,
      syncTypes: []
    };
    serviceStatus.value = 'error';
  }
}

// 加载仪表板同步记录
async function loadDashboardRecords() {
  try {
    const result = await props.api.get('plugin/WatchSync/records?limit=3');
    if (result && result.success) {
      syncRecords.value = result.data || [];
    } else {
      syncRecords.value = [];
    }
  } catch (error) {
    console.error('获取同步记录失败:', error);
    syncRecords.value = [];
  }
}

// 手动刷新数据
async function refreshData() {
  await fetchDashboardData();
}

// 设置定时刷新
function setupRefreshTimer() {
  if (props.allowRefresh) {
    // 每30秒刷新一次
    refreshTimer = setInterval(() => {
      fetchDashboardData();
    }, 30000);
  }
}

// 初始化
onMounted(() => {
  fetchDashboardData();
  setupRefreshTimer();
});

// 清理
onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer);
  }
});

return (_ctx, _cache) => {
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_card_title = _resolveComponent("v-card-title");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_card_item = _resolveComponent("v-card-item");
  const _component_v_progress_circular = _resolveComponent("v-progress-circular");
  const _component_v_spacer = _resolveComponent("v-spacer");
  const _component_v_col = _resolveComponent("v-col");
  const _component_v_row = _resolveComponent("v-row");
  const _component_v_avatar = _resolveComponent("v-avatar");
  const _component_v_list_item_title = _resolveComponent("v-list-item-title");
  const _component_v_list_item_subtitle = _resolveComponent("v-list-item-subtitle");
  const _component_v_list_item = _resolveComponent("v-list-item");
  const _component_v_list = _resolveComponent("v-list");
  const _component_v_card_text = _resolveComponent("v-card-text");
  const _component_v_card = _resolveComponent("v-card");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_v_card, {
      flat: !__props.config?.attrs?.border,
      variant: __props.config?.attrs?.border ? 'outlined' : 'flat',
      class: "rounded-lg h-100 border-opacity-50"
    }, {
      default: _withCtx(() => [
        (__props.config?.attrs?.border)
          ? (_openBlock(), _createBlock(_component_v_card_item, {
              key: 0,
              class: "border-b bg-grey-lighten-4 pa-3"
            }, {
              prepend: _withCtx(() => [
                _createVNode(_component_v_icon, {
                  color: "primary",
                  class: "mr-2"
                }, {
                  default: _withCtx(() => [...(_cache[0] || (_cache[0] = [
                    _createTextVNode("mdi-chart-timeline-variant-shimmer", -1)
                  ]))]),
                  _: 1
                })
              ]),
              append: _withCtx(() => [
                _createVNode(_component_v_btn, {
                  icon: "",
                  variant: "tonal",
                  color: "primary",
                  size: "x-small",
                  class: "bg-white elevation-1",
                  onClick: refreshData,
                  loading: loading.value
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_icon, { size: "small" }, {
                      default: _withCtx(() => [...(_cache[1] || (_cache[1] = [
                        _createTextVNode("mdi-refresh", -1)
                      ]))]),
                      _: 1
                    })
                  ]),
                  _: 1
                }, 8, ["loading"])
              ]),
              default: _withCtx(() => [
                _createVNode(_component_v_card_title, { class: "text-subtitle-1 font-weight-bold text-primary" }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(__props.config?.attrs?.title || '观看状态仪表盘'), 1)
                  ]),
                  _: 1
                })
              ]),
              _: 1
            }))
          : _createCommentVNode("", true),
        _createVNode(_component_v_card_text, {
          class: _normalizeClass(__props.config?.attrs?.border ? 'pa-4 pb-2' : 'pa-0'),
          style: {"height":"100%"}
        }, {
          default: _withCtx(() => [
            _createElementVNode("div", _hoisted_2, [
              (loading.value)
                ? (_openBlock(), _createElementBlock("div", _hoisted_3, [
                    _createVNode(_component_v_progress_circular, {
                      indeterminate: "",
                      color: "primary",
                      size: 36,
                      width: 3
                    })
                  ]))
                : (_openBlock(), _createElementBlock("div", _hoisted_4, [
                    _createElementVNode("div", {
                      class: _normalizeClass(["d-flex align-center px-4 py-2 mb-4 rounded-lg bg-surface-variant text-on-surface-variant shadow-sm border border-opacity-25", `bg-${serviceStatusColor.value}-lighten-5 border-${serviceStatusColor.value}`])
                    }, [
                      _createVNode(_component_v_icon, {
                        color: serviceStatusColor.value,
                        size: "small",
                        class: "mr-2"
                      }, {
                        default: _withCtx(() => [
                          _createTextVNode(_toDisplayString(serviceStatusIcon.value), 1)
                        ]),
                        _: 1
                      }, 8, ["color"]),
                      _createElementVNode("span", {
                        class: _normalizeClass(["text-body-2 font-weight-bold", `text-${serviceStatusColor.value}-darken-2`])
                      }, _toDisplayString(serviceStatusText.value), 3),
                      _createVNode(_component_v_spacer),
                      _createElementVNode("div", {
                        class: _normalizeClass(["d-flex align-center bg-white px-2 py-1 rounded-pill elevation-1", `text-${stats.value.successRate >= 90 ? 'success' : stats.value.successRate >= 70 ? 'warning' : 'error'}`])
                      }, [
                        _createVNode(_component_v_icon, {
                          start: "",
                          size: "x-small",
                          class: "mr-1"
                        }, {
                          default: _withCtx(() => [...(_cache[2] || (_cache[2] = [
                            _createTextVNode("mdi-brightness-percent", -1)
                          ]))]),
                          _: 1
                        }),
                        _createElementVNode("span", _hoisted_5, _toDisplayString(stats.value.successRate) + "% 成功率", 1)
                      ], 2)
                    ], 2),
                    _createVNode(_component_v_row, { class: "mb-4 mt-2 mx-0 align-stretch" }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_col, {
                          cols: "4",
                          class: "text-center bg-grey-lighten-5 rounded-s-lg py-3"
                        }, {
                          default: _withCtx(() => [
                            _createElementVNode("div", _hoisted_6, _toDisplayString(stats.value.todayCount), 1),
                            _cache[3] || (_cache[3] = _createElementVNode("div", { class: "text-caption font-weight-medium text-medium-emphasis mt-1" }, "今日同步指令", -1))
                          ]),
                          _: 1
                        }),
                        _createVNode(_component_v_col, {
                          cols: "4",
                          class: "text-center border-s border-e bg-blue-grey-lighten-5 py-3"
                        }, {
                          default: _withCtx(() => [
                            _createElementVNode("div", _hoisted_7, _toDisplayString(stats.value.activeUsers), 1),
                            _cache[4] || (_cache[4] = _createElementVNode("div", { class: "text-caption font-weight-medium text-medium-emphasis mt-1" }, "24H 涉及用户", -1))
                          ]),
                          _: 1
                        }),
                        _createVNode(_component_v_col, {
                          cols: "4",
                          class: "text-center bg-grey-lighten-5 rounded-e-lg py-3"
                        }, {
                          default: _withCtx(() => [
                            _createElementVNode("div", _hoisted_8, _toDisplayString(stats.value.syncTypes.length), 1),
                            _cache[5] || (_cache[5] = _createElementVNode("div", { class: "text-caption font-weight-medium text-medium-emphasis mt-1" }, "同步涉及类型", -1))
                          ]),
                          _: 1
                        })
                      ]),
                      _: 1
                    }),
                    _createElementVNode("div", _hoisted_9, [
                      _createVNode(_component_v_icon, {
                        size: "small",
                        class: "mr-1"
                      }, {
                        default: _withCtx(() => [...(_cache[6] || (_cache[6] = [
                          _createTextVNode("mdi-history", -1)
                        ]))]),
                        _: 1
                      }),
                      _cache[7] || (_cache[7] = _createTextVNode("近期最新动向 ", -1))
                    ]),
                    (syncRecords.value.length)
                      ? (_openBlock(), _createBlock(_component_v_list, {
                          key: 0,
                          density: "compact",
                          class: "py-0 rounded-lg border border-opacity-50"
                        }, {
                          default: _withCtx(() => [
                            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(syncRecords.value.slice(0, 3), (record, index) => {
                              return (_openBlock(), _createBlock(_component_v_list_item, {
                                key: index,
                                class: _normalizeClass([{'border-b': index < syncRecords.value.slice(0, 3).length - 1}, "px-3"])
                              }, {
                                prepend: _withCtx(() => [
                                  _createVNode(_component_v_avatar, {
                                    color: getStatusColor(record.status),
                                    size: "28",
                                    class: "mr-3 mt-1 elevation-1"
                                  }, {
                                    default: _withCtx(() => [
                                      _createVNode(_component_v_icon, {
                                        size: "16",
                                        color: "white"
                                      }, {
                                        default: _withCtx(() => [
                                          _createTextVNode(_toDisplayString(getStatusIcon(record.status)), 1)
                                        ]),
                                        _: 2
                                      }, 1024)
                                    ]),
                                    _: 2
                                  }, 1032, ["color"])
                                ]),
                                append: _withCtx(() => [
                                  _createElementVNode("span", _hoisted_13, _toDisplayString(formatTime(record.timestamp)), 1)
                                ]),
                                default: _withCtx(() => [
                                  _createVNode(_component_v_list_item_title, { class: "text-body-2 font-weight-bold text-primary-darken-1 pt-1 text-truncate" }, {
                                    default: _withCtx(() => [
                                      _createTextVNode(_toDisplayString(record.media_name || '未命名媒体'), 1)
                                    ]),
                                    _: 2
                                  }, 1024),
                                  _createVNode(_component_v_list_item_subtitle, { class: "text-caption d-flex align-center mt-1 pb-1" }, {
                                    default: _withCtx(() => [
                                      _createVNode(_component_v_icon, {
                                        size: "x-small",
                                        color: getSyncTypeColor(record.sync_type),
                                        class: "mr-1"
                                      }, {
                                        default: _withCtx(() => [
                                          _createTextVNode(_toDisplayString(getSyncTypeIcon(record.sync_type)), 1)
                                        ]),
                                        _: 2
                                      }, 1032, ["color"]),
                                      _createElementVNode("span", _hoisted_10, [
                                        _createElementVNode("span", _hoisted_11, _toDisplayString(record.source_user), 1),
                                        _createVNode(_component_v_icon, {
                                          size: "x-small",
                                          class: "mx-1 text-grey"
                                        }, {
                                          default: _withCtx(() => [...(_cache[8] || (_cache[8] = [
                                            _createTextVNode("mdi-arrow-right", -1)
                                          ]))]),
                                          _: 1
                                        }),
                                        _createElementVNode("span", _hoisted_12, _toDisplayString(record.target_user), 1)
                                      ])
                                    ]),
                                    _: 2
                                  }, 1024)
                                ]),
                                _: 2
                              }, 1032, ["class"]))
                            }), 128))
                          ]),
                          _: 1
                        }))
                      : (_openBlock(), _createElementBlock("div", _hoisted_14, [
                          _createVNode(_component_v_icon, {
                            size: "48",
                            color: "blue-grey-lighten-3",
                            class: "d-block mx-auto mb-2"
                          }, {
                            default: _withCtx(() => [...(_cache[9] || (_cache[9] = [
                              _createTextVNode("mdi-cube-scan", -1)
                            ]))]),
                            _: 1
                          }),
                          _cache[10] || (_cache[10] = _createTextVNode(" 这里还是一片荒芜...", -1)),
                          _cache[11] || (_cache[11] = _createElementVNode("br", null, null, -1)),
                          _cache[12] || (_cache[12] = _createTextVNode("暂无有效同步记录 ", -1))
                        ]))
                  ]))
            ])
          ]),
          _: 1
        }, 8, ["class"])
      ]),
      _: 1
    }, 8, ["flat", "variant"])
  ]))
}
}

};
const Dashboard = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-cdbc66da"]]);

export { Dashboard as default };
