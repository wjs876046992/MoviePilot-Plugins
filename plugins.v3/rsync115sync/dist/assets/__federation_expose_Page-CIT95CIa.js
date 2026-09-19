import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,renderList:_renderList,Fragment:_Fragment} = await importShared('vue');


const _hoisted_1 = { class: "plugin-page" };
const _hoisted_2 = { class: "header-icon-box mr-3" };
const _hoisted_3 = { class: "d-flex align-center ga-1" };
const _hoisted_4 = { class: "stat-card stat-info rounded-xl pa-3 text-center" };
const _hoisted_5 = { class: "text-h5 font-weight-black text-info" };
const _hoisted_6 = { class: "text-caption text-medium-emphasis mt-1" };
const _hoisted_7 = { class: "stat-card stat-primary rounded-xl pa-3 text-center" };
const _hoisted_8 = { class: "text-h5 font-weight-black text-primary" };
const _hoisted_9 = { class: "stat-card stat-error rounded-xl pa-3 text-center" };
const _hoisted_10 = { class: "text-h5 font-weight-black text-error" };
const _hoisted_11 = { class: "action-strip d-flex align-center justify-space-between flex-wrap ga-2 rounded-xl pa-3 mb-4" };
const _hoisted_12 = { class: "d-flex align-center ga-2" };
const _hoisted_13 = {
  key: 0,
  class: "text-caption font-weight-bold text-primary"
};
const _hoisted_14 = { key: 0 };
const _hoisted_15 = {
  key: 0,
  class: "d-flex flex-column ga-2"
};
const _hoisted_16 = { class: "overflow-hidden mr-3" };
const _hoisted_17 = { class: "font-weight-bold text-body-2 text-truncate" };
const _hoisted_18 = { class: "text-caption text-medium-emphasis mt-0.5" };
const _hoisted_19 = {
  key: 0,
  class: "ml-2 text-warning font-weight-medium"
};
const _hoisted_20 = {
  key: 1,
  class: "ml-2 text-success font-weight-medium"
};
const _hoisted_21 = {
  key: 1,
  class: "empty-box d-flex flex-column align-center justify-center py-10 px-4 rounded-xl text-center"
};
const _hoisted_22 = { key: 1 };
const _hoisted_23 = {
  key: 0,
  class: "d-flex flex-column ga-2"
};
const _hoisted_24 = { class: "overflow-hidden mr-3" };
const _hoisted_25 = { class: "font-weight-bold text-body-2 text-error text-truncate" };
const _hoisted_26 = { class: "overflow-hidden mr-3" };
const _hoisted_27 = { class: "font-weight-bold text-body-2 text-warning text-truncate" };
const _hoisted_28 = {
  key: 1,
  class: "empty-box d-flex flex-column align-center justify-center py-10 px-4 rounded-xl text-center"
};

const {ref,onMounted,onUnmounted} = await importShared('vue');



const _sfc_main = {
  __name: 'Page',
  props: {
  model: { type: Object, default: () => ({}) },
  api: { type: Object, required: true },
},
  emits: ['close', 'switch'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;

const loading = ref(false);
const syncing = ref(false);
const retrying = ref(false);
const cleaning = ref(false);
const currentTab = ref('queue');
const actionMsg = ref('');

const statusData = ref({
  is_running: false,
  ready_count: 0,
  cooling_count: 0,
  delay_hours: 2.0,
  last_status: {},
  sync_pairs_count: 0,
});

const queueList = ref([]);
let timer = null;

function notifyClose() {
  emit('close');
}

function notifySwitch() {
  emit('switch');
}

async function fetchStatus() {
  loading.value = true;
  try {
    const res = await props.api.get('plugin/Rsync115Sync/status');
    if (res && res.success && res.data) {
      statusData.value = res.data;
    }
    const qRes = await props.api.get('plugin/Rsync115Sync/queue');
    if (qRes && qRes.success && qRes.data) {
      queueList.value = qRes.data;
    }
  } catch (e) {
    console.error('获取状态失败:', e);
  } finally {
    loading.value = false;
  }
}

async function triggerSync() {
  syncing.value = true;
  actionMsg.value = '正在启动同步任务...';
  try {
    const res = await props.api.post('plugin/Rsync115Sync/sync');
    actionMsg.value = res?.message || '已触发同步';
    fetchStatus();
  } catch (e) {
    actionMsg.value = '启动同步出错: ' + e.message;
  } finally {
    syncing.value = false;
  }
}

async function triggerRetry() {
  retrying.value = true;
  actionMsg.value = '正在启动定向重试...';
  try {
    const res = await props.api.post('plugin/Rsync115Sync/retry');
    actionMsg.value = res?.message || '已触发重试';
    fetchStatus();
  } catch (e) {
    actionMsg.value = '启动重试出错: ' + e.message;
  } finally {
    retrying.value = false;
  }
}

async function triggerClean() {
  cleaning.value = true;
  actionMsg.value = '正在扫描并清理幽灵文件...';
  try {
    const res = await props.api.post('plugin/Rsync115Sync/clean');
    actionMsg.value = `已清理 ${res?.cleaned_count || 0} 个 ..* 幽灵临时文件！`;
    fetchStatus();
  } catch (e) {
    actionMsg.value = '清理出错: ' + e.message;
  } finally {
    cleaning.value = false;
  }
}

onMounted(() => {
  fetchStatus();
  timer = setInterval(fetchStatus, 30000);
});

onUnmounted(() => {
  if (timer) clearInterval(timer);
});

return (_ctx, _cache) => {
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_chip = _resolveComponent("v-chip");
  const _component_v_card_title = _resolveComponent("v-card-title");
  const _component_v_tooltip = _resolveComponent("v-tooltip");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_card_item = _resolveComponent("v-card-item");
  const _component_v_col = _resolveComponent("v-col");
  const _component_v_row = _resolveComponent("v-row");
  const _component_v_tab = _resolveComponent("v-tab");
  const _component_v_tabs = _resolveComponent("v-tabs");
  const _component_v_card_text = _resolveComponent("v-card-text");
  const _component_v_card = _resolveComponent("v-card");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_v_card, {
      class: "d-flex flex-column h-100 rounded-xl overflow-hidden page-main-card",
      elevation: "0",
      variant: "outlined"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_v_card_item, { class: "header-surface px-5 py-3 border-b" }, {
          prepend: _withCtx(() => [
            _createElementVNode("div", _hoisted_2, [
              _createVNode(_component_v_icon, {
                color: "primary",
                size: "22"
              }, {
                default: _withCtx(() => [...(_cache[1] || (_cache[1] = [
                  _createTextVNode("mdi-cloud-sync", -1)
                ]))]),
                _: 1
              })
            ])
          ]),
          append: _withCtx(() => [
            _createElementVNode("div", _hoisted_3, [
              _createVNode(_component_v_btn, {
                icon: "",
                variant: "tonal",
                color: "primary",
                size: "small",
                class: "rounded-lg mr-1",
                onClick: fetchStatus,
                loading: loading.value
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_icon, { size: "18" }, {
                    default: _withCtx(() => [...(_cache[4] || (_cache[4] = [
                      _createTextVNode("mdi-refresh", -1)
                    ]))]),
                    _: 1
                  }),
                  _createVNode(_component_v_tooltip, {
                    activator: "parent",
                    location: "bottom"
                  }, {
                    default: _withCtx(() => [...(_cache[5] || (_cache[5] = [
                      _createTextVNode("刷新状态", -1)
                    ]))]),
                    _: 1
                  })
                ]),
                _: 1
              }, 8, ["loading"]),
              _createVNode(_component_v_btn, {
                color: "primary",
                rounded: "lg",
                variant: "outlined",
                size: "small",
                class: "px-3 font-weight-medium mr-1",
                onClick: notifySwitch
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_icon, {
                    start: "",
                    size: "16"
                  }, {
                    default: _withCtx(() => [...(_cache[6] || (_cache[6] = [
                      _createTextVNode("mdi-cog-outline", -1)
                    ]))]),
                    _: 1
                  }),
                  _cache[7] || (_cache[7] = _createTextVNode(" 配置 ", -1))
                ]),
                _: 1
              }),
              _createVNode(_component_v_btn, {
                icon: "",
                variant: "text",
                size: "small",
                class: "rounded-lg close-btn text-medium-emphasis",
                onClick: notifyClose
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_icon, { size: "18" }, {
                    default: _withCtx(() => [...(_cache[8] || (_cache[8] = [
                      _createTextVNode("mdi-close", -1)
                    ]))]),
                    _: 1
                  }),
                  _createVNode(_component_v_tooltip, {
                    activator: "parent",
                    location: "bottom"
                  }, {
                    default: _withCtx(() => [...(_cache[9] || (_cache[9] = [
                      _createTextVNode("关闭", -1)
                    ]))]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ])
          ]),
          default: _withCtx(() => [
            _createElementVNode("div", null, [
              _createVNode(_component_v_card_title, { class: "text-subtitle-1 font-weight-bold pa-0 d-flex align-center flex-wrap ga-2" }, {
                default: _withCtx(() => [
                  _cache[2] || (_cache[2] = _createElementVNode("span", null, "115 网盘同步监控", -1)),
                  _createVNode(_component_v_chip, {
                    size: "x-small",
                    variant: "tonal",
                    color: statusData.value.is_running ? 'warning' : (statusData.value.last_status?.success ? 'success' : 'error'),
                    class: "font-weight-bold"
                  }, {
                    default: _withCtx(() => [
                      _createTextVNode(_toDisplayString(statusData.value.is_running ? '正在同步 ⏳' : (statusData.value.last_status?.success ? '空闲中 ✅' : '有异常待重试 ⚠️')), 1)
                    ]),
                    _: 1
                  }, 8, ["color"])
                ]),
                _: 1
              }),
              _cache[3] || (_cache[3] = _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "监控入库延迟冷却进度、双向对账异常与一键快速定向重试", -1))
            ])
          ]),
          _: 1
        }),
        _createVNode(_component_v_card_text, { class: "pa-4 flex-grow-1 overflow-y-auto body-surface" }, {
          default: _withCtx(() => [
            _createVNode(_component_v_row, { class: "mb-3 mx-0" }, {
              default: _withCtx(() => [
                _createVNode(_component_v_col, {
                  cols: "12",
                  sm: "4",
                  class: "pa-1"
                }, {
                  default: _withCtx(() => [
                    _createElementVNode("div", _hoisted_4, [
                      _createElementVNode("div", _hoisted_5, _toDisplayString(statusData.value.cooling_count || 0), 1),
                      _createElementVNode("div", _hoisted_6, "冷却缓冲中 (设定 " + _toDisplayString(statusData.value.delay_hours || 2) + "h)", 1)
                    ])
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_col, {
                  cols: "12",
                  sm: "4",
                  class: "pa-1"
                }, {
                  default: _withCtx(() => [
                    _createElementVNode("div", _hoisted_7, [
                      _createElementVNode("div", _hoisted_8, _toDisplayString(statusData.value.ready_count || 0), 1),
                      _cache[10] || (_cache[10] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mt-1" }, "冷却就绪待传输", -1))
                    ])
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_col, {
                  cols: "12",
                  sm: "4",
                  class: "pa-1"
                }, {
                  default: _withCtx(() => [
                    _createElementVNode("div", _hoisted_9, [
                      _createElementVNode("div", _hoisted_10, _toDisplayString((statusData.value.last_status?.missing_files?.length || 0) + (statusData.value.last_status?.corrupt_files?.length || 0)), 1),
                      _cache[11] || (_cache[11] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mt-1" }, "待重试缺失/残缺文件", -1))
                    ])
                  ]),
                  _: 1
                })
              ]),
              _: 1
            }),
            _createElementVNode("div", _hoisted_11, [
              _createElementVNode("div", _hoisted_12, [
                _createVNode(_component_v_btn, {
                  color: "primary",
                  variant: "flat",
                  size: "small",
                  rounded: "lg",
                  onClick: triggerSync,
                  loading: syncing.value,
                  disabled: statusData.value.is_running
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_icon, {
                      start: "",
                      size: "16"
                    }, {
                      default: _withCtx(() => [...(_cache[12] || (_cache[12] = [
                        _createTextVNode("mdi-play", -1)
                      ]))]),
                      _: 1
                    }),
                    _cache[13] || (_cache[13] = _createTextVNode(" 同步已就绪媒体 ", -1))
                  ]),
                  _: 1
                }, 8, ["loading", "disabled"]),
                _createVNode(_component_v_btn, {
                  color: "warning",
                  variant: "tonal",
                  size: "small",
                  rounded: "lg",
                  onClick: triggerRetry,
                  loading: retrying.value,
                  disabled: statusData.value.is_running || (!statusData.value.last_status?.missing_files?.length && !statusData.value.last_status?.corrupt_files?.length)
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_icon, {
                      start: "",
                      size: "16"
                    }, {
                      default: _withCtx(() => [...(_cache[14] || (_cache[14] = [
                        _createTextVNode("mdi-refresh", -1)
                      ]))]),
                      _: 1
                    }),
                    _cache[15] || (_cache[15] = _createTextVNode(" 定向重试失败文件 ", -1))
                  ]),
                  _: 1
                }, 8, ["loading", "disabled"]),
                _createVNode(_component_v_btn, {
                  color: "secondary",
                  variant: "tonal",
                  size: "small",
                  rounded: "lg",
                  onClick: triggerClean,
                  loading: cleaning.value,
                  disabled: statusData.value.is_running
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_icon, {
                      start: "",
                      size: "16"
                    }, {
                      default: _withCtx(() => [...(_cache[16] || (_cache[16] = [
                        _createTextVNode("mdi-broom", -1)
                      ]))]),
                      _: 1
                    }),
                    _cache[17] || (_cache[17] = _createTextVNode(" 清理网盘 ..* 幽灵文件 ", -1))
                  ]),
                  _: 1
                }, 8, ["loading", "disabled"])
              ]),
              (actionMsg.value)
                ? (_openBlock(), _createElementBlock("div", _hoisted_13, _toDisplayString(actionMsg.value), 1))
                : _createCommentVNode("", true)
            ]),
            _createVNode(_component_v_tabs, {
              modelValue: currentTab.value,
              "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((currentTab).value = $event)),
              color: "primary",
              density: "compact",
              class: "mb-3 border-b"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_tab, { value: "queue" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_icon, {
                      start: "",
                      size: "16"
                    }, {
                      default: _withCtx(() => [...(_cache[18] || (_cache[18] = [
                        _createTextVNode("mdi-timer-sand", -1)
                      ]))]),
                      _: 1
                    }),
                    _createTextVNode(" 入库延迟冷却队列 (" + _toDisplayString(queueList.value.length) + ") ", 1)
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_tab, { value: "failed" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_icon, {
                      start: "",
                      size: "16"
                    }, {
                      default: _withCtx(() => [...(_cache[19] || (_cache[19] = [
                        _createTextVNode("mdi-alert-circle-outline", -1)
                      ]))]),
                      _: 1
                    }),
                    _createTextVNode(" 对账异常清单 (" + _toDisplayString((statusData.value.last_status?.missing_files?.length || 0) + (statusData.value.last_status?.corrupt_files?.length || 0)) + ") ", 1)
                  ]),
                  _: 1
                })
              ]),
              _: 1
            }, 8, ["modelValue"]),
            (currentTab.value === 'queue')
              ? (_openBlock(), _createElementBlock("div", _hoisted_14, [
                  (queueList.value.length)
                    ? (_openBlock(), _createElementBlock("div", _hoisted_15, [
                        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(queueList.value, (item, idx) => {
                          return (_openBlock(), _createElementBlock("div", {
                            key: idx,
                            class: "queue-item-card d-flex align-center justify-space-between rounded-xl pa-3"
                          }, [
                            _createElementVNode("div", _hoisted_16, [
                              _createElementVNode("div", _hoisted_17, _toDisplayString(item.key), 1),
                              _createElementVNode("div", _hoisted_18, [
                                _createTextVNode(" 入库时间: " + _toDisplayString(item.enter_time) + " ", 1),
                                (!item.is_ready)
                                  ? (_openBlock(), _createElementBlock("span", _hoisted_19, " (还需冷却等待 " + _toDisplayString(Math.ceil(item.remaining_seconds / 60)) + " 分钟) ", 1))
                                  : (_openBlock(), _createElementBlock("span", _hoisted_20, " (已达到冷却时间，随时可同步) "))
                              ])
                            ]),
                            _createVNode(_component_v_chip, {
                              size: "x-small",
                              color: item.is_ready ? 'success' : 'warning',
                              variant: "tonal",
                              class: "font-weight-bold flex-shrink-0"
                            }, {
                              default: _withCtx(() => [
                                _createTextVNode(_toDisplayString(item.is_ready ? '已就绪' : '缓冲中'), 1)
                              ]),
                              _: 2
                            }, 1032, ["color"])
                          ]))
                        }), 128))
                      ]))
                    : (_openBlock(), _createElementBlock("div", _hoisted_21, [
                        _createVNode(_component_v_icon, {
                          size: "32",
                          color: "primary",
                          class: "mb-2"
                        }, {
                          default: _withCtx(() => [...(_cache[20] || (_cache[20] = [
                            _createTextVNode("mdi-check-circle-outline", -1)
                          ]))]),
                          _: 1
                        }),
                        _cache[21] || (_cache[21] = _createElementVNode("div", { class: "text-caption font-weight-bold text-medium-emphasis" }, "暂无正在冷却中的媒体文件", -1))
                      ]))
                ]))
              : _createCommentVNode("", true),
            (currentTab.value === 'failed')
              ? (_openBlock(), _createElementBlock("div", _hoisted_22, [
                  ((statusData.value.last_status?.missing_files?.length || 0) + (statusData.value.last_status?.corrupt_files?.length || 0))
                    ? (_openBlock(), _createElementBlock("div", _hoisted_23, [
                        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(statusData.value.last_status?.missing_files || [], (file, idx) => {
                          return (_openBlock(), _createElementBlock("div", {
                            key: 'm-' + idx,
                            class: "failed-item-card d-flex align-center justify-space-between rounded-xl pa-3"
                          }, [
                            _createElementVNode("div", _hoisted_24, [
                              _createElementVNode("div", _hoisted_25, _toDisplayString(file), 1),
                              _cache[22] || (_cache[22] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mt-0.5" }, "两端均无对应文件或目标端未创建成功", -1))
                            ]),
                            _createVNode(_component_v_chip, {
                              size: "x-small",
                              color: "error",
                              variant: "flat",
                              class: "font-weight-bold flex-shrink-0"
                            }, {
                              default: _withCtx(() => [...(_cache[23] || (_cache[23] = [
                                _createTextVNode("彻底缺失", -1)
                              ]))]),
                              _: 1
                            })
                          ]))
                        }), 128)),
                        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(statusData.value.last_status?.corrupt_files || [], (file, idx) => {
                          return (_openBlock(), _createElementBlock("div", {
                            key: 'c-' + idx,
                            class: "failed-item-card d-flex align-center justify-space-between rounded-xl pa-3"
                          }, [
                            _createElementVNode("div", _hoisted_26, [
                              _createElementVNode("div", _hoisted_27, _toDisplayString(file), 1),
                              _cache[24] || (_cache[24] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mt-0.5" }, "目标端大小不一致，传输中途断流", -1))
                            ]),
                            _createVNode(_component_v_chip, {
                              size: "x-small",
                              color: "warning",
                              variant: "flat",
                              class: "font-weight-bold flex-shrink-0"
                            }, {
                              default: _withCtx(() => [...(_cache[25] || (_cache[25] = [
                                _createTextVNode("文件残缺", -1)
                              ]))]),
                              _: 1
                            })
                          ]))
                        }), 128))
                      ]))
                    : (_openBlock(), _createElementBlock("div", _hoisted_28, [
                        _createVNode(_component_v_icon, {
                          size: "32",
                          color: "success",
                          class: "mb-2"
                        }, {
                          default: _withCtx(() => [...(_cache[26] || (_cache[26] = [
                            _createTextVNode("mdi-shield-check", -1)
                          ]))]),
                          _: 1
                        }),
                        _cache[27] || (_cache[27] = _createElementVNode("div", { class: "text-caption font-weight-bold text-medium-emphasis" }, "两端文件经对账完全一致，零缺失零残缺！", -1))
                      ]))
                ]))
              : _createCommentVNode("", true)
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
const App = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-4b40485c"]]);

export { App as default };
