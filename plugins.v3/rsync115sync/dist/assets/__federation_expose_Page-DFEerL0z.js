import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,Fragment:_Fragment,createBlock:_createBlock,renderList:_renderList} = await importShared('vue');


const _hoisted_1 = { class: "plugin-page" };
const _hoisted_2 = { class: "header-icon-box mr-3" };
const _hoisted_3 = { class: "d-flex align-center flex-wrap justify-end ga-1 header-append" };
const _hoisted_4 = { class: "stat-card stat-info rounded-xl pa-3 text-center" };
const _hoisted_5 = { class: "text-h5 font-weight-black text-info" };
const _hoisted_6 = { class: "text-caption text-medium-emphasis mt-1" };
const _hoisted_7 = { class: "stat-card stat-primary rounded-xl pa-3 text-center" };
const _hoisted_8 = { class: "text-h5 font-weight-black text-primary" };
const _hoisted_9 = { class: "stat-card stat-error rounded-xl pa-3 text-center" };
const _hoisted_10 = { class: "text-h5 font-weight-black text-error" };
const _hoisted_11 = {
  key: 0,
  class: "font-weight-medium"
};
const _hoisted_12 = { key: 1 };
const _hoisted_13 = { key: 2 };
const _hoisted_14 = { class: "action-strip rounded-xl pa-3 mb-4" };
const _hoisted_15 = { class: "action-strip-row d-flex flex-column flex-sm-row align-stretch align-sm-center justify-sm-space-between ga-2" };
const _hoisted_16 = { class: "action-group d-flex align-center flex-wrap ga-2" };
const _hoisted_17 = { class: "action-group d-flex align-center flex-wrap ga-2" };
const _hoisted_18 = {
  key: 0,
  class: "text-caption font-weight-bold text-primary mr-1 action-msg"
};
const _hoisted_19 = {
  key: 0,
  class: "d-flex align-center flex-wrap ga-3 mt-2 pt-2 batch-bar"
};
const _hoisted_20 = { class: "text-caption font-weight-bold" };
const _hoisted_21 = { class: "text-caption text-medium-emphasis batch-hint" };
const _hoisted_22 = { key: 1 };
const _hoisted_23 = {
  key: 0,
  class: "d-flex flex-column ga-2"
};
const _hoisted_24 = { class: "list-row-main d-flex align-center overflow-hidden mr-sm-3 mr-0" };
const _hoisted_25 = { class: "overflow-hidden" };
const _hoisted_26 = { class: "font-weight-bold text-body-2 text-truncate" };
const _hoisted_27 = { class: "text-caption text-medium-emphasis mt-0.5" };
const _hoisted_28 = {
  key: 0,
  class: "ml-2 text-warning font-weight-medium"
};
const _hoisted_29 = {
  key: 1,
  class: "ml-2 text-success font-weight-medium"
};
const _hoisted_30 = { class: "list-row-actions d-flex align-center flex-wrap ga-1 flex-shrink-0" };
const _hoisted_31 = {
  key: 1,
  class: "empty-box d-flex flex-column align-center justify-center py-10 px-4 rounded-xl text-center"
};
const _hoisted_32 = { key: 2 };
const _hoisted_33 = {
  key: 0,
  class: "d-flex flex-column ga-2"
};
const _hoisted_34 = { class: "list-row-main d-flex align-center overflow-hidden mr-sm-3 mr-0" };
const _hoisted_35 = { class: "overflow-hidden" };
const _hoisted_36 = { class: "font-weight-bold text-body-2 text-error text-truncate" };
const _hoisted_37 = { class: "list-row-actions d-flex align-center flex-wrap ga-1 flex-shrink-0" };
const _hoisted_38 = { class: "list-row-main d-flex align-center overflow-hidden mr-sm-3 mr-0" };
const _hoisted_39 = { class: "overflow-hidden" };
const _hoisted_40 = { class: "font-weight-bold text-body-2 text-warning text-truncate" };
const _hoisted_41 = { class: "list-row-actions d-flex align-center flex-wrap ga-1 flex-shrink-0" };
const _hoisted_42 = {
  key: 1,
  class: "empty-box d-flex flex-column align-center justify-center py-10 px-4 rounded-xl text-center"
};
const _hoisted_43 = { key: 3 };
const _hoisted_44 = {
  key: 0,
  class: "d-flex flex-column ga-2"
};
const _hoisted_45 = { class: "list-row-main overflow-hidden mr-sm-3 mr-0" };
const _hoisted_46 = { class: "font-weight-bold text-body-2 text-truncate" };
const _hoisted_47 = { class: "text-caption text-medium-emphasis mt-0.5" };
const _hoisted_48 = { key: 0 };
const _hoisted_49 = { class: "list-row-actions d-flex align-center flex-wrap ga-1 flex-shrink-0" };
const _hoisted_50 = {
  key: 1,
  class: "empty-box d-flex flex-column align-center justify-center py-10 px-4 rounded-xl text-center"
};

const {ref,computed,onMounted,onUnmounted} = await importShared('vue');



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
const currentTab = ref('queue');
const actionMsg = ref('');

const statusData = ref({
  is_running: false,
  ready_count: 0,
  cooling_count: 0,
  delay_hours: 2.0,
  last_status: {},
  sync_pairs_count: 0,
  backfill_remaining: 0,
  missed_count: 0,
  missed_last_scan: 0,
  backfill_total: 0,
  rate_limit_enabled: true,
  upload_window_count: 0,
  upload_max_per_window: 500,
  upload_window_secs: 1800,
  upload_blocked_until: 0,
});

const ignoredList = ref([]);

// 批量选择 / 单条手动触发
const selectMode = ref(false);
const selectedKeys = ref([]);
const itemLoading = ref('');
const batchSyncing = ref(false);
// 存量补传：扫描中状态
const backfillScanning = ref(false);

const failedCount = computed(() =>
  (statusData.value.last_status?.missing_files?.length || 0) +
  (statusData.value.last_status?.corrupt_files?.length || 0)
);

// 是否处于风控退避期（时间戳为未来时刻）
const isThrottled = computed(
  () => (statusData.value.upload_blocked_until || 0) * 1000 > Date.now()
);
const blockedMinutes = computed(() =>
  Math.max(1, Math.ceil(((statusData.value.upload_blocked_until || 0) * 1000 - Date.now()) / 60000))
);

const queueList = ref([]);
let timer = null;

// 当前标签页可被勾选的条目 key 列表
const selectableItems = computed(() => {
  if (currentTab.value === 'queue') {
    return queueList.value.map((it) => it.key)
  }
  if (currentTab.value === 'failed') {
    return [
      ...(statusData.value.last_status?.missing_files || []),
      ...(statusData.value.last_status?.corrupt_files || []),
    ]
  }
  return []
});

const allSelected = computed(
  () =>
    selectableItems.value.length > 0 &&
    selectableItems.value.every((k) => selectedKeys.value.includes(k))
);

function toggleSelectMode() {
  selectMode.value = !selectMode.value;
  if (!selectMode.value) selectedKeys.value = [];
}

function toggleSelect(key) {
  const i = selectedKeys.value.indexOf(key);
  if (i >= 0) selectedKeys.value.splice(i, 1);
  else selectedKeys.value.push(key);
}

// 全选/取消全选：仅作用于当前标签页的条目，不影响其它标签页已勾选的内容
function toggleSelectAll(val) {
  const current = selectableItems.value;
  if (val) {
    const merged = new Set([...selectedKeys.value, ...current]);
    selectedKeys.value = Array.from(merged);
  } else {
    selectedKeys.value = selectedKeys.value.filter((k) => !current.includes(k));
  }
}

// 单条手动触发同步（不等冷却，立即定向上传）
async function syncSingle(key) {
  if (!key || statusData.value.is_running) return
  itemLoading.value = key;
  actionMsg.value = `正在触发同步: ${key}`;
  try {
    const res = await props.api.post('plugin/Rsync115Sync/sync_item', { key });
    if (res && res.success) {
      actionMsg.value = res.message || `已触发同步: ${key}`;
      // 从选中列表移除，避免重复提交
      const i = selectedKeys.value.indexOf(key);
      if (i >= 0) selectedKeys.value.splice(i, 1);
    } else {
      actionMsg.value = res?.message || '触发同步失败';
    }
    await fetchStatus();
  } catch (e) {
    actionMsg.value = '触发同步出错: ' + e.message;
  } finally {
    itemLoading.value = '';
  }
}

// 补传存量媒体：先本地扫描预览规模，用户确认后再启动
async function scanBackfill() {
  if (statusData.value.is_running) return
  backfillScanning.value = true;
  actionMsg.value = '正在扫描本地存量媒体（不访问 115）...';
  try {
    const res = await props.api.get('plugin/Rsync115Sync/backfill_scan');
    if (!res || !res.success) {
      actionMsg.value = res?.message || '扫描失败';
      return
    }
    const { count, batch_size: batch, windows_needed: windows } = res.data || {};
    if (!count) {
      actionMsg.value = '没有需要补传的存量文件';
      return
    }
    // 明确告知代价：候选数 = 至少这么多次目标端 stat
    const ok = window.confirm(
      `发现 ${count} 个待补传文件（含同名字幕）。\n\n` +
      `补传将按每批 ${batch} 个、每个限流窗口分多轮自动推进，` +
      `预计需要约 ${windows} 个窗口（${windows} × ${Math.round((statusData.value.upload_window_secs || 1800) / 60)} 分钟）。\n\n` +
      `注意：每个候选文件至少产生一次 115 端校验请求，已存在的文件会被跳过而不会重传。\n\n` +
      `确定开始补传吗？`
    );
    if (!ok) {
      actionMsg.value = '已取消补传';
      return
    }
    const start = await props.api.post('plugin/Rsync115Sync/backfill_start', {});
    actionMsg.value = start?.message || '已启动补传';
    await fetchStatus();
  } catch (e) {
    actionMsg.value = '补传出错: ' + e.message;
  } finally {
    backfillScanning.value = false;
  }
}

// 清空补传队列
async function clearBackfill() {
  try {
    const res = await props.api.post('plugin/Rsync115Sync/backfill_clear', {});
    actionMsg.value = res?.message || '已取消补传';
    await fetchStatus();
  } catch (e) {
    actionMsg.value = '取消失败: ' + e.message;
  }
}

// 批量触发选中条目
async function batchSyncSelected() {
  if (!selectedKeys.value.length || statusData.value.is_running) return
  batchSyncing.value = true;
  actionMsg.value = `正在批量触发 ${selectedKeys.value.length} 个文件...`;
  try {
    const res = await props.api.post('plugin/Rsync115Sync/sync_item', { keys: [...selectedKeys.value] });
    if (res && res.success) {
      actionMsg.value = res.message || '已批量触发同步';
      selectedKeys.value = [];
    } else {
      actionMsg.value = res?.message || '批量触发失败';
    }
    await fetchStatus();
  } catch (e) {
    actionMsg.value = '批量触发出错: ' + e.message;
  } finally {
    batchSyncing.value = false;
  }
}

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
    const iRes = await props.api.get('plugin/Rsync115Sync/ignored');
    if (iRes && iRes.success && iRes.data) {
      ignoredList.value = iRes.data;
    }
    // 清理已不存在条目的勾选状态，避免提交到已消失的文件
    if (selectedKeys.value.length) {
      const alive = new Set([
        ...queueList.value.map((it) => it.key),
        ...(statusData.value.last_status?.missing_files || []),
        ...(statusData.value.last_status?.corrupt_files || []),
      ]);
      selectedKeys.value = selectedKeys.value.filter((k) => alive.has(k));
    }
  } catch (e) {
    console.error('获取状态失败:', e);
  } finally {
    loading.value = false;
  }
}

async function ignoreFile(file, match = 'exact') {
  try {
    const res = await props.api.post('plugin/Rsync115Sync/ignore', { rule: file, match });
    actionMsg.value = res?.message || '已加入忽略清单';
    fetchStatus();
  } catch (e) {
    actionMsg.value = '忽略失败: ' + e.message;
  }
}

async function removeIgnore(index) {
  try {
    const res = await props.api.post('plugin/Rsync115Sync/unignore', { index });
    actionMsg.value = res?.message || '已恢复对账';
    fetchStatus();
  } catch (e) {
    actionMsg.value = '恢复失败: ' + e.message;
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
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_checkbox = _resolveComponent("v-checkbox");
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
        _createVNode(_component_v_card_item, { class: "header-surface header-card-item px-5 py-3 border-b" }, {
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
              _cache[3] || (_cache[3] = _createElementVNode("div", { class: "header-subtitle text-caption text-medium-emphasis" }, "监控入库延迟冷却进度、双向对账异常与一键快速定向重试", -1))
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
            (statusData.value.backfill_remaining || isThrottled.value || statusData.value.missed_count)
              ? (_openBlock(), _createBlock(_component_v_alert, {
                  key: 0,
                  type: isThrottled.value ? 'warning' : 'info',
                  variant: "tonal",
                  density: "compact",
                  class: "rounded-lg mb-3 text-body-2"
                }, {
                  default: _withCtx(() => [
                    (isThrottled.value)
                      ? (_openBlock(), _createElementBlock("div", _hoisted_11, " ⏸ 为避免触发 115 风控，上传已自动暂停，约 " + _toDisplayString(blockedMinutes.value) + " 分钟后恢复，无需手动操作。 ", 1))
                      : _createCommentVNode("", true),
                    (statusData.value.backfill_remaining)
                      ? (_openBlock(), _createElementBlock("div", _hoisted_12, [
                          _cache[12] || (_cache[12] = _createTextVNode(" 存量补传进行中：剩余 ", -1)),
                          _createElementVNode("strong", null, _toDisplayString(statusData.value.backfill_remaining), 1),
                          (statusData.value.backfill_total)
                            ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                                _createTextVNode(" / 共 " + _toDisplayString(statusData.value.backfill_total), 1)
                              ], 64))
                            : _createCommentVNode("", true),
                          _createTextVNode(" 个。 为防风控，每个时间窗口最多上传 " + _toDisplayString(statusData.value.upload_max_per_window) + " 个 （本窗口已用 " + _toDisplayString(statusData.value.upload_window_count) + " 个），未传完的会自动继续。 ", 1)
                        ]))
                      : _createCommentVNode("", true),
                    (statusData.value.missed_count)
                      ? (_openBlock(), _createElementBlock("div", _hoisted_13, [
                          _cache[13] || (_cache[13] = _createTextVNode(" 🕳️ 检测到 ", -1)),
                          _createElementVNode("strong", null, _toDisplayString(statusData.value.missed_count), 1),
                          _cache[14] || (_cache[14] = _createTextVNode(" 个文件可能因插件重载错过了入库事件， 已由源端扫描补回，将在下次同步时一并上传（这些文件不再等待冷却）。 ", -1))
                        ]))
                      : _createCommentVNode("", true)
                  ]),
                  _: 1
                }, 8, ["type"]))
              : _createCommentVNode("", true),
            _createElementVNode("div", _hoisted_14, [
              _createElementVNode("div", _hoisted_15, [
                _createElementVNode("div", _hoisted_16, [
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
                        default: _withCtx(() => [...(_cache[15] || (_cache[15] = [
                          _createTextVNode("mdi-play", -1)
                        ]))]),
                        _: 1
                      }),
                      _cache[16] || (_cache[16] = _createTextVNode(" 同步已就绪媒体 ", -1))
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
                        default: _withCtx(() => [...(_cache[17] || (_cache[17] = [
                          _createTextVNode("mdi-refresh", -1)
                        ]))]),
                        _: 1
                      }),
                      _cache[18] || (_cache[18] = _createTextVNode(" 定向重试失败文件 ", -1))
                    ]),
                    _: 1
                  }, 8, ["loading", "disabled"]),
                  _createVNode(_component_v_btn, {
                    color: "info",
                    variant: "tonal",
                    size: "small",
                    rounded: "lg",
                    onClick: scanBackfill,
                    loading: backfillScanning.value,
                    disabled: statusData.value.is_running
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_icon, {
                        start: "",
                        size: "16"
                      }, {
                        default: _withCtx(() => [...(_cache[19] || (_cache[19] = [
                          _createTextVNode("mdi-database-arrow-up-outline", -1)
                        ]))]),
                        _: 1
                      }),
                      _cache[21] || (_cache[21] = _createTextVNode(" 补传存量媒体 ", -1)),
                      _createVNode(_component_v_tooltip, {
                        activator: "parent",
                        location: "top"
                      }, {
                        default: _withCtx(() => [...(_cache[20] || (_cache[20] = [
                          _createTextVNode(" 扫描本地存量媒体（含同名字幕）并分批补传；只读源端目录，不遍历 115 ", -1)
                        ]))]),
                        _: 1
                      })
                    ]),
                    _: 1
                  }, 8, ["loading", "disabled"]),
                  (statusData.value.backfill_remaining)
                    ? (_openBlock(), _createBlock(_component_v_btn, {
                        key: 0,
                        color: "error",
                        variant: "text",
                        size: "small",
                        rounded: "lg",
                        onClick: clearBackfill,
                        disabled: statusData.value.is_running
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_icon, {
                            start: "",
                            size: "16"
                          }, {
                            default: _withCtx(() => [...(_cache[22] || (_cache[22] = [
                              _createTextVNode("mdi-cancel", -1)
                            ]))]),
                            _: 1
                          }),
                          _cache[23] || (_cache[23] = _createTextVNode(" 取消补传 ", -1))
                        ]),
                        _: 1
                      }, 8, ["disabled"]))
                    : _createCommentVNode("", true)
                ]),
                _createElementVNode("div", _hoisted_17, [
                  (actionMsg.value)
                    ? (_openBlock(), _createElementBlock("div", _hoisted_18, _toDisplayString(actionMsg.value), 1))
                    : _createCommentVNode("", true),
                  (currentTab.value !== 'ignored')
                    ? (_openBlock(), _createBlock(_component_v_btn, {
                        key: 1,
                        size: "small",
                        variant: "tonal",
                        color: selectMode.value ? 'error' : 'secondary',
                        rounded: "lg",
                        onClick: toggleSelectMode
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_icon, {
                            start: "",
                            size: "16"
                          }, {
                            default: _withCtx(() => [
                              _createTextVNode(_toDisplayString(selectMode.value ? 'mdi-close' : 'mdi-checkbox-multiple-marked-outline'), 1)
                            ]),
                            _: 1
                          }),
                          _createTextVNode(" " + _toDisplayString(selectMode.value ? '退出批量' : '批量选择'), 1)
                        ]),
                        _: 1
                      }, 8, ["color"]))
                    : _createCommentVNode("", true),
                  (selectMode.value)
                    ? (_openBlock(), _createBlock(_component_v_btn, {
                        key: 2,
                        size: "small",
                        variant: "flat",
                        color: "primary",
                        rounded: "lg",
                        loading: batchSyncing.value,
                        disabled: !selectedKeys.value.length || statusData.value.is_running,
                        onClick: batchSyncSelected
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_icon, {
                            start: "",
                            size: "16"
                          }, {
                            default: _withCtx(() => [...(_cache[24] || (_cache[24] = [
                              _createTextVNode("mdi-cloud-upload-outline", -1)
                            ]))]),
                            _: 1
                          }),
                          _createTextVNode(" 同步选中 (" + _toDisplayString(selectedKeys.value.length) + ") ", 1)
                        ]),
                        _: 1
                      }, 8, ["loading", "disabled"]))
                    : _createCommentVNode("", true)
                ])
              ]),
              (selectMode.value)
                ? (_openBlock(), _createElementBlock("div", _hoisted_19, [
                    _createVNode(_component_v_checkbox, {
                      "model-value": allSelected.value,
                      indeterminate: selectedKeys.value.length > 0 && !allSelected.value,
                      density: "compact",
                      "hide-details": "",
                      color: "primary",
                      class: "flex-shrink-0",
                      "onUpdate:modelValue": toggleSelectAll
                    }, {
                      label: _withCtx(() => [
                        _createElementVNode("span", _hoisted_20, "全选本页 (" + _toDisplayString(selectableItems.value.length) + ")", 1)
                      ]),
                      _: 1
                    }, 8, ["model-value", "indeterminate"]),
                    _createElementVNode("span", _hoisted_21, "已选 " + _toDisplayString(selectedKeys.value.length) + " 项 · 可跨分组勾选后一次性上传统一触发", 1)
                  ]))
                : _createCommentVNode("", true)
            ]),
            _createVNode(_component_v_tabs, {
              modelValue: currentTab.value,
              "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((currentTab).value = $event)),
              color: "primary",
              density: "compact",
              "show-arrows": "",
              class: "mb-3 border-b"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_tab, { value: "queue" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_icon, {
                      start: "",
                      size: "16"
                    }, {
                      default: _withCtx(() => [...(_cache[25] || (_cache[25] = [
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
                      default: _withCtx(() => [...(_cache[26] || (_cache[26] = [
                        _createTextVNode("mdi-alert-circle-outline", -1)
                      ]))]),
                      _: 1
                    }),
                    _createTextVNode(" 对账异常清单 (" + _toDisplayString(failedCount.value) + ") ", 1)
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_tab, { value: "ignored" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_icon, {
                      start: "",
                      size: "16"
                    }, {
                      default: _withCtx(() => [...(_cache[27] || (_cache[27] = [
                        _createTextVNode("mdi-eye-off-outline", -1)
                      ]))]),
                      _: 1
                    }),
                    _createTextVNode(" 已忽略 (" + _toDisplayString(ignoredList.value.length) + ") ", 1)
                  ]),
                  _: 1
                })
              ]),
              _: 1
            }, 8, ["modelValue"]),
            (currentTab.value === 'queue')
              ? (_openBlock(), _createElementBlock("div", _hoisted_22, [
                  (queueList.value.length)
                    ? (_openBlock(), _createElementBlock("div", _hoisted_23, [
                        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(queueList.value, (item, idx) => {
                          return (_openBlock(), _createElementBlock("div", {
                            key: 'q-' + idx,
                            class: "queue-item-card d-flex flex-column flex-sm-row align-stretch align-sm-center justify-sm-space-between rounded-xl pa-3 ga-2"
                          }, [
                            _createElementVNode("div", _hoisted_24, [
                              (selectMode.value)
                                ? (_openBlock(), _createBlock(_component_v_checkbox, {
                                    key: 0,
                                    "model-value": selectedKeys.value.includes(item.key),
                                    density: "compact",
                                    "hide-details": "",
                                    color: "primary",
                                    class: "flex-shrink-0 mr-2",
                                    "onUpdate:modelValue": $event => (toggleSelect(item.key))
                                  }, null, 8, ["model-value", "onUpdate:modelValue"]))
                                : _createCommentVNode("", true),
                              _createElementVNode("div", _hoisted_25, [
                                _createElementVNode("div", _hoisted_26, _toDisplayString(item.key), 1),
                                _createElementVNode("div", _hoisted_27, [
                                  _createTextVNode(" 入库时间: " + _toDisplayString(item.enter_time) + " ", 1),
                                  (!item.is_ready)
                                    ? (_openBlock(), _createElementBlock("span", _hoisted_28, " (还需冷却等待 " + _toDisplayString(Math.ceil(item.remaining_seconds / 60)) + " 分钟) ", 1))
                                    : (_openBlock(), _createElementBlock("span", _hoisted_29, " (已达到冷却时间，随时可同步) "))
                                ])
                              ])
                            ]),
                            _createElementVNode("div", _hoisted_30, [
                              _createVNode(_component_v_chip, {
                                size: "x-small",
                                color: item.is_ready ? 'success' : 'warning',
                                variant: "tonal",
                                class: "font-weight-bold"
                              }, {
                                default: _withCtx(() => [
                                  _createTextVNode(_toDisplayString(item.is_ready ? '已就绪' : '缓冲中'), 1)
                                ]),
                                _: 2
                              }, 1032, ["color"]),
                              _createVNode(_component_v_btn, {
                                size: "x-small",
                                variant: "tonal",
                                color: "primary",
                                rounded: "lg",
                                class: "px-2",
                                loading: itemLoading.value === item.key,
                                disabled: statusData.value.is_running || (!!itemLoading.value && itemLoading.value !== item.key),
                                onClick: $event => (syncSingle(item.key))
                              }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_icon, {
                                    start: "",
                                    size: "14"
                                  }, {
                                    default: _withCtx(() => [...(_cache[28] || (_cache[28] = [
                                      _createTextVNode("mdi-cloud-upload-outline", -1)
                                    ]))]),
                                    _: 1
                                  }),
                                  _cache[30] || (_cache[30] = _createTextVNode(" 立即同步 ", -1)),
                                  _createVNode(_component_v_tooltip, {
                                    activator: "parent",
                                    location: "top"
                                  }, {
                                    default: _withCtx(() => [...(_cache[29] || (_cache[29] = [
                                      _createTextVNode(" 不等待冷却，立即定向同步此文件（会自动移出冷却队列） ", -1)
                                    ]))]),
                                    _: 1
                                  })
                                ]),
                                _: 1
                              }, 8, ["loading", "disabled", "onClick"])
                            ])
                          ]))
                        }), 128))
                      ]))
                    : (_openBlock(), _createElementBlock("div", _hoisted_31, [
                        _createVNode(_component_v_icon, {
                          size: "32",
                          color: "primary",
                          class: "mb-2"
                        }, {
                          default: _withCtx(() => [...(_cache[31] || (_cache[31] = [
                            _createTextVNode("mdi-check-circle-outline", -1)
                          ]))]),
                          _: 1
                        }),
                        _cache[32] || (_cache[32] = _createElementVNode("div", { class: "text-caption font-weight-bold text-medium-emphasis" }, "暂无正在冷却中的媒体文件", -1))
                      ]))
                ]))
              : _createCommentVNode("", true),
            (currentTab.value === 'failed')
              ? (_openBlock(), _createElementBlock("div", _hoisted_32, [
                  (failedCount.value)
                    ? (_openBlock(), _createElementBlock("div", _hoisted_33, [
                        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(statusData.value.last_status?.missing_files || [], (file, idx) => {
                          return (_openBlock(), _createElementBlock("div", {
                            key: 'm-' + idx,
                            class: "failed-item-card d-flex flex-column flex-sm-row align-stretch align-sm-center justify-sm-space-between rounded-xl pa-3 ga-2"
                          }, [
                            _createElementVNode("div", _hoisted_34, [
                              (selectMode.value)
                                ? (_openBlock(), _createBlock(_component_v_checkbox, {
                                    key: 0,
                                    "model-value": selectedKeys.value.includes(file),
                                    density: "compact",
                                    "hide-details": "",
                                    color: "primary",
                                    class: "flex-shrink-0 mr-2",
                                    "onUpdate:modelValue": $event => (toggleSelect(file))
                                  }, null, 8, ["model-value", "onUpdate:modelValue"]))
                                : _createCommentVNode("", true),
                              _createElementVNode("div", _hoisted_35, [
                                _createElementVNode("div", _hoisted_36, _toDisplayString(file), 1),
                                _cache[33] || (_cache[33] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mt-0.5" }, "本地已入库，但 115 网盘端尚未同步到位", -1))
                              ])
                            ]),
                            _createElementVNode("div", _hoisted_37, [
                              _createVNode(_component_v_chip, {
                                size: "x-small",
                                color: "error",
                                variant: "flat",
                                class: "font-weight-bold"
                              }, {
                                default: _withCtx(() => [...(_cache[34] || (_cache[34] = [
                                  _createTextVNode("待同步", -1)
                                ]))]),
                                _: 1
                              }),
                              _createVNode(_component_v_btn, {
                                size: "x-small",
                                variant: "tonal",
                                color: "primary",
                                rounded: "lg",
                                class: "px-2",
                                loading: itemLoading.value === file,
                                disabled: statusData.value.is_running || (!!itemLoading.value && itemLoading.value !== file),
                                onClick: $event => (syncSingle(file))
                              }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_icon, {
                                    start: "",
                                    size: "14"
                                  }, {
                                    default: _withCtx(() => [...(_cache[35] || (_cache[35] = [
                                      _createTextVNode("mdi-refresh", -1)
                                    ]))]),
                                    _: 1
                                  }),
                                  _cache[37] || (_cache[37] = _createTextVNode(" 重试 ", -1)),
                                  _createVNode(_component_v_tooltip, {
                                    activator: "parent",
                                    location: "top"
                                  }, {
                                    default: _withCtx(() => [...(_cache[36] || (_cache[36] = [
                                      _createTextVNode("立即定向重传此文件", -1)
                                    ]))]),
                                    _: 1
                                  })
                                ]),
                                _: 1
                              }, 8, ["loading", "disabled", "onClick"]),
                              _createVNode(_component_v_btn, {
                                icon: "",
                                size: "x-small",
                                variant: "text",
                                color: "primary",
                                onClick: $event => (ignoreFile(file, 'exact'))
                              }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_icon, { size: "16" }, {
                                    default: _withCtx(() => [...(_cache[38] || (_cache[38] = [
                                      _createTextVNode("mdi-eye-off-outline", -1)
                                    ]))]),
                                    _: 1
                                  }),
                                  _createVNode(_component_v_tooltip, {
                                    activator: "parent",
                                    location: "top"
                                  }, {
                                    default: _withCtx(() => [...(_cache[39] || (_cache[39] = [
                                      _createTextVNode("忽略此项（不再报警）", -1)
                                    ]))]),
                                    _: 1
                                  })
                                ]),
                                _: 1
                              }, 8, ["onClick"])
                            ])
                          ]))
                        }), 128)),
                        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(statusData.value.last_status?.corrupt_files || [], (file, idx) => {
                          return (_openBlock(), _createElementBlock("div", {
                            key: 'c-' + idx,
                            class: "failed-item-card d-flex flex-column flex-sm-row align-stretch align-sm-center justify-sm-space-between rounded-xl pa-3 ga-2"
                          }, [
                            _createElementVNode("div", _hoisted_38, [
                              (selectMode.value)
                                ? (_openBlock(), _createBlock(_component_v_checkbox, {
                                    key: 0,
                                    "model-value": selectedKeys.value.includes(file),
                                    density: "compact",
                                    "hide-details": "",
                                    color: "primary",
                                    class: "flex-shrink-0 mr-2",
                                    "onUpdate:modelValue": $event => (toggleSelect(file))
                                  }, null, 8, ["model-value", "onUpdate:modelValue"]))
                                : _createCommentVNode("", true),
                              _createElementVNode("div", _hoisted_39, [
                                _createElementVNode("div", _hoisted_40, _toDisplayString(file), 1),
                                _cache[40] || (_cache[40] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mt-0.5" }, "目标端大小不一致，传输中途断流", -1))
                              ])
                            ]),
                            _createElementVNode("div", _hoisted_41, [
                              _createVNode(_component_v_chip, {
                                size: "x-small",
                                color: "warning",
                                variant: "flat",
                                class: "font-weight-bold"
                              }, {
                                default: _withCtx(() => [...(_cache[41] || (_cache[41] = [
                                  _createTextVNode("文件残缺", -1)
                                ]))]),
                                _: 1
                              }),
                              _createVNode(_component_v_btn, {
                                size: "x-small",
                                variant: "tonal",
                                color: "primary",
                                rounded: "lg",
                                class: "px-2",
                                loading: itemLoading.value === file,
                                disabled: statusData.value.is_running || (!!itemLoading.value && itemLoading.value !== file),
                                onClick: $event => (syncSingle(file))
                              }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_icon, {
                                    start: "",
                                    size: "14"
                                  }, {
                                    default: _withCtx(() => [...(_cache[42] || (_cache[42] = [
                                      _createTextVNode("mdi-refresh", -1)
                                    ]))]),
                                    _: 1
                                  }),
                                  _cache[44] || (_cache[44] = _createTextVNode(" 重试 ", -1)),
                                  _createVNode(_component_v_tooltip, {
                                    activator: "parent",
                                    location: "top"
                                  }, {
                                    default: _withCtx(() => [...(_cache[43] || (_cache[43] = [
                                      _createTextVNode("先清理目标端残缺文件，再重新上传", -1)
                                    ]))]),
                                    _: 1
                                  })
                                ]),
                                _: 1
                              }, 8, ["loading", "disabled", "onClick"]),
                              _createVNode(_component_v_btn, {
                                icon: "",
                                size: "x-small",
                                variant: "text",
                                color: "primary",
                                onClick: $event => (ignoreFile(file, 'exact'))
                              }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_icon, { size: "16" }, {
                                    default: _withCtx(() => [...(_cache[45] || (_cache[45] = [
                                      _createTextVNode("mdi-eye-off-outline", -1)
                                    ]))]),
                                    _: 1
                                  }),
                                  _createVNode(_component_v_tooltip, {
                                    activator: "parent",
                                    location: "top"
                                  }, {
                                    default: _withCtx(() => [...(_cache[46] || (_cache[46] = [
                                      _createTextVNode("忽略此项（不再报警）", -1)
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
                    : (_openBlock(), _createElementBlock("div", _hoisted_42, [
                        _createVNode(_component_v_icon, {
                          size: "32",
                          color: "success",
                          class: "mb-2"
                        }, {
                          default: _withCtx(() => [...(_cache[47] || (_cache[47] = [
                            _createTextVNode("mdi-shield-check", -1)
                          ]))]),
                          _: 1
                        }),
                        _cache[48] || (_cache[48] = _createElementVNode("div", { class: "text-caption font-weight-bold text-medium-emphasis" }, "冷却队列与待重试文件经对账全部一致，零缺失零残缺！", -1))
                      ]))
                ]))
              : _createCommentVNode("", true),
            (currentTab.value === 'ignored')
              ? (_openBlock(), _createElementBlock("div", _hoisted_43, [
                  (ignoredList.value.length)
                    ? (_openBlock(), _createElementBlock("div", _hoisted_44, [
                        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(ignoredList.value, (rule, idx) => {
                          return (_openBlock(), _createElementBlock("div", {
                            key: 'i-' + idx,
                            class: "queue-item-card d-flex flex-column flex-sm-row align-stretch align-sm-center justify-sm-space-between rounded-xl pa-3 ga-2"
                          }, [
                            _createElementVNode("div", _hoisted_45, [
                              _createElementVNode("div", _hoisted_46, _toDisplayString(rule.rule), 1),
                              _createElementVNode("div", _hoisted_47, [
                                _createTextVNode(_toDisplayString(rule.match === 'exact' ? '精确匹配' : '包含匹配') + " · 加入于 " + _toDisplayString(rule.created_at) + " ", 1),
                                (rule.created_by)
                                  ? (_openBlock(), _createElementBlock("span", _hoisted_48, " · 操作人 " + _toDisplayString(rule.created_by), 1))
                                  : _createCommentVNode("", true)
                              ])
                            ]),
                            _createElementVNode("div", _hoisted_49, [
                              _createVNode(_component_v_chip, {
                                size: "x-small",
                                color: "secondary",
                                variant: "tonal",
                                class: "font-weight-bold"
                              }, {
                                default: _withCtx(() => [...(_cache[49] || (_cache[49] = [
                                  _createTextVNode("已忽略", -1)
                                ]))]),
                                _: 1
                              }),
                              _createVNode(_component_v_btn, {
                                icon: "",
                                size: "x-small",
                                variant: "text",
                                color: "success",
                                onClick: $event => (removeIgnore(idx))
                              }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_icon, { size: "16" }, {
                                    default: _withCtx(() => [...(_cache[50] || (_cache[50] = [
                                      _createTextVNode("mdi-restore", -1)
                                    ]))]),
                                    _: 1
                                  }),
                                  _createVNode(_component_v_tooltip, {
                                    activator: "parent",
                                    location: "top"
                                  }, {
                                    default: _withCtx(() => [...(_cache[51] || (_cache[51] = [
                                      _createTextVNode("恢复对账", -1)
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
                    : (_openBlock(), _createElementBlock("div", _hoisted_50, [
                        _createVNode(_component_v_icon, {
                          size: "32",
                          color: "primary",
                          class: "mb-2"
                        }, {
                          default: _withCtx(() => [...(_cache[52] || (_cache[52] = [
                            _createTextVNode("mdi-eye-off-outline", -1)
                          ]))]),
                          _: 1
                        }),
                        _cache[53] || (_cache[53] = _createElementVNode("div", { class: "text-caption font-weight-bold text-medium-emphasis" }, "当前没有忽略任何文件", -1))
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
const App = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-86fd8c83"]]);

export { App as default };
