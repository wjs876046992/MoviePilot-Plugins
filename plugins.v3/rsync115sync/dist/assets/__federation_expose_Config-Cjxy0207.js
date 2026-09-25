import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {toDisplayString:_toDisplayString$1,createTextVNode:_createTextVNode$1,resolveComponent:_resolveComponent$1,withCtx:_withCtx$1,createVNode:_createVNode$1,createElementVNode:_createElementVNode$1,openBlock:_openBlock$1,createElementBlock:_createElementBlock$1,createCommentVNode:_createCommentVNode$1,withModifiers:_withModifiers,withKeys:_withKeys,renderSlot:_renderSlot,vShow:_vShow,withDirectives:_withDirectives,createBlock:_createBlock$1} = await importShared('vue');


const _hoisted_1$1 = ["aria-expanded", "onKeydown"];
const _hoisted_2$1 = { class: "font-weight-bold" };
const _hoisted_3$1 = {
  key: 0,
  class: "text-medium-emphasis note-hint"
};
const _hoisted_4$1 = { class: "mt-1" };

const {ref: ref$1} = await importShared('vue');



const _sfc_main$1 = {
  __name: 'CollapsibleNote',
  props: {
  title: { type: String, required: true },
},
  setup(__props) {



const open = ref$1(false);
function toggle() { open.value = !open.value; }

return (_ctx, _cache) => {
  const _component_v_icon = _resolveComponent$1("v-icon");
  const _component_v_alert = _resolveComponent$1("v-alert");

  return (_openBlock$1(), _createBlock$1(_component_v_alert, {
    type: "info",
    variant: "tonal",
    density: "compact",
    icon: false,
    class: "rounded-lg text-body-2 collapsible-note"
  }, {
    default: _withCtx$1(() => [
      _createElementVNode$1("div", {
        class: "note-head d-flex align-center",
        role: "button",
        tabindex: "0",
        "aria-expanded": open.value ? 'true' : 'false',
        onClick: toggle,
        onKeydown: [
          _withKeys(_withModifiers(toggle, ["prevent"]), ["enter"]),
          _withKeys(_withModifiers(toggle, ["prevent"]), ["space"])
        ]
      }, [
        _createVNode$1(_component_v_icon, {
          size: "16",
          class: "mr-1 flex-shrink-0"
        }, {
          default: _withCtx$1(() => [
            _createTextVNode$1(_toDisplayString$1(open.value ? 'mdi-chevron-up' : 'mdi-chevron-down'), 1)
          ]),
          _: 1
        }),
        _createElementVNode$1("span", _hoisted_2$1, _toDisplayString$1(__props.title), 1),
        (!open.value)
          ? (_openBlock$1(), _createElementBlock$1("span", _hoisted_3$1, "（点击展开）"))
          : _createCommentVNode$1("", true)
      ], 40, _hoisted_1$1),
      _withDirectives(_createElementVNode$1("div", _hoisted_4$1, [
        _renderSlot(_ctx.$slots, "default", {}, undefined, true)
      ], 512), [
        [_vShow, open.value]
      ])
    ]),
    _: 3
  }))
}
}

};
const CollapsibleNote = /*#__PURE__*/_export_sfc(_sfc_main$1, [['__scopeId',"data-v-2251128a"]]);

const {createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createElementBlock:_createElementBlock,renderList:_renderList,Fragment:_Fragment} = await importShared('vue');


const _hoisted_1 = { class: "plugin-config" };
const _hoisted_2 = { class: "header-icon-box mr-3" };
const _hoisted_3 = {
  key: 0,
  class: "card-pad-x pt-3"
};
const _hoisted_4 = { class: "settings-group-card rounded-xl overflow-hidden mb-4" };
const _hoisted_5 = { class: "setting-row setting-row-inline d-flex align-center justify-space-between row-pad-x py-3 border-b" };
const _hoisted_6 = { class: "setting-row setting-row-inline d-flex align-center justify-space-between row-pad-x py-3" };
const _hoisted_7 = { class: "row-pad-x pb-3" };
const _hoisted_8 = { class: "setting-row setting-row-inline d-flex align-center justify-space-between row-pad-x py-3 border-t" };
const _hoisted_9 = { class: "font-weight-bold text-body-2" };
const _hoisted_10 = { class: "setting-row setting-row-stacked row-pad-x py-3" };
const _hoisted_11 = { class: "row-pad-x pb-3" };
const _hoisted_12 = { class: "section-header d-flex align-center justify-space-between mb-2" };
const _hoisted_13 = { class: "font-weight-bold text-subtitle-2 d-flex align-center" };
const _hoisted_14 = {
  key: 0,
  class: "d-flex flex-column ga-3 mb-4"
};
const _hoisted_15 = { class: "d-flex align-center justify-space-between mb-3" };
const _hoisted_16 = { class: "font-weight-bold text-body-2 text-primary" };
const _hoisted_17 = {
  key: 1,
  class: "empty-hint-box text-center py-6 rounded-xl mb-4 text-caption text-disabled"
};
const _hoisted_18 = { class: "font-weight-bold text-subtitle-2 d-flex align-center mb-2" };
const _hoisted_19 = { class: "settings-group-card rounded-xl overflow-hidden pa-4 mb-4" };
const _hoisted_20 = { class: "font-weight-bold text-subtitle-2 d-flex align-center mb-2" };
const _hoisted_21 = { class: "settings-group-card rounded-xl overflow-hidden pa-4" };
const _hoisted_22 = { class: "font-weight-bold text-subtitle-2 d-flex align-center mb-2 mt-4" };
const _hoisted_23 = { class: "settings-group-card rounded-xl overflow-hidden" };
const _hoisted_24 = { class: "setting-row setting-row-inline d-flex align-center justify-space-between row-pad-x py-3 border-b" };
const _hoisted_25 = {
  key: 0,
  class: "row-pad-x py-2 batch-bar"
};
const _hoisted_26 = { class: "d-flex align-center flex-wrap ga-2" };
const _hoisted_27 = { class: "text-caption text-medium-emphasis" };
const _hoisted_28 = {
  key: 0,
  class: "text-caption text-warning font-weight-medium mt-1"
};
const _hoisted_29 = { class: "row-pad-x py-3" };
const _hoisted_30 = { class: "font-weight-bold text-subtitle-2 d-flex align-center mb-2" };
const _hoisted_31 = { class: "dep-split rounded-lg mb-3" };
const _hoisted_32 = { class: "dep-split-row" };
const _hoisted_33 = { class: "dep-split-row" };
const _hoisted_34 = { class: "settings-group-card rounded-xl overflow-hidden" };
const _hoisted_35 = { class: "setting-row setting-row-stacked row-pad-x py-3 border-b" };
const _hoisted_36 = { class: "setting-row d-flex align-center justify-space-between row-pad-x py-3" };
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
  // 源端扫描（入库发现的主通道，2026-09-25 起取代宿主整理事件订阅）
  source_scan_enabled: true,
  // cron 表达式（与「定时检查」同一套写法）。旧版这里是「间隔秒数」，
  // 后端会把它换算成等价的 */N 表达式并保留，见 _read_source_scan_cron。
  source_scan_cron: '*/30 * * * *',
  notify: true,
  // 4h：源端扫描引入后，冷却期多了一层职责 —— 等文件写完（见上面的 hint）
  delay_hours: 4.0,
  cron: '0 */2 * * *',
  sync_pairs: [],
  // ⚠️ 必须与后端 constants.DEFAULT_MEDIA_EXTENSIONS **逐字一致**。
  // 这是同一份默认串的第 3 份拷贝（另两份在后端默认值与旧默认值迁移表），
  // 漏改这里会让「新装用户在表单里看到的值」与「后端实际生效的值」不同 ——
  // 用户点一次保存就会把窄白名单写回去，表现为「升级后音频又不传了」。
  // Keep byte-identical with the backend default (see DEVELOPMENT §4.0f).
  media_extensions: 'mp4,mkv,ts,iso,rmvb,avi,mov,mpeg,mpg,wmv,3gp,asf,m4v,flv,m2ts,tp,f4v,srt,ssa,ass,sup,sub,idx,vtt,mp3,flac,m4a,aac,opus,wav,mka,ape,wma',
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
  // **没有任何配置项**：入口只认 `source=rsync115sync`，其它来源归平台解析器。
  // （渠道白名单与自建端点的四条防护均已移除，见 __init__.py 的 webhook 配置节。）
  // strm 观察宽限期：与后端 DEFAULT 及 _api_get_config 的兜底值保持 6.0 一致。
  // 这里必须显式声明：/config 未返回该字段时（例如宿主配置里从未存过），
  // v-model.number 绑定 undefined 会让输入框空白并写回 NaN。
  strm_grace_minutes: 5,
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

// 注：这里曾有一段「分钟 ↔ 秒」的单位换算（源端扫描间隔）。改为 cron 表达式后
// 不再需要 —— 前后端存的是同一个字符串，没有单位可错。
// 教训值得留着：那次换算的边界处理错一次就会表现成「保存 10 分钟、回来变成 0」，
// 而 0 和 10 在界面上都"像那么回事"。**能用一个自描述的类型就别用数值 + 单位换算。**
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
        _createVNode(_component_v_card_item, { class: "header-surface header-card-item card-pad-x py-4" }, {
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
                      _createTextVNode("v0.2.7", -1)
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
        _createVNode(_component_v_card_text, { class: "config-body card-pad-x py-4 overflow-y-auto" }, {
          default: _withCtx(() => [
            _createElementVNode("div", _hoisted_4, [
              _createElementVNode("div", _hoisted_5, [
                _cache[25] || (_cache[25] = _createElementVNode("div", null, [
                  _createElementVNode("div", { class: "font-weight-bold text-body-2" }, "启用同步助手"),
                  _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "总控主开关，开启后生效定时轮询与入库监听")
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
                  _createElementVNode("div", { class: "font-weight-bold text-body-2" }, "启用入库监听"),
                  _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "Webhook 与源端扫描共用的总闸")
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
                _createVNode(CollapsibleNote, {
                  title: "怎么把入库推给本插件（Webhook）",
                  class: "mb-0"
                }, {
                  default: _withCtx(() => [...(_cache[27] || (_cache[27] = [
                    _createTextVNode(" 在发送端（自建脚本、下载器回调等）把地址指向平台 webhook 入口，并带上本插件的收件人标识： ", -1),
                    _createElementVNode("br", null, null, -1),
                    _createElementVNode("code", { class: "wrap-anywhere" }, "http://<moviepilot地址>:3001/api/v1/webhook/?token=<API_TOKEN>&source=rsync115sync", -1),
                    _createElementVNode("br", null, null, -1),
                    _createTextVNode(" 也可以改用请求头 ", -1),
                    _createElementVNode("code", null, "X-Webhook-Target: rsync115sync", -1),
                    _createTextVNode("。 ", -1),
                    _createElementVNode("b", null, [
                      _createTextVNode("这个值必须是 "),
                      _createElementVNode("code", null, "rsync115sync")
                    ], -1),
                    _createTextVNode(" —— 填成别的（包括 ", -1),
                    _createElementVNode("code", null, "emby", -1),
                    _createTextVNode("） 本插件都不会处理，那些报文归平台自己的解析器管。 ", -1),
                    _createElementVNode("br", null, null, -1),
                    _createTextVNode(" 本插件没有任何需要在这里配置的项：只认上面这个标识，其余来源一概不监听 （这是", -1),
                    _createElementVNode("b", null, "有意的设计", -1),
                    _createTextVNode("，不是待办 —— 媒体服务器自己的入库归平台处理）。 ", -1),
                    _createElementVNode("br", null, null, -1),
                    _createTextVNode(" 推送内容支持单个文件路径或目录（目录会自动展开），事件请用", -1),
                    _createElementVNode("b", null, "入库类", -1),
                    _createTextVNode(" （如 ", -1),
                    _createElementVNode("code", null, "library.new", -1),
                    _createTextVNode("）—— 播放类事件会被自动忽略，填了也不会误触发上传。 ", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _createElementVNode("div", _hoisted_8, [
                _createElementVNode("div", null, [
                  _createElementVNode("div", _hoisted_9, [
                    _cache[29] || (_cache[29] = _createTextVNode(" 源端扫描入库 ", -1)),
                    _createVNode(_component_v_chip, {
                      size: "x-small",
                      color: "primary",
                      variant: "tonal",
                      class: "ml-1 font-weight-bold"
                    }, {
                      default: _withCtx(() => [...(_cache[28] || (_cache[28] = [
                        _createTextVNode("主通道", -1)
                      ]))]),
                      _: 1
                    })
                  ]),
                  _cache[30] || (_cache[30] = _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "遍历本地源目录发现新入库，不依赖任何外部通知", -1))
                ]),
                _createVNode(_component_v_switch, {
                  modelValue: config.value.source_scan_enabled,
                  "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((config.value.source_scan_enabled) = $event)),
                  color: "primary",
                  inset: "",
                  "hide-details": "",
                  density: "compact"
                }, null, 8, ["modelValue"])
              ]),
              _createElementVNode("div", _hoisted_10, [
                _cache[31] || (_cache[31] = _createElementVNode("div", null, [
                  _createElementVNode("div", { class: "font-weight-bold text-body-2" }, "源端扫描 Cron 规则"),
                  _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "多久扫一轮（默认 30 分钟）")
                ], -1)),
                _createVNode(_component_v_text_field, {
                  modelValue: config.value.source_scan_cron,
                  "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((config.value.source_scan_cron) = $event)),
                  variant: "outlined",
                  density: "compact",
                  "hide-details": "",
                  placeholder: "*/30 * * * *",
                  class: "mt-2 max-field"
                }, null, 8, ["modelValue"])
              ]),
              _createElementVNode("div", _hoisted_11, [
                _createVNode(CollapsibleNote, {
                  title: "入库是怎么被发现的",
                  class: "mb-0"
                }, {
                  default: _withCtx(() => [...(_cache[32] || (_cache[32] = [
                    _createTextVNode(" 本插件有", -1),
                    _createElementVNode("b", null, "两条", -1),
                    _createTextVNode("入库来源，分工是刻意的： ", -1),
                    _createElementVNode("div", { class: "mt-1" }, [
                      _createElementVNode("b", null, "① 源端扫描 —— 主通道，完整性的唯一承担者。"),
                      _createTextVNode(" 按上面的 cron 遍历各映射的本地源目录，把「修改时间晚于上次成功扫描时刻」的文件纳入冷却队列。 整理入库、手动放进媒体库、外部工具搬入，以及插件重载期间发生的入库，它都能看见。 "),
                      _createElementVNode("b", null, "每轮只做本地目录遍历，不访问 115 挂载点，不消耗上传配额、不触发风控。"),
                      _createTextVNode(" 扫得更勤"),
                      _createElementVNode("b", null, "不会"),
                      _createTextVNode("让文件更早上传（进队列后还要等满冷却），只是让它更早进队列。 ")
                    ], -1),
                    _createElementVNode("div", { class: "mt-1" }, [
                      _createElementVNode("b", null, "② Webhook —— 加速器，不承担完整性。"),
                      _createTextVNode(" 发送端主动通知（接入方式见上方「怎么把入库推给本插件」）。它让文件早一点进队列， 但即使整条失效，扫描也会在下一轮把同一个文件捞回来（去重由队列幂等保证）。 ")
                    ], -1),
                    _createElementVNode("div", { class: "mt-1" }, " 关闭「启用入库监听」= 两条来源一起停（分开成两个开关会让用户遇到 「关了一个、另一个还在悄悄入队」）。仅关闭「源端扫描入库」则只剩 Webhook 一条路 —— 那时手动放入、外部搬入，以及 webhook 配置出问题时的入库都会静默丢失。 ", -1)
                  ]))]),
                  _: 1
                })
              ])
            ]),
            _createElementVNode("div", _hoisted_12, [
              _createElementVNode("div", _hoisted_13, [
                _createVNode(_component_v_icon, {
                  size: "18",
                  color: "primary",
                  class: "mr-1"
                }, {
                  default: _withCtx(() => [...(_cache[33] || (_cache[33] = [
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
                    default: _withCtx(() => [...(_cache[34] || (_cache[34] = [
                      _createTextVNode("mdi-plus", -1)
                    ]))]),
                    _: 1
                  }),
                  _cache[35] || (_cache[35] = _createTextVNode(" 添加目录映射 ", -1))
                ]),
                _: 1
              })
            ]),
            _createVNode(CollapsibleNote, {
              title: "每个映射是一对路径：本地源目录 → CD2 挂载的 115 目录",
              class: "mb-3"
            }, {
              default: _withCtx(() => [...(_cache[36] || (_cache[36] = [
                _createTextVNode(" 插件只同步这些映射内的文件，不会扫描其它位置。 ", -1),
                _createElementVNode("div", { class: "mt-2" }, [
                  _createElementVNode("b", null, "任务备注名称"),
                  _createTextVNode("：会成为文件清单的前缀（如 "),
                  _createElementVNode("code", null, "电视剧:剧名/剧名 S01E01.mkv"),
                  _createTextVNode("）。改名不会导致重复同步， 但会让旧的异常清单条目失去对应关系，建议一次定好。")
                ], -1),
                _createElementVNode("div", { class: "mt-1" }, [
                  _createElementVNode("b", null, "本地源目录"),
                  _createTextVNode("：NAS 上的媒体目录，需在容器内可访问。")
                ], -1),
                _createElementVNode("div", { class: "mt-1" }, [
                  _createElementVNode("b", null, "CD2 挂载 115 目录"),
                  _createTextVNode("：上面对应的网盘目标目录。")
                ], -1),
                _createElementVNode("div", { class: "mt-1" }, [
                  _createElementVNode("b", null, "同步所有文件类型"),
                  _createTextVNode("：关闭时只传下方「同步的扩展名」白名单里的文件 （推荐）；开启后该映射下的 nfo、图片等一律上传。开启后还有一个区别： 收到「推来单个文件」的通知时，同目录下的其它文件会一并入队（不递归子目录）—— 否则「全都要上传」就变成了「只传被点到名的那一个」。")
                ], -1),
                _createElementVNode("div", { class: "mt-1" }, [
                  _createElementVNode("b", null, "strm 目录"),
                  _createTextVNode("：可选。填了才对该映射启用上传结果交叉验证 —— 同步成功后进入观察期，到期仍未生成对应 "),
                  _createElementVNode("code", null, ".strm"),
                  _createTextVNode(" 会标记为「疑似上传异常」。 看板可先请 STRM 助手补生成（成本低、多半直接解决），确认无效后再删旧重传。 观察与扫描全程纯本地，"),
                  _createElementVNode("b", null, "零 115 API"),
                  _createTextVNode("。 "),
                  _createElementVNode("b", null, "不依赖 P115StrmHelper"),
                  _createTextVNode("：任何会生成 .strm 的插件都可以， 甚至完全不用插件、只填一个目录也能工作。")
                ], -1),
                _createElementVNode("div", { class: "mt-1" }, [
                  _createElementVNode("b", null, "网盘目录"),
                  _createTextVNode("：可选，"),
                  _createElementVNode("b", null, "仅「先尝试生成 strm」"),
                  _createTextVNode("用得到。 填该映射在 115 网盘里的目录（"),
                  _createElementVNode("b", null, "不是"),
                  _createTextVNode(" CD2 挂载路径）；本地 strm 目录与 网盘目录是两棵独立的树，无法自动推导，所以要单独填。 注意助手只接受它自己「全量同步路径」里配置过的网盘路径，填了但助手没配会被拒绝 （提示路径匹配错误）。"),
                  _createElementVNode("b", null, "依赖 P115StrmHelper"),
                  _createTextVNode("；留空只是该映射不能用补生成， 不影响同步、对账、观察与删旧重传。")
                ], -1)
              ]))]),
              _: 1
            }),
            (config.value.sync_pairs.length)
              ? (_openBlock(), _createElementBlock("div", _hoisted_14, [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(config.value.sync_pairs, (pair, idx) => {
                    return (_openBlock(), _createElementBlock("div", {
                      key: idx,
                      class: "pair-card rounded-xl pa-4"
                    }, [
                      _createElementVNode("div", _hoisted_15, [
                        _createElementVNode("span", _hoisted_16, "映射任务 #" + _toDisplayString(idx + 1), 1),
                        _createVNode(_component_v_btn, {
                          icon: "",
                          size: "x-small",
                          variant: "text",
                          color: "error",
                          onClick: $event => (removePair(idx))
                        }, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_icon, { size: "18" }, {
                              default: _withCtx(() => [...(_cache[37] || (_cache[37] = [
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
                                label: "同步所有文件类型（含 nfo、图片等）",
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
                                label: "strm 目录（可选，启用上传结果交叉验证）",
                                variant: "outlined",
                                density: "compact",
                                placeholder: "例如 /vol1/strm/TV —— 留空则不启用该映射的验证"
                              }, null, 8, ["modelValue", "onUpdate:modelValue"])
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
                                placeholder: "例如 /HomeTheater/TV —— 填 115 网盘里的真实路径，留空则该映射不支持补生成"
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
              : (_openBlock(), _createElementBlock("div", _hoisted_17, " 暂未配置任何目录映射，点击上方按钮添加你的本地媒体目录与 CD2 挂载路径 ")),
            _createElementVNode("div", _hoisted_18, [
              _createVNode(_component_v_icon, {
                size: "18",
                color: "primary",
                class: "mr-1"
              }, {
                default: _withCtx(() => [...(_cache[38] || (_cache[38] = [
                  _createTextVNode("mdi-timer-sand", -1)
                ]))]),
                _: 1
              }),
              _cache[39] || (_cache[39] = _createTextVNode(" 入库冷却缓冲与调度 ", -1))
            ]),
            _createElementVNode("div", _hoisted_19, [
              _createVNode(_component_v_row, { density: "comfortable" }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_col, {
                    cols: "12",
                    sm: "6"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_text_field, {
                        modelValue: config.value.delay_hours,
                        "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((config.value.delay_hours) = $event)),
                        modelModifiers: { number: true },
                        label: "入库冷却延迟时长 (小时)",
                        type: "number",
                        step: "0.5",
                        min: "0",
                        variant: "outlined",
                        density: "compact",
                        suffix: "小时",
                        hint: "媒体入库后等待 N 小时再上传。它同时兜两件事：① 留足外挂字幕与刮削时间；② 等文件写完 —— 源端扫描没有「写完了」这个信号，而正在写入的文件修改时间恰好是最新的，冷却期是唯一挡住「传到一半源文件还在变」的机制。建议 4~6 小时。设为 0 可关闭等待",
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
                        "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((config.value.cron) = $event)),
                        label: "定时检查 Cron 规则",
                        variant: "outlined",
                        density: "compact",
                        placeholder: "0 */2 * * *",
                        hint: "多久巡检一次。到期文件会按上面的限流规则分批上传；本轮无到期文件时才续跑补传队列（新鲜入库优先于存量补传）",
                        "persistent-hint": ""
                      }, null, 8, ["modelValue"])
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _createElementVNode("div", _hoisted_20, [
              _createVNode(_component_v_icon, {
                size: "18",
                color: "primary",
                class: "mr-1"
              }, {
                default: _withCtx(() => [...(_cache[40] || (_cache[40] = [
                  _createTextVNode("mdi-shield-check-outline", -1)
                ]))]),
                _: 1
              }),
              _cache[41] || (_cache[41] = _createTextVNode(" CD2 核心过滤与防假死参数 ", -1))
            ]),
            _createElementVNode("div", _hoisted_21, [
              _createVNode(_component_v_row, { density: "compact" }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_col, {
                    cols: "12",
                    sm: "6"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_text_field, {
                        modelValue: config.value.rsync_timeout,
                        "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((config.value.rsync_timeout) = $event)),
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
                        "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((config.value.task_timeout) = $event)),
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
                        "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((config.value.exclude_patterns) = $event)),
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
            _createElementVNode("div", _hoisted_22, [
              _createVNode(_component_v_icon, {
                size: "18",
                color: "primary",
                class: "mr-1"
              }, {
                default: _withCtx(() => [...(_cache[42] || (_cache[42] = [
                  _createTextVNode("mdi-speedometer-slow", -1)
                ]))]),
                _: 1
              }),
              _cache[43] || (_cache[43] = _createTextVNode(" 上传限流与风控退避 ", -1))
            ]),
            _createVNode(CollapsibleNote, {
              title: "为什么需要限流？",
              class: "mb-2"
            }, {
              default: _withCtx(() => [...(_cache[44] || (_cache[44] = [
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
            _createElementVNode("div", _hoisted_23, [
              _createElementVNode("div", _hoisted_24, [
                _cache[45] || (_cache[45] = _createElementVNode("div", null, [
                  _createElementVNode("div", { class: "font-weight-bold text-body-2" }, "启用上传限流"),
                  _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "按时间窗口限制上传文件数，防止小文件高频上传触发 115 风控")
                ], -1)),
                _createVNode(_component_v_switch, {
                  modelValue: config.value.rate_limit_enabled,
                  "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((config.value.rate_limit_enabled) = $event)),
                  color: "primary",
                  inset: "",
                  "hide-details": "",
                  density: "compact"
                }, null, 8, ["modelValue"])
              ]),
              (config.value.rate_limit_enabled)
                ? (_openBlock(), _createElementBlock("div", _hoisted_25, [
                    _createElementVNode("div", _hoisted_26, [
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
                            default: _withCtx(() => [...(_cache[46] || (_cache[46] = [
                              _createTextVNode("mdi-speedometer", -1)
                            ]))]),
                            _: 1
                          }),
                          _createTextVNode(" 当前速率约 " + _toDisplayString(effectiveRateText.value), 1)
                        ]),
                        _: 1
                      }),
                      _createElementVNode("span", _hoisted_27, " 即每 " + _toDisplayString(windowHumanText.value) + " 最多上传 " + _toDisplayString(config.value.upload_max_per_window || 0) + " 个文件 ", 1)
                    ]),
                    (rateConfigWarnings.value.length)
                      ? (_openBlock(), _createElementBlock("div", _hoisted_28, [
                          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(rateConfigWarnings.value, (w, i) => {
                            return (_openBlock(), _createElementBlock("div", { key: i }, "⚠️ " + _toDisplayString(w), 1))
                          }), 128))
                        ]))
                      : _createCommentVNode("", true)
                  ]))
                : _createCommentVNode("", true),
              _createElementVNode("div", _hoisted_29, [
                _createVNode(_component_v_row, { density: "compact" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_col, {
                      cols: "12",
                      sm: "6"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_text_field, {
                          modelValue: config.value.upload_batch_size,
                          "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((config.value.upload_batch_size) = $event)),
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
                          "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((config.value.upload_max_per_window) = $event)),
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
                          "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => ((config.value.upload_window_secs) = $event)),
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
                          "onUpdate:modelValue": _cache[15] || (_cache[15] = $event => ((config.value.backoff_secs) = $event)),
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
                          "onUpdate:modelValue": _cache[16] || (_cache[16] = $event => ((config.value.rate_limit_keywords) = $event)),
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
                          "onUpdate:modelValue": _cache[17] || (_cache[17] = $event => ((config.value.force_cooldown_days) = $event)),
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
            _createElementVNode("div", _hoisted_30, [
              _createVNode(_component_v_icon, {
                size: "18",
                color: "warning",
                class: "mr-1"
              }, {
                default: _withCtx(() => [...(_cache[47] || (_cache[47] = [
                  _createTextVNode("mdi-television-classic", -1)
                ]))]),
                _: 1
              }),
              _cache[49] || (_cache[49] = _createTextVNode(" strm 交叉验证 ", -1)),
              _createVNode(_component_v_chip, {
                size: "x-small",
                variant: "tonal",
                color: "success",
                class: "ml-2 font-weight-bold"
              }, {
                default: _withCtx(() => [...(_cache[48] || (_cache[48] = [
                  _createTextVNode(" 不依赖任何插件 ", -1)
                ]))]),
                _: 1
              })
            ]),
            _createVNode(CollapsibleNote, {
              title: "它解决的是「假成功」—— 为什么对账看不出来",
              class: "mb-3"
            }, {
              default: _withCtx(() => [...(_cache[50] || (_cache[50] = [
                _createTextVNode(" CD2 改名失败时，挂载视图会显示目标文件 「存在且大小正常」，而 115 云端其实只有一份改名失败的半成品。此时双向对账 与 rsync 的 --size-only 都会被蒙蔽，插件从自身视角", -1),
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
            _createElementVNode("div", _hoisted_31, [
              _createElementVNode("div", _hoisted_32, [
                _createVNode(_component_v_chip, {
                  size: "x-small",
                  color: "success",
                  variant: "tonal",
                  class: "font-weight-bold flex-shrink-0"
                }, {
                  default: _withCtx(() => [...(_cache[51] || (_cache[51] = [
                    _createTextVNode(" 本插件独立完成 ", -1)
                  ]))]),
                  _: 1
                }),
                _cache[52] || (_cache[52] = _createElementVNode("span", null, [
                  _createTextVNode(" 观察期、主动扫描（全量 / 关键字）、疑似清单、忽略规则、清理无效项、 "),
                  _createElementVNode("b", null, "删旧重传"),
                  _createTextVNode("、状态通知 ")
                ], -1))
              ]),
              _createElementVNode("div", _hoisted_33, [
                _createVNode(_component_v_chip, {
                  size: "x-small",
                  color: "info",
                  variant: "tonal",
                  class: "font-weight-bold flex-shrink-0"
                }, {
                  default: _withCtx(() => [...(_cache[53] || (_cache[53] = [
                    _createTextVNode(" 需要 P115StrmHelper ", -1)
                  ]))]),
                  _: 1
                }),
                _cache[54] || (_cache[54] = _createElementVNode("span", null, [
                  _createTextVNode(" 仅「"),
                  _createElementVNode("b", null, "先尝试生成 strm"),
                  _createTextVNode("」一项。它请助手按文件所在的网盘目录重新生成 一次指针文件：生成成功 ⇒ 是情况 ①，"),
                  _createElementVNode("b", null, "无需删旧重传"),
                  _createTextVNode("； 生成后仍无 ⇒ 是情况 ②，此时再删旧重传。 ")
                ], -1))
              ])
            ]),
            _createVNode(CollapsibleNote, {
              title: "「先尝试生成 strm」的启用前提（两处都要配）",
              class: "mb-3"
            }, {
              default: _withCtx(() => [...(_cache[55] || (_cache[55] = [
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
            _createElementVNode("div", _hoisted_34, [
              _createElementVNode("div", _hoisted_35, [
                _cache[56] || (_cache[56] = _createElementVNode("div", null, [
                  _createElementVNode("div", { class: "font-weight-bold text-body-2" }, "观察宽限期（分钟）"),
                  _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, [
                    _createTextVNode(" strm 生成并不实时（可能还在上传或刮削中），因此同步成功后先等待一段时间再判定， 避免把「还没生成」误判为上传异常。最小 1 分钟。 "),
                    _createElementVNode("b", null, "单位此前是小时，已改为分钟"),
                    _createTextVNode(" —— 老配置的值不会自动换算， 请按分钟重设（启动日志里会提示）。 ")
                  ])
                ], -1)),
                _createVNode(_component_v_text_field, {
                  modelValue: config.value.strm_grace_minutes,
                  "onUpdate:modelValue": _cache[18] || (_cache[18] = $event => ((config.value.strm_grace_minutes) = $event)),
                  modelModifiers: { number: true },
                  type: "number",
                  step: "1",
                  min: "1",
                  variant: "outlined",
                  density: "compact",
                  class: "mt-2 max-field",
                  "hide-details": ""
                }, null, 8, ["modelValue"])
              ]),
              _createElementVNode("div", _hoisted_36, [
                _cache[57] || (_cache[57] = _createElementVNode("div", null, [
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
            ])
          ]),
          _: 1
        }),
        _createVNode(_component_v_card_actions, { class: "config-actions card-pad-x py-3 border-t bg-surface" }, {
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
                  default: _withCtx(() => [...(_cache[58] || (_cache[58] = [
                    _createTextVNode("mdi-view-dashboard-outline", -1)
                  ]))]),
                  _: 1
                }),
                _cache[59] || (_cache[59] = _createTextVNode(" 查看监控看板 ", -1))
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
                  default: _withCtx(() => [...(_cache[60] || (_cache[60] = [
                    _createTextVNode("mdi-content-save", -1)
                  ]))]),
                  _: 1
                }),
                _cache[61] || (_cache[61] = _createTextVNode(" 保存配置 ", -1))
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
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-08e286af"]]);

export { Config as default };
