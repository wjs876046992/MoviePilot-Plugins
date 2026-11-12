# DynamicWeChat（动态企微可信IP）V3 交付总结

> 状态：**已交付 / 已推送 / 已部署到 NAS（未重启）**
> 日期：2026-11-11
> 仓库：`wjs876046992/MoviePilot-Plugins`，分支 `main`
> 当前版本：**v3.1.6**

---

## 一、交付概览

本轮工作把「动态企微可信IP」从「叠在 V2 目录里的 3.x 代码」正式迁为 V3 专用插件，
随后完成 6 轮页面重设计与评审修复，并修掉一个会破坏其它站点数据的 CookieCloud
写入缺陷。

| 阶段 | 版本 | 提交 | 一句话 |
|---|---|---|---|
| 代际迁移 | 3.0.2 | `a7b98d0` | V2 目录回滚上游 2.1.9，功能全部落到 `plugins.v3/` |
| 首轮页面重设计 | 3.1.0 | `e07f300` | 详情页状态可见 + 配置页四区 + 魔法语法拆字段 |
| 依赖修正① | — | `50729d5` | cloakbrowser 声明改 `>=0.6,<0.7`（0.7.0 起强制 license key） |
| 评审修复 | 3.1.1 | `93161a5` | 消除静默失败链、四区标题、死字段补渲染 |
| 配置页卡片化 | 3.1.2 | `cd5fb8f` | 五张 VCard，扫码独立成卡 |
| 依赖修正② | — | `f52868a` | 去掉 `<0.7` 上界，宿主预检不再判降级 |
| 多 DDNS 域名 | 3.1.3 | `bc38027` | 全部解析并合并；pinned 移入 IP 来源卡 |
| 详情页卡片化 | 3.1.4 | `9b8011f` | 三张 VCard 与配置页统一 |
| CookieCloud 修复 | 3.1.5 | `c8d7632` | 读-合并-写 + 回读校验 + 本地落盘兜底 |
| 详情页视觉重构 | 3.1.6 | `72551cc` | VChip 徽章 + VTable 替代色块横幅 |

> **两次依赖修正的关系**：`50729d5` 把声明从 `>=0.7,<0.8` 改为 `>=0.6,<0.7`；
> 但宿主预检把「插件要求 `<0.7`、实例装 0.7.2」判为需降级并拒绝加载，
> 故 `f52868a` 再改为只留下限 `>=0.6`。实际版本固定交由 NAS 侧
> `UV_CONSTRAINT` 完成（见第五节）。

---

## 二、当前架构与文件清单

### 目录与索引

```
plugins.v3/dynamicwechat/          ← 唯一维护目标
├── __init__.py                    # 插件主体（get_form / get_page / 全部业务逻辑）
├── helper.py                      # PyCookieCloud / MySender / IpLocationParser / JsonFieldManager
├── pyproject.toml                 # V3 依赖清单
├── USAGE.md                       # 用户文档
├── DEVELOPMENT.md                 # 设计与开发记录（逐版本）
└── REDESIGN_REQUIREMENTS.md       # 首轮页面重设计需求规格
tests/v3/dynamicwechat/
├── test_v3_contract.py            # 代际合同 / 版本三元组
├── test_page_shape.py             # 页面形状与状态回归（含评审修复）
└── test_cookie_persistence.py     # CookieCloud 合并写入 / 落盘兜底
```

### 版本与代际约束

| 项 | 值 |
|---|---|
| `plugin_version` | `3.1.6`（`__init__.py:34`） |
| `package.v3.json` version | `3.1.6`，history 首项 `v3.1.6` |
| `system_version` | `>=3.0.0` |
| `package.v2.json` | **2.1.9**（上游原样）+ `"v3": false` |
| `package.json` V1 | 1.7.3（上游原样）+ `"v3": false` |
| V2 源码 | 与 `refs/remotes/upstream/main` 逐字节一致 |

**维护约定**：后续只改 `plugins.v3/dynamicwechat/` 与 `tests/v3/dynamicwechat/`。

---

## 三、业务能力与页面设计

### 配置页（五张 VCard）

| 卡 | 主要控件 | 设计要点 |
|---|---|---|
| 基础 | 启用 / 立即检测一次 / 强制更新IP | 触发器说明独立成 alert，开关短 label |
| 扫码登录 | 本地扫码修改IP | 从基础区独立成卡（首次使用的第二个动作） |
| IP 来源 | DDNS域名（多个）、多WAN开关+数量、自定义探测URL、**固定可信IP** | 副标题区分「检测来源只取一个」与「固定项始终保留」 |
| 通知 | MP内置通知、IP变动后通知、测试按钮、第三方Token | 识别结果行注明「保存后更新」 |
| 高级 | CookieCloud | 保持默认即可 |

### 详情页（三张 VCard + chip/table）

- **运行状态**：卡头摘要 chip（未启用/缺应用ID/校验未通过/等待首轮/运行中，
  绑定 `keepalive_ok` 实际结果）；VTable 三行——Cookie 登录态、保活校验、IP 检测，
  每行「标签 | 状态 VChip | 详情（数值加粗 / mono）」。
- **IP 来源**：摘要 chip 显示生效模式，旁边是当前可信IP（**全页唯一**）；
  VTable 列出 DDNS 与固定可信IP 状态。
- **扫码登录**：二维码状态 chip（无任务/运行中/有效）+ 图片；等待验证码时
  显示全页唯一的 VAlert。

**视觉语言**：VChip `variant:tonal` + 主题 token（success/error/warning/默认灰），
无任何硬编码色；橙与黄合并为 warning，Cookie 失效一处用 `flat` 保持唯一警报。
数值不再埋在长句里；页面纯渲染、无写副作用。

### 关键业务能力

- IP 检测来源优先级：DDNS 多域名（全部解析合并去重）> 多WAN 出口 > 公网探测
- Cookie 保活：独立 10 分钟循环，登录态三态（True/False/None）判定
- 通知：MP 内置 + 第三方双通道；如实声明 MP 送达结果不可查询
- 验证码：企微消息以 `？` 结尾，或 `/wxcode` 命令
- 一次性触发：`/push_qr`、配置页「立即检测一次 / 强制更新IP」保存后自动复位

---

## 四、关键问题与修复记录（值得复用的教训）

### 1. CookieCloud 覆盖写入（v3.1.5，最严重）

**症状**：开了 CookieCloud，重启插件后 Cookie 仍失效。
**真机证据**：解密 CookieCloud 文件，`work.weixin.qq.com` 只剩
`wwrtx.c_gdpr`、`ww_lang` 两个边缘 cookie，登录凭证 `wwrtx.sid` 不见了。
**根因**：`helper.update_cookie` 只上传企微域，而 CookieCloud `/update` 是
**整体替换**——那次写入清空了另外 699 个站点的 Cookie，企微域也只留不完整子集。
不是别的浏览器覆盖了它，是插件自己覆盖了整个 CookieCloud。

**修复三项**：
1. `decrypt()` + `download_raw()` → **读全量 → 只替换 `*weixin*` 域 → 写回**；
   拿不到全量时拒绝写入
2. 写入后**回读校验** `wwrtx.sid` 是否存在
3. **本地落盘兜底** `get_data_path()/cookie.json`（600 权限，只存 weixin 域），
   读取顺序：内存 → 落盘 → CookieCloud

**遗留**：此前被清空的其它站点 Cookie 需要重新同步一次（MP 站点同步会补回）。

### 2. 静默失败链（v3.1.1）

应用ID 占位符演示 `1000002`（正是运行期校验拒绝的格式）+ 顶部绿条判据只是
「字段非空」→ 用户照页面指引填完却看到绿色「运行中」，实际从未工作。
修复：占位符改真实格式、100000x 命中发站内提示、绿条绑定实际校验结果。

### 3. 状态表达层（v3.1.6）

机械核查量化：5 种底色上白字对比度 **1.92～4.00:1 全部低于 WCAG AA**；
典型态 6 条彩条占视口 41%，最坏态 9 条占 108%。
**告警通胀的根源是色彩面积而非文案**——换成 VChip + VTable 后色面积 <2%。

### 4. 其它踩坑

- 「是否曾经登录」不能只看 `_is_special_upload`（失效后被重置），
  需三条件或：`_is_special_upload or _saved_cookie or lifetime>0`
- keepalive `ok=None` 有两种含义（没跑过 / 跑了但无结论），显示成「还没跑过」
  会把网络故障变成谎言
- 大段替换源码不要经过 shell heredoc（`\n` 转义把文件写坏过一次），
  用临时文件 + Python 定位替换
- 多域名语义选「全部解析合并」而非「第一个成功者胜」：多线路需要每个出口
  都进白名单；全部失败时不静默回退其它来源

---

## 五、依赖与 NAS 运行环境

### cloakbrowser 固定（重要运维约束）

| 层 | 内容 |
|---|---|
| 插件声明 | `cloakbrowser>=0.6`（**只留下限**，写上界会被宿主预检判为「要求降级」而拒绝加载） |
| NAS 约束 | `/config/plugin-constraints.txt` → `cloakbrowser>=0.6,<0.7`（持久卷，compose 的 `UV_CONSTRAINT` 指向它） |
| 容器实装 | `/opt/venv` 里 **0.6.5** |
| 备份 | `/config/_backup_cloak_20261111111154/`（0.7.2 包 + 原约束 + 原 manifest） |

**原因**：CloakBrowser 0.7.0 起启动前强制 license key（无 TTY 时明确报错、
交互 TTY 会弹菜单挂死）；当前机器暂时拿不到 key。0.6.5 提供同样的
`launch_context_async` 且无此门槛。

### 宿主预检规则（只读核实）

`cloakbrowser` 属于 `protected=True`、`strict=False` → 宿主只拦「降级冲突」，
纯升级放行。因此插件清单不能带 `<0.7` 上界；版本固定由实例侧约束完成。
验证过的宿主预检结果：`preflight ok: True | msg: (none)`。

### 部署与操作规则（用户确立）

1. **部署**：`cd /volume2/docker/moviepilot/config/local_plugins/plugins.v3/dynamicwechat`
   → `git pull`；SSL 中断时加 `-c http.version=HTTP/1.1`，
   仍失败需从仓库根 fetch 后 merge。**不用 tar 覆盖、不往 `/app` 手工拷贝**。
2. **重启**：非授权禁止 `docker restart mp3`。
3. **容器内测试**：一律 `docker exec -u 1026:100 mp3 ...`，
   否则 root 属主的 `/tmp` 残留会让 nginx 缓存管理器刷 `[crit] opendir`。
4. **部署不含重启**；「部署到 NAS」不自动包含「让它生效」。

---

## 六、验证结果

| 验证项 | 结果 |
|---|---|
| 插件测试（`--noconftest`） | **49 passed** |
| 版本门禁（strict=dynamicwechat） | 通过 |
| `compileall` | 通过 |
| CI 后端无关批 | 51 passed |
| 文案红线（Markdown / 内部术语） | 零违规 |
| 硬编码色（get_page） | 零（已全部主题 token 化） |
| 宿主预检（cookie 冲突） | `preflight ok: True` |

**已核实但未消除的既有限制**：`tests/ci/test_v3_dependency_manifests.py`
的 2 个失败是仓库既有问题（`rsync115sync` 的 `project.name`、
`p115strmhelper` 的 `uv.sources`），与本插件无关。

---

## 七、当前部署状态

| 项 | 值 |
|---|---|
| 远端 `origin/main` | `72551cc` |
| NAS `local_plugins` HEAD | `72551ccf`，`plugin_version = "3.1.6"`，工作区 clean |
| 容器 `mp3` | healthy（最近一次授权重启后） |
| 容器内 cloakbrowser | 0.6.5 |
| 运行中的插件代码 | 取决于宿主插件文件监控是否自动重载；**未再重启** |

**生效提示**：若配置页/详情页看到的还是旧布局，说明插件尚未重载。
按规则需要你明确授权才会重启容器；宿主的文件监控通常会自动重载本地插件。

---

## 八、待办 / 开放项

1. **真机视觉验收**：无 thead 的 VTable 需在实际宿主里看一眼；
   渲染异常时兜底补一行表头（项目/状态/详情）。
2. **CookieCloud 站点 Cookie 补同步**：3.1.5 之前被清空的其它站点 Cookie
   需重新同步一次。
3. **free key**：拿到 CloakBrowser license key 后可解除 0.6.x 固定，
   写进 `/config/app.env` 的 `CLOAKBROWSER_LICENSE_KEY`。
4. **未实现的能力**（历次评审刻意延后）：详情页「立即扫码/立即检测」按钮、
   验证码页面输入、`cookie_header` 配置页输入框。
5. **快照 9 个未消费 key**（通知通道 / CookieCloud 组）：对应状态配置页已表达，
   详情页重复展示违反单一信息源，维持不渲染。

---

## 附：文档索引

| 文档 | 用途 |
|---|---|
| `plugins.v3/dynamicwechat/USAGE.md` | 用户使用说明（配置项、首次使用、详情页、FAQ） |
| `plugins.v3/dynamicwechat/DEVELOPMENT.md` | 逐版本设计决策、踩坑、被否决方案、测试记录 |
| `plugins.v3/dynamicwechat/REDESIGN_REQUIREMENTS.md` | 首轮页面重设计的需求规格（问题清单、四态矩阵、验收标准） |
| `docs/Development_Log.md` | 仓库级开发日志（本插件全部迭代条目） |
| `.impeccable/critique/` | 两轮设计评审的持久化快照 |
