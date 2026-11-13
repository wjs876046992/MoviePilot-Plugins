# DynamicWeChat（动态企微可信IP）V3 交付总结

> 状态：**已交付 / 已推送 / 已部署到 NAS / 用户确认无问题**
> 日期：2026-11-11 起，2026-11-14 收敛
> 仓库：`wjs876046992/MoviePilot-Plugins`，分支 `main`
> 当前版本：**v3.3.3**（NAS HEAD `4a6429d`）
> 测试：**81 项全绿**（`--noconftest`）

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
| DDNS 分支状态 | 3.1.7 | `aca5a83` | DDNS 成功时补写 IP 检测状态 |
| Cookie 严格二选一 | 3.1.8 | `1530f85` | 开 CookieCloud 只存云端、关则只存本地 |
| 保活假成功 | 3.1.9 | `7e38dc2` | 无 Cookie 可校验时不再谎报成功 |
| 推送守卫 + 刷新 | 3.1.10 | `66c7790` | /push_qr 不再被第三方 Token 守卫挡住 |
| Cookie 原子写 | 3.2.0 | `0352ff3` | 根治「每次更新插件后 Cookie 失效」 |
| 停止标志残留 | 3.2.1 | `23a79eb` | 重载后所有后台命令静默失效 |
| 补 import json | 3.2.2 | `756d6c2` | 上版原子写的直接回归 |
| 审查集中修复 | 3.3.0 | `6563af9` | 14 项（假成功 / 数据 / 健壮性） |
| 刷新按钮语义 | 3.3.1 | `d2ac5fc` | 改为纯取快照，不再触发真实检测 |
| 响应 envelope | 3.3.2 | `4ae0742` | 插件 API 需显式 `schemas.Response` |
| 登录后陈旧提示 | 3.3.3 | `4a6429d` | 「没有可校验的 Cookie」只在空时写→永不过期 |

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
| `plugin_version` | `3.3.3`（`__init__.py` 类属性） |
| `package.v3.json` version | `3.3.3`，history 首项 `v3.3.3` |
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
- 插件 API 的响应形状是**宿主合同**：`events.click.api` 走宿主普通数据客户端，
  严格校验 `success/message/data` 三字段 envelope，端点必须显式声明
  `response_model = schemas.Response[T]`。返回裸 dict 缺 `message` 会被前端
  判为无效（v3.3.2 实锤）。与「endpoint 签名被 FastAPI introspect」同类。

### 5. 问题谱系：本轮反复出现的一类缺陷

本轮 12 个补丁里有 **7 个属于同一族：状态字段没有由真实执行路径维护**。
这不是巧合，而是这个插件「长跑 + 多分支 + 大量外部依赖」的必然产物。

| 版本 | 形态 | 具体表现 |
|---|---|---|
| 3.1.7 | 漏写 | DDNS 分支成功时不写 IP 检测状态，旧「失败」记录永不清除 |
| 3.1.9 | 假成功 | 无 Cookie 可校验却打「保活成功」，页面永远「还没跑过第一轮」 |
| 3.2.0 | 截断式写 | `open(w)` 先清空，中途异常留 0 字节，重载后从空文件恢复 |
| 3.2.1 | 提前 return 跳过重置 | `_stopping` 永久 True，所有后台任务启动即被取消 |
| 3.3.0 | 失败不写回 | `ChangeIP` 失败只设 `_ip_changed`，页面永远「IP 检测正常」 |
| 3.3.0 | 异常不更新 | 外层 `except` 只记日志，浏览器连续失败时页面仍显示「正常」 |
| 3.3.3 | 条件写入 | 「没有可校验的 Cookie」加 `and not note` 守卫，写下一次后永不过期 |

**共同判据（写进任何插件的自查清单）**：

1. 每个状态字段，**每条执行路径**（成功 / 失败 / 异常 / 无结论）都必须写一次，
   不允许「正常流程一定会走到」的假设。
2. 写入**不得带「仅当为空时」的条件**——那等于制造陈旧状态。
3. 成功日志必须由「真正做过那件事」的变量守卫（如 `cookie_used`），
   不能由「配置上看起来应该成功」的变量守卫（如 `_cookie_valid` 的初值）。
4. 持久化必须原子写；截断式写入的失败形态（0 字节文件）比没有文件更糟。
5. 宿主返回 None 的接口（`post_message`）不得当作成功。

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
| 插件测试（`--noconftest`） | **81 passed** |
| 版本门禁（strict=dynamicwechat） | 通过 |
| `compileall` | 通过 |
| CI 后端无关批 | 51 passed |
| 文案红线（Markdown / 内部术语） | 零违规 |
| 硬编码色（get_page） | 零（已全部主题 token 化） |
| 宿主预检（cookie 冲突） | `preflight ok: True` |
| 真机验收 | 用户确认「已确认无问题」 |

测试文件构成：`test_v3_contract.py`（代际合同/版本三元组）、
`test_page_shape.py`（页面结构与状态回归）、`test_cookie_persistence.py`
（CookieCloud 合并写入 / 原子落盘 / 跨模式）、`test_review_fixes.py`
（审查 14 项逐条回归）。

**已核实但未消除的既有限制**：`tests/ci/test_v3_dependency_manifests.py`
的 2 个失败是仓库既有问题（`rsync115sync` 的 `project.name`、
`p115strmhelper` 的 `uv.sources`），与本插件无关。

---

## 七、当前部署状态

| 项 | 值 |
|---|---|
| 远端 `origin/main` | `6563af9`（v3.3.0）→ 其后 v3.3.1/3.3.2/3.3.3 已推送到远端 |
| NAS `local_plugins` HEAD | `4a6429dc`，`plugin_version = "3.3.3"` |
| 容器 `mp3` | healthy |
| 容器内 cloakbrowser | 0.6.5（`UV_CONSTRAINT` 固定 `>=0.6,<0.7`） |
| Cookie 存储模式 | 本地（`use_cookiecloud = false`），`cookie.json` 原子写 |
| 真机状态 | 用户确认无问题 |

**生效提示**：宿主会检测 `local_plugins` 变化自动重载；按既定规则，
**未经明确授权不重启容器**。

---

## 八、待办 / 开放项

1. **CookieCloud 站点 Cookie 补同步**：3.1.5 之前被清空的其它站点 Cookie
   需重新同步一次（一次性，MoviePilot 的站点同步会补回）。
2. **free key**：拿到 CloakBrowser license key 后可解除 0.6.x 固定
   （当前无 key 时 0.7.x 启动会报错/挂起），写进 `/config/app.env` 的
   `CLOAKBROWSER_LICENSE_KEY`。
3. **未实现的能力**（历次评审刻意延后）：验证码页面输入、
   `cookie_header` 配置页输入框。（「立即检测」已由 v3.3.1 收敛为纯快照刷新，
   触发检测的职责交还配置页开关。）
4. **快照未消费字段**（通知通道 / CookieCloud 组）：对应状态配置页已表达，
   详情页重复展示违反单一信息源，维持不渲染。
5. **未列出的审查补充项**：审查还提到若干低优先级项（如更细粒度的锁粒度），
   本轮未全部展开；如出现相关症状再按「问题谱系」的五条判据排查。

---

## 附：文档索引

| 文档 | 用途 |
|---|---|
| `plugins.v3/dynamicwechat/USAGE.md` | 用户使用说明（配置项、首次使用、详情页、FAQ） |
| `plugins.v3/dynamicwechat/DEVELOPMENT.md` | 逐版本设计决策、踩坑、被否决方案、测试记录 |
| `plugins.v3/dynamicwechat/REDESIGN_REQUIREMENTS.md` | 首轮页面重设计的需求规格（问题清单、四态矩阵、验收标准） |
| `docs/Development_Log.md` | 仓库级开发日志（本插件全部迭代条目） |
| `.impeccable/critique/` | 两轮设计评审的持久化快照 |
