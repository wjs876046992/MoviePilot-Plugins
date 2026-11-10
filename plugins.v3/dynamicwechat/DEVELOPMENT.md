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
