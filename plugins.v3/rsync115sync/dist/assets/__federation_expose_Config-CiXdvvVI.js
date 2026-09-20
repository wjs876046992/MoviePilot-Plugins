import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createElementBlock:_createElementBlock,renderList:_renderList,Fragment:_Fragment} = await importShared('vue');


const _hoisted_1 = {
  class: "plugin-config",
  style: {"padding":"18px 22px !important","box-sizing":"border-box","width":"100%"}
};
const _hoisted_2 = { class: "header-icon-box mr-3" };
const _hoisted_3 = {
  key: 0,
  class: "px-5 pt-3"
};
const _hoisted_4 = { class: "settings-group-card rounded-xl overflow-hidden mb-4" };
const _hoisted_5 = { class: "setting-row d-flex align-center justify-space-between px-4 py-3 border-b" };
const _hoisted_6 = { class: "setting-row d-flex align-center justify-space-between px-4 py-3" };
const _hoisted_7 = { class: "d-flex align-center justify-space-between mb-2" };
const _hoisted_8 = { class: "font-weight-bold text-subtitle-2 d-flex align-center" };
const _hoisted_9 = {
  key: 0,
  class: "d-flex flex-column ga-3 mb-4"
};
const _hoisted_10 = { class: "d-flex align-center justify-space-between mb-3" };
const _hoisted_11 = { class: "font-weight-bold text-body-2 text-primary" };
const _hoisted_12 = {
  key: 1,
  class: "empty-hint-box text-center py-6 rounded-xl mb-4 text-caption text-disabled"
};
const _hoisted_13 = { class: "font-weight-bold text-subtitle-2 d-flex align-center mb-2" };
const _hoisted_14 = { class: "settings-group-card rounded-xl overflow-hidden pa-4 mb-4" };
const _hoisted_15 = { class: "font-weight-bold text-subtitle-2 d-flex align-center mb-2" };
const _hoisted_16 = { class: "settings-group-card rounded-xl overflow-hidden pa-4" };

const {ref,onMounted} = await importShared('vue');



const _sfc_main = {
  __name: 'Config',
  props: {
  model: { type: Object, default: () => ({}) },
  api: { type: Object, required: true },
},
  emits: ['close', 'switch'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;

const saving = ref(false);
const error = ref(null);
const successMessage = ref(null);

const config = ref({
  enabled: false,
  listen_transfer: true,
  notify: true,
  delay_hours: 2.0,
  cron: '0 */2 * * *',
  sync_pairs: [],
  media_extensions: 'mp4,mkv,avi,mov,ts,m2ts,iso,wmv,flv,rmvb',
  exclude_patterns: '@eaDir/\n#recycle/\n@__thumb/\n.DS_Store',
  rsync_timeout: 60,
  task_timeout: 3600,
});

function addPair() {
  config.value.sync_pairs.push({
    name: '',
    src: '',
    dest: '',
    all_ext: false,
  });
}

function removePair(index) {
  config.value.sync_pairs.splice(index, 1);
}

function notifyClose() {
  emit('close');
}

function notifySwitch() {
  emit('switch');
}

async function loadConfig() {
  try {
    const res = await props.api.get('plugin/Rsync115Sync/config');
    if (res && res.success && res.data) {
      Object.assign(config.value, res.data);
    }
  } catch (e) {
    console.error('读取配置失败:', e);
  }
}

async function saveConfig() {
  saving.value = true;
  error.value = null;
  successMessage.value = null;
  try {
    const res = await props.api.post('plugin/Rsync115Sync/config', config.value);
    if (res && res.success) {
      successMessage.value = '配置已成功保存！';
    } else {
      error.value = res?.message || '保存配置失败';
    }
  } catch (e) {
    error.value = e.message || '保存配置失败';
  } finally {
    saving.value = false;
  }
}

onMounted(() => {
  loadConfig();
});

return (_ctx, _cache) => {
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_chip = _resolveComponent("v-chip");
  const _component_v_card_title = _resolveComponent("v-card-title");
  const _component_v_tooltip = _resolveComponent("v-tooltip");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_card_item = _resolveComponent("v-card-item");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_switch = _resolveComponent("v-switch");
  const _component_v_text_field = _resolveComponent("v-text-field");
  const _component_v_col = _resolveComponent("v-col");
  const _component_v_checkbox = _resolveComponent("v-checkbox");
  const _component_v_row = _resolveComponent("v-row");
  const _component_v_textarea = _resolveComponent("v-textarea");
  const _component_v_card_text = _resolveComponent("v-card-text");
  const _component_v_spacer = _resolveComponent("v-spacer");
  const _component_v_card_actions = _resolveComponent("v-card-actions");
  const _component_v_card = _resolveComponent("v-card");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_v_card, {
      class: "d-flex flex-column h-100 rounded-xl overflow-hidden config-main-card",
      elevation: "0",
      variant: "outlined"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_v_card_item, { class: "header-surface header-card-item px-5 py-4" }, {
          prepend: _withCtx(() => [
            _createElementVNode("div", _hoisted_2, [
              _createVNode(_component_v_icon, {
                color: "primary",
                size: "22"
              }, {
                default: _withCtx(() => [...(_cache[9] || (_cache[9] = [
                  _createTextVNode("mdi-cloud-sync", -1)
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
              _createVNode(_component_v_card_title, { class: "text-subtitle-1 font-weight-bold pa-0 d-flex align-center" }, {
                default: _withCtx(() => [
                  _cache[11] || (_cache[11] = _createTextVNode(" 115 网盘同步配置 ", -1)),
                  _createVNode(_component_v_chip, {
                    size: "x-small",
                    color: "primary",
                    variant: "tonal",
                    class: "ml-2 font-weight-bold"
                  }, {
                    default: _withCtx(() => [...(_cache[10] || (_cache[10] = [
                      _createTextVNode("v0.0.4", -1)
                    ]))]),
                    _: 1
                  })
                ]),
                _: 1
              }),
              _cache[12] || (_cache[12] = _createElementVNode("div", { class: "header-subtitle text-caption text-medium-emphasis" }, "设定 CD2 挂载目录映射、入库冷却缓冲策略与防假死参数", -1))
            ])
          ]),
          _: 1
        }),
        (successMessage.value || error.value)
          ? (_openBlock(), _createElementBlock("div", _hoisted_3, [
              (successMessage.value)
                ? (_openBlock(), _createBlock(_component_v_alert, {
                    key: 0,
                    type: "success",
                    variant: "tonal",
                    class: "rounded-lg mb-2",
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
                    class: "rounded-lg mb-2",
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
          : _createCommentVNode("", true),
        _createVNode(_component_v_card_text, { class: "config-body px-5 py-4 overflow-y-auto" }, {
          default: _withCtx(() => [
            _createElementVNode("div", _hoisted_4, [
              _createElementVNode("div", _hoisted_5, [
                _cache[15] || (_cache[15] = _createElementVNode("div", null, [
                  _createElementVNode("div", { class: "font-weight-bold text-body-2" }, "启用同步助手"),
                  _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "总控主开关，开启后生效定时轮询与事件监听")
                ], -1)),
                _createVNode(_component_v_switch, {
                  modelValue: config.value.enabled,
                  "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((config.value.enabled) = $event)),
                  color: "primary",
                  inset: "",
                  "hide-details": "",
                  density: "compact"
                }, null, 8, ["modelValue"])
              ]),
              _createElementVNode("div", _hoisted_6, [
                _cache[16] || (_cache[16] = _createElementVNode("div", null, [
                  _createElementVNode("div", { class: "font-weight-bold text-body-2" }, "监听媒体转移入库事件"),
                  _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "下载与刮削转移完成后自动纳入延迟冷却队列")
                ], -1)),
                _createVNode(_component_v_switch, {
                  modelValue: config.value.listen_transfer,
                  "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((config.value.listen_transfer) = $event)),
                  color: "primary",
                  inset: "",
                  "hide-details": "",
                  density: "compact"
                }, null, 8, ["modelValue"])
              ])
            ]),
            _createElementVNode("div", _hoisted_7, [
              _createElementVNode("div", _hoisted_8, [
                _createVNode(_component_v_icon, {
                  size: "18",
                  color: "primary",
                  class: "mr-1"
                }, {
                  default: _withCtx(() => [...(_cache[17] || (_cache[17] = [
                    _createTextVNode("mdi-folder-swap-outline", -1)
                  ]))]),
                  _: 1
                }),
                _createTextVNode(" 同步目录映射对 (" + _toDisplayString(config.value.sync_pairs.length) + ") ", 1)
              ]),
              _createVNode(_component_v_btn, {
                size: "small",
                variant: "tonal",
                color: "primary",
                rounded: "lg",
                onClick: addPair
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_icon, {
                    start: "",
                    size: "16"
                  }, {
                    default: _withCtx(() => [...(_cache[18] || (_cache[18] = [
                      _createTextVNode("mdi-plus", -1)
                    ]))]),
                    _: 1
                  }),
                  _cache[19] || (_cache[19] = _createTextVNode(" 添加目录映射 ", -1))
                ]),
                _: 1
              })
            ]),
            (config.value.sync_pairs.length)
              ? (_openBlock(), _createElementBlock("div", _hoisted_9, [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(config.value.sync_pairs, (pair, idx) => {
                    return (_openBlock(), _createElementBlock("div", {
                      key: idx,
                      class: "pair-card rounded-xl pa-4"
                    }, [
                      _createElementVNode("div", _hoisted_10, [
                        _createElementVNode("span", _hoisted_11, "映射任务 #" + _toDisplayString(idx + 1), 1),
                        _createVNode(_component_v_btn, {
                          icon: "",
                          size: "x-small",
                          variant: "text",
                          color: "error",
                          onClick: $event => (removePair(idx))
                        }, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_icon, { size: "18" }, {
                              default: _withCtx(() => [...(_cache[20] || (_cache[20] = [
                                _createTextVNode("mdi-trash-can-outline", -1)
                              ]))]),
                              _: 1
                            })
                          ]),
                          _: 1
                        }, 8, ["onClick"])
                      ]),
                      _createVNode(_component_v_row, { density: "compact" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_col, {
                            cols: "12",
                            sm: "4"
                          }, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_text_field, {
                                modelValue: pair.name,
                                "onUpdate:modelValue": $event => ((pair.name) = $event),
                                label: "任务备注名称",
                                variant: "outlined",
                                density: "compact",
                                placeholder: "例如：电影/电视剧"
                              }, null, 8, ["modelValue", "onUpdate:modelValue"])
                            ]),
                            _: 2
                          }, 1024),
                          _createVNode(_component_v_col, {
                            cols: "12",
                            sm: "4"
                          }, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_text_field, {
                                modelValue: pair.src,
                                "onUpdate:modelValue": $event => ((pair.src) = $event),
                                label: "本地源目录",
                                variant: "outlined",
                                density: "compact",
                                placeholder: "/volume3/HomeTheater/emby/TV"
                              }, null, 8, ["modelValue", "onUpdate:modelValue"])
                            ]),
                            _: 2
                          }, 1024),
                          _createVNode(_component_v_col, {
                            cols: "12",
                            sm: "4"
                          }, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_text_field, {
                                modelValue: pair.dest,
                                "onUpdate:modelValue": $event => ((pair.dest) = $event),
                                label: "CD2 挂载 115 目录",
                                variant: "outlined",
                                density: "compact",
                                placeholder: "/volume2/CloudNAS/115/TV"
                              }, null, 8, ["modelValue", "onUpdate:modelValue"])
                            ]),
                            _: 2
                          }, 1024),
                          _createVNode(_component_v_col, { cols: "12" }, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_checkbox, {
                                modelValue: pair.all_ext,
                                "onUpdate:modelValue": $event => ((pair.all_ext) = $event),
                                label: "同步所有文件类型 (默认仅同步视频，勾选后将同步字幕与元数据等全部格式)",
                                density: "compact",
                                "hide-details": "",
                                color: "primary"
                              }, null, 8, ["modelValue", "onUpdate:modelValue"])
                            ]),
                            _: 2
                          }, 1024)
                        ]),
                        _: 2
                      }, 1024)
                    ]))
                  }), 128))
                ]))
              : (_openBlock(), _createElementBlock("div", _hoisted_12, " 暂未配置任何目录映射，点击上方按钮添加你的本地媒体目录与 CD2 挂载路径 ")),
            _createElementVNode("div", _hoisted_13, [
              _createVNode(_component_v_icon, {
                size: "18",
                color: "primary",
                class: "mr-1"
              }, {
                default: _withCtx(() => [...(_cache[21] || (_cache[21] = [
                  _createTextVNode("mdi-timer-sand", -1)
                ]))]),
                _: 1
              }),
              _cache[22] || (_cache[22] = _createTextVNode(" 入库冷却缓冲与调度 ", -1))
            ]),
            _createElementVNode("div", _hoisted_14, [
              _createVNode(_component_v_row, { density: "comfortable" }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_col, {
                    cols: "12",
                    sm: "6"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_text_field, {
                        modelValue: config.value.delay_hours,
                        "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((config.value.delay_hours) = $event)),
                        modelModifiers: { number: true },
                        label: "入库冷却延迟时长 (小时)",
                        type: "number",
                        step: "0.5",
                        min: "0",
                        variant: "outlined",
                        density: "compact",
                        suffix: "小时",
                        hint: "媒体入库后等待 N 小时，留足外挂字幕下载与刮削时间，到期后才触发上传",
                        "persistent-hint": ""
                      }, null, 8, ["modelValue"])
                    ]),
                    _: 1
                  }),
                  _createVNode(_component_v_col, {
                    cols: "12",
                    sm: "6"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_text_field, {
                        modelValue: config.value.cron,
                        "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((config.value.cron) = $event)),
                        label: "定时检查 Cron 规则",
                        variant: "outlined",
                        density: "compact",
                        placeholder: "0 */2 * * *",
                        hint: "默认每 2 小时定时巡检一次达到冷却要求的就绪文件",
                        "persistent-hint": ""
                      }, null, 8, ["modelValue"])
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _createElementVNode("div", _hoisted_15, [
              _createVNode(_component_v_icon, {
                size: "18",
                color: "primary",
                class: "mr-1"
              }, {
                default: _withCtx(() => [...(_cache[23] || (_cache[23] = [
                  _createTextVNode("mdi-shield-check-outline", -1)
                ]))]),
                _: 1
              }),
              _cache[24] || (_cache[24] = _createTextVNode(" CD2 核心过滤与防假死参数 ", -1))
            ]),
            _createElementVNode("div", _hoisted_16, [
              _createVNode(_component_v_row, { density: "compact" }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_col, {
                    cols: "12",
                    sm: "6"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_text_field, {
                        modelValue: config.value.rsync_timeout,
                        "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((config.value.rsync_timeout) = $event)),
                        modelModifiers: { number: true },
                        label: "rsync I/O 超时 (秒)",
                        type: "number",
                        variant: "outlined",
                        density: "compact",
                        hint: "网络异常中断时快速失败，防止 FUSE 挂起死锁",
                        "persistent-hint": ""
                      }, null, 8, ["modelValue"])
                    ]),
                    _: 1
                  }),
                  _createVNode(_component_v_col, {
                    cols: "12",
                    sm: "6"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_text_field, {
                        modelValue: config.value.task_timeout,
                        "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((config.value.task_timeout) = $event)),
                        modelModifiers: { number: true },
                        label: "单次任务最大超时 (秒)",
                        type: "number",
                        variant: "outlined",
                        density: "compact",
                        hint: "进程超过此时长强制杀死，彻底避免进程僵死",
                        "persistent-hint": ""
                      }, null, 8, ["modelValue"])
                    ]),
                    _: 1
                  }),
                  _createVNode(_component_v_col, { cols: "12" }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_textarea, {
                        modelValue: config.value.exclude_patterns,
                        "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((config.value.exclude_patterns) = $event)),
                        label: "排除文件与目录规则 (每行一条，严格继承 sync_115.sh)",
                        variant: "outlined",
                        density: "compact",
                        rows: "3",
                        hint: "默认排除群晖元数据与系统废件",
                        "persistent-hint": ""
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
        _createVNode(_component_v_card_actions, { class: "px-5 py-3 border-t bg-surface" }, {
          default: _withCtx(() => [
            _createVNode(_component_v_btn, {
              variant: "tonal",
              rounded: "lg",
              color: "primary",
              onClick: notifySwitch
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_icon, {
                  start: "",
                  size: "16"
                }, {
                  default: _withCtx(() => [...(_cache[25] || (_cache[25] = [
                    _createTextVNode("mdi-view-dashboard-outline", -1)
                  ]))]),
                  _: 1
                }),
                _cache[26] || (_cache[26] = _createTextVNode(" 查看监控看板 ", -1))
              ]),
              _: 1
            }),
            _createVNode(_component_v_spacer),
            _createVNode(_component_v_btn, {
              variant: "flat",
              color: "primary",
              rounded: "lg",
              class: "px-6",
              onClick: saveConfig,
              loading: saving.value
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_icon, {
                  start: "",
                  size: "16"
                }, {
                  default: _withCtx(() => [...(_cache[27] || (_cache[27] = [
                    _createTextVNode("mdi-content-save", -1)
                  ]))]),
                  _: 1
                }),
                _cache[28] || (_cache[28] = _createTextVNode(" 保存配置 ", -1))
              ]),
              _: 1
            }, 8, ["loading"])
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
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-0b19968b"]]);

export { Config as default };
