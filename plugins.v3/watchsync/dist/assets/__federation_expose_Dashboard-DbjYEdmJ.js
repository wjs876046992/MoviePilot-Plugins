import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,normalizeClass:_normalizeClass,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createElementBlock:_createElementBlock,renderList:_renderList,Fragment:_Fragment} = await importShared('vue');


const _hoisted_1 = { class: "dashboard-widget h-100" };
const _hoisted_2 = { class: "header-icon-box mr-3" };
const _hoisted_3 = { class: "dashboard-content d-flex flex-column h-100" };
const _hoisted_4 = {
  key: 0,
  class: "d-flex flex-column justify-center align-center flex-grow-1 py-11"
};
const _hoisted_5 = {
  key: 1,
  class: "flex-grow-1 d-flex flex-column"
};
const _hoisted_6 = { class: "text-caption font-weight-black" };
const _hoisted_7 = { class: "stat-card stat-primary rounded-lg text-center py-3 px-1 h-100" };
const _hoisted_8 = { class: "text-h5 font-weight-black text-primary stat-value" };
const _hoisted_9 = { class: "stat-card stat-info rounded-lg text-center py-3 px-1 h-100" };
const _hoisted_10 = { class: "text-h5 font-weight-black text-info stat-value" };
const _hoisted_11 = { class: "stat-card stat-secondary rounded-lg text-center py-3 px-1 h-100" };
const _hoisted_12 = { class: "text-h5 font-weight-black text-secondary stat-value" };
const _hoisted_13 = { class: "d-flex align-center justify-space-between mb-2 px-1" };
const _hoisted_14 = { class: "text-caption font-weight-bold text-medium-emphasis d-flex align-center" };
const _hoisted_15 = {
  key: 0,
  class: "text-caption text-disabled"
};
const _hoisted_16 = {
  key: 0,
  class: "flex-grow-1"
};
const _hoisted_17 = { class: "flex-grow-1 overflow-hidden mr-2" };
const _hoisted_18 = { class: "record-title text-caption font-weight-bold text-truncate" };
const _hoisted_19 = { class: "text-caption text-disabled d-flex align-center text-truncate mt-1" };
const _hoisted_20 = { class: "text-truncate" };
const _hoisted_21 = { class: "text-truncate" };
const _hoisted_22 = { class: "text-right flex-shrink-0" };
const _hoisted_23 = { class: "text-caption text-disabled text-no-wrap" };
const _hoisted_24 = {
  key: 1,
  class: "empty-box d-flex flex-column align-center justify-center flex-grow-1 py-7 px-4 rounded-lg text-center"
};
const _hoisted_25 = { class: "empty-icon mb-2" };

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
const recentRecords = ref([]);
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

// 成功率徽章配色
const rateTone = computed(() => {
  if (stats.value.successRate >= 90) return 'rate-success'
  if (stats.value.successRate >= 70) return 'rate-warning'
  return 'rate-error'
});

// 格式化时间
function formatTime(timestamp) {
  if (!timestamp) return ''
  const date = new Date(timestamp);
  if (isNaN(date.getTime())) return ''
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
      recentRecords.value = result.data || [];
    } else {
      recentRecords.value = [];
    }
  } catch (error) {
    console.error('获取同步记录失败:', error);
    recentRecords.value = [];
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
  const _component_v_tooltip = _resolveComponent("v-tooltip");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_card_item = _resolveComponent("v-card-item");
  const _component_v_progress_circular = _resolveComponent("v-progress-circular");
  const _component_v_spacer = _resolveComponent("v-spacer");
  const _component_v_col = _resolveComponent("v-col");
  const _component_v_row = _resolveComponent("v-row");
  const _component_v_card_text = _resolveComponent("v-card-text");
  const _component_v_card = _resolveComponent("v-card");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_v_card, {
      flat: !__props.config?.attrs?.border,
      variant: __props.config?.attrs?.border ? 'outlined' : 'flat',
      class: _normalizeClass(["rounded-xl h-100 overflow-hidden dashboard-card", __props.config?.attrs?.border ? 'border-opacity-25' : ''])
    }, {
      default: _withCtx(() => [
        (__props.config?.attrs?.border)
          ? (_openBlock(), _createBlock(_component_v_card_item, {
              key: 0,
              class: "px-4 py-3 border-b header-surface"
            }, {
              prepend: _withCtx(() => [
                _createElementVNode("div", _hoisted_2, [
                  _createVNode(_component_v_icon, {
                    color: "primary",
                    size: "20"
                  }, {
                    default: _withCtx(() => [...(_cache[0] || (_cache[0] = [
                      _createTextVNode("mdi-chart-timeline-variant-shimmer", -1)
                    ]))]),
                    _: 1
                  })
                ])
              ]),
              append: _withCtx(() => [
                _createVNode(_component_v_btn, {
                  icon: "",
                  variant: "tonal",
                  color: "primary",
                  size: "small",
                  rounded: "lg",
                  onClick: refreshData,
                  loading: loading.value
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_icon, { size: "18" }, {
                      default: _withCtx(() => [...(_cache[1] || (_cache[1] = [
                        _createTextVNode("mdi-refresh", -1)
                      ]))]),
                      _: 1
                    }),
                    _createVNode(_component_v_tooltip, {
                      activator: "parent",
                      location: "bottom"
                    }, {
                      default: _withCtx(() => [...(_cache[2] || (_cache[2] = [
                        _createTextVNode("刷新数据", -1)
                      ]))]),
                      _: 1
                    })
                  ]),
                  _: 1
                }, 8, ["loading"])
              ]),
              default: _withCtx(() => [
                _createVNode(_component_v_card_title, { class: "text-subtitle-1 font-weight-bold d-flex align-center" }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(__props.config?.attrs?.title || '观看状态仪表盘') + " ", 1),
                    _createElementVNode("span", {
                      class: _normalizeClass(["status-dot ml-2", `dot-${serviceStatus.value}`])
                    }, null, 2)
                  ]),
                  _: 1
                })
              ]),
              _: 1
            }))
          : _createCommentVNode("", true),
        _createVNode(_component_v_card_text, {
          class: _normalizeClass(__props.config?.attrs?.border ? 'pa-4' : 'pa-0'),
          style: {"height":"100%"}
        }, {
          default: _withCtx(() => [
            _createElementVNode("div", _hoisted_3, [
              (loading.value)
                ? (_openBlock(), _createElementBlock("div", _hoisted_4, [
                    _createVNode(_component_v_progress_circular, {
                      indeterminate: "",
                      color: "primary",
                      size: 40,
                      width: 3.5,
                      class: "mb-3"
                    }),
                    _cache[3] || (_cache[3] = _createElementVNode("span", { class: "text-caption text-medium-emphasis" }, "正在汇总同步数据…", -1))
                  ]))
                : (_openBlock(), _createElementBlock("div", _hoisted_5, [
                    _createElementVNode("div", {
                      class: _normalizeClass(["status-strip d-flex align-center px-3 py-2 mb-3 rounded-lg", `strip-${serviceStatusColor.value}`])
                    }, [
                      _createVNode(_component_v_icon, {
                        color: serviceStatusColor.value,
                        size: "18",
                        class: "mr-2"
                      }, {
                        default: _withCtx(() => [
                          _createTextVNode(_toDisplayString(serviceStatusIcon.value), 1)
                        ]),
                        _: 1
                      }, 8, ["color"]),
                      _createElementVNode("span", {
                        class: _normalizeClass(["text-caption font-weight-bold", `text-${serviceStatusColor.value}-darken-2`])
                      }, _toDisplayString(serviceStatusText.value), 3),
                      _createVNode(_component_v_spacer),
                      _createElementVNode("div", {
                        class: _normalizeClass(["rate-pill d-flex align-center px-2 py-1 rounded-pill", rateTone.value])
                      }, [
                        _createVNode(_component_v_icon, {
                          size: "12",
                          class: "mr-1"
                        }, {
                          default: _withCtx(() => [...(_cache[4] || (_cache[4] = [
                            _createTextVNode("mdi-shield-check-outline", -1)
                          ]))]),
                          _: 1
                        }),
                        _createElementVNode("span", _hoisted_6, _toDisplayString(stats.value.successRate) + "%", 1)
                      ], 2)
                    ], 2),
                    _createVNode(_component_v_row, { class: "mb-3 mx-0 align-stretch" }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_col, {
                          cols: "4",
                          class: "pa-1"
                        }, {
                          default: _withCtx(() => [
                            _createElementVNode("div", _hoisted_7, [
                              _createElementVNode("div", _hoisted_8, _toDisplayString(stats.value.todayCount), 1),
                              _cache[5] || (_cache[5] = _createElementVNode("div", { class: "text-caption text-medium-emphasis font-weight-medium mt-1" }, "今日指令", -1))
                            ])
                          ]),
                          _: 1
                        }),
                        _createVNode(_component_v_col, {
                          cols: "4",
                          class: "pa-1"
                        }, {
                          default: _withCtx(() => [
                            _createElementVNode("div", _hoisted_9, [
                              _createElementVNode("div", _hoisted_10, _toDisplayString(stats.value.activeUsers), 1),
                              _cache[6] || (_cache[6] = _createElementVNode("div", { class: "text-caption text-medium-emphasis font-weight-medium mt-1" }, "24H 用户", -1))
                            ])
                          ]),
                          _: 1
                        }),
                        _createVNode(_component_v_col, {
                          cols: "4",
                          class: "pa-1"
                        }, {
                          default: _withCtx(() => [
                            _createElementVNode("div", _hoisted_11, [
                              _createElementVNode("div", _hoisted_12, _toDisplayString(stats.value.syncTypes.length), 1),
                              _cache[7] || (_cache[7] = _createElementVNode("div", { class: "text-caption text-medium-emphasis font-weight-medium mt-1" }, "涉及类型", -1))
                            ])
                          ]),
                          _: 1
                        })
                      ]),
                      _: 1
                    }),
                    _createElementVNode("div", _hoisted_13, [
                      _createElementVNode("span", _hoisted_14, [
                        _createVNode(_component_v_icon, {
                          size: "14",
                          class: "mr-1 text-primary"
                        }, {
                          default: _withCtx(() => [...(_cache[8] || (_cache[8] = [
                            _createTextVNode("mdi-history", -1)
                          ]))]),
                          _: 1
                        }),
                        _cache[9] || (_cache[9] = _createTextVNode(" 最近动向 ", -1))
                      ]),
                      (recentRecords.value.length)
                        ? (_openBlock(), _createElementBlock("span", _hoisted_15, "最新 " + _toDisplayString(recentRecords.value.length) + " 条", 1))
                        : _createCommentVNode("", true)
                    ]),
                    (recentRecords.value.length)
                      ? (_openBlock(), _createElementBlock("div", _hoisted_16, [
                          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(recentRecords.value, (record, index) => {
                            return (_openBlock(), _createElementBlock("div", {
                              key: index,
                              class: "record-item d-flex align-center py-2 px-3 mb-2 rounded-lg"
                            }, [
                              _createElementVNode("div", {
                                class: _normalizeClass(["record-badge mr-3", `badge-${getStatusColor(record.status)}`])
                              }, [
                                _createVNode(_component_v_icon, {
                                  size: "16",
                                  color: getStatusColor(record.status)
                                }, {
                                  default: _withCtx(() => [
                                    _createTextVNode(_toDisplayString(getStatusIcon(record.status)), 1)
                                  ]),
                                  _: 2
                                }, 1032, ["color"])
                              ], 2),
                              _createElementVNode("div", _hoisted_17, [
                                _createElementVNode("div", _hoisted_18, _toDisplayString(record.media_name || '未命名媒体'), 1),
                                _createElementVNode("div", _hoisted_19, [
                                  _createVNode(_component_v_icon, {
                                    size: "12",
                                    color: getSyncTypeColor(record.sync_type),
                                    class: "mr-1 flex-shrink-0"
                                  }, {
                                    default: _withCtx(() => [
                                      _createTextVNode(_toDisplayString(getSyncTypeIcon(record.sync_type)), 1)
                                    ]),
                                    _: 2
                                  }, 1032, ["color"]),
                                  _createElementVNode("span", _hoisted_20, _toDisplayString(record.source_user), 1),
                                  _createVNode(_component_v_icon, {
                                    size: "10",
                                    class: "mx-1 flex-shrink-0 text-grey"
                                  }, {
                                    default: _withCtx(() => [...(_cache[10] || (_cache[10] = [
                                      _createTextVNode("mdi-arrow-right", -1)
                                    ]))]),
                                    _: 1
                                  }),
                                  _createElementVNode("span", _hoisted_21, _toDisplayString(record.target_user), 1)
                                ])
                              ]),
                              _createElementVNode("div", _hoisted_22, [
                                _createElementVNode("span", _hoisted_23, _toDisplayString(formatTime(record.timestamp || record.created_at)), 1)
                              ])
                            ]))
                          }), 128))
                        ]))
                      : (_openBlock(), _createElementBlock("div", _hoisted_24, [
                          _createElementVNode("div", _hoisted_25, [
                            _createVNode(_component_v_icon, {
                              size: "26",
                              color: "primary"
                            }, {
                              default: _withCtx(() => [...(_cache[11] || (_cache[11] = [
                                _createTextVNode("mdi-sync-off", -1)
                              ]))]),
                              _: 1
                            })
                          ]),
                          _cache[12] || (_cache[12] = _createElementVNode("div", { class: "text-caption font-weight-bold text-medium-emphasis" }, "这里还是一片荒芜", -1)),
                          _cache[13] || (_cache[13] = _createElementVNode("div", { class: "text-caption text-disabled mt-1" }, "暂无有效同步记录", -1))
                        ]))
                  ]))
            ])
          ]),
          _: 1
        }, 8, ["class"])
      ]),
      _: 1
    }, 8, ["flat", "variant", "class"])
  ]))
}
}

};
const Dashboard = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-80efe785"]]);

export { Dashboard as default };
