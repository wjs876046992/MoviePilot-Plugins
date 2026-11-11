# 动态企微可信IP（DynamicWeChat）V3 版开发记录

## 3.0.2 V2 → V3 代际迁移

### 为什么迁

fork 侧的 v3.0.0/3.0.1/3.0.2（通知系统重构、固定可信IP、合入上游 DDNS 域名模式
与 2.1.9 Cookie 校验）从一开始就是**为 V3 准备的版本号**，只是被叠加到了
`plugins.v2/dynamicwechat/`。V3 宿主靠「无 `package.v3.json` 条目 → 回退 legacy
索引」的兼容机制加载这份 V2 实现，可以跑但不是正式合同，且每次同步上游都会与
上游对同一文件的修改冲突。

本轮把位置摆正：**V2 目录整体回滚上游 2.1.9**（`__init__.py`/`helper.py` 与
`package.v2.json` 条目、`package.json` V1 条目），**V3 目录接 3.0.2**
（`plugin_version`、索引版本、history 首项均为 3.0.2，history 保留
v3.0.2/3.0.1/3.0.0）。相对 V2 的 2.1.9，3.0.2 正好是主版本跃迁 ——
`_check_v3_release_contract` 按 `package.v2.json` 算出 expected_major=3，
曾误按「V2 3.0.2 → V3 4.0.0」做过一版，4.0.0 会被门禁直接拒绝。

### 迁移决策与核实过的宿主事实（v3 分支源码，2026-11-10）

逐条从 `jxxghp/MoviePilot` v3 分支源码核实后才写导入，没有猜：

| 事实 | 结论 |
|---|---|
| `app/sdk/events.py` 导出 `eventmanager`、`Event` | `from app.sdk.events import eventmanager, Event` |
| `EventType` 不在 `app.sdk.events`，官方 V3 插件（autosignin）从 `app.schemas.types` 取 | 同样处理 |
| `NotificationType` 在 V3 已删除，compat manifest 将其别名到 `app.schemas.types.MessageType`，且 `MessageType.Plugin` 存在 | 全部 4 处 `NotificationType.Plugin` → `MessageType.Plugin` |
| `MessageChannel` 别名到 `NotificationChannel`，但本插件只 import 未使用 | 直接删除 |
| `CookieCloudHelper` V3 物理位置 `app.adapters.external.cookiecloud`；`app.helper.cookiecloud` 只是登记的兼容别名，新代码不进 baseline | 直接导入物理路径 |
| `CookieCloudHelper.download()` V3 返回 `(dict|None, str)` 元组 | 与 V2 现有的 tuple 兼容解析一致，无需改 |
| `_PluginBase` V3 合同在 `app.sdk.plugin`（惰性导出）；`post_message(channel, mtype=MessageType, ...)`、`systemmessage`、`update_config/save_data/get_data/get_data_path` 签名兼容 | `from app.sdk.plugin import _PluginBase` |
| settings 属性 `TZ/NGINX_PORT/COOKIECLOUD_*/VERSION_FLAG` 都在 v3 runtime config | 无需改 |
| `cloakbrowser` 0.7.2 为纯 Python wheel（`py3-none-any`，requires-python>=3.9） | 可声明依赖，无 cp314t 障碍；但依赖 `playwright<1.65`，与宿主 playwright 共存性由依赖安装门禁验证 |

### 被否决的方案

- **改用 `app.sdk.browser`（PlaywrightHelper）替代 CloakBrowser**：会改变登录
  流程行为（CloakBrowser 的核心价值是反爬指纹），属于大改而非迁移，明确不做。
- **顺带修复两个已知缺陷**（① `ChangeIP` 检出二维码时未置 `_cookie_valid=False`，
  与另一分支不一致；② `_push_qr_code_async` 的 `if self._my_send:` 守卫挡住
  「只开 MP 内置通知」用户的二维码推送）：用户拍板本轮纯迁移不顺带修，
  已记录为后续待办。**迁移后的 diff 只含合同变更，便于审计。**
- **迁移 `UpdateWeChatIp`**：范围决定为一次只迁一个；它依赖宿主消息能力
  接口（`ChannelCapability`），V3 适配面更大，另起一轮。

### 刻意保留

- `plugins.v2/dynamicwechat/` 与 `plugins/dynamicwechat/` 原样未动，仅索引加
  `"v3": false` 阻断 V3 回退；V1 副本（Playwright 同步版 1.7.3）继续服务旧宿主。
- `src/UpdateHelp.py`（Cryptodome 版死代码，V3 目录不含它）在 V2 目录里仍保留，
  虽无引用但属上游原始结构，不在迁移里清理。

### 测试

`tests/v3/dynamicwechat/test_v3_contract.py`（19 项，`--noconftest` 可跑，
依赖注入 `requests/aiohttp/pycryptodome`）：

- 代际合同（AST 静态扫描，不导入宿主）：禁止 `app.core/app.helper/app.log/app.utils`
  前缀导入；必须经 `app.sdk.config/events/logging/plugin` 与
  `app.adapters.external.cookiecloud`；源码不得再出现 `NotificationType`/
  `MessageChannel`；版本三元组（plugin_version/index version/history 首项）=
  3.0.2；V1/V2 索引条目 `v3: false`；V3 目录无 `UpdateHelp.py`；pyproject 合同。
- 纯逻辑：`MySender` 渠道识别（ServerChan/PushPlus/IYUU/多通道/quiet 标志）、
  `IpLocationParser` 去重限量（注意：`add_ips` 语义是**新 IP 在前**，`new + current`，
  测试初版按「旧在前」断言失败后修正——这是 V2 以来的既有行为，未改）、
  `JsonFieldManager` 读改写。

已知边界：`_merge_pinned_ips`、`check_login_status` 三态等插件类方法依赖宿主
`_PluginBase`，后端无关测试覆盖不到，由真机验证兜底。`scripts/check_v3_imports.py`
导入门禁本机无后端跑不了，其口径已由合同测试的同前缀静态检查等效覆盖。

### 真机验证清单（交付后）

- [ ] V3 宿主加载日志出现 `加载插件：DynamicWeChat 版本：3.0.2`
- [ ] 配置页五组控件齐全、详情页二维码/Cookie寿命/测试通知按钮正常
- [ ] 一轮保活（10 分钟 cron）与一轮 IP 检测日志无异常
- [ ] DEBUG=true 下无旧导入告警

---

## 3.1.0 页面重设计（详情页 + 配置页）

### 问题

用户认为两个页面设计不合理。需求分析（见同目录 REDESIGN_REQUIREMENTS.md，P1–P11
逐条带行号证据）确认：后端早已区分的运行时状态（登录三态、两个独立循环、验证码
等待、通知通道识别结果）在页面上完全不可见，且现有两处信息还挂错了条件。

#### 症状最重的三个

1. **Cookie 失效红条挂错对象**：整条 gated 在 `_is_special_upload and _enabled`
   上，而该标志只在扫码登录/CookieCloud 写回成功时为 True——Cookie 失效时
   （最需要红条的时刻）红条整个消失。这是 Plugin_Dev_Workflow §1.5 点名的
   「提示嵌在被推到极端就消失的条件下」反例。
2. **「IP变动后通知」开关静默消失**：未配第三方 Token 时开关不渲染，且
   init_plugin 会静默把它复位 False——「看起来开了、保存后没了」。
3. **通知 Token placeholder 教用户填无效内容**：写「支持微信、Server酱、
   PushPlus、AnPush」，但 MySender 只识别 sct 前缀/IYUU/其余按 PushPlus——
   微信与 AnPush 填了根本不被识别。

#### 误判记录

初版快照用 `_is_special_upload` 判「是否曾经登录过」，页面形状测试立刻抓出：
「登录过但 Cookie 已失效」会被误判成「从未登录」（`_is_special_upload` 失效后
被重置）。修正为 `_is_special_upload or _saved_cookie or _cookie_lifetime>0`
三条件或——**单标志不足以表达「曾经登录」，测试先行抓住了这个设计漏洞。**

### 做法

- 新增 `_page_snapshot()`：只读汇总状态矩阵所需全部字段，`get_page` 消费；
  不改任何写路径。`get_page` 改为纯渲染（去掉渲染中 `_qr_code_image = None`
  的写副作用，测试断言连续两次调用不改变实例状态）。
- 详情页：五组状态条（总开关/Cookie 登录态/保活循环/IP 检测循环/验证码等待）
  + 二维码三态分离（无任务灰/过期黄/有效绿，文案互不相同）。
- 配置页四区重排（基础/IP来源/通知/高级）；`await_ip` 恒显示，缺前置时其上
  方插橙色 VAlert 警示「保存后会被自动关闭」；测试按钮从详情页移入通知区；
  placeholder 只写真实支持的渠道并紧邻说明 `||`/`||Q`；删除底部两条游离 VAlert。
- 魔法语法拆字段（用户拍板）：`||wanN` → `wan_enabled` 开关 + `wan_max_ips`
  数字框；`ids||url1,url2` → `custom_ip_urls` 列表框。`_migrate_legacy_magic_strings()`
  在 init_plugin 读配置后做一次幂等迁移，旧语法兼容解析一轮。
- 必填项缺失（应用ID/检测周期）在启用时发 systemmessage 站内提示，不再只写日志。

### 否决的方案

- **验证码做成详情页输入框**：需新端点与新交互路径，用户拍板本轮只做「等待
  状态可见」，提交仍走企微消息/`/wxcode`。
- **get_render_mode 改 Vue**：vuetify JSON 表单已够表达状态矩阵，改 Vue 引入
  构建链与联邦 CSS 负担，收益不成比例。
- **实时轮询刷新详情页**：宿主按需快照渲染，维持现状。

### 边界

- MP 内置通知的「失败态」页面无法表达：宿主 `post_message` 契约返回 None、
  失败不上报。文案如实写「是否送达本页无法查询，可用测试按钮验证」，
  不编造「发送成功」。
- 状态条是进入详情页时的快照，不轮询——「上次结果」字段由后台流程在流程末尾
  写入，刷新页面即见最新。
- 两个已知缺陷（ChangeIP 二维码分支、_push_qr_code_async 守卫）仍未修：
  页面如实显示其后果，行为修复另行一轮。

### 测试

`tests/v3/dynamicwechat/test_page_shape.py` 11 项（--noconftest）：以
textwrap.dedent 切出 `get_page`/`_page_snapshot`/`_migrate_legacy_magic_strings`
源码在 stub 命名空间 exec，object 级 stub 实例调用，逐条断言 REDESIGN_REQUIREMENTS
验收标准 1–8、10 + 迁移逻辑（多WAN/自定义URL/幂等/无后缀不动）。
contract 测试的版本三元组断言同步到 3.1.0。
页面形状测试过程中抓出两处真问题（见误判记录），证明这套测试有效。

---

## 3.1.1 评审修复（impeccable critique 驱动）

### 问题

对 v3.1.0 页面跑了一次双通道设计评审（独立设计评审 + 机械事实核查并行，互不可见
对方输出）。总分 25/40。机械核查给出三个 LLM 评审抓不到的硬事实：`ddns_ok` 是
7 组状态字段中唯一只有 1 个渲染分支的；`_page_snapshot` 有 14 个 key 设而未用
（其中 `pinned_valid/pinned_count/ddns_ip_masked` 是需求矩阵承诺过却没落地的）；
颜色/端点/文案红线全部零违规。

### 最有价值的发现（P0）

应用ID 的 label 写「不要填 100000x 开头」，占位符却是 `如 1000002,1000003`——
恰好是被运行期校验拒绝的格式。组合上顶部绿条（判据只是字段非空）与校验只写
logger，用户照页面指引填完会看到绿色「后台任务运行中」而实际什么都没发生。
**照页面指引操作必然失败**是设计缺陷里最坏的一类，修复却只值一行占位符加一条
站内提示。

### 修复清单（用户拍板：先修静默失败链，全部问题都修，死字段补渲染）

- **P0**：占位符改 `如 1021042,1052986`；`init_plugin` 检测 100000x 命中时发
  systemmessage（此前只写日志）
- **P0 关联**：顶部绿条改绑定 `keepalive_ok`——校验失败显示红条「任务在跑，
  可信IP不会更新」，None 且 note 空显示灰条「等待第一轮校验结果」
- **P1**：keepalive `ok=None` 区分两种含义（note 非空→橙条「保活校验无结论：
  {转译原因}」，note 空→灰条「还没跑过第一轮」）。此前网络故障中间态被显示成
  「还没跑过」，用户会在错误方向重试
- **P1**：配置页四区加 `_section_title()` 区标题条（vuetify JSON 表单模式下
  唯一可用的视觉分组手段）——上轮四区只存在于代码注释
- **P2**：详情页补 DDNS 正常态（绿：解析到 XX）与 pinned 状态条（绿：N 个/
  橙：格式不对会被忽略），消费此前 14 个死字段中的 3 个
- **P3**：一次性开关 label 补「保存后执行一次并自动复位」
- **Minor**：pinned 占位符改真实 IP 示例（203.0.113.x 文档保留段）；通道识别
  alert 说明「保存后更新」；Cookie 失效红条补影响面（「失效期间公网IP一旦变化，
  通知将发送失败」）；二维码黄条拆「运行中未出码」与「已过期」两态、全部补
  「请刷新本页」指引（快照渲染的盲等问题）；「6秒可见」改为「需刷新本页」
  （6 秒数字本无出处）；`captcha_component or {}` 改条件展开

### 测试

页面形状测试从 30 项扩到 36 项，新增 6 条评审回归：keepalive 两 None 区分、
绿条绑定校验（校验失败时不得出现「后台任务运行中」）、DDNS/pinned 正常态渲染、
区标题存在、占位符不含 100000x、一次性开关声明复位。既有 QR 三态测试同步更新
（黄条拆两态后断言「运行中」条必须含「刷新」）。

### 未做（有意）

- 「立即扫码/立即检测」按钮、验证码页面输入：交互升级，维持上轮决定另起一轮
- `cookie_header` 输入框：Alex 诉求，但属于新功能而非修复
- 14 个死字段中未消费的 11 个（cc_*、wan_mode、third_channels 等）：对应状态
  在配置页已有表达（CookieCloud 开关在高级区、通道识别 alert 在通知区），
  详情页重复展示违反「同一状态一个信息源」；保留快照字段供后续轮使用
