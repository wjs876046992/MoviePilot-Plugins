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

---

## 3.1.2 配置页卡片式布局

### 问题

v3.1.1 后用户反馈四点不满：开关行太拥挤（「保存后执行一次并自动复位」长说明挤在
开关 label 里）；分区视觉层级弱（区标题条与字段行扫视节奏乱）；想要卡片式分组；
扫码流程感觉绕（入口埋在基础区的开关里）。

### 做法

`get_form` 重写为 VCard 卡片分区，参照 `tunnelyield` 的 `section()` 模式（宿主对
get_form 内 VCard 有一等支持，已在本仓多个插件验证）。五张卡：

| 卡 | 内容 | 布局变化 |
|---|---|---|
| 基础 | 三开关 + 触发器说明 alert + cron/应用ID | 触发器说明从开关 label 移出为独立 alert，开关行变短 |
| 扫码登录 | local_scan 开关 + 运行中警示 | **从基础区独立成卡**——它是「首次使用的第二个动作」，不该混在开关行里 |
| IP 来源 | 优先级 alert + DDNS/多WAN/自定义URL | 保持 |
| 通知 | 双开关 + 测试按钮 + Token + 识别结果 | 保持 |
| 高级 | CookieCloud + 固定可信IP | 保持 |

每张卡结构：`VCard(outlined) > VCardText > [标题 div(text-subtitle-1) + 副标题
div(text-caption) + 字段行]`，副标题用一句「这区是干嘛的」，替代此前的区标题条。

### 边界

- 分区手段从 VAlert 标题条换成 VCard：卡片有边框和留白，视觉分组比色条强；
  副标题承载了原区标题条里的说明，无信息损失。
- 形状测试两条断言同步更新（区标题改为卡片断言；「自动复位」语义改为断言
  「触发器」说明存在）。扫描测试时曾把整个文件写坏一次（shell heredoc 转义
  `\n` 成字面量），`git checkout` 恢复后改用临时文件 + Python 定位替换——
  **大段替换源码不要经过 shell 字符串，直接文件读写**。

---

## 3.1.3 多 DDNS 域名 + 布局微调

### 问题（用户反馈三条）

1. 「固定可信IP」放在【高级】卡不合理
2. DDNS 只支持单个域名；多线路（家庭宽带 + 备用）需要多个
3. 多WAN 的开关与出口数量输入框 6+6 并排，挤在一起不好看

### 做法

- **多域名**：新增 `resolve_domains()`，把配置按英文/中文逗号切开，**逐个解析后合并去重**
  （分号拼接）。用户明确选择「所有域名都解析、合并成多 IP」而不是「第一个成功者胜」——
  多线路场景需要把每个出口都写进可信白名单。部分失败不影响其余；全部失败才判失败，
  且 `click_app_management_buttons` 里**不静默回退到其他来源**（避免写错 IP）。
  `CheckIP` 与 `click_app_management_buttons` 两处消费点都改为多域名。
- **固定可信IP**：从【高级】移到【IP来源】卡，排在 DDNS/多WAN/自定义URL 之后，
  并在卡副标题里说明「检测来源按优先级只取一个，固定可信IP始终额外保留」——
  因为它不是“检测来源”，而是“额外常量”，放进同一卡需要这层区分。
- **多WAN 行**：开关 `_col(4)` + 数量框 `_col(8)`，label 补「仅在开启多WAN时生效」。

### 边界

- 域名解析仍用 `socket.gethostbyname`（IPv4 单条）。同一域名若同时有 A/AAAA 记录，
  只取 IPv4——企微可信IP本身只接受 IPv4。
- 去重是「保留首次出现顺序」的稳定去重，便于日志与详情页对比。
- 详情页 DDNS 条改为报告「N 个域名解析到 IP 列表」，失败文案改为「全部解析失败」。

### 测试

形状测试 36→40 项：`resolve_domains` 五组用例（合并/去重/部分失败/全失败/中英文逗号+空串）、
pinned 位置断言（IP来源卡 < pinned < 高级卡）、多WAN 4/8 列布局断言、DDNS 多域名文案断言。

---

## 3.1.4 详情页卡片式布局

### 做法

`get_page` 重写为三张 VCard，与配置页 3.1.2 的 `_card` 同构（标题 + text-caption
副标题 + 内容行）：

| 卡 | 内容 |
|---|---|
| 运行状态 | 插件总开关（绑定 keepalive 实际结果）/ Cookie 登录态五态 / 保活循环 / IP 检测循环 |
| IP 来源 | DDNS 三态 / 固定可信IP 两态 / 当前模式+当前可信IP 汇总行（新增） |
| 扫码登录 | 二维码状态条 + 图片/占位 + 验证码等待条（等待时才显示） |

**状态条文案、四态语义、配色全部不变**——只动布局不动状态逻辑（3.1.1 评审已打磨过）。
卡片视觉语言与配置页统一后，用户在两个页面间切换时「标题 → 副标题 → 内容」的扫视
模式一致。

新增「当前模式 + 当前可信IP」汇总行：mode 判定为 多WAN > DDNS > 公网探测，与
CheckIP 的实际优先级一致。

### 测试

形状测试 40→42 项：三卡标题断言、卡片包裹后 `_banner_texts` 递归收集回归
（保证既有 40 项状态断言在卡片结构下依然生效）。

---

## 3.1.5 CookieCloud 覆盖式写入缺陷（严重）

### 症状

用户反馈「开了 CookieCloud，重启插件后 Cookie 仍然失效」。真机日志每 10 分钟一轮：
```
15:30:02 开始从 CookieCloud 获取 Cookie
15:30:09 CookieCloud Cookie失效，发送通知
```

### 根因（真机解密证实）

解密 `/config/cookies/<uuid>.json` 后发现，`work.weixin.qq.com` 域里**只剩 2 个
边缘 cookie**：

```
[.work.weixin.qq.com]  cookie 数量=2  名称=['wwrtx.c_gdpr', 'ww_lang']
```

登录凭证 `wwrtx.sid` 不见了。原因是 `helper.update_cookie` 的实现：

```python
cookie = {'cookie_data': formatted_cookies}   # 只有 work.weixin.qq.com 一个域
requests.post(self.url + '/update', ...)      # /update 是整体替换语义
```

两个后果：
1. **清空了其它所有站点**的 Cookie（那次解密看到 700 个域名，其中 699 个本应
   由 MoviePilot 的站点同步维护，会被插件写操作覆盖掉）
2. 企微域只写入了浏览器当时采到的子集，后续再写一次不完整的数据就会把
   `wwrtx.sid` 覆盖没

**不是别的浏览器配置覆盖了它，是插件自己覆盖了整个 CookieCloud。**

### 做法（三项，用户拍板全做）

1. **读-合并-写**：新增 `decrypt()` 与 `PyCookieCloud.download_raw()`；`update_cookie`
   先取全量、移除所有 `*weixin*` 域、只写回企微组。**拿不到全量时直接拒绝写入**
   （宁可这轮不更新，也不能清空别人的 Cookie）。
2. **回读校验**：写入成功后立刻 `download_raw()` 检查 `wwrtx.sid` 是否存在，
   不存在则报错并标记上传失败——避免「接口返回 done 但内容不对」的静默失败。
3. **本地落盘兜底**：`get_data_path()/cookie.json`（权限 600），只存 weixin 相关域；
   读取顺序改为 内存 → 本地落盘 → CookieCloud，重启后不再完全依赖云端。

`PyCookieCloud` 新增 `local_dir` 构造参数（内建 CookieCloud 的数据目录），
让 helper 保持纯逻辑、不直接依赖宿主 `app.sdk.config`。

### 边界

- 合并时按 `"weixin" in domain.lower()` 删除旧组，因此 `mac.weixin.qq.com`
  （微信客户端相关）也会被一并替换——它不由本插件维护，但同属企微生态，
  保留旧值反而可能残留过期凭证。
- 落盘只存 weixin 域，不把浏览器里的其它站点 Cookie 抄一份到插件数据目录。
- **此前被清空的其它站点 Cookie 需要用户重新同步一次**（MoviePilot 的站点同步
  任务会补回，日志已见 `CookieCloud同步成功`）。

### 测试

新增 `tests/v3/dynamicwechat/test_cookie_persistence.py` 7 项：加解密往返、
错误密钥不还原明文、**合并写入保留其它站点**、**无全量时拒绝写入**、落盘/读回
（含 600 权限）、读取优先级、回读校验检查 wwrtx.sid。

---

## 3.1.6 详情页视觉重构（chip + 表格替代色块横幅）

### 问题（双通道评审：设计评审 + 机械核查）

用户反馈「布局改动了但设计还是不太好」。机械核查给出量化病根：

- **对比度全线不达标**：5 种底色上白字对比度 1.92:1（#bbbbbb）～4.00:1（#ff0000），
  全部低于 WCAG AA 正文 4.5:1——连红都不达标。
- **告警通胀**：典型态 6 条彩条占视口 41%，最坏态 9 条占 108%（超一屏），红占 40%。
  穷举 172 万状态组合，5 色可同页共存——「一切都在喊等于没人在喊」。
- **橙/黄同属琥珀色系无法靠颜色区分**；硬编码 hex 与宿主主题脱节，暗色下刺眼。
- **数值埋在长句**：3 条超 60 字的横幅；可信IP 一页出现 2 次。
- 组件统计对照 updatewechatip（同为企微 Cookie 保活的成熟详情页）：
  13 种组件 vs 本页 4 种；VChip/VTable/VAlert 全部为 0。

### 做法

采用宿主原生状态语言（updatewechatip + courseorganizer 已验证的模式）：

- **VChip 徽章**（`variant:tonal` + 主题 token）替代全部色块：success/error/warning/
  默认灰；**橙与黄合并为 warning**（本就难辨，区分交给所在卡与文案）；Cookie 失效
  一处用 `flat` 保持「红=唯一警报」的隔离效应。
- **VTable 键值表**（无表头三列：项目 | 状态chip | 详情）替代长句横幅：标签列是
  常驻锚点，数值独立成格（保活时长加粗、IP/cron 用 `font-monospace`）。
- **卡头摘要行**（chip + 说明 span，`d-flex flex-wrap align-center ga-2`）：摘要
  chip 绑定 keepalive 实际结果；可信IP 全页唯一一处（卡 2 摘要行）。
- **卡骨架改 VCard title/subtitle props**（courseorganizer 式，删手拼 div）；
  验证码等待改 VAlert warning tonal（全页唯一 alert，值得 alert 级）。
- 四态文案精简（【】删除——chip 承担强调），语义不丢；`_page_snapshot` 零改动。

### 边界

- 9 个快照 key 仍未消费（通知通道/CookieCloud 组）：对应状态配置页已表达，
  详情页重复展示违反单一信息源（3.1.1 决定维持）。
- 无 thead 的 VTable 若宿主渲染异常，兜底是加一行表头（项目/状态/详情）——真机看一眼。

### 测试

形状测试 walker 增收 VChip/td/span 文本；「无成功色」断言改为「无 success chip」；
新增断言：页面必须含 VChip/VTable、不得再有 `_banner(` 与任何硬编码 hex。
49 项全绿。

---

## 3.1.7 DDNS 分支不刷新 IP 检测状态（真机确认的陈旧状态缺陷）

### 症状

用户面板截图：Cookie「有效·已保活 9小时50分」，但 IP 检测行显示「失败 · Cookie已失效，
本轮未检测IP」。DDNS 行同时显示「正常·3 个域名」。两个条目自相矛盾，且矛盾挂了
9 个多小时。

### 根因

3.1.0 给 `CheckIP` 三个分支加了状态记录，但 **DDNS 分支的成功路径漏写**：

| 分支 | 成功时写 `_last_ip_check_ok=True`？ |
|---|---|
| 多WAN | ✅ |
| 单IP探测 | ✅ |
| DDNS | ❌ 只写 `_last_ddns_*` |

Cookie 失效期间 `check()` 每轮写「失败」；恢复后 DDNS 分支每轮都成功、更新
`_last_ddns_*`，却从不覆盖旧的失败记录——没有任何清除路径。

3.1.1 修过同类问题（keepalive 的两类 None），但只对照了 keepalive 自身，
**没有对照三个 IP 来源分支**——同一模式在第三处出现时漏掉了。

### 做法

DDNS 分支补齐：解析成功即写 `_last_ip_check_ok=True` + 说明（含失败域名计数），
检测到变化时写「检测到IP变化，正在更新可信IP」，未变化写「DDNS解析结果未变化」。

### 测试

+2 项（`CheckIP` async 函数提取到 stub 命名空间直接执行）：DDNS 成功覆盖旧的
「Cookie已失效」记录、检测到变化时说明同步更新。51 项全绿。

---

## 3.1.8 Cookie 存储严格二选一（关掉混合回退）

### 症状（第二次 Cookie 丢失）

19:40 宿主自动重载插件 → 内存 `_saved_cookie` 清空 → 19:50 首轮保活要走恢复链，
**两头都失败**：

- `cookie.json` 是 **0 字节**（存在但空）
- 解密 CookieCloud：企微域又只剩 `wwrtx.c_gdpr` + `ww_lang`，`wwrtx.sid` 再次消失
  （顶层域名从 700 降到 678，说明有外部客户端用整份浏览器快照覆盖了云端）

### 根因（两个）

1. **落盘取错范围**：`_update_cookie` 用 `context.cookies(current_url)` 取 cookie，
   而企微凭证挂在 `.work.weixin.qq.com`；扫码完成后当前 URL 未必属于该域，
   过滤后为空 → 写出 0 字节文件。0 字节比没有文件更糟：读回时解析失败，
   看起来像「有备份但坏了」。
2. **混合回退制造了双写**：此前读取顺序是 内存 → 本地 → 云端、写入是
   云端 + 本地。同一份企微数据同时存在于两个位置，而**云端还有第三方写入方**
   （浏览器 CookieCloud 扩展上传整份快照），谁后写谁赢。插件侧「读-合并-写」
   只能保护自己写入时不覆盖别人，挡不住别人覆盖自己。

### 做法（用户拍板：开启就只用云端，关闭就只用本地）

- `get_cookie_async`：`use_cookiecloud=True` 只走云端；`False` 只读本地
  `cookie.json`，读到空就明确告警「需要重新扫码」，**不再交叉回退**。
- `_update_cookie`：云端分支不再落盘；本地分支才落盘。两种模式各自闭环。
- 落盘取 `context.cookies()`（全量）后再筛 weixin 域。
- 空 payload → `unlink` 删除旧文件，绝不写 0 字节。
- `_load_cookie_from_disk`：文件 ≤2 字节或空数组都按「无备份」处理。
- 配置页：开关文案直接写清两种模式各自存哪、代价是什么；下方 VAlert 按当前
  模式给出对应说明（关闭时提示「推荐保持关闭——开启 CookiesCloud 会与浏览器
  扩展互相覆盖同一份数据」）。

### 边界与代价

- 关闭 CookieCloud 后**没有跨设备备份**：Cookie 失效只能重新扫码。但插件每
  10 分钟保活一次，正常情况下 Cookie 寿命很长，代价可接受。
- 开启 CookieCloud 时若云端被外部客户端整份覆盖，插件仍会失效——这是
  对方行为，插件无法拦截；配置页文案已明确指引改用本地模式。

### 测试

`test_cookie_persistence.py` 重写为 8 项：严格互斥（关闭不落云端、开启不落本地）、
空 payload 删除文件、空文件按无备份、全量 cookie 读取（真机事故回归）。
共 55 项全绿。

---

## 3.1.9 本地模式假成功：保活校验永远显示「还没跑过第一轮」

### 症状

3.1.8 切到本地模式后，页面「保活校验」永远是「未运行 · 还没跑过第一轮」，
但日志每 10 分钟都在打「Cookie 保活成功，当前生命周期: N 秒」。

### 根因（真机日志确认）

近 20 小时日志里，「检查登录状态」与「本地缓存 Cookie 有效」出现 **0 次** ——
也就是说校验根本没跑过。链条：

1. `_saved_cookie` 是纯内存属性，插件重载后为空；`init_plugin` **没有**从
   `cookie.json` 恢复它
2. `refresh_cookie` 第一段 `if self._saved_cookie:` 不成立 → 跳过本地校验
3. 第二段 `if not cookie_used and self._use_cookiecloud:` → 本地模式下云端关闭 → 跳过
4. 落到 `if self._cookie_valid:` —— `_cookie_valid` 类属性初始值为 **True** →
   **延长寿命并打「保活成功」**
5. `_last_keepalive_ok` 从未被赋值，恒为 None → 页面显示「还没跑过第一轮」

同时 IP 检测也在用空 Cookie，改 IP 实际会失败——只是还没到触发点。

### 做法

1. `init_plugin`：本地模式且内存无 Cookie 时，从 `cookie.json` 恢复；
   恢复不到就明确告警「请重新扫码」。
2. `refresh_cookie`：校验前再补一次落盘读取（配置文件切换/运行期写坏时兜底）。
3. **假成功守卫**：延长寿命与「保活成功」日志改为 `if self._cookie_valid and cookie_used:`，
   即必须真的拿 Cookie 进过浏览器并得出过结论。没有可校验 Cookie 时记 warning，
   并把说明写进 `_last_keepalive_note`，页面因此能显示「没有可校验的 Cookie，请重新扫码登录」。

### 教训

「状态字段恒为初始值」这类缺陷不会有任何报错：日志在打成功、页面在显示默认值，
两者互相印证成一个假象。**成功的日志必须由「真正做过那件事」的变量来守卫**，
而不是由「配置上看起来应该成功」的变量守卫。

### 测试

+3 项回归：init_plugin 必须恢复落盘 Cookie、保活前补读、假成功守卫存在。
共 58 项全绿。

---

## 3.1.10 /push_qr 发不出二维码 + 详情页刷新与最近运行时间

### 问题 1：/push_qr 收不到二维码（真机复现）

用户只开启了 MP 内置通知、没配第三方 Token，发 `/push_qr` 后插件侧**一行日志都没有**。

根因：

```python
if image_src:
    if self._my_send:          # ← 只有配了第三方 Token 才进得去
        ...
        if self._use_mp_notify:  # ← MP 通知被套在里面
            self.post_message(...)
```

这是 3.1.1 评审就已记录、当时选择「先不修」的缺陷（记录了待办）。现在它真实发生了。

修法：两个通道**各自独立判断**（`has_mp` / `has_third`），任一可用即推送；
都不可用时记 warning 并发站内提示，不再静默。

### 问题 2：详情页需要刷新入口与「最近运行」时间

页面是快照，用户不知道数据是哪一刻的。

- 新增 `_last_keepalive_at` / `_last_ip_check_at`，两个循环收尾时打时间戳；
  快照取二者较晚者作为 `last_run_at`，显示在「运行状态」卡副标题
  （无记录时显示「暂无运行记录」，不显示空的「最近：」）。
- 新增 `GET /refresh` 端点 + 卡内「立即检测」按钮（`mdi-refresh`）。

**为什么按钮叫「立即检测」而不是「刷新」**：宿主 JSON 表单里的按钮只能调 API，
没有「重载前端页面」的原生动作，做不成真正的刷新图标。改为触发一轮真实检测，
用户点完等几秒手动刷新本页即可看到新状态——按钮因此有实际作用，而不是一个
按了没反应的装饰。

### 测试

+4 项：MP 通知不得嵌套在第三方守卫内、页面含刷新按钮与最近运行、端点已注册、
两个循环都打时间戳。共 62 项全绿。

---

## 3.2.0 本地 Cookie 原子写（根治「每次更新插件后 Cookie 失效」）

### 症状

用户反馈「每次更新插件后 Cookie 都自动失效」。真机核查 15:12 那次扫码登录：

```
15:12:38,761  从浏览器获取cookie成功
15:12:38,833  Cookie 已保存到本地（未启用 CookieCloud）
```

而 `cookie.json`：

```
Size: 0   Modify: 15:12:38.827   ← 比"已保存"早 6ms
```

0 字节，且插件日志里**没有**「Cookie 已落盘（N 条）」也没有「落盘失败」——
两条本应出现的日志都不在。

### 根因

`_save_cookie_to_disk` 的实现是：

```python
with open(path, "w", encoding="utf-8") as fh:   # ← 先截断
    json.dump(payload, fh, ensure_ascii=False)   # ← 再写；中途任何异常都留 0 字节
```

`open(w)` 的语义是**先清空文件**。只要 `json.dump` 在中途抛任何异常
（不可序列化的值、磁盘满、权限变化），文件就停在被截断后的 0 字节状态。
而异常被 `except Exception` 吞成一条 `logger.warning`，用户完全看不到。

于是每次发布新版本 → 宿主重载插件 → 内存 `_saved_cookie` 清空 →
`init_plugin` 从 0 字节的 `cookie.json` 恢复 → 得到空列表 → 判定失效。
**更新插件与 Cookie 失效之间没有因果关系，只是每次更新都触发一次重载。**
真正致命的是「重载时本地备份是空的」。

### 做法

1. **原子写**：先 `json.dumps` 到内存（序列化失败时连临时文件都不创建），
   再写 `.json.tmp` + `fsync`，最后 `os.replace()` 原子替换。
   任何阶段失败，原文件分毫不动。
2. **失败不再静默**：`except` 从 warning 提升为 `logger.error`，
   并 `systemmessage.put` 告诉用户「本次登录态只在内存，重载会丢」。
3. **读取侧收紧**：0 字节、空数组、以及「有内容但无企微域条目」的文件
   都按无备份处理，且只在异常时记日志（初次安装没有文件属正常）。

### 测试

+3：原子写结构哨兵（必须 `os.replace`、必须先序列化后落盘、失败必须 error +
站内提示）、真实行为测试（序列化失败时原文件内容不变、临时文件被清理）、
读取侧识别三类无效文件。共 64 项全绿。

---

## 3.2.1 更新插件后所有后台命令静默失效（停止标志残留）

### 症状

用户发 `/push_qr`，宿主日志显示「开始执行：立即推送登录二维码 ... 执行完成」，
但**插件日志一行都没有**，Telegram 收不到二维码。详情页「立即检测」同样无反应。

### 根因

`init_plugin` 的顺序：

```python
if not self.stop_service():          # 有残留任务 → False
    logger.warning("仍有后台任务未退出，跳过启动新后台循环")
    self.__update_config()
    return                            # ← _stopping 仍是 True
self._stopping = False                # ← 永远走不到
```

而 `_start_bg_task` 的线程分支会在任务启动后立刻轮询 `self._stopping`：

```python
task = asyncio.create_task(coro)
while not task.done():
    if self._stopping:      # True → 立刻 cancel
        task.cancel()
        break
```

于是重载后 `_stopping` 永久为 True，**任何**新后台任务（`/push_qr`、立即检测）
在协程体第一行之前就被取消——命令「成功」但零输出。

为什么会有残留任务：`stop_service` 对「当前事件循环里的任务」只能 cancel 不能同步等待，
把它们留在 `_bg_tasks` 里返回 False。这条路径在每次重载时都可能走到。

### 做法

1. `self._stopping = False` 提到 `stop_service()` 之后**无条件执行**，早于任何 return。
   残留任务已被 cancel，新标志只服务于新任务，二者不冲突。
2. `_start_bg_task` 的线程分支增加 `await asyncio.sleep(0)`：先让协程真正跑起来，
   再开始监控停止标志。取消时记 info 日志，不再静默。

### 教训

「提前 return 跳过了状态重置」是这类 bug 的通用形态。与 3.1.7（DDNS 分支漏写状态）、
3.1.9（无 Cookie 却报成功）同属一族：**状态必须由真正的执行路径维护，不能依赖
「正常流程一定会走到某一行」的假设**。

### 测试

+2：重置必须早于 stop_service 后的早退分支；协程先让出一轮再检查停止标志
（锚点落在代码行而非注释，注释里也提到了同一段代码）。

---

## 3.2.2 原子写用了 json 却没 import（v3.2.0 的回归）

### 症状

3.2.1 上线后重新扫码登录，日志：

```
16:27:52,126  从浏览器获取cookie成功
16:27:52,148  ERROR Cookie 落盘失败（本次更新后重载将丢失登录态）: name 'json' is not defined
```

`cookie.json` 仍是 0 字节。

### 根因

3.2.0 的原子写实现用了 `json.dumps`，但 `plugins.v3/dynamicwechat/__init__.py`
**从未 `import json`** —— 此前所有 json 操作都在 `helper.py` 里。函数一执行就
`NameError`，被 `except` 捕获后走「落盘失败」分支。

### 值得记的一点

这次之所以能**一眼定位**而不是又排查一轮，正是因为 3.2.0 把「落盘失败」从
`logger.warning`（易被淹没）提升成了 `logger.error` + 站内消息。防御性日志的
价值在这里兑现了：**错误的可见性比错误本身更容易被低估**。

### 做法

1. `import json` 补进 `__init__.py`。
2. 端到端验证（真容器内执行方法体）：落盘 2 条 / 177 字节、临时文件无残留、
   读回含 `wwrtx.sid`、权限 600 —— 全部符合预期。
3. 测试 +1：`__init__.py` 顶部必须 `import json`（防止再犯）。

共 67 项全绿。

---

## 3.3.0 全量代码审查后的集中修复（14 项）

一次完整审查（全文件 + 逐条核实）发现的问题，按「假成功 → 数据丢失 → 状态失真 → 边界」分类。

### 假成功（最伤信任，全部修掉）

| # | 问题 | 修法 |
|---|---|---|
| 1 | `refresh_cookie` 把三态 `None`（无结论）当成 Cookie 失效，清内存 Cookie 并发失效通知 | 只累计 `_none_streak`，保留 Cookie 与有效性；本地/云端两条校验路径都区分 `None` |
| 2 | `post_message` 返回 None、失败不上报，却被计为「发送成功」 | 改为 `mp_attempted` 语义，文案写「已提交（送达不可确认）」；三处（失效通知/二维码/测试通知） |
| 3 | `_merge_pinned_ips` 不校验 IPv4，企微拒绝整份列表却报「修改成功」 | 只收合法 IPv4，非法项记 warning 并忽略 |
| 4 | `CheckIP` 在 `ChangeIP` 之前就记 `ok=True`，更新失败也永远显示「正常」 | `ChangeIP` 的每个失败分支都写回 `_last_ip_check_ok=False` + 原因 |
| 5 | 外层 `except` 只打日志不动状态，浏览器连续失败时页面仍显示「正常」 | 异常也写 `_last_keepalive_ok=False` + 原因 |

### 数据与状态

| # | 问题 | 修法 |
|---|---|---|
| 6 | `_push_qr_code_async` 丢弃 `refuse_time`，详情页因无时间戳不渲染图 | 推送成功即写 `_future_timestamp` |
| 7 | 切换 CookieCloud 开关后仍用旧模式的内存 Cookie（破坏严格二选一） | `init_plugin` 无条件清 `_saved_cookie`，再按模式恢复；新增 `_cookie_verified` 区分「有 Cookie」与「已验证」 |
| 8 | `local_scanning` 无锁，与 `/push_qr` 并发时抢 `_qr_running`/验证码/临时文件 | 复用 `_qr_lock` 互斥，`finally` 释放 |
| 9 | `_is_local()` 用 URL 前缀判断，自建 CookieCloud 在 localhost 会误判 | 改为「是否提供 local_dir」 |
| 10 | `_verification_code` 只在成功时清除，失败后残留污染下一轮 | 三个失败分支 + 新一轮扫码开始时都清 |

### 健壮性

| # | 问题 | 修法 |
|---|---|---|
| 11 | `settings.json` 三处非原子写，中断即损坏 | 新增 `atomic_write_json()`（临时文件 + `os.replace`） |
| 12 | `JsonFieldManager._load` 解析失败静默返回 `{}`，随后的读-改-写会抹掉其它字段 | 损坏时先备份为 `.corrupt` 再返回空字典 |
| 13 | `_bg_threads` 只增不减 | 每次启动前过滤已结束线程 |
| 14 | `stop_service` 逐个 `join(10s)` 串行阻塞宿主 | 改为总预算 deadline；`context.close()` 统一加 10 秒超时（真机日志里的「浏览器关闭超时」不再抛到外层） |
| 15 | `_cc_server` 从不重置，改凭据需重启 | `try_connect_cc_async` 开头先清空 |

### 测试

新增 `test_review_fixes.py` 13 项，覆盖：None 不误判失效、MP 通知不计成功、pinned 校验、
跨模式重置、二维码时间戳、验证码清理、扫码互斥、原子写替换、损坏备份、`_is_local` 判定。
合计 79 项全绿。

---

## 3.3.1 「立即检测」按钮改为「刷新」（仅取快照）

### 用户反馈

「立即检测，改成仅刷新页面」——按钮触发真实检测与配置页「立即检测一次」开关
职责重复，而且检测要开浏览器、要等，不是用户点刷新时期待的行为。

### 做法

- `GET /refresh` 改为返回 `_page_snapshot()` 的最新快照数据（纯只读，不启动任何任务）
- 按钮文案改「刷新」，旁注「状态为进入页面时的快照；查看最新请刷新浏览器页面」
- 触发检测的职责交还给配置页「立即检测一次」开关，职责不再重叠

### 边界

按钮调 API 依然不能真正重载前端页面（宿主限制不变）；现在它至少把最新快照
交给调用方，未来前端若支持响应式更新即可直接消费。

### 测试

+2：端点必须纯只读（不得 `_start_bg_task` / `check`）、按钮文案为「刷新」
且页面不再出现「立即检测」字样。共 80 项全绿。

---

## 3.3.2 「刷新」按钮报「服务器返回了无效响应」

### 症状

3.3.1 上线后点详情页「刷新」按钮，前端提示「服务器返回了无效响应」。

### 根因

`docs/V3_API_Response_Adaptation.md` §2 明确：Vuetify JSON 页面的
`events.click.api` 走宿主普通数据客户端，**严格校验 `success/message/data`
三字段 envelope**，endpoint 必须显式返回并声明 `schemas.Response[DataModel]`。
`/refresh` 返回的是裸 `{"success": True, "data": {...}}`——缺 `message` 字段，
宿主客户端判定无效。

这是文档里写明的合同，实现时没查——与 3.2.1 之前的「endpoint 签名变
response model」属同一类：**插件 API 的响应形状是宿主合同，不是插件自由裁量**。

### 做法

照 `courseorganizer` 的防御模式：

1. 顶部 `try: from app import schemas as _schemas`（桩环境降级）
2. `get_api()` 里给全部路由声明 `response_model = _schemas.Response[Dict[str, Any]]`
3. `_envelope(success, data, message)` 辅助函数返回标准 envelope

### 测试

+1：`get_api` 必须声明 response_model、`_api_refresh` 必须走 `_envelope`、
envelope 必须含 message。共 81 项全绿。
