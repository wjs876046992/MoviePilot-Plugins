import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,toDisplayString:_toDisplayString,mergeProps:_mergeProps,createElementVNode:_createElementVNode,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createElementBlock:_createElementBlock,renderList:_renderList,Fragment:_Fragment,normalizeClass:_normalizeClass} = await importShared('vue');


const _hoisted_1 = { class: "plugin-page" };
const _hoisted_2 = { class: "d-flex align-center gap-3" };
const _hoisted_3 = {
  key: 1,
  class: "pa-4"
};
const _hoisted_4 = { key: 2 };
const _hoisted_5 = {
  key: 0,
  class: "mt-2"
};
const _hoisted_6 = { class: "d-flex justify-space-between align-center mb-2" };
const _hoisted_7 = { class: "d-flex align-center" };
const _hoisted_8 = { class: "font-weight-bold text-subtitle-2 text-primary-darken-1" };
const _hoisted_9 = { class: "text-caption text-medium-emphasis bg-grey-lighten-4 px-2 py-1 rounded-pill" };
const _hoisted_10 = { class: "text-body-2 mb-2 d-flex align-center flex-wrap gap-1" };
const _hoisted_11 = {
  key: 0,
  class: "text-caption text-indigo-darken-1 bg-indigo-lighten-5 pa-2 rounded d-flex align-center"
};
const _hoisted_12 = {
  key: 1,
  class: "text-caption text-error bg-error-lighten-5 pa-2 rounded mt-2 d-flex align-start border border-error border-opacity-25"
};
const _hoisted_13 = {
  key: 0,
  class: "text-center mt-6 mb-2"
};
const _hoisted_14 = {
  key: 1,
  class: "text-center mt-3 text-caption text-medium-emphasis font-weight-medium"
};
const _hoisted_15 = {
  key: 1,
  class: "text-center py-10"
};

const {ref,onMounted} = await importShared('vue');


// 接收初始配置

const _sfc_main = {
  __name: 'Page',
  props: {
  model: {
    type: Object,
    default: () => {},
  },
  api: {
    type: Object,
    default: () => {},
  },
},
  emits: ['action', 'switch', 'close'],
  setup(__props, { emit: __emit }) {

const props = __props;

// 组件状态
const title = ref('观看记录同步');
const loading = ref(true);
const error = ref(null);
const syncRecords = ref([]);
const groupedSyncRecords = ref([]);
const clearing = ref(false);
// 分页相关状态
const pagination = ref({
  offset: 0,
  limit: 20,
  total: 0,
  hasMore: false,
  loading: false
});

// 自定义事件，用于通知主应用刷新数据
const emit = __emit;

// 获取状态图标
function getItemIcon(status) {
  const icons = {
    'success': 'mdi-check',
    'error': 'mdi-alert',
    'pending': 'mdi-clock-outline',
  };
  return icons[status] || 'mdi-information'
}

// 获取状态颜色
function getItemColor(status) {
  const colors = {
    'success': 'success',
    'error': 'error',
    'pending': 'warning',
  };
  return colors[status] || 'grey'
}

// 获取媒体类型图标
function getMediaTypeIcon(mediaType) {
  const icons = {
    'Movie': 'mdi-movie',
    'Episode': 'mdi-television',
    'Series': 'mdi-television-box',
  };
  return icons[mediaType] || 'mdi-play-circle'
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

// 获取媒体类型颜色
function getMediaTypeColor(mediaType) {
  const colors = {
    'Movie': 'blue',
    'Episode': 'green',
    'Series': 'purple',
  };
  return colors[mediaType] || 'grey'
}

// 获取事件描述
function getEventDescription(syncType) {
  const descriptions = {
    'favorite': '收藏了媒体',
    'not_favorite': '取消收藏媒体',
    'mark_played': '标记为已看',
    'mark_unplayed': '标记为未看'
  };
  return descriptions[syncType]
}

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
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString()
  }
}

// 格式化播放进度 (始终显示 hh:mm:ss 格式)
function formatProgress(positionTicks) {
  if (!positionTicks) return ''

  // 将ticks转换为秒 (1 tick = 100 nanoseconds, 10,000,000 ticks = 1 second)
  const totalSeconds = Math.floor(positionTicks / 10000000);

  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  // 始终显示 hh:mm:ss 格式
  return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`
}

// 获取和刷新数据
async function refreshData() {
  loading.value = true;
  error.value = null;

  try {
    // 获取同步记录
    await loadSyncRecords();
  } catch (err) {
    console.error('获取数据失败:', err);
    error.value = err.message || '获取数据失败';
  } finally {
    loading.value = false;
    // 通知主应用组件已更新
    emit('action');
  }
}

// 加载同步记录（初始加载）
async function loadSyncRecords() {
  try {
    // 重置分页状态
    pagination.value.offset = 0;

    // 使用props.api进行API调用，它已经包含了认证信息
    const result = await props.api.get(`plugin/WatchSync/records?limit=${pagination.value.limit}&offset=${pagination.value.offset}`);

    if (result && result.success) {
      syncRecords.value = result.data || [];

      // 更新分页信息
      if (result.pagination) {
        pagination.value.total = result.pagination.total;
        pagination.value.hasMore = result.pagination.has_more;
      }

      // 对同步记录进行分组
      groupSyncRecords();
      return
    } else {
      console.warn('获取同步记录失败:', result?.message || '未知错误');
    }
  } catch (err) {
    console.error('获取同步记录失败:', err);
  }
  // 设置空数组作为默认值
  syncRecords.value = [];
  groupedSyncRecords.value = [];
}

// 加载更多记录
async function loadMoreRecords() {
  if (pagination.value.loading || !pagination.value.hasMore) {
    return
  }

  pagination.value.loading = true;

  try {
    // 计算下一页的offset
    const nextOffset = pagination.value.offset + pagination.value.limit;

    const result = await props.api.get(`plugin/WatchSync/records?limit=${pagination.value.limit}&offset=${nextOffset}`);

    if (result && result.success) {
      // 追加新记录到现有记录
      syncRecords.value.push(...(result.data || []));

      // 更新分页信息
      if (result.pagination) {
        pagination.value.offset = nextOffset;
        pagination.value.total = result.pagination.total;
        pagination.value.hasMore = result.pagination.has_more;
      }

      // 重新分组记录
      groupSyncRecords();
    } else {
      console.warn('加载更多记录失败:', result?.message || '未知错误');
    }
  } catch (err) {
    console.error('加载更多记录失败:', err);
  } finally {
    pagination.value.loading = false;
  }
}

// 分组同步记录
function groupSyncRecords() {
  const groups = new Map();

  syncRecords.value.forEach(record => {
    const timestamp = new Date(record.timestamp || record.created_at);
    // 使用1分钟的时间窗口来聚合由单个操作触发的多个同步事件
    const timeWindow = Math.floor(timestamp.getTime() / (1 * 60 * 1000));

    // 分组键由源用户、媒体、操作类型和时间窗口共同决定
    const groupKey = `${record.source_user}_${record.media_name}_${record.sync_type}_${timeWindow}`;

    if (!groups.has(groupKey)) {
      groups.set(groupKey, {
        ...record,
        target_users: [record.target_user] // 初始化目标用户列表
      });
    } else {
      const group = groups.get(groupKey);
      // 将新的目标用户添加到现有组中
      if (!group.target_users.includes(record.target_user)) {
        group.target_users.push(record.target_user);
      }

      // 确保使用最新的时间戳
      if (timestamp > new Date(group.timestamp)) {
        group.timestamp = record.timestamp;
      }

      // 对于播放事件，始终更新到最新的进度
      if (record.sync_type === 'playback' && record.position_ticks > (group.position_ticks || 0)) {
          group.position_ticks = record.position_ticks;
      }

      // 如果有任何一个同步失败，整个组标记为失败
      if (record.status === 'error' || record.status === 'failed') {
        group.status = 'error';
      }
    }
  });

  // 转换为数组并按时间排序
  groupedSyncRecords.value = Array.from(groups.values())
    .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
    .map(group => {
      // 添加描述
      if (group.sync_type === 'playback') {
        group.description = `播放进度: ${formatProgress(group.position_ticks)}`;
      } else {
        group.description = getEventDescription(group.sync_type);
      }

      return group
    });
}

// 清理旧记录
async function clearOldRecords(days = 30) {
  clearing.value = true;
  try {
    const result = await props.api.delete(`plugin/WatchSync/records/old?days=${days}`);
    if (result && result.success) {
      console.log('清理记录成功:', result.message);
      // 重新加载数据
      await loadSyncRecords();
    } else {
      console.warn('清理记录失败:', result?.message || '未知错误');
    }
  } catch (err) {
    console.error('清理记录失败:', err);
  } finally {
    clearing.value = false;
  }
}

// 导出日志
function exportLogs() {
  try {
    const data = {
      exportTime: new Date().toISOString(),
      records: syncRecords.value
    };

    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `watchsync-logs-${new Date().toISOString().split('T')[0]}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    console.log('日志导出成功');
  } catch (err) {
    console.error('导出日志失败:', err);
  }
}

// 通知主应用切换到配置页面
function notifySwitch() {
  emit('switch');
}

// 通知主应用关闭组件
function notifyClose() {
  emit('close');
}

// 组件挂载时加载数据
onMounted(() => {
  refreshData();
});

return (_ctx, _cache) => {
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_card_title = _resolveComponent("v-card-title");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_list_item_title = _resolveComponent("v-list-item-title");
  const _component_v_list_item = _resolveComponent("v-list-item");
  const _component_v_list = _resolveComponent("v-list");
  const _component_v_menu = _resolveComponent("v-menu");
  const _component_v_card_item = _resolveComponent("v-card-item");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_skeleton_loader = _resolveComponent("v-skeleton-loader");
  const _component_v_chip = _resolveComponent("v-chip");
  const _component_v_card = _resolveComponent("v-card");
  const _component_v_timeline_item = _resolveComponent("v-timeline-item");
  const _component_v_timeline = _resolveComponent("v-timeline");
  const _component_v_card_text = _resolveComponent("v-card-text");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_v_card, {
      class: "rounded-lg shadow-sm",
      elevation: "0",
      variant: "outlined"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_v_card_item, { class: "border-b bg-grey-lighten-4 pa-4" }, {
          prepend: _withCtx(() => [
            _createVNode(_component_v_icon, {
              color: "primary",
              size: "x-large",
              class: "mr-2"
            }, {
              default: _withCtx(() => [...(_cache[3] || (_cache[3] = [
                _createTextVNode("mdi-history", -1)
              ]))]),
              _: 1
            })
          ]),
          append: _withCtx(() => [
            _createElementVNode("div", _hoisted_2, [
              _createVNode(_component_v_btn, {
                color: "primary",
                rounded: "lg",
                onClick: refreshData,
                loading: loading.value,
                text: "刷新",
                variant: "flat",
                size: "small",
                class: "px-4 font-weight-medium box-shadow-sm"
              }, {
                prepend: _withCtx(() => [
                  _createVNode(_component_v_icon, null, {
                    default: _withCtx(() => [...(_cache[4] || (_cache[4] = [
                      _createTextVNode("mdi-refresh", -1)
                    ]))]),
                    _: 1
                  })
                ]),
                _: 1
              }, 8, ["loading"]),
              _createVNode(_component_v_menu, null, {
                activator: _withCtx(({ props }) => [
                  _createVNode(_component_v_btn, _mergeProps(props, {
                    color: "secondary",
                    rounded: "lg",
                    loading: clearing.value,
                    text: "清理",
                    variant: "tonal",
                    size: "small",
                    class: "px-4 font-weight-medium"
                  }), {
                    prepend: _withCtx(() => [
                      _createVNode(_component_v_icon, null, {
                        default: _withCtx(() => [...(_cache[5] || (_cache[5] = [
                          _createTextVNode("mdi-delete-sweep", -1)
                        ]))]),
                        _: 1
                      })
                    ]),
                    _: 1
                  }, 16, ["loading"])
                ]),
                default: _withCtx(() => [
                  _createVNode(_component_v_list, {
                    rounded: "lg",
                    elevation: "3",
                    class: "mt-1"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_list_item, {
                        onClick: _cache[0] || (_cache[0] = $event => (clearOldRecords(7)))
                      }, {
                        prepend: _withCtx(() => [
                          _createVNode(_component_v_icon, {
                            size: "small",
                            class: "mr-2",
                            color: "warning"
                          }, {
                            default: _withCtx(() => [...(_cache[6] || (_cache[6] = [
                              _createTextVNode("mdi-calendar-alert", -1)
                            ]))]),
                            _: 1
                          })
                        ]),
                        default: _withCtx(() => [
                          _createVNode(_component_v_list_item_title, { class: "text-body-2" }, {
                            default: _withCtx(() => [...(_cache[7] || (_cache[7] = [
                              _createTextVNode("清理7天前", -1)
                            ]))]),
                            _: 1
                          })
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_v_list_item, {
                        onClick: _cache[1] || (_cache[1] = $event => (clearOldRecords(30)))
                      }, {
                        prepend: _withCtx(() => [
                          _createVNode(_component_v_icon, {
                            size: "small",
                            class: "mr-2",
                            color: "error"
                          }, {
                            default: _withCtx(() => [...(_cache[8] || (_cache[8] = [
                              _createTextVNode("mdi-calendar-remove", -1)
                            ]))]),
                            _: 1
                          })
                        ]),
                        default: _withCtx(() => [
                          _createVNode(_component_v_list_item_title, { class: "text-body-2" }, {
                            default: _withCtx(() => [...(_cache[9] || (_cache[9] = [
                              _createTextVNode("清理30天前", -1)
                            ]))]),
                            _: 1
                          })
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_v_list_item, {
                        onClick: _cache[2] || (_cache[2] = $event => (clearOldRecords(90)))
                      }, {
                        prepend: _withCtx(() => [
                          _createVNode(_component_v_icon, {
                            size: "small",
                            class: "mr-2",
                            color: "grey"
                          }, {
                            default: _withCtx(() => [...(_cache[10] || (_cache[10] = [
                              _createTextVNode("mdi-delete-forever", -1)
                            ]))]),
                            _: 1
                          })
                        ]),
                        default: _withCtx(() => [
                          _createVNode(_component_v_list_item_title, { class: "text-body-2" }, {
                            default: _withCtx(() => [...(_cache[11] || (_cache[11] = [
                              _createTextVNode("清理90天前", -1)
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
              }),
              _createVNode(_component_v_btn, {
                color: "info",
                rounded: "lg",
                onClick: exportLogs,
                text: "导出",
                variant: "tonal",
                size: "small",
                class: "px-4 font-weight-medium"
              }, {
                prepend: _withCtx(() => [
                  _createVNode(_component_v_icon, null, {
                    default: _withCtx(() => [...(_cache[12] || (_cache[12] = [
                      _createTextVNode("mdi-download", -1)
                    ]))]),
                    _: 1
                  })
                ]),
                _: 1
              }),
              _createVNode(_component_v_btn, {
                color: "primary",
                rounded: "lg",
                onClick: notifySwitch,
                text: "配置",
                variant: "outlined",
                size: "small",
                class: "px-4 font-weight-medium bg-white"
              }, {
                prepend: _withCtx(() => [
                  _createVNode(_component_v_icon, null, {
                    default: _withCtx(() => [...(_cache[13] || (_cache[13] = [
                      _createTextVNode("mdi-cog", -1)
                    ]))]),
                    _: 1
                  })
                ]),
                _: 1
              }),
              _createVNode(_component_v_btn, {
                icon: "",
                color: "grey-darken-1",
                variant: "text",
                size: "small",
                onClick: notifyClose,
                class: "bg-white elevation-1 ml-1",
                style: {"border":"1px solid #e0e0e0"}
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_icon, null, {
                    default: _withCtx(() => [...(_cache[14] || (_cache[14] = [
                      _createTextVNode("mdi-close", -1)
                    ]))]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ])
          ]),
          default: _withCtx(() => [
            _createVNode(_component_v_card_title, { class: "text-primary font-weight-bold" }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(title.value), 1)
              ]),
              _: 1
            })
          ]),
          _: 1
        }),
        _createVNode(_component_v_card_text, {
          class: "pa-4 bg-grey-lighten-5",
          style: {"max-height":"75vh","overflow-y":"auto"}
        }, {
          default: _withCtx(() => [
            (error.value)
              ? (_openBlock(), _createBlock(_component_v_alert, {
                  key: 0,
                  type: "error",
                  variant: "tonal",
                  class: "mb-4 border border-error"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(error.value), 1)
                  ]),
                  _: 1
                }))
              : _createCommentVNode("", true),
            (loading.value)
              ? (_openBlock(), _createElementBlock("div", _hoisted_3, [
                  _createVNode(_component_v_skeleton_loader, { type: "list-item-avatar-two-line, list-item-avatar-two-line, list-item-avatar-two-line" })
                ]))
              : (_openBlock(), _createElementBlock("div", _hoisted_4, [
                  (groupedSyncRecords.value && groupedSyncRecords.value.length)
                    ? (_openBlock(), _createElementBlock("div", _hoisted_5, [
                        _createVNode(_component_v_timeline, {
                          density: "compact",
                          side: "end",
                          align: "start"
                        }, {
                          default: _withCtx(() => [
                            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(groupedSyncRecords.value, (group, index) => {
                              return (_openBlock(), _createBlock(_component_v_timeline_item, {
                                key: index,
                                size: "small",
                                "dot-color": getItemColor(group.status),
                                "fill-dot": ""
                              }, {
                                icon: _withCtx(() => [
                                  _createVNode(_component_v_icon, {
                                    size: "14",
                                    color: "white"
                                  }, {
                                    default: _withCtx(() => [
                                      _createTextVNode(_toDisplayString(getItemIcon(group.status)), 1)
                                    ]),
                                    _: 2
                                  }, 1024)
                                ]),
                                default: _withCtx(() => [
                                  _createVNode(_component_v_card, {
                                    variant: "outlined",
                                    class: _normalizeClass(["rounded-lg pa-3 ml-2 shadow-sm bg-white border-opacity-75", group.status === 'error' ? 'border-error' : 'border-success'])
                                  }, {
                                    default: _withCtx(() => [
                                      _createElementVNode("div", _hoisted_6, [
                                        _createElementVNode("div", _hoisted_7, [
                                          _createVNode(_component_v_icon, {
                                            color: getMediaTypeColor(group.media_type),
                                            size: "small",
                                            class: "mr-1"
                                          }, {
                                            default: _withCtx(() => [
                                              _createTextVNode(_toDisplayString(getMediaTypeIcon(group.media_type)), 1)
                                            ]),
                                            _: 2
                                          }, 1032, ["color"]),
                                          _createVNode(_component_v_icon, {
                                            color: getSyncTypeColor(group.sync_type),
                                            size: "small",
                                            class: "mr-2"
                                          }, {
                                            default: _withCtx(() => [
                                              _createTextVNode(_toDisplayString(getSyncTypeIcon(group.sync_type)), 1)
                                            ]),
                                            _: 2
                                          }, 1032, ["color"]),
                                          _createElementVNode("span", _hoisted_8, _toDisplayString(group.media_name), 1)
                                        ]),
                                        _createElementVNode("span", _hoisted_9, _toDisplayString(formatTime(group.timestamp)), 1)
                                      ]),
                                      _createElementVNode("div", _hoisted_10, [
                                        _createVNode(_component_v_chip, {
                                          size: "x-small",
                                          variant: "flat",
                                          color: "grey-lighten-3",
                                          class: "text-grey-darken-3 font-weight-medium"
                                        }, {
                                          default: _withCtx(() => [
                                            _createVNode(_component_v_icon, {
                                              start: "",
                                              size: "x-small"
                                            }, {
                                              default: _withCtx(() => [...(_cache[15] || (_cache[15] = [
                                                _createTextVNode("mdi-account-arrow-right", -1)
                                              ]))]),
                                              _: 1
                                            }),
                                            _createTextVNode(" " + _toDisplayString(group.source_user), 1)
                                          ]),
                                          _: 2
                                        }, 1024),
                                        _createVNode(_component_v_icon, {
                                          size: "x-small",
                                          color: "grey-lighten-1",
                                          class: "mx-1"
                                        }, {
                                          default: _withCtx(() => [...(_cache[16] || (_cache[16] = [
                                            _createTextVNode("mdi-arrow-right-bold", -1)
                                          ]))]),
                                          _: 1
                                        }),
                                        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(group.target_users, (target_user, idx) => {
                                          return (_openBlock(), _createBlock(_component_v_chip, {
                                            key: idx,
                                            size: "x-small",
                                            variant: "flat",
                                            color: group.status === 'error' ? 'error-lighten-4' : 'success-lighten-4',
                                            class: _normalizeClass([group.status === 'error' ? 'text-error' : 'text-success-darken-2', "font-weight-medium mr-1"])
                                          }, {
                                            default: _withCtx(() => [
                                              _createTextVNode(_toDisplayString(target_user), 1)
                                            ]),
                                            _: 2
                                          }, 1032, ["color", "class"]))
                                        }), 128))
                                      ]),
                                      (group.description)
                                        ? (_openBlock(), _createElementBlock("div", _hoisted_11, [
                                            _createVNode(_component_v_icon, {
                                              size: "small",
                                              class: "mr-2",
                                              color: "indigo"
                                            }, {
                                              default: _withCtx(() => [...(_cache[17] || (_cache[17] = [
                                                _createTextVNode("mdi-information-outline", -1)
                                              ]))]),
                                              _: 1
                                            }),
                                            _createTextVNode(" " + _toDisplayString(group.description), 1)
                                          ]))
                                        : _createCommentVNode("", true),
                                      (group.error_message)
                                        ? (_openBlock(), _createElementBlock("div", _hoisted_12, [
                                            _createVNode(_component_v_icon, {
                                              size: "small",
                                              class: "mr-1 mt-n1",
                                              color: "error"
                                            }, {
                                              default: _withCtx(() => [...(_cache[18] || (_cache[18] = [
                                                _createTextVNode("mdi-alert-circle", -1)
                                              ]))]),
                                              _: 1
                                            }),
                                            _createElementVNode("span", null, _toDisplayString(group.error_message), 1)
                                          ]))
                                        : _createCommentVNode("", true)
                                    ]),
                                    _: 2
                                  }, 1032, ["class"])
                                ]),
                                _: 2
                              }, 1032, ["dot-color"]))
                            }), 128))
                          ]),
                          _: 1
                        }),
                        (pagination.value.hasMore)
                          ? (_openBlock(), _createElementBlock("div", _hoisted_13, [
                              _createVNode(_component_v_btn, {
                                color: "primary",
                                variant: "outlined",
                                rounded: "pill",
                                class: "px-6 bg-white",
                                onClick: loadMoreRecords,
                                loading: pagination.value.loading
                              }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_icon, { left: "" }, {
                                    default: _withCtx(() => [...(_cache[19] || (_cache[19] = [
                                      _createTextVNode("mdi-chevron-down", -1)
                                    ]))]),
                                    _: 1
                                  }),
                                  _cache[20] || (_cache[20] = _createTextVNode(" 加载更多历史记录 ", -1))
                                ]),
                                _: 1
                              }, 8, ["loading"])
                            ]))
                          : _createCommentVNode("", true),
                        (pagination.value.total > 0)
                          ? (_openBlock(), _createElementBlock("div", _hoisted_14, " 当前展示 " + _toDisplayString(syncRecords.value.length) + " / " + _toDisplayString(pagination.value.total) + " 条记录 ", 1))
                          : _createCommentVNode("", true)
                      ]))
                    : (_openBlock(), _createElementBlock("div", _hoisted_15, [
                        _createVNode(_component_v_icon, {
                          size: "80",
                          color: "grey-lighten-2",
                          class: "mb-4"
                        }, {
                          default: _withCtx(() => [...(_cache[21] || (_cache[21] = [
                            _createTextVNode("mdi-history", -1)
                          ]))]),
                          _: 1
                        }),
                        _cache[22] || (_cache[22] = _createElementVNode("div", { class: "text-h6 text-grey-darken-1 font-weight-medium" }, "暂无同步记录", -1)),
                        _cache[23] || (_cache[23] = _createElementVNode("div", { class: "text-body-2 text-grey" }, "当配置生效且触发同步后，相关的记录会展示在此处", -1))
                      ]))
                ]))
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
const Page = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-51f66530"]]);

export { Page as default };
