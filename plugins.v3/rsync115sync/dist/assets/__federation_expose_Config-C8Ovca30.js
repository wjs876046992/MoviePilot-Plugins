import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createElementBlock:_createElementBlock,renderList:_renderList,Fragment:_Fragment} = await importShared('vue');


const _hoisted_1 = { class: "plugin-config" };
const _hoisted_2 = { class: "header-icon-box mr-3" };
const _hoisted_3 = {
  key: 0,
  class: "px-5 pt-3"
};
const _hoisted_4 = { class: "settings-group-card rounded-xl overflow-hidden mb-4" };
const _hoisted_5 = { class: "setting-row d-flex align-center justify-space-between px-4 py-3 border-b" };
const _hoisted_6 = { class: "setting-row d-flex align-center justify-space-between px-4 py-3" };
const _hoisted_7 = { class: "setting-row d-flex align-center justify-space-between px-4 py-3" };
const _hoisted_8 = { class: "font-weight-bold text-body-2" };
const _hoisted_9 = { class: "section-header d-flex align-center justify-space-between mb-2" };
const _hoisted_10 = { class: "font-weight-bold text-subtitle-2 d-flex align-center" };
const _hoisted_11 = {
  key: 0,
  class: "d-flex flex-column ga-3 mb-4"
};
const _hoisted_12 = { class: "d-flex align-center justify-space-between mb-3" };
const _hoisted_13 = { class: "font-weight-bold text-body-2 text-primary" };
const _hoisted_14 = { class: "dep-note dep-free mt-1" };
const _hoisted_15 = { class: "dep-note dep-needs-helper mt-1" };
const _hoisted_16 = {
  key: 1,
  class: "empty-hint-box text-center py-6 rounded-xl mb-4 text-caption text-disabled"
};
const _hoisted_17 = { class: "font-weight-bold text-subtitle-2 d-flex align-center mb-2" };
const _hoisted_18 = { class: "settings-group-card rounded-xl overflow-hidden pa-4 mb-4" };
const _hoisted_19 = { class: "font-weight-bold text-subtitle-2 d-flex align-center mb-2" };
const _hoisted_20 = { class: "settings-group-card rounded-xl overflow-hidden pa-4" };
const _hoisted_21 = { class: "font-weight-bold text-subtitle-2 d-flex align-center mb-2 mt-4" };
const _hoisted_22 = { class: "settings-group-card rounded-xl overflow-hidden" };
const _hoisted_23 = { class: "setting-row d-flex align-center justify-space-between px-4 py-3 border-b" };
const _hoisted_24 = {
  key: 0,
  class: "px-4 py-2 batch-bar"
};
const _hoisted_25 = { class: "d-flex align-center flex-wrap ga-2" };
const _hoisted_26 = { class: "text-caption text-medium-emphasis" };
const _hoisted_27 = {
  key: 0,
  class: "text-caption text-warning font-weight-medium mt-1"
};
const _hoisted_28 = { class: "px-4 py-3" };
const _hoisted_29 = { class: "font-weight-bold text-subtitle-2 d-flex align-center mb-2" };
const _hoisted_30 = { class: "dep-split rounded-lg mb-3" };
const _hoisted_31 = { class: "dep-split-row" };
const _hoisted_32 = { class: "dep-split-row" };
const _hoisted_33 = { class: "settings-group-card rounded-xl overflow-hidden" };
const _hoisted_34 = { class: "setting-row d-flex align-center justify-space-between px-4 py-3 border-b" };
const _hoisted_35 = { class: "setting-row d-flex align-center justify-space-between px-4 py-3" };
const _hoisted_36 = { class: "section-header d-flex align-center mb-2 mt-5" };
const _hoisted_37 = { class: "font-weight-bold text-subtitle-2 d-flex align-center" };
const _hoisted_38 = { class: "settings-group-card rounded-xl overflow-hidden mb-4" };
const _hoisted_39 = { class: "setting-row d-flex align-items-center px-4 py-3 border-b" };

const {ref,computed,onMounted} = await importShared('vue');



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
  // 与后端 _MISSED_SCAN_ENABLED_DEFAULT 保持一致：默认关闭
  missed_scan_enabled: false,
  notify: true,
  delay_hours: 2.0,
  cron: '0 */2 * * *',
  sync_pairs: [],
  media_extensions: 'mp4,mkv,ts,iso,rmvb,avi,mov,mpeg,mpg,wmv,3gp,asf,m4v,flv,m2ts,tp,f4v,srt,ssa,ass',
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
  // 只剩渠道过滤一项：与后端实例默认值保持一致，渠道默认只开 emby
  // （宿主原生支持、零额外配置）。自建端点及其四条防护配置已于 2026-09-22 移除。
  webhook_channels: ['emby'],
  // strm 观察宽限期：与后端 DEFAULT 及 _api_get_config 的兜底值保持 6.0 一致。
  // 这里必须显式声明：/config 未返回该字段时（例如宿主配置里从未存过），
  // v-model.number 绑定 undefined 会让输入框空白并写回 NaN。
  strm_grace_hours: 6.0,
});

// ---- 限流参数的实时可读化：把秒数/个数换算成用户能判断的速率与提示 ----

// 窗口时长的可读表述（秒 → 分钟/小时）
const windowHumanText = computed(() => {
  const s = Number(config.value.upload_window_secs) || 0;
  if (s <= 0) return '（未设置）'
  if (s % 3600 === 0) return `${s / 3600} 小时`
  if (s % 60 === 0) return `${s / 60} 分钟`
  return `${s} 秒`
});

// 平均速率：每窗口配额 / 窗口时长，让用户直观看到“每分钟大概传几个”
const effectiveRateText = computed(() => {
  const n = Number(config.value.upload_max_per_window) || 0;
  const s = Number(config.value.upload_window_secs) || 0;
  if (n <= 0 || s <= 0) return '未启用'
  const perMin = (n * 60) / s;
  if (perMin >= 10) return `${perMin.toFixed(0)} 个/分钟`
  if (perMin >= 1) return `${perMin.toFixed(1)} 个/分钟`
  return `${(perMin * 60).toFixed(0)} 个/小时`
});

// 参数合理性提醒：避免用户把限流调成“形同虚设”或“永远跑不完”
const rateConfigWarnings = computed(() => {
  const warns = [];
  const batch = Number(config.value.upload_batch_size) || 0;
  const quota = Number(config.value.upload_max_per_window) || 0;
  const win = Number(config.value.upload_window_secs) || 0;
  const backoff = Number(config.value.backoff_secs) || 0;

  if (quota <= 0) {
    warns.push('单窗口配额为 0：限流将拦截全部上传，建议保持 500 或更高。');
  }
  if (batch <= 0) {
    warns.push('单批上限为 0：单次将不处理任何文件。');
  }
  if (batch > 0 && quota > 0 && batch > quota) {
    warns.push(
      `单批上限（${batch}）大于窗口配额（${quota}）：单批就会耗尽整个窗口额度，` +
      `建议把单批上限设为不高于窗口配额。`
    );
  }
  if (win <= 0) {
    warns.push('窗口时长需大于 0 秒，否则配额会立即失效。');
  }
  if (backoff > 0 && backoff < 60) {
    warns.push(`退避时长仅 ${backoff} 秒：过短可能来不及让 115 侧恢复，建议至少 300 秒。`);
  }
  // 速率过高告警：这是最容易触发风控的配置，必须显式提示
  if (quota > 0 && win > 0) {
    const perMin = (quota * 60) / win;
    if (perMin > 60) {
      warns.push(
        `当前速率约 ${perMin.toFixed(0)} 个/分钟（超过每秒 1 个），触发 115 风控的风险很高。` +
        `建议降低「单窗口上传文件数上限」或延长「限流窗口时长」。`
      );
    }
  }
  return warns
});

// 渠道列表在界面上按逗号分隔的纯文本编辑（用户只需要填一两个渠道名，
// 为此做一个 chips 编辑器不划算），但后端存的是数组 —— 因此双向转换，
// 且写入时过滤空项：把 `"emby,,jellyfin"` 里的空串存进配置，后端要额外兜。
const webhookChannelsText = computed({
  get: () => (Array.isArray(config.value.webhook_channels)
    ? config.value.webhook_channels.join(', ')
    : String(config.value.webhook_channels || '')),
  set: (value) => {
    config.value.webhook_channels = String(value || '')
      .split(',')
      .map((item) => item.trim().toLowerCase())
      .filter((item) => item.length > 0);
  },
});

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
                default: _withCtx(() => [...(_cache[19] || (_cache[19] = [
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
                  default: _withCtx(() => [...(_cache[23] || (_cache[23] = [
                    _createTextVNode("mdi-close", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_v_tooltip, {
                  activator: "parent",
                  location: "bottom"
                }, {
                  default: _withCtx(() => [...(_cache[24] || (_cache[24] = [
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
                  _cache[21] || (_cache[21] = _createTextVNode(" 115 网盘同步配置 ", -1)),
                  _createVNode(_component_v_chip, {
                    size: "x-small",
                    color: "primary",
                    variant: "tonal",
                    class: "ml-2 font-weight-bold"
                  }, {
                    default: _withCtx(() => [...(_cache[20] || (_cache[20] = [
                      _createTextVNode("v0.2.3", -1)
                    ]))]),
                    _: 1
                  })
                ]),
                _: 1
              }),
              _cache[22] || (_cache[22] = _createElementVNode("div", { class: "header-subtitle text-caption text-medium-emphasis" }, "设定 CD2 挂载目录映射、入库冷却缓冲策略与防假死参数", -1))
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
                _cache[25] || (_cache[25] = _createElementVNode("div", null, [
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
                _cache[26] || (_cache[26] = _createElementVNode("div", null, [
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
              ]),
              _createElementVNode("div", _hoisted_7, [
                _createElementVNode("div", null, [
                  _createElementVNode("div", _hoisted_8, [
                    _cache[28] || (_cache[28] = _createTextVNode(" 源端补齐扫描（默认关闭） ", -1)),
                    _createVNode(_component_v_chip, {
                      size: "x-small",
                      color: "warning",
                      variant: "tonal",
                      class: "ml-1 font-weight-bold"
                    }, {
                      default: _withCtx(() => [...(_cache[27] || (_cache[27] = [
                        _createTextVNode("谨慎", -1)
                      ]))]),
                      _: 1
                    })
                  ]),
                  _cache[29] || (_cache[29] = _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, [
                    _createTextVNode(" 每轮同步前遍历本地源目录，把「插件忙时错过的入库事件」补回来。 它靠文件修改时间判断新增，"),
                    _createElementVNode("strong", null, "无法区分「真的新入库」和「老文件被重新写入」"),
                    _createTextVNode(" （刮削写 nfo、下载器续传、套件刷新时间戳都会命中）， 开启后可能把很久以前就入库的文件反复当成新文件补进队列，且这类补入不等待冷却。 只有在确认经常丢事件时才开启。 ")
                  ], -1))
                ]),
                _createVNode(_component_v_switch, {
                  modelValue: config.value.missed_scan_enabled,
                  "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((config.value.missed_scan_enabled) = $event)),
                  color: "warning",
                  inset: "",
                  "hide-details": "",
                  density: "compact"
                }, null, 8, ["modelValue"])
              ])
            ]),
            _createElementVNode("div", _hoisted_9, [
              _createElementVNode("div", _hoisted_10, [
                _createVNode(_component_v_icon, {
                  size: "18",
                  color: "primary",
                  class: "mr-1"
                }, {
                  default: _withCtx(() => [...(_cache[30] || (_cache[30] = [
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
                    default: _withCtx(() => [...(_cache[31] || (_cache[31] = [
                      _createTextVNode("mdi-plus", -1)
                    ]))]),
                    _: 1
                  }),
                  _cache[32] || (_cache[32] = _createTextVNode(" 添加目录映射 ", -1))
                ]),
                _: 1
              })
            ]),
            _createVNode(_component_v_alert, {
              type: "info",
              variant: "tonal",
              density: "compact",
              class: "rounded-lg mb-3 text-body-2"
            }, {
              default: _withCtx(() => [...(_cache[33] || (_cache[33] = [
                _createTextVNode(" 为每个媒体库配置一对路径：", -1),
                _createElementVNode("b", null, "本地源目录", -1),
                _createTextVNode(" → ", -1),
                _createElementVNode("b", null, "CD2 挂载的 115 目录", -1),
                _createTextVNode("。 插件只同步这些映射内的文件，不会扫描其它位置。 ", -1),
                _createElementVNode("b", null, "「同步所有文件类型」", -1),
                _createTextVNode("关闭时只传视频与字幕（推荐），开启后连同 nfo、图片等一律上传； 文件类型由下方「同步的扩展名」统一控制。开启该选项的映射还有一个区别： webhook 只推来一个文件时，同目录下的其它文件会一并入队（不递归子目录）—— 否则「全都要上传」就变成了「只传被点到名的那一个」。 ", -1)
              ]))]),
              _: 1
            }),
            (config.value.sync_pairs.length)
              ? (_openBlock(), _createElementBlock("div", _hoisted_11, [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(config.value.sync_pairs, (pair, idx) => {
                    return (_openBlock(), _createElementBlock("div", {
                      key: idx,
                      class: "pair-card rounded-xl pa-4"
                    }, [
                      _createElementVNode("div", _hoisted_12, [
                        _createElementVNode("span", _hoisted_13, "映射任务 #" + _toDisplayString(idx + 1), 1),
                        _createVNode(_component_v_btn, {
                          icon: "",
                          size: "x-small",
                          variant: "text",
                          color: "error",
                          onClick: $event => (removePair(idx))
                        }, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_icon, { size: "18" }, {
                              default: _withCtx(() => [...(_cache[34] || (_cache[34] = [
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
                          }, 1024),
                          _createVNode(_component_v_col, { cols: "12" }, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_text_field, {
                                modelValue: pair.strm_dir,
                                "onUpdate:modelValue": $event => ((pair.strm_dir) = $event),
                                label: "strm 目录（可选，用于上传结果交叉验证）",
                                variant: "outlined",
                                density: "compact",
                                placeholder: "例如 /vol1/strm/TV —— 留空则不启用该映射的验证",
                                hint: "若你用 strm 类插件在本地生成指针文件，且 strm 文件名与整理后文件同名，填写其根目录。同步成功后进入观察期（默认 6 小时），到期仍未生成对应 .strm 会标记为「疑似上传异常」。看板上可先请 STRM 助手补生成（成本低、多半能直接解决），确认无效后再删旧重传。观察与扫描全程纯本地，零 115 API。",
                                "persistent-hint": ""
                              }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                              _createElementVNode("div", _hoisted_14, [
                                _createVNode(_component_v_icon, { size: "13" }, {
                                  default: _withCtx(() => [...(_cache[35] || (_cache[35] = [
                                    _createTextVNode("mdi-check-circle-outline", -1)
                                  ]))]),
                                  _: 1
                                }),
                                _cache[36] || (_cache[36] = _createTextVNode(" 不依赖 P115StrmHelper：任何会生成 .strm 的插件都可以， 甚至完全不用插件、只填一个目录也能工作 ", -1))
                              ])
                            ]),
                            _: 2
                          }, 1024),
                          _createVNode(_component_v_col, { cols: "12" }, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_text_field, {
                                modelValue: pair.pan_dir,
                                "onUpdate:modelValue": $event => ((pair.pan_dir) = $event),
                                label: "网盘目录（可选，仅「先尝试生成 strm」需要）",
                                variant: "outlined",
                                density: "compact",
                                placeholder: "例如 /HomeTheater/TV —— 填 115 网盘里的真实路径，留空则该映射不支持补生成",
                                hint: "填写该映射在 115 网盘里的目录（不是 CD2 挂载路径）。看板的「先尝试生成 strm」会据此把参数传给 P115StrmHelper。注意：助手只接受它自己「全量同步路径」里配置过的网盘路径，填了但助手没配的话，命令会被助手拒绝（提示路径匹配错误）。本地 strm 目录与网盘目录是两棵独立的树，所以需要单独填、无法自动推导。",
                                "persistent-hint": ""
                              }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                              _createElementVNode("div", _hoisted_15, [
                                _createVNode(_component_v_icon, { size: "13" }, {
                                  default: _withCtx(() => [...(_cache[37] || (_cache[37] = [
                                    _createTextVNode("mdi-link-variant", -1)
                                  ]))]),
                                  _: 1
                                }),
                                _cache[38] || (_cache[38] = _createElementVNode("b", null, "依赖 P115StrmHelper", -1)),
                                _cache[39] || (_cache[39] = _createTextVNode("：仅「先尝试生成 strm」用得到它。 留空只是该映射不能用补生成，", -1)),
                                _cache[40] || (_cache[40] = _createElementVNode("b", null, "不影响同步、对账、观察与删旧重传", -1))
                              ])
                            ]),
                            _: 2
                          }, 1024)
                        ]),
                        _: 2
                      }, 1024)
                    ]))
                  }), 128))
                ]))
              : (_openBlock(), _createElementBlock("div", _hoisted_16, " 暂未配置任何目录映射，点击上方按钮添加你的本地媒体目录与 CD2 挂载路径 ")),
            _createElementVNode("div", _hoisted_17, [
              _createVNode(_component_v_icon, {
                size: "18",
                color: "primary",
                class: "mr-1"
              }, {
                default: _withCtx(() => [...(_cache[41] || (_cache[41] = [
                  _createTextVNode("mdi-timer-sand", -1)
                ]))]),
                _: 1
              }),
              _cache[42] || (_cache[42] = _createTextVNode(" 入库冷却缓冲与调度 ", -1))
            ]),
            _createElementVNode("div", _hoisted_18, [
              _createVNode(_component_v_row, { density: "comfortable" }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_col, {
                    cols: "12",
                    sm: "6"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_text_field, {
                        modelValue: config.value.delay_hours,
                        "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((config.value.delay_hours) = $event)),
                        modelModifiers: { number: true },
                        label: "入库冷却延迟时长 (小时)",
                        type: "number",
                        step: "0.5",
                        min: "0",
                        variant: "outlined",
                        density: "compact",
                        suffix: "小时",
                        hint: "媒体入库后等待 N 小时再上传，留足外挂字幕下载与刮削时间，避免抢先上传导致字幕丢失。设为 0 可关闭等待",
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
                        "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((config.value.cron) = $event)),
                        label: "定时检查 Cron 规则",
                        variant: "outlined",
                        density: "compact",
                        placeholder: "0 */2 * * *",
                        hint: "多久巡检一次。到期文件会按上面的限流规则分批上传。补传队列未完成时优先续跑",
                        "persistent-hint": ""
                      }, null, 8, ["modelValue"])
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _createElementVNode("div", _hoisted_19, [
              _createVNode(_component_v_icon, {
                size: "18",
                color: "primary",
                class: "mr-1"
              }, {
                default: _withCtx(() => [...(_cache[43] || (_cache[43] = [
                  _createTextVNode("mdi-shield-check-outline", -1)
                ]))]),
                _: 1
              }),
              _cache[44] || (_cache[44] = _createTextVNode(" CD2 核心过滤与防假死参数 ", -1))
            ]),
            _createElementVNode("div", _hoisted_20, [
              _createVNode(_component_v_row, { density: "compact" }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_col, {
                    cols: "12",
                    sm: "6"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_text_field, {
                        modelValue: config.value.rsync_timeout,
                        "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((config.value.rsync_timeout) = $event)),
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
                        "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((config.value.task_timeout) = $event)),
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
                        "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((config.value.exclude_patterns) = $event)),
                        label: "排除文件与目录规则 (每行一条，严格继承 sync_115.sh)",
                        variant: "outlined",
                        density: "compact",
                        rows: "3",
                        hint: "每行一条，命中即跳过。默认排除群晖元数据与系统临时文件；注意排除只作用于源端，无法清理 115 上已有的残留",
                        "persistent-hint": ""
                      }, null, 8, ["modelValue"])
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _createElementVNode("div", _hoisted_21, [
              _createVNode(_component_v_icon, {
                size: "18",
                color: "primary",
                class: "mr-1"
              }, {
                default: _withCtx(() => [...(_cache[45] || (_cache[45] = [
                  _createTextVNode("mdi-speedometer-slow", -1)
                ]))]),
                _: 1
              }),
              _cache[46] || (_cache[46] = _createTextVNode(" 上传限流与风控退避 ", -1))
            ]),
            _createVNode(_component_v_alert, {
              type: "info",
              variant: "tonal",
              density: "compact",
              class: "rounded-lg mb-2 text-body-2"
            }, {
              default: _withCtx(() => [...(_cache[47] || (_cache[47] = [
                _createElementVNode("div", { class: "font-weight-bold mb-1" }, "为什么需要限流？", -1),
                _createTextVNode(" 115 网盘会统计", -1),
                _createElementVNode("b", null, "单位时间内上传的文件个数", -1),
                _createTextVNode("。大量小文件（尤其是字幕、样张） 在短时间内集中上传最容易被判定为异常流量而触发风控，导致上传被拒绝甚至临时封禁。 ", -1),
                _createElementVNode("br", null, null, -1),
                _createTextVNode(" 本插件用两层限制来避免：", -1),
                _createElementVNode("b", null, "单批上限", -1),
                _createTextVNode("控制一次传输提交多少文件， ", -1),
                _createElementVNode("b", null, "窗口配额", -1),
                _createTextVNode("控制一段时间内累计上传多少文件。超出的部分不会丢弃， 会在下一个窗口自动继续，直到全部传完。 ", -1)
              ]))]),
              _: 1
            }),
            _createElementVNode("div", _hoisted_22, [
              _createElementVNode("div", _hoisted_23, [
                _cache[48] || (_cache[48] = _createElementVNode("div", null, [
                  _createElementVNode("div", { class: "font-weight-bold text-body-2" }, "启用上传限流"),
                  _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "按时间窗口限制上传文件数，防止小文件高频上传触发 115 风控")
                ], -1)),
                _createVNode(_component_v_switch, {
                  modelValue: config.value.rate_limit_enabled,
                  "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((config.value.rate_limit_enabled) = $event)),
                  color: "primary",
                  inset: "",
                  "hide-details": "",
                  density: "compact"
                }, null, 8, ["modelValue"])
              ]),
              (config.value.rate_limit_enabled)
                ? (_openBlock(), _createElementBlock("div", _hoisted_24, [
                    _createElementVNode("div", _hoisted_25, [
                      _createVNode(_component_v_chip, {
                        size: "small",
                        color: "primary",
                        variant: "tonal",
                        class: "font-weight-bold"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_icon, {
                            start: "",
                            size: "14"
                          }, {
                            default: _withCtx(() => [...(_cache[49] || (_cache[49] = [
                              _createTextVNode("mdi-speedometer", -1)
                            ]))]),
                            _: 1
                          }),
                          _createTextVNode(" 当前速率约 " + _toDisplayString(effectiveRateText.value), 1)
                        ]),
                        _: 1
                      }),
                      _createElementVNode("span", _hoisted_26, " 即每 " + _toDisplayString(windowHumanText.value) + " 最多上传 " + _toDisplayString(config.value.upload_max_per_window || 0) + " 个文件 ", 1)
                    ]),
                    (rateConfigWarnings.value.length)
                      ? (_openBlock(), _createElementBlock("div", _hoisted_27, [
                          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(rateConfigWarnings.value, (w, i) => {
                            return (_openBlock(), _createElementBlock("div", { key: i }, "⚠️ " + _toDisplayString(w), 1))
                          }), 128))
                        ]))
                      : _createCommentVNode("", true)
                  ]))
                : _createCommentVNode("", true),
              _createElementVNode("div", _hoisted_28, [
                _createVNode(_component_v_row, { density: "compact" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_col, {
                      cols: "12",
                      sm: "6"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_text_field, {
                          modelValue: config.value.upload_batch_size,
                          "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((config.value.upload_batch_size) = $event)),
                          modelModifiers: { number: true },
                          label: "单批文件数上限",
                          type: "number",
                          variant: "outlined",
                          density: "compact",
                          disabled: !config.value.rate_limit_enabled,
                          hint: "一次传输最多提交多少个文件。宁小勿大：小文件扎堆时，大批量最容易触发风控。超出部分自动留到下一轮，不会丢失",
                          "persistent-hint": ""
                        }, null, 8, ["modelValue", "disabled"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_v_col, {
                      cols: "12",
                      sm: "6"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_text_field, {
                          modelValue: config.value.upload_max_per_window,
                          "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((config.value.upload_max_per_window) = $event)),
                          modelModifiers: { number: true },
                          label: "单窗口上传文件数上限",
                          type: "number",
                          variant: "outlined",
                          density: "compact",
                          disabled: !config.value.rate_limit_enabled,
                          hint: "一个窗口内累计最多上传多少个文件。这是防风控的主要闸门——115 按单位时间内的文件个数判定异常",
                          "persistent-hint": ""
                        }, null, 8, ["modelValue", "disabled"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_v_col, {
                      cols: "12",
                      sm: "6"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_text_field, {
                          modelValue: config.value.upload_window_secs,
                          "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((config.value.upload_window_secs) = $event)),
                          modelModifiers: { number: true },
                          label: "限流窗口时长 (秒)",
                          type: "number",
                          variant: "outlined",
                          density: "compact",
                          disabled: !config.value.rate_limit_enabled,
                          hint: "默认 1800 秒（30 分钟）。窗口结束后额度自动重置，未传完的继续。窗口越短、峰值越高，建议不要低于 300 秒",
                          "persistent-hint": ""
                        }, null, 8, ["modelValue", "disabled"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_v_col, {
                      cols: "12",
                      sm: "6"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_text_field, {
                          modelValue: config.value.backoff_secs,
                          "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => ((config.value.backoff_secs) = $event)),
                          modelModifiers: { number: true },
                          label: "命中风控后退避时长 (秒)",
                          type: "number",
                          variant: "outlined",
                          density: "compact",
                          disabled: !config.value.rate_limit_enabled,
                          hint: "一旦命中风控特征，暂停上传这么久再恢复，给 115 侧缓冲时间。默认 3600 秒（1 小时）",
                          "persistent-hint": ""
                        }, null, 8, ["modelValue", "disabled"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_v_col, { cols: "12" }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_textarea, {
                          modelValue: config.value.rate_limit_keywords,
                          "onUpdate:modelValue": _cache[15] || (_cache[15] = $event => ((config.value.rate_limit_keywords) = $event)),
                          label: "风控特征关键词 (每行一条，命中即退避)",
                          variant: "outlined",
                          density: "compact",
                          rows: "3",
                          disabled: !config.value.rate_limit_enabled,
                          hint: "从 rsync / CD2 的错误输出里匹配这些关键词，命中即暂停上传并进入退避。每行一条，不区分大小写",
                          "persistent-hint": ""
                        }, null, 8, ["modelValue", "disabled"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_v_col, {
                      cols: "12",
                      sm: "6"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_text_field, {
                          modelValue: config.value.force_cooldown_days,
                          "onUpdate:modelValue": _cache[16] || (_cache[16] = $event => ((config.value.force_cooldown_days) = $event)),
                          modelModifiers: { number: true },
                          label: "全量校验冷却 (天)",
                          type: "number",
                          variant: "outlined",
                          density: "compact",
                          hint: "全量校验会遍历 115 全部目录，请求量按媒体库文件数计算（可能上万次），因此限频。默认 7 天；0 表示不限制（不建议）",
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
            _createElementVNode("div", _hoisted_29, [
              _createVNode(_component_v_icon, {
                size: "18",
                color: "warning",
                class: "mr-1"
              }, {
                default: _withCtx(() => [...(_cache[50] || (_cache[50] = [
                  _createTextVNode("mdi-television-classic", -1)
                ]))]),
                _: 1
              }),
              _cache[52] || (_cache[52] = _createTextVNode(" strm 交叉验证 ", -1)),
              _createVNode(_component_v_chip, {
                size: "x-small",
                variant: "tonal",
                color: "success",
                class: "ml-2 font-weight-bold"
              }, {
                default: _withCtx(() => [...(_cache[51] || (_cache[51] = [
                  _createTextVNode(" 不依赖任何插件 ", -1)
                ]))]),
                _: 1
              })
            ]),
            _createVNode(_component_v_alert, {
              type: "info",
              variant: "tonal",
              density: "compact",
              class: "rounded-lg mb-3 text-body-2"
            }, {
              default: _withCtx(() => [...(_cache[53] || (_cache[53] = [
                _createElementVNode("b", null, "它是用来发现「假成功」的", -1),
                _createTextVNode("：CD2 改名失败时，挂载视图会显示目标文件 「存在且大小正常」，而 115 云端其实只有一份改名失败的半成品。此时双向对账 与 rsync 的 --size-only 都会被蒙蔽，插件从自身视角", -1),
                _createElementVNode("b", null, "结构上看不见", -1),
                _createTextVNode("这种失败。 ", -1),
                _createElementVNode("br", null, null, -1),
                _createTextVNode(" strm 类插件生成的 .strm 指针文件依据与 CD2 无关，是独立见证人。 同步成功后文件进入观察期，到期仍未生成对应 .strm 即标记为「疑似上传异常」。 观察、扫描与判定的全过程都是", -1),
                _createElementVNode("b", null, "纯本地文件检查，零 115 API 开销", -1),
                _createTextVNode("。 ", -1),
                _createElementVNode("br", null, null, -1),
                _createElementVNode("b", null, "启用方式", -1),
                _createTextVNode("：在上方目录映射中为需要验证的映射填写「strm 目录」， 留空的映射不启用验证，", -1),
                _createElementVNode("b", null, "不影响任何现有行为", -1),
                _createTextVNode("。 ", -1),
                _createElementVNode("br", null, null, -1),
                _createElementVNode("br", null, null, -1),
                _createElementVNode("b", null, "发现疑似后怎么处理", -1),
                _createTextVNode("：「缺 strm」有两种成因，处理成本差很多 —— ", -1),
                _createElementVNode("b", null, "①", -1),
                _createTextVNode(" strm 插件自己漏生成（云端文件其实是好的）；", -1),
                _createElementVNode("b", null, "②", -1),
                _createTextVNode(" CD2 改名失败假成功 （云端只有半成品，必须删旧重传）。插件", -1),
                _createElementVNode("b", null, "无法从本地视角区分", -1),
                _createTextVNode("这两者。 ", -1)
              ]))]),
              _: 1
            }),
            _createElementVNode("div", _hoisted_30, [
              _createElementVNode("div", _hoisted_31, [
                _createVNode(_component_v_chip, {
                  size: "x-small",
                  color: "success",
                  variant: "tonal",
                  class: "font-weight-bold flex-shrink-0"
                }, {
                  default: _withCtx(() => [...(_cache[54] || (_cache[54] = [
                    _createTextVNode(" 本插件独立完成 ", -1)
                  ]))]),
                  _: 1
                }),
                _cache[55] || (_cache[55] = _createElementVNode("span", null, [
                  _createTextVNode(" 观察期、主动扫描（全量 / 关键字）、疑似清单、忽略规则、清理无效项、 "),
                  _createElementVNode("b", null, "删旧重传"),
                  _createTextVNode("、状态通知 ")
                ], -1))
              ]),
              _createElementVNode("div", _hoisted_32, [
                _createVNode(_component_v_chip, {
                  size: "x-small",
                  color: "info",
                  variant: "tonal",
                  class: "font-weight-bold flex-shrink-0"
                }, {
                  default: _withCtx(() => [...(_cache[56] || (_cache[56] = [
                    _createTextVNode(" 需要 P115StrmHelper ", -1)
                  ]))]),
                  _: 1
                }),
                _cache[57] || (_cache[57] = _createElementVNode("span", null, [
                  _createTextVNode(" 仅「"),
                  _createElementVNode("b", null, "先尝试生成 strm"),
                  _createTextVNode("」一项。它请助手按文件所在的网盘目录重新生成 一次指针文件：生成成功 ⇒ 是情况 ①，"),
                  _createElementVNode("b", null, "无需删旧重传"),
                  _createTextVNode("； 生成后仍无 ⇒ 是情况 ②，此时再删旧重传。 ")
                ], -1))
              ])
            ]),
            _createVNode(_component_v_alert, {
              type: "info",
              variant: "tonal",
              density: "compact",
              class: "rounded-lg mb-3 text-body-2"
            }, {
              default: _withCtx(() => [...(_cache[58] || (_cache[58] = [
                _createElementVNode("b", null, "「先尝试生成 strm」的启用前提（两处都要配）", -1),
                _createTextVNode("： ", -1),
                _createElementVNode("br", null, null, -1),
                _createElementVNode("b", null, "①", -1),
                _createTextVNode(" 上方目录映射里为该映射填写「", -1),
                _createElementVNode("b", null, "网盘目录", -1),
                _createTextVNode("」 （115 网盘里的真实路径，与本地 strm 目录是两棵独立的树，无法自动推导）； ", -1),
                _createElementVNode("br", null, null, -1),
                _createElementVNode("b", null, "②", -1),
                _createTextVNode(" 该网盘路径必须已在 P115StrmHelper 的", -1),
                _createElementVNode("b", null, "「全量同步路径」", -1),
                _createTextVNode("里配置过 —— 助手的 ", -1),
                _createElementVNode("code", null, "/p115_strm", -1),
                _createTextVNode(" 只接受它自己这个列表里的路径，其它字段 （如「监控生活路径」）里配的目录传过去会被拒绝。 ", -1),
                _createElementVNode("br", null, null, -1),
                _createTextVNode(" 注意这一步会", -1),
                _createElementVNode("b", null, "访问 115 网盘", -1),
                _createTextVNode("（助手按目录遍历云端），因此看板上是手动触发、 逐目录去重，且单次涉及目录数有上限（超过则整批拒绝，不会自动放大访问量）。 ", -1),
                _createElementVNode("b", null, "不配也不影响上面「本插件独立完成」的任何一项", -1),
                _createTextVNode("。 ", -1)
              ]))]),
              _: 1
            }),
            _createElementVNode("div", _hoisted_33, [
              _createElementVNode("div", _hoisted_34, [
                _cache[59] || (_cache[59] = _createElementVNode("div", null, [
                  _createElementVNode("div", { class: "font-weight-bold text-body-2" }, "观察宽限期 (小时)"),
                  _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, " strm 生成并不实时（可能还在上传或刮削中），因此同步成功后先等待一段时间再判定， 避免把「还没生成」误判为上传异常。最小 0.5 小时。 ")
                ], -1)),
                _createVNode(_component_v_text_field, {
                  modelValue: config.value.strm_grace_hours,
                  "onUpdate:modelValue": _cache[17] || (_cache[17] = $event => ((config.value.strm_grace_hours) = $event)),
                  modelModifiers: { number: true },
                  type: "number",
                  step: "0.5",
                  min: "0.5",
                  variant: "outlined",
                  density: "compact",
                  style: {"max-width":"130px"},
                  "hide-details": ""
                }, null, 8, ["modelValue"])
              ]),
              _createElementVNode("div", _hoisted_35, [
                _cache[60] || (_cache[60] = _createElementVNode("div", null, [
                  _createElementVNode("div", { class: "font-weight-bold text-body-2" }, "当前状态"),
                  _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, " 处于观察期的文件数会在看板顶部提示，疑似异常清单在独立的「strm 疑似异常」标签页内。 ")
                ], -1)),
                _createVNode(_component_v_chip, {
                  size: "small",
                  variant: "tonal",
                  color: "warning"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(config.value.sync_pairs.filter((p) => (p.strm_dir || '').trim()).length) + " / " + _toDisplayString(config.value.sync_pairs.length) + " 个映射已配置 ", 1)
                  ]),
                  _: 1
                })
              ])
            ]),
            _createElementVNode("div", _hoisted_36, [
              _createElementVNode("div", _hoisted_37, [
                _createVNode(_component_v_icon, {
                  size: "18",
                  color: "primary",
                  class: "mr-1"
                }, {
                  default: _withCtx(() => [...(_cache[61] || (_cache[61] = [
                    _createTextVNode("mdi-webhook", -1)
                  ]))]),
                  _: 1
                }),
                _cache[62] || (_cache[62] = _createTextVNode(" Webhook 入库（第二来源） ", -1))
              ])
            ]),
            _createVNode(_component_v_alert, {
              type: "info",
              variant: "tonal",
              density: "compact",
              class: "rounded-lg mb-3 text-body-2"
            }, {
              default: _withCtx(() => [...(_cache[63] || (_cache[63] = [
                _createTextVNode(" 现有的入库监听挂宿主的「整理完成」事件，因此看不到三类入库： ", -1),
                _createElementVNode("b", null, "手动放进媒体库", -1),
                _createTextVNode("、", -1),
                _createElementVNode("b", null, "外部工具搬入", -1),
                _createTextVNode("、", -1),
                _createElementVNode("b", null, "整理事件漏发", -1),
                _createTextVNode("。 Webhook 作为", -1),
                _createElementVNode("b", null, "补充来源", -1),
                _createTextVNode("覆盖它们 —— 不是替代，同一条入库走两条路进来时， 冷却队列的重复检测会保证不重复上传。 ", -1)
              ]))]),
              _: 1
            }),
            _createElementVNode("div", _hoisted_38, [
              _createElementVNode("div", _hoisted_39, [
                _cache[64] || (_cache[64] = _createElementVNode("div", null, [
                  _createElementVNode("div", { class: "font-weight-bold text-body-2" }, "来源渠道（channel 过滤）"),
                  _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, [
                    _createTextVNode(" 多个插件会同时订阅宿主广播的 webhook 事件，因此必须各自声明自己的来源。 一般保持 "),
                    _createElementVNode("code", null, "emby"),
                    _createTextVNode(" 即可。 ")
                  ])
                ], -1)),
                _createVNode(_component_v_text_field, {
                  modelValue: webhookChannelsText.value,
                  "onUpdate:modelValue": _cache[18] || (_cache[18] = $event => ((webhookChannelsText).value = $event)),
                  variant: "outlined",
                  density: "compact",
                  placeholder: "emby",
                  style: {"max-width":"200px"},
                  "hide-details": ""
                }, null, 8, ["modelValue"])
              ]),
              _cache[65] || (_cache[65] = _createElementVNode("div", { class: "setting-row px-4 py-3 border-b" }, [
                _createElementVNode("div", { class: "font-weight-bold text-body-2 mb-1" }, "平台 webhook 地址（宿主原生链路）"),
                _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, [
                  _createTextVNode(" 无需在本插件做任何额外配置，只需在 "),
                  _createElementVNode("b", null, "Emby 后台 → 通知 → Webhooks"),
                  _createTextVNode(" 里添加地址： "),
                  _createElementVNode("br"),
                  _createElementVNode("code", null, "http://<moviepilot地址>:3001/api/v1/webhook/?token=<API_TOKEN>&source=<emby实例名>"),
                  _createElementVNode("br"),
                  _createTextVNode(" 其中 "),
                  _createElementVNode("code", null, "source"),
                  _createTextVNode(" 要填你在 MoviePilot 里配置的 Emby 实例名（可省略，但多实例时建议填上）。 事件勾选 "),
                  _createElementVNode("b", null, "新媒体入库"),
                  _createTextVNode(" 一类即可；播放类事件插件会自动忽略，"),
                  _createElementVNode("b", null, "填了也不会误触发上传"),
                  _createTextVNode("。 "),
                  _createElementVNode("br"),
                  _createElementVNode("b", null, "自定义发送端"),
                  _createTextVNode("（自建脚本等）也可以走这个地址，把 "),
                  _createElementVNode("code", null, "source"),
                  _createTextVNode(" 换成 "),
                  _createElementVNode("code", null, "rsync115sync"),
                  _createTextVNode("（或加请求头 "),
                  _createElementVNode("code", null, "X-Webhook-Target: rsync115sync"),
                  _createTextVNode("）， 插件会认领它。 "),
                  _createElementVNode("b", null, [
                    _createTextVNode("注意这个值必须是 "),
                    _createElementVNode("code", null, "rsync115sync")
                  ]),
                  _createTextVNode(" —— 填成别的（包括 "),
                  _createElementVNode("code", null, "emby"),
                  _createTextVNode("） 插件都不会处理。 ")
                ])
              ], -1))
            ])
          ]),
          _: 1
        }),
        _createVNode(_component_v_card_actions, { class: "config-actions px-5 py-3 border-t bg-surface" }, {
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
                  default: _withCtx(() => [...(_cache[66] || (_cache[66] = [
                    _createTextVNode("mdi-view-dashboard-outline", -1)
                  ]))]),
                  _: 1
                }),
                _cache[67] || (_cache[67] = _createTextVNode(" 查看监控看板 ", -1))
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
                  default: _withCtx(() => [...(_cache[68] || (_cache[68] = [
                    _createTextVNode("mdi-content-save", -1)
                  ]))]),
                  _: 1
                }),
                _cache[69] || (_cache[69] = _createTextVNode(" 保存配置 ", -1))
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
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-80475d27"]]);

export { Config as default };
