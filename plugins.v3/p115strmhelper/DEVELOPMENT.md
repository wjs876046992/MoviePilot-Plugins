# 115网盘STRM助手 —— 开发说明

本文件记录**本仓相对上游的改动**与其中的设计取舍，避免后续升级上游时把结论丢掉。
上游代码以 `DDSRem-Dev/MoviePilot-Plugins` 为准；本仓在 `v3.4.x` 上做了一轮
「统一媒体库目录映射」改造。

---

## 1. 统一媒体库目录映射（v3.4.0 起）

### 1.1 要解决的问题

上游把路径配置拆在**多个按功能划分的字段**里，同一个媒体库目录要在四处重复填写：

| 场景 | 字段 | 格式 |
|---|---|---|
| 监控 MP 整理 | `transfer_monitor_paths` | `本地#网盘#CD2前缀` |
| 全量同步 | `full_sync_strm_paths` | `本地#网盘#0\|1` |
| 增量同步 | `increment_sync_strm_paths` | `本地#网盘` |
| 监控 115 生活事件 | `monitor_life_paths` | `本地#网盘` |
| API STRM 生成 | `api_strm_config` | `[{local_path, pan_path}]` |
| 媒体服务器路径转换 | `transfer_` / `increment_sync_` / `monitor_life_` / `api_strm_` / `share_strm_mp_mediaserver_paths` | `媒体服务器#MP` |

后果有二：

1. **配置冗余**：新增一个媒体库要在 4~5 个页签各粘一次，漏配任一处就出现
   「某个场景莫名不工作」。
2. **跨插件静默失败**：`Rsync115Sync` 的「补生成 strm」只认助手的
   `full_sync_strm_paths`。用户若只在增量里配了目录，命令发过去被助手拒绝，
   而拒绝提示只发到助手侧 —— 表现为「点了按钮什么也没发生」。

### 1.2 方案：前端统一表 + 双向无损融合（后端 0 改动）

**只改前端**，后端所有 Python 服务（`configer`、`FullSyncStrmHelper`、
`TransferHelper`、`LifeService` …）继续读写原有字段，完全无感。

```
Load：四个 legacy 字符串 ──解析+归一化──▶ Map<local:::remote, item> ──▶ unifiedPaths
                                                        item.enable_transfer/full/inc/life

Save：unifiedPaths ──按勾选条件分发──▶ 四个 legacy 字符串 + api_strm_config + mp_mediaserver
```

**为什么不做后端重构**：`core/config.py` 的字段被 `helper/`、`service/`、`api.py`
共 30+ 处直接读取，重写等于把上游每个版本都变成手工合并。前端方案把耦合面
收缩到一个文件（`usePathManagement.js`），上游改后端时几乎不冲突。

**为什么保留「独立自定义路径」开关**：统一表覆盖 99% 的情况，但仍要允许某个
场景单独配置（例如某个目录只想走全量、绝不走增量）。开关打开后该场景回退到
原字段的自有 ref，其余场景照旧继承。

### 1.3 双向无损融合的关键细节

| 细节 | 处理方式 | 不这么做会怎样 |
|---|---|---|
| **CD2 前缀** | `parseTransferLines` 从 `remote` 里剥离前缀，只留纯网盘路径；序列化时再由 `normalizePathJoin` 拼回一次 | 每保存一次就叠一层 `/115open/115open/...` |
| **全量 `#0`** | 未勾选的行仍写 `${local}#${remote}#0`（不是整行删掉） | 机器人命令按路径匹配会失效；且下次读取时该行凭空消失 |
| **尾斜杠 / 反斜杠** | `normalizePath` 统一转正斜杠、压重复斜杠、去尾斜杠后再做 Map 键 | `/media/strm/TV` 与 `/media/strm/TV/` 被当成两条，重复显示 |
| **空行** | 序列化前过滤掉 local/remote 都为空的行 | 后端配置里出现孤零零的 `#` |

### 1.4 ⚠️ 踩过的坑：Vue watcher 是异步的

**v3.4.0 的首个实现有 bug，v3.4.1 修复。**

```js
// loadConfig() 内
Object.assign(config, data);
reconcileUnifiedPaths();   // ← 此刻 config.* 已有值，但 refs 还是初始空数组
```

`transferPaths` / `fullSyncPaths` 这些 ref 由 `watch(..., { immediate: true })`
填充，而 Vue 的 watcher 默认**下一个 tick** 才跑。于是首版 `reconcile` 读 refs
读到的是空 → 生成一行空白。

**更危险的是它的后果**：用户看到空白后点保存，`syncAllPathsToConfig()` 会拿
这行空白把 `config.full_sync_strm_paths` 覆盖成空串 —— **静默清空配置**。

**修法**：`reconcileUnifiedPaths` 直接解析 `config.*` 的原始字符串，与时序无关。
为此把四种 legacy 格式的解析抽成导出的纯函数
（`parseTransferLines` / `parseFullSyncLines` / `parsePairLines`），
**watcher 与 reconcile 共用同一份**，避免两处规则漂移。

回归测试（`tests/unified_paths.test.js`）里那条
`reconcileUnifiedPaths reads config strings, not the async watcher refs`
**故意不 await nextTick**，就是为了钉住这个场景。

---

## 2. API STRM 场景也接入统一表（v3.4.4）

`api_strm_config` 与 `api_strm_mp_mediaserver_paths` 默认继承 `unifiedPaths` /
`unifiedMpPaths`，与其它场景一致；`customApiStrmPaths` 打开后使用专属配置。
此前该页签仍有一套独立路径输入框，等于把「重复配置」这个问题留在最不常用的
角落里 —— 现在它不再默认展示了。

### 2.1 媒体服务器路径转换的真实定位

它**不是媒体目录映射**，而是容器维度的**路径翻译表**（格式：`媒体服务器路径#MP路径`）：
- **左边** = Emby/Jellyfin 容器内部目录（如 `/mnt/strms`）
- **右边** = MoviePilot 容器内部目录（如 `/media/strms`）
- **何时使用**：仅当调用媒体服务器 API（刷新媒体库 / 提取媒体信息）时，将 MP 本地路径动态替换为 Emby 认得的路径；两端挂载路径一致时直接留空；
- **全场景统一**：v3.4.5 起将 `share_strm_mp_mediaserver_paths` 一并收编进统一映射，整理、增量、生活、API 与分享转存全场景自动单点生效。

---

## 3. 移动端排版约定

配置页在手机上最常被投诉的两件事，各自的根因与规矩：

### 3.1 标签放框外上方，框内只留 placeholder

**不要**给这些路径输入框传 `label=`。

- Vuetify 在 outlined 变体里会把 label 渲染成**两份**（框内一份 + 边框缺口一份），
  缺口宽度由后者决定 → 窄屏上要么豁口、要么把输入区挤窄；
- 路径类输入框的价值全在**横向可见字符数**，框内 label 恰好占用最宝贵的左侧空间。

统一做法：`.stacked-label` div 在框外上方，框内只放 `placeholder` 示例。
与 `Rsync115Sync` 的配置页是同一套取向（见其 `Config.vue` 里 `stacked-label`
那段长注释）。

### 3.2 标签不许纵向折字

复选框 / 开关的 `v-label` 在 flex 容器里会被压到逐字换行（「监控整理」竖着排）。
统一加：

```css
white-space: nowrap !important;
word-break: keep-all !important;
```

并给控件本身 `flex: 0 0 auto`，让它们不被压缩。

### 3.3 一行放不下就整行换行，不要硬挤

`sm=` 断点让两列在 ≥600px 并排；605px 以下各占 `cols="12"` 独占整行。
**不要**用 `d-flex` + `flex-grow-1` 强行让两个输入框同处一行 ——
窄屏下会被压到只剩几像素，看起来就是「输入框消失了」。

### 3.4 继承提示条的对齐

`.inheritance-banner` 里左侧是说明 + 跳转按钮，右侧只有开关。
开关容器必须 `align-items: center` 且限高，否则在 `flex-wrap` 生效后
容易跑出基线、看起来「错位」。

---

## 4. 生活事件合并通知列出具体文件（v3.4.7）

### 4.1 要解决的问题

生活事件的合并推送原本只有一行正文：

```
✅【115网盘】生活事件生成 STRM 文件

📄 生成STRM文件 1 个
```

N=1 时用户既不知道是哪个文件，也无法判断这次事件是不是自己在等的那个 ——
只能再去翻 `moviepilot.log` 或插件日志。用户的原话是「这是通知，能具体到是哪个文件吗」。

### 4.2 计数与展示分离

生活事件里的**目录事件**（整季上传、整个目录复制）会一次展开上千个文件。两条极端
都不行：全列会撑爆消息渠道，只列前几条又会让「N 个」这个数字失真。

因此把两件事拆开：

| 关注点 | 行为 |
|---|---|
| 计数 | **照常累加**，`📄 生成STRM文件 500 个` 永远是真实数量 |
| 展示 | 路径只保留前 `_NOTIFICATION_ITEM_LIMIT`（默认 10）条，其余折成 `... 还有 490 个` |

上限是 `MonitorLife._NOTIFICATION_ITEM_LIMIT`（`helper/life/client.py`），
调一个数即可；设为 0 时只剩数量与汇总行，计数不会丢。

### 4.3 ⚠️ 踩过的坑：先发送再重置会吞掉事件

原实现是「取计数 → 发送 → 计数器归零」。发送是同步 HTTP 调用，可能耗时几百毫秒到
几秒；这期间如果恰好有新事件进来并累加计数器，**归零会把它一起抹掉** ——
那次事件不推送、不留痕，属于一类只在高并发生活事件下才偶发的静默丢失。

现实现改为：

```python
batch = self._monitor_life_notification_batch          # 先摘下当前批次
self._monitor_life_notification_batch = NotificationBatch(...)  # 立刻换新批次
if not batch.empty:
    post_message(...)                                  # 再发送，发送期间的累加落进新批次
```

这条时序约束由 `_send_notification` 的注释固定下来，改动时不要退回「先发送后重置」。

### 4.4 代码组织

计数与渲染抽到 `helper/life/notification.py` 的 `NotificationBatch`：

- **只依赖标准库**（`pathlib` / `typing`），因此可以在没有 MoviePilot 后端的环境下
  直接单测 —— 这是 `Client.py` 里加方法做不到的（导入即触发 `app.*`）。
- `add(bucket, paths, count=None)` 一次追加一批（目录事件用），
  `add_one(...)` 追加单个（文件事件用）；`count` 可大于 `len(paths)`，
  用来表达「处理了 500 个，但只收集到 10 条路径」。
- `render()` 负责小标题 / 缩进文件行 / 省略行，`empty` 供调用方提前跳过推送。

`MonitorLife` 侧只保留两类调用点：目录分支在遍历时把前 10 条路径收进 `strm_paths` /
`mediainfo_paths`，遍历结束一次性 `add(..., count=总数)`；文件分支直接 `add_one(...)`。

### 4.5 测试

`tests/v3/p115strmhelper/test_life_notification.py`（7 条，`--noconftest` 可跑）：

| 用例 | 保护的东西 |
|---|---|
| `test_single_file_is_listed_by_path` | 单个文件时正文带完整路径，不只报数量 |
| `test_items_over_limit_are_summarised` | 超限只列前 N 条，省略数量准确 |
| `test_bulk_count_can_exceed_listed_paths` | 批量场景 `count` > 路径数时，汇总行按 `count` 算 |
| `test_limit_of_zero_still_counts` | 上限为 0 时不丢计数 |
| `test_unknown_bucket_is_rejected` | 未知类别报错，不静默丢弃 |

---

## 5. 测试

前端逻辑有 Node 原生测试（不依赖 MoviePilot 后端，可直接跑）：

```bash
npm test --prefix plugins.v3/p115strmhelper
```

覆盖点：

| 测试 | 保护的东西 |
|---|---|
| `reconcileUnifiedPaths merges symmetrical paths…` | 四场景全配同一目录 → 合并成 1 行、4 个开关全亮 |
| `reconcileUnifiedPaths merges asymmetrical paths losslessly` | 只在部分场景出现的目录不被丢弃；`#0` 正确映射为「不参与」 |
| `syncAllPathsToConfig serializes correctly…` | 各字段格式逐字正确（含 CD2 前缀拼回、`#0`/`#1`） |
| `save after load must not wipe existing paths` | 读→写往返不丢字符（1.4 那个 bug 的后果断言） |
| `reconcileUnifiedPaths reads config strings, not the async watcher refs` | 1.4 的时序 bug 不复发 |
| `parse helpers honor the legacy field formats` | 三个纯函数的格式契约 |
| `defaults API STRM paths to unified mapping` / `respects customApiStrmPaths override` | API 场景的继承与逃生 |

注意：`plugins.v3/p115strmhelper/tests/` 下的 Python 测试需要 MoviePilot 后端才能跑，
与前端这套 Node 测试是两条独立的线。
