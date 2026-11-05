# 开发日志

本文档记录插件开发与维护过程中的关键变更，供后续参考。

---

## 2026-11-05

**分支：** `main`
**涉及插件：** P115StrmHelper

### P115StrmHelper（`plugins.v3/p115strmhelper/`）

**版本：** v3.3.0 → v3.4.5（本仓改动，未同步上游）

**提交：** `9f1fe2c` → `b75a3f1` → `b3614f2` → `855df37` → `ab868d5` → `待提交`

#### 统一媒体库目录映射

上游把路径配置按功能拆成 `transfer_monitor_paths` / `full_sync_strm_paths` /
`increment_sync_strm_paths` / `monitor_life_paths` / `api_strm_config` /
`share_strm_mp_mediaserver_paths` 等多个字段，
同一个媒体库目录要在 4~5 个页签重复填写。除了配置冗余，还导致跨插件静默失败：
`Rsync115Sync` 的「补生成 strm」只认助手的 `full_sync_strm_paths`，用户只在增量里
配过目录时命令会被助手拒绝，而拒绝提示只发到助手侧，表现为「点了按钮没反应」。

采用**前端统一表 + 双向无损融合**，后端 Python 代码零改动：

- Load：解析五个 legacy 字符串 → 路径归一化 → 按 `local:::remote` 并集聚合为
  `unifiedPaths`，还原每个目录在四个场景的启用状态；
- Save：按勾选条件分发回原字段，CD2 前缀只拼一次，全量未勾选仍写 `#0` 保留命令匹配；
- 媒体服务器路径转换（容器映射翻译）：集中维护 Emby ⇄ MoviePilot 路径映射，统一分发至整理、增量、生活、API 与分享转存全场景；
- 各场景页签保留「独立自定义路径」开关作为逃生通道。

#### v3.4.1 修掉的一个会清空配置的 bug

首版在 `loadConfig()` 里 `Object.assign(config, data)` 之后**同步**调用聚合函数，
而它读的是由异步 watcher 填充的 refs —— 那一瞬间 refs 还是空数组，已有配置被读成
「一行空白」。用户若此时点保存，会把 `full_sync_strm_paths` 等字段覆盖成空串。

修法：聚合改为直接解析 `config.*` 原始字符串，与时序无关；四种格式的解析抽成
纯函数由 watcher 与聚合共用。回归测试里那条用例**故意不 await nextTick**，
以此钉住该场景。

#### 移动端排版

- 路径输入框一律去掉 `label=`，改为框外 `.stacked-label` + 框内 `placeholder`，
  把横向空间全部让给路径文本；
- 复选框 / 开关标签强制 `nowrap` + `keep-all`，消除「一行一个字」的纵向折字；
- 窄屏下两列路径改为各占整行，不再用 flex 硬挤（挤压后输入框会缩到看不见）；
- 继承提示条统一垂直居中，修复开关错位。

#### 小结（可复用的结论）

1. **Vue watcher 是异步的** —— 在 `Object.assign` 之后同步读取由 watcher 派生的
   状态，读到的一定是旧值。要么改读源数据，要么 `await nextTick()`。
2. **"渲染出来再藏掉" vs "让它压根不渲染"** —— 与同仓 `Rsync115Sync` 的结论一致：
   后者稳。不给 `label` 就不会有 Vuetify 的双份 label 与边框缺口问题。
3. 改动集中在 `src/components/composables/usePathManagement.js`，上游升级后端时冲突面最小。

详细设计与测试说明见 `plugins.v3/p115strmhelper/DEVELOPMENT.md`。

---

## 2026-09-14

**提交：** `cd159e7`  
**分支：** `main`  
**涉及插件：** DynamicWeChat、WatchSync

---

### DynamicWeChat（`plugins.v2/dynamicwechat/`）

**版本：** v2.1.8 → v3.0.0

#### 通知系统重构

旧架构中，微信通知与第三方通知耦合在 `MySender` 内部，通过 `_wechat_available` 标志控制降级。新架构将两者解耦：

- **MP 内置通知**：通过 `post_message` 发送，由 MoviePilot 管理所有已配置渠道（微信、Telegram 等），由 `use_mp_notify` 配置项控制
- **第三方通知**：通过 `MySender` 发送（Server酱、PushPlus、IYUU 等），由 `notification_token` 配置项控制
- 两种通知独立并行，互不影响

核心变更：
- 移除 `_wechat_available` 标志和 `_send_wechat` / `_send_v2_wechat` 方法
- `MySender.__init__` 不再接收 `func` 参数，仅负责第三方通道
- 所有通知点（cookie 失效、二维码推送、IP 变更、测试通知）统一为双通道模式
- 修复 `change_ip` 中仍调用已删除的 `diy_channel="WeChat"` 问题

#### 新增配置项

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `use_mp_notify` | 是否使用 MP 内置通知 | `True` |
| `pinned_ips` | 固定可信IP，始终保留在可信IP列表中 | `""` |

`pinned_ips` 与检测到的IP通过 `_merge_pinned_ips()` 合并去重后填入企微应用。

#### 缺陷修复

- **`parse_cookie_header` 空值防御**：旧代码对空字符串、无 `=` 字段做了跳过处理，重构时误删。补回 `if not cookie_header: return []` 和 `if '=' not in item: continue`
- **CookieCloud 返回格式兼容**：适配 `download()` 返回 tuple 和非 tuple 两种情况
- **日志级别**：8 处 `debug` → `info` 误提升已恢复（后台循环、扫码等待、任务取消等正常流程）

#### 测试通知功能

详情页新增"测试通知推送"按钮，通过 `GET /test_notify` API 端点触发，同时测试 MP 内置通知和所有第三方通道，返回成功/失败计数。

---

### WatchSync（`plugins.v2/watchsync/`，新增）

**版本：** v3.0.0

#### 功能概述

Emby/极影视观看记录跨用户同步插件。当组内某用户播放、收藏或标记媒体时，自动同步到组内其他用户。

#### 支持的同步类型

| 事件 | 同步内容 |
|------|----------|
| `playback.pause` / `playback.stop` | 播放进度（PositionTicks） |
| `user.favorite` / `item.favorite` / `item.rate` | 收藏状态 |
| `playback.scrobble` / `item.markplayed` | 标记已播放 |
| `item.markunplayed` | 标记未播放 |

#### 片尾自动标记已播放

问题：`playback.stop`/`playback.pause` 在片尾触发时仅同步进度，不标记已播放。依赖 `playback.scrobble` 但该事件在部分 Emby 配置下不触发。

修复：在 `_handle_playback_event` 中检测 `position_ticks >= RunTimeTicks * 0.9`，满足时额外调用 `_sync_played_status_to_targets` 标记目标为已播放。

#### 极影视支持

- 通过 `ModuleManager` 获取 Emby/ZSpace 服务器实例
- 自动发现本机极影视：读取 `/zvideo/zvideo.db` 获取凭证，探测 8021 端口
- `LocalZSpaceInstance`：极影视 Emby 兼容层封装，支持 `get_data` / `post_data`
- 极影视源端进度轮询：`BackgroundScheduler` 定时拉取继续观看列表，检测变化后触发同步

#### 防循环机制

`SyncLoopProtector`：同步操作成功后，将目标用户-媒体-操作类型加入保护缓存（TTL 30秒）。短时间内收到的回弹事件自动跳过。

#### 代码质量修复（Review 后）

- 删除 `_add_to_ignore_cache` 死代码（引用未初始化的 `_sync_ignore_cache`）
- `_init_database()` 从 `__init__` 移至 `init_plugin`，避免 `PLUGIN_DATA_PATH` 未就绪
- 约 80 处 `logger.info` 降为 `logger.debug`（匹配过程、API 详情、属性检查）
- 删除不应提交的 `yarn.lock`

---

### CLAUDE.md

新增 Claude Code 仓库指引文档，覆盖：

- 仓库定位（MoviePilot 插件仓库，非独立运行时）
- 三代目录布局（plugins / plugins.v2 / plugins.v3）
- V3 插件结构与命名规则
- 测试命令（全量、分代、单插件）
- 测试规范（目录位置、导入风格、pytest 风格）
- 开发规则（SDK 导入、版本一致性、依赖管理）
- CI 门禁（版本门禁、测试门禁、依赖安装门禁）
- 文档索引

---

### 代码审查要点备忘

本次 Review 发现的典型问题，后续开发中注意避免：

1. **版本号一致性**：`plugin_version`、`package.json` 的 `version`、`history` 最新三处必须一致
2. **日志级别**：中间匹配过程、API 详情、属性检查用 `debug`；实际操作结果、状态变更用 `info`
3. **删除方法后检查调用点**：`_send_wechat` 删除后，`change_ip` 中的 `diy_channel="WeChat"` 调用未同步清理
4. **属性初始化**：引用 `self.xxx` 前确保 `__init__` 中已初始化
5. **防御性编程**：`cookie_header.split()` 等链式调用前检查空值
6. **`__init__` 中避免副作用**：数据库初始化等依赖运行时配置的操作放到 `init_plugin`
7. **不提交构建产物**：`yarn.lock`、`node_modules` 等不应进入插件目录
