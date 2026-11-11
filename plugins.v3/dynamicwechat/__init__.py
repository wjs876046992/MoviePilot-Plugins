import asyncio
import io
import os
import random
import re
import base64
import threading
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any

import aiohttp
import pytz
from apscheduler.triggers.cron import CronTrigger
from cloakbrowser import launch_context_async

from app.sdk.config import settings
from app.sdk.events import eventmanager, Event
from app.adapters.external.cookiecloud import CookieCloudHelper
from app.sdk.logging import logger
from app.sdk.plugin import _PluginBase
from app.schemas.types import EventType, MessageType

from .helper import PyCookieCloud, MySender, IpLocationParser, JsonFieldManager


class DynamicWeChat(_PluginBase):
    # 插件名称
    plugin_name = "动态企微可信IP"
    # 插件描述
    plugin_desc = "修改企微应用可信IP,详细说明查看'作者主页',支持第三方通知。验证码以？结尾发送到企业微信应用"
    # 插件图标
    plugin_icon = "Wecom_A.png"
    # 插件版本
    plugin_version = "3.1.3"
    # 插件作者
    plugin_author = "RamenRa"
    # 作者主页
    author_url = "https://github.com/RamenRa/MoviePilot-Plugins"
    # 插件配置项ID前缀
    plugin_config_prefix = "dynamicwechat_"
    # 加载顺序
    plugin_order = 47
    # 可使用的用户级别
    auth_level = 2
    # 检测间隔时间,默认10分钟
    _refresh_cron = '*/10 * * * *'

    # ---------- 常量配置 ----------
    BROWSER_LAUNCH_TIMEOUT = 30.0      # 浏览器启动超时（秒）
    BROWSER_RETRY_COUNT = 3            # 浏览器启动重试次数
    BROWSER_RETRY_DELAY = 2.0          # 浏览器启动重试间隔（秒）
    QR_CODE_MAX_ATTEMPTS = 4           # 扫码最大检查次数
    QR_CODE_CHECK_INTERVAL = 20        # 扫码检查间隔（秒）
    QR_CODE_EXPIRE_SECONDS = 110       # 二维码过期时间（秒）
    QR_CODE_REFUSE_OFFSET = 5          # 二维码拒绝时间偏移（秒，用于前端展示）
    FILE_LOCK_TIMEOUT = 5.0            # 文件锁获取超时（秒）
    BACKUP_TASK_JOIN_TIMEOUT = 10      # 停止时等待后台任务超时（秒）

    # ------------------------------------------私有属性------------------------------------------
    _enabled = False  # 开关
    _cron = None
    _onlyonce = False
    # IP更改成功状态
    _ip_changed = False
    # 强制更改IP
    _forced_update = False
    # CloudCookie服务器
    _cc_server = None
    # 本地扫码开关
    _local_scan = False
    # 类初始化时添加标记变量
    _is_special_upload = False
    # 聚合通知
    _my_send = None
    # 多wan口支持
    wan2 = None
    # 当前检测url
    wan2_url = None
    # IP变动后发送通知开关
    _await_ip = False
    # 保存cookie
    _saved_cookie = None
    # 通知方式token/api
    _notification_token = ''
    # 是否使用MP内置通知（由MP管理，可能是微信、Telegram等）
    _use_mp_notify = True
    # 仅标记IP变动后 通知发送过了没有
    _send_notification = False
    # 固定可信IP列表（始终保留，不会被清除）
    _pinned_ips = ''
    # Cookie检查结果 # timeout  # captcha_incomplete # captcha_btn_error
    _last_check_result = None
    _login_confirmed_by = None

    # 匹配ip地址的正则
    _ip_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
    # 获取ip地址的网址列表
    _ip_urls = ["https://myip.ipip.net", "https://ddns.oray.com/checkip", "https://ip.3322.net",
                "https://r.inews.qq.com/api/ip2city", "https://uapis.cn/api/v1/network/myip"]
    # DDNS域名：填写后优先解析该域名获取动态公网IP（家里插件才能拿到IP而不是自家IP）
    _company_domain = ""
    # 当前ip地址（可能为分号分隔的多个IP）
    _current_ip_address = '0.0.0.0'
    # 企业微信登录
    _wechatUrl = 'https://work.weixin.qq.com/wework_admin/loginpage_wx?from=myhome'

    # 输入的企业应用id
    _input_id_list = ''
    # 多WAN开关与最多出口IP数（从旧 ||wanN 语法拆出的独立字段）
    _wan_enabled = False
    _wan_max_ips = ""
    # 自定义公网IP探测地址（从旧 ids||url1,url2 语法拆出的独立字段，逗号分隔）
    _custom_ip_urls = ""
    # 二维码
    _qr_code_image = None
    # 用户消息
    text = ""
    # 手机验证码
    _verification_code = ''
    # 过期时间
    _future_timestamp = 0
    # 配置文件路径
    _settings_file_path = None

    # cookie有效检测
    _cookie_valid = True
    # cookie失效通知已发送标志（防止重复通知）
    _cookie_invalid_notified = False
    # cookie存活时间
    _cookie_lifetime = 0
    # 使用CookieCloud开关
    _use_cookiecloud = True
    # 登录cookie
    _cookie_header = ""
    # 内建CookieCloud服务器
    _server = f'http://localhost:{settings.NGINX_PORT}/cookiecloud'
    # CookieCloud客户端
    _cookiecloud = CookieCloudHelper()
    # 后台任务列表（asyncio.Task）- 实例级，由 init_plugin 初始化
    _bg_tasks: Optional[List[asyncio.Task]] = None
    # 后台线程列表（用于无事件循环时启动）- 实例级
    _bg_threads: Optional[List[threading.Thread]] = None
    # 文件写入锁（线程锁，兼容多线程）
    _file_lock: threading.Lock = None
    # 二维码运行状态锁
    _qr_lock: threading.Lock = None
    # 通知去重锁
    _notify_lock: threading.Lock = None
    # 停止标志
    _stopping = False
    # 后台循环启动标志（防止重复启动）
    _loops_started = False

    # 类级别锁，用于串行化浏览器启动环境变量修改
    _browser_env_lock = threading.Lock()

    if hasattr(settings, 'VERSION_FLAG'):
        version = settings.VERSION_FLAG  # V2
    else:
        version = "v1"

    def init_plugin(self, config: dict = None):
        """
        插件初始化，读取配置，停止旧任务，启动新服务
        :param config: 插件配置字典
        """
        # 清空运行时状态（保留持久化数据）
        self._last_code = ""
        self._notification_token = ''
        self._cron = '*/10 * * * *'
        self._ip_changed = True
        self._forced_update = False
        self._use_cookiecloud = True
        self._local_scan = False
        self._input_id_list = ''
        self._cookie_header = ""
        self._settings_file_path = self.get_data_path() / "settings.json"
        self.cfg = JsonFieldManager(self._settings_file_path)
        self._qr_running = False
        self._stopping = False
        self._loops_started = False
        self._cookie_invalid_notified = False
        # 页面状态记录点（只被后台流程在流程末尾赋值，供详情页快照展示）
        self._last_check_result = None
        self._login_confirmed_by = None
        self._none_streak = 0
        self._last_ip_check_ok = None          # None=还没跑过 / True / False
        self._last_ip_check_note = ''          # 上次IP检测的一句用户可读结论
        self._last_keepalive_ok = None         # None=还没跑过 / True / False
        self._last_keepalive_note = ''         # 上次保活的一句用户可读结论
        self._waiting_captcha = False          # 是否正在等待短信验证码
        self._last_ddns_ok = None              # None=没配DDNS / True / False
        self._last_ddns_ip = ''                # DDNS 最近一次解析到的IP（展示用脱敏）

        # 初始化实例级后台任务容器
        if self._bg_tasks is None:
            self._bg_tasks = []
        if self._bg_threads is None:
            self._bg_threads = []

        # 初始化线程锁
        if self._file_lock is None:
            self._file_lock = threading.Lock()
        if self._qr_lock is None:
            self._qr_lock = threading.Lock()
        if self._notify_lock is None:
            self._notify_lock = threading.Lock()

        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._notification_token = config.get("notification_token")
            self._use_mp_notify = config.get("use_mp_notify", True)
            self._cron = config.get("cron")
            self._onlyonce = config.get("onlyonce")
            self._input_id_list = config.get("input_id_list")
            self._company_domain = config.get("company_domain") or ""
            self._forced_update = config.get("forced_update")
            self._local_scan = config.get("local_scan")
            self._use_cookiecloud = config.get("use_cookiecloud")
            self._cookie_header = config.get("cookie_header")
            self._await_ip = config.get("await_ip")
            self._pinned_ips = config.get("pinned_ips", "")
            self._wan_enabled = bool(config.get("wan_enabled"))
            self._wan_max_ips = str(config.get("wan_max_ips") or "").strip()
            self._custom_ip_urls = str(config.get("custom_ip_urls") or "").strip()

        # 旧值迁移：应用ID里的 ||wanN（多WAN）与 ids||url1,url2（自定义探测URL）
        # 拆到独立字段。幂等：新字段已存在时旧语法仍被兼容解析，不重复迁移。
        self._migrate_legacy_magic_strings()

        # 初始化第三方通知发送器（MP内置通知由 post_message 直接处理）
        self._my_send = MySender(self._notification_token)

        if not self._my_send.init_success:
            self._my_send = None
        if not self._my_send or not self._my_send.other_channel:
            if self._await_ip:
                logger.info("未配置第三方通知Token，「IP变动后通知」已自动关闭")
            self._await_ip = False

        # 处理多WAN口
        if self._wan_enabled:
            max_ips = int(self._wan_max_ips) if self._wan_max_ips.isdigit() and int(self._wan_max_ips) > 0 else 3
            self.wan2 = IpLocationParser(self._settings_file_path, max_ips=max_ips)
            self._current_ip_address = self.wan2.read_ips("ips")
        else:
            self.wan2 = None
            self._current_ip_address = self.cfg.get("WECHAT_NOW_IP")

        # 停止之前残留的任务，若未完全停止则跳过启动
        if not self.stop_service():
            logger.warning("仍有后台任务未退出，跳过启动新后台循环")
            self.__update_config()
            return

        # 重置停止标志，使新任务可以启动
        self._stopping = False
        self._loops_started = False

        # 配置检查（缺失时站内提示，不再只写日志）
        if not self._input_id_list:
            logger.warning("插件未配置应用ID，请填写企业微信应用ID")
            if self._enabled:
                self.systemmessage.put("【动态企微可信IP】已启用但未填写应用ID，不会执行任何检测，请到插件配置页填写")
            self.__update_config()
            return
        # 100000x 开头的应用ID是企微原生自建应用，插件不支持且会静默拒绝——
        # 站内提示，别让用户照着旧占位符填完还在绿条下等一个永不发生的结果
        bad_ids = [a.strip() for a in str(self._input_id_list).split(",")
                   if a.strip().startswith("100000") and len(a.strip()) == 7]
        if bad_ids:
            logger.warning(f"应用ID包含不支持的100000x格式: {bad_ids}")
            self.systemmessage.put(
                f"【动态企微可信IP】应用ID {','.join(bad_ids)} 是100000x开头的自建应用，插件不支持，"
                "这些ID会被跳过；请到插件配置页改用企业微信应用页面URL末尾的通讯录应用ID")
        if self._enabled and not str(self._cron or "").strip():
            logger.warning("未配置检测周期，IP检测不会运行")
            self.systemmessage.put("【动态企微可信IP】未配置检测周期，IP变化不会被自动更新，请到插件配置页填写")

        # 启用插件时启动后台循环和一次性任务
        if (self._enabled or self._onlyonce) and self._input_id_list:
            self._start_background_loops()
            self._handle_once_tasks()

        self.__update_config()

    def _migrate_legacy_magic_strings(self):
        """
        把旧版塞在应用ID字段里的魔法语法拆到独立字段（一次性、幂等）：
        - 「ids||wanN」→ wan_enabled=True + wan_max_ips=N
        - 「ids||url1,url2」→ custom_ip_urls=url1,url2
        新字段已有值时不覆盖（用户可能在迁移后自行改过）；应用ID只保留逗号分隔的ID部分。
        """
        input_ids = self._input_id_list
        if not isinstance(input_ids, str) or "||" not in input_ids:
            return
        ids_part, suffix = input_ids.split("||", 1)
        ids_part = ids_part.strip()
        suffix = suffix.strip()
        if suffix.startswith("wan"):
            # 多WAN语法
            if not self._wan_enabled:
                self._wan_enabled = True
                digit = suffix[3:].strip()
                if digit.isdigit():
                    self._wan_max_ips = digit
                logger.info(f"检测到旧版多WAN语法「||{suffix}」，已迁移到「多WAN多出口」开关（最多{self._wan_max_ips or 3}个出口IP）")
        elif "," in suffix or suffix.startswith("http"):
            # 自定义探测URL语法
            if not self._custom_ip_urls:
                self._custom_ip_urls = suffix
                logger.info("检测到旧版自定义探测URL语法，已迁移到「自定义公网IP探测地址」字段")
        else:
            logger.warning(f"应用ID中包含无法识别的「||{suffix}」后缀，已忽略；应用ID只保留 {ids_part}")
        if ids_part != input_ids:
            self._input_id_list = ids_part

    def _handle_once_tasks(self):
        """
        处理一次性任务（onlyonce / forced_update / local_scan）
        这些任务仅在用户点击保存或手动触发时执行一次
        """
        if self._onlyonce:
            if self.wan2:
                if not self._forced_update or not self._local_scan:
                    logger.info("多网络出口检查需要时间较长，预计25秒内完成")
                    # 顺序执行，避免 check 读取到旧的 wan2_url 或 IP 文件
                    async def run_wan2_once():
                        await self.write_wan2_ip()
                        if not self._stopping:
                            await self.check()
                    self._start_bg_task(run_wan2_once())
            else:
                if not self._forced_update or not self._local_scan:
                    self._start_bg_task(self.check())
            self._onlyonce = False

        if self._forced_update:
            if not self._local_scan:
                logger.info("使用Cookie强制更新公网IP")
                self._start_bg_task(self.forced_change())
            self._forced_update = False

        if self._local_scan:
            logger.info("使用本地扫码登陆")
            self._start_bg_task(self.local_scanning())
            self._local_scan = False

    def _start_background_loops(self):
        """
        启动周期性后台循环任务（兼容有/无事件循环环境）
        防止重复启动，使用 _loops_started 标志控制
        """
        if self._loops_started:
            logger.debug("后台循环已启动，忽略重复调用")
            return
        self._loops_started = True

        # 无论有无循环，都通过 _start_bg_task 启动，它内部会处理
        self._start_bg_task(self._refresh_cookie_loop())
        if self._cron:
            self._start_bg_task(self._check_ip_loop())

    async def _refresh_cookie_loop(self):
        """
        周期性刷新cookie的后台循环
        使用CronTrigger计算下次执行时间，睡眠期间每1秒检查停止标志
        """
        tz = pytz.timezone(settings.TZ) if settings.TZ else pytz.utc
        try:
            trigger = CronTrigger.from_crontab(self._refresh_cron, timezone=tz)
        except Exception as e:
            logger.error(f"Cookie刷新定时器配置错误: {e}，任务退出")
            return
        while not self._stopping:
            if not self._enabled:
                break
            now = datetime.now(tz)
            next_time = trigger.get_next_fire_time(None, now)
            if not next_time:
                logger.error("无法计算下一次执行时间，Cookie刷新任务退出")
                break
            delay = (next_time - now).total_seconds()
            # 短睡眠轮询，及时响应停止信号
            while delay > 0 and not self._stopping and self._enabled:
                sleep_sec = min(delay, 1.0)
                await asyncio.sleep(sleep_sec)
                delay = (next_time - datetime.now(tz)).total_seconds()
            if self._stopping or not self._enabled:
                break
            try:
                await self.refresh_cookie()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"刷新cookie循环异常: {e}")
        logger.info("Cookie刷新循环已退出")

    async def _check_ip_loop(self):
        """
        周期性检查IP的后台循环
        多WAN模式时先刷新出口IP列表，再执行检查
        """
        tz = pytz.timezone(settings.TZ) if settings.TZ else pytz.utc
        try:
            trigger = CronTrigger.from_crontab(self._cron, timezone=tz)
        except Exception as e:
            logger.error(f"IP检测定时器配置错误: {e}，任务退出")
            return
        while not self._stopping:
            if not self._enabled:
                break
            now = datetime.now(tz)
            next_time = trigger.get_next_fire_time(None, now)
            if not next_time:
                logger.error("无法计算下一次执行时间，IP检测任务退出")
                break
            delay = (next_time - now).total_seconds()
            while delay > 0 and not self._stopping and self._enabled:
                sleep_sec = min(delay, 1.0)
                await asyncio.sleep(sleep_sec)
                delay = (next_time - datetime.now(tz)).total_seconds()
            if self._stopping or not self._enabled:
                break
            try:
                # 多WAN模式：先刷新出口IP
                if self.wan2:
                    await self.write_wan2_ip()
                await self.check()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"IP检测循环异常: {e}")
        logger.info("IP检测循环已退出")

    def _start_bg_task(self, coro):
        """
        启动一个后台协程并自动跟踪（兼容有/无事件循环）
        有循环时创建Task，无循环时在新线程中运行并监控停止标志
        """
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(coro)
            self._bg_tasks.append(task)
            def cleanup(t):
                try:
                    if t in self._bg_tasks:
                        self._bg_tasks.remove(t)
                except ValueError:
                    pass
            task.add_done_callback(cleanup)
        except RuntimeError:
            # 无循环，在新线程中运行，并主动监控 _stopping 以取消协程
            def run():
                async def runner():
                    task = asyncio.create_task(coro)
                    try:
                        while not task.done():
                            if self._stopping:
                                task.cancel()
                                break
                            await asyncio.sleep(0.5)
                        await task
                    except asyncio.CancelledError:
                        logger.debug("后台协程已取消")
                    except Exception as e:
                        logger.error(f"后台协程执行失败: {e}")

                asyncio.run(runner())

            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            self._bg_threads.append(thread)

    async def _acquire_file_lock(self):
        """
        带超时的文件锁获取（非阻塞轮询）
        避免协程取消后锁未释放导致永久阻塞
        """
        try:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.FILE_LOCK_TIMEOUT
            while not self._file_lock.acquire(blocking=False):
                remaining = deadline - loop.time()
                if remaining <= 0:
                    logger.warning("获取文件锁超时")
                    return False
                await asyncio.sleep(min(0.1, remaining))
            return True
        except Exception as e:
            logger.warning(f"获取文件锁异常: {e}")
            return False

    # ---------- 异步核心方法 ----------

    async def forced_change(self, event: Event = None):
        """
        强制修改IP（使用已保存的Cookie）
        事件触发入口，需检查 event_data 中的 action
        """
        if not self._enabled:
            logger.error("插件未开启")
            return
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "dynamicwechat":
                return
        context = None
        try:
            context = await self._launch_browser_context_with_retry(headless=True)
            cookie = await self.get_cookie_async()
            if cookie:
                await context.add_cookies(cookie)
            page = await context.new_page()
            await page.goto(self._wechatUrl)
            await asyncio.sleep(3)
            if await self.check_login_status(page, task='forced_change'):
                await self.click_app_management_buttons(page)
            else:
                logger.error("cookie失效,强制修改IP失败：请使用'本地扫码修改IP'")
                self._cookie_valid = False
                self._cookie_invalid_notified = False
        except Exception as err:
            logger.error(f"强制修改IP失败: {err}")
        finally:
            if context:
                await context.close()
                await asyncio.sleep(0.5)
        logger.info("----------------------本次任务结束----------------------")

    async def local_scanning(self, event: Event = None):
        """
        本地扫码登录
        生成二维码并等待用户扫码，成功登录后更新Cookie并修改可信IP
        """
        if not self._enabled:
            logger.error("插件未开启")
            return
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "dynamicwechat":
                return
        context = None
        self._qr_running = True
        try:
            context = await self._launch_browser_context_with_retry(headless=True)
            page = await context.new_page()
            await page.goto(self._wechatUrl)
            await asyncio.sleep(3)
            img, _ = await self.find_qrc(page)
            if img:
                self.systemmessage.put("✅ 二维码已生成，请点击插件面板查看扫码")
                current_time = datetime.now()
                future_time = current_time + timedelta(seconds=self.QR_CODE_EXPIRE_SECONDS)
                self._future_timestamp = int(future_time.timestamp())
                logger.info("请重新进入插件面板扫码! 每20秒检查登录状态,最大尝试5次")
                for attempt in range(self.QR_CODE_MAX_ATTEMPTS):
                    # 短轮询，每1秒检查一次停止信号
                    for _ in range(self.QR_CODE_CHECK_INTERVAL):
                        if self._stopping:
                            logger.debug("收到停止信号，退出扫码等待")
                            return
                        await asyncio.sleep(1)
                    if await self.check_login_status(page, task='local_scanning'):
                        await self._update_cookie(page, context)
                        await self.click_app_management_buttons(page)
                        break
                else:
                    logger.info("用户可能没有扫码或登录失败")
            else:
                logger.error("未找到二维码,任务结束")
            logger.info("----------------------本次任务结束----------------------")
        except Exception as e:
            logger.error(f"本地扫码任务失败: {e}")
        finally:
            self._qr_running = False
            if context:
                await context.close()
                await asyncio.sleep(0.5)

    async def write_wan2_ip(self, event: Event = None):
        """
        获取多WAN出口IP并写入配置文件
        从多个IP检测网站轮流获取，成功则更新 wan2_url
        """
        if not self._enabled:
            logger.error("插件未开启")
            return
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "dynamicwechat":
                return
        urls = ["https://ip.skk.moe/multi", "https://ip.m27.tech", "https://ip.orz.tools"]
        random.shuffle(urls)
        self.wan2_url = None
        for url in urls:
            context = None
            try:
                context = await self._launch_browser_context_with_retry(headless=url != "https://ip.skk.moe/multi")
                page = await context.new_page()
                china_ips = await self.wan2.get_ipv4(page, url)
                if china_ips:
                    if await self._acquire_file_lock():
                        try:
                            await self.wan2.overwrite_ips_async("url_ip", china_ips)
                            self.wan2_url = url
                            break
                        finally:
                            self._file_lock.release()
                    else:
                        logger.warning(f"获取文件锁超时，放弃写入 {url} 的IP，尝试下一个")
                        continue
            except asyncio.CancelledError:
                logger.debug("任务被取消，放弃写入多WAN IP")
                return
            except asyncio.TimeoutError as e:
                logger.warning(f"{url} 多出口IP获取超时, Error: {e}")
                continue
            except Exception as e:
                logger.warning(f"{url} 多出口IP获取失败, Error: {e}")
            finally:
                if context:
                    await context.close()
                    await asyncio.sleep(0.5)

    async def check(self, event: Event = None):
        """
        主检测任务（定时执行）
        根据cookie有效性决定是否检查IP，并依据配置决定是否立即通知
        """
        if not self._enabled:
            logger.error("插件未开启")
            return
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "dynamicwechat":
                return
        # 情况1：cookie有效，正常检测IP并更新
        if self._cookie_valid:
            logger.info("开始检测公网IP")
            if await self.CheckIP():
                await self.ChangeIP()
                self.__update_config()
            logger.info("----------------------本次任务结束----------------------")
            return
        # 情况2：cookie失效但启用了"IP变动后通知"
        if self._await_ip:
            logger.info("开始检测公网IP,等待IP变动后发送通知")
            if await self.CheckIP(func="public"):
                await self._send_cookie_false()
            logger.info("----------------------本次任务结束----------------------")
            return
        # 情况3：cookie失效且未启用延迟通知，立即通知
        logger.info("Cookie已失效，本次不检查IP")
        self._last_ip_check_ok = False
        self._last_ip_check_note = "Cookie已失效，本轮未检测IP"
        await self._send_cookie_false()

    def _translate_check_result(self, reason) -> str:
        """把 check_login_status 的结论原因转译成一句用户可读的说明"""
        return {
            'stopped': '插件正在重启或停用',
            'timeout': '网络较慢或企业微信页面变化，未能确认登录状态',
            'captcha_incomplete': '扫码后的验证码流程未完成',
            'captcha_btn_error': '验证码确认环节页面异常',
            'logged_in': '登录正常',
            'qr_visible': '页面显示登录二维码（未登录）',
            'captcha_no_code': '未收到短信验证码',
            'captcha_failed': '验证码已提交但登录未成功',
        }.get(reason, '原因未知')

    async def CheckIP(self, func=None):
        """
        检测IP是否变化
        多WAN模式从配置文件读取已保存的IP列表，单IP模式直接从网络获取
        返回True表示IP已变化需要更新，否则False
        """
        # DDNS域名模式：解析域名获取动态公网IP，优先于多WAN和URL检测
        # 支持多个域名（英文逗号分隔）：全部解析并合并且分号拼接，任一成功即可用
        company_domain = str(getattr(self, "_company_domain", "") or "").strip()
        if company_domain:
            ip_address, ok_domains, failed_domains = await asyncio.to_thread(
                self.resolve_domains, company_domain)
            if not ip_address:
                logger.error(f"DDNS 域名全部解析失败（{company_domain}），不操作可信IP")
                self._last_ddns_ok = False
                self._last_ip_check_ok = False
                self._last_ip_check_note = "DDNS域名解析失败，未改动可信IP"
                return False
            if failed_domains:
                logger.warning(f"部分 DDNS 域名解析失败：{','.join(failed_domains)}；已用：{','.join(ok_domains)}")
            logger.info(f"IP获取成功: 解析域名 {','.join(ok_domains)}: {ip_address}")
            self._last_ddns_ok = True
            self._last_ddns_ip = str(ip_address)
            if not self._ip_changed and func != "public":
                logger.info("上次IP修改IP失败 继续尝试修改IP")
                return True
            if ip_address != self._current_ip_address:
                logger.info("检测到IP变化")
                self._wechat_available = False
                self._cookie_invalid_notified = False
                return True
            return False
        if self.wan2:
            # 多WAN模式：读取保存的url_ip和ips
            if not await self._acquire_file_lock():
                logger.warning("获取文件锁超时，跳过IP检查")
                return False
            try:
                ip_address = await self.wan2.read_ips_async("url_ip")
                # url用于日志展示，若为空则使用默认文本，不阻断检测
                url = self.wan2_url or "已保存的多WAN检测结果"
                saved_ips = await self.wan2.read_ips_async("ips")
            finally:
                self._file_lock.release()
            if not ip_address or ip_address == "获取IP失败":
                logger.error("获取IP失败 不操作可信IP")
                self._last_ip_check_ok = False
                self._last_ip_check_note = "多WAN出口IP获取失败，未改动可信IP"
                return False
            if url and ip_address:
                logger.info(f"IP获取成功: {url}: {ip_address}")
            if not self._ip_changed and func != "public":
                logger.info("上次IP修改IP失败 继续尝试修改IP")
                return True
            if isinstance(ip_address, str):
                url_ips = [ip for ip in ip_address.split(";") if ip]
            else:
                url_ips = [ip for ip in ip_address if ip]
            if not url_ips:
                self._last_ip_check_ok = False
                self._last_ip_check_note = "多WAN未检测到出口IP"
                return False
            self._last_ip_check_ok = True
            self._last_ip_check_note = "多WAN出口IP未变化"
            saved_ips_list = [ip for ip in saved_ips.split(";") if ip] if saved_ips else []
            need_add = False
            for ip in url_ips:
                if ip not in saved_ips_list:
                    need_add = True
                    break
            if need_add:
                if not await self._acquire_file_lock():
                    logger.warning("获取文件锁超时，无法添加新IP")
                    return False
                try:
                    for ip in url_ips:
                        if ip not in saved_ips_list:
                            await self.wan2.add_ips_async("ips", ip)
                finally:
                    self._file_lock.release()
                # 检测到IP变化，重置通知标志
                self._cookie_invalid_notified = False
                return True
            return False
        else:
            # 单IP模式：从网络获取当前公网IP
            url, ip_address = await self.get_ip_from_url()
            if not ip_address or ip_address == "获取IP失败" or not url:
                logger.error("获取IP失败 不操作可信IP")
                self._last_ip_check_ok = False
                self._last_ip_check_note = "公网IP获取失败，未改动可信IP"
                return False
            if url and ip_address:
                logger.info(f"IP获取成功: {url}: {ip_address}")
            if not self._ip_changed and func != "public":
                logger.info("上次IP修改IP失败 继续尝试修改IP")
                return True
            if ip_address != self._current_ip_address:
                logger.info("检测到IP变化")
                self._cookie_invalid_notified = False  # 重置通知标志
                self._last_ip_check_ok = True
                self._last_ip_check_note = "检测到IP变化，正在更新可信IP"
                return True
            self._last_ip_check_ok = True
            self._last_ip_check_note = "公网IP未变化"
        return False

    async def try_connect_cc_async(self):
        """异步连接CookieCloud服务器"""
        if not self._use_cookiecloud:
            self._cc_server = None
            return
        if not settings.COOKIECLOUD_KEY or not settings.COOKIECLOUD_PASSWORD:
            self._cc_server = None
            logger.error("没有配置CookieCloud的用户KEY和PASSWORD")
            return
        if settings.COOKIECLOUD_ENABLE_LOCAL:
            self._cc_server = PyCookieCloud(
                url=self._server,
                uuid=settings.COOKIECLOUD_KEY,
                password=settings.COOKIECLOUD_PASSWORD
            )
            logger.info("使用内建CookieCloud服务器")
        else:
            self._cc_server = PyCookieCloud(
                url=settings.COOKIECLOUD_HOST,
                uuid=settings.COOKIECLOUD_KEY,
                password=settings.COOKIECLOUD_PASSWORD
            )
            logger.info("使用自定义CookieCloud服务器")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self._cc_server.url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                    if resp.status != 200:
                        self._cc_server = None
                        logger.error("没有可用的CookieCloud服务器")
        except Exception as e:
            self._cc_server = None
            logger.error(f"CookieCloud连接失败: {e}")

    async def get_ip_from_url(self) -> (str, str):
        """
        从URL获取IP地址
        多WAN分支：锁失败则继续尝试下一个URL，避免返回未保存的数据
        """
        custom_urls = str(getattr(self, "_custom_ip_urls", "") or "").strip()
        if custom_urls:
            urls = [u.strip() for u in custom_urls.split(",") if u.strip()]
        elif isinstance(self._input_id_list, list):
            urls = self._input_id_list
        else:
            urls = self._ip_urls
        random.shuffle(urls)
        if not self.wan2:
            async with aiohttp.ClientSession() as session:
                for url in urls:
                    try:
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as response:
                            if response.status == 200:
                                text = await response.text()
                                ip_address = re.search(self._ip_pattern, text)
                                if ip_address:
                                    return url, ip_address.group()
                    except Exception as e:
                        if "104" not in str(e) and 'Read timed out' not in str(e):
                            logger.warning(f"{url} 获取IP失败, Error: {e}")
            return None, "获取IP失败"
        else:
            urls = ["https://ip.skk.moe/multi", "https://ip.m27.tech", "https://ip.orz.tools"]
            random.shuffle(urls)
            for url in urls:
                context = None
                try:
                    context = await self._launch_browser_context_with_retry(headless=url != "https://ip.skk.moe/multi")
                    page = await context.new_page()
                    china_ips = await self.wan2.get_ipv4(page, url)
                    if china_ips:
                        if await self._acquire_file_lock():
                            try:
                                await self.wan2.overwrite_ips_async("url_ip", china_ips)
                                self.wan2_url = url
                                return url, china_ips
                            finally:
                                self._file_lock.release()
                        else:
                            logger.warning(f"获取文件锁超时，放弃写入 {url} 的IP，尝试下一个")
                            continue
                except asyncio.CancelledError:
                    logger.debug("任务被取消，放弃获取多WAN IP")
                    return None, "获取IP失败"
                except asyncio.TimeoutError as e:
                    logger.warning(f"{url} 多出口IP获取超时, Error: {e}")
                except Exception as e:
                    logger.warning(f"{url} 多出口IP获取失败, Error: {e}")
                finally:
                    if context:
                        await context.close()
                        await asyncio.sleep(0.5)
            self.wan2_url = None
            return None, "获取IP失败"

    def get_ip_from_domain(self, domain) -> str:
        """
        解析DDNS域名获取当前公网IP（IP动态变化时，域名始终指向最新IP）
        """
        if not domain or not str(domain).strip():
            return "获取IP失败"
        try:
            import socket
            ip_address = socket.gethostbyname(str(domain).strip())
            if re.match(self._ip_pattern, ip_address):
                return ip_address
            return "获取IP失败"
        except Exception as e:
            logger.warning(f"域名{domain}解析失败,Error: {e}")
            return "获取IP失败"

    def resolve_domains(self, raw: str) -> Tuple[str, List[str], List[str]]:
        """
        解析配置中的多个 DDNS 域名（英文逗号分隔），返回 (合并IP串, 成功域名, 失败域名)。

        语义：所有域名都解析，结果去重后合并且分号拼接（多线路场景可一次填入多个出口IP）；
        只要有任一域名解析成功就返回可用结果，只有全部失败时合并IP串为空。
        纯函数式：除日志外不修改实例状态，便于测试。
        """
        domains = [d.strip() for d in str(raw or "").replace("，", ",").split(",") if d.strip()]
        if not domains:
            return "", [], []
        ok_ips: List[str] = []
        ok_domains: List[str] = []
        failed_domains: List[str] = []
        for domain in domains:
            ip = self.get_ip_from_domain(domain)
            if not ip or ip == "获取IP失败":
                failed_domains.append(domain)
                continue
            ok_domains.append(domain)
            # 同一域名可能被多个域名指向同一出口，去重但保留顺序
            for single in str(ip).split(";"):
                single = single.strip()
                if single and single not in ok_ips:
                    ok_ips.append(single)
        if failed_domains:
            logger.warning(f"DDNS 解析失败的域名：{','.join(failed_domains)}（其余域名已生效）")
        return ";".join(ok_ips), ok_domains, failed_domains

    async def find_qrc(self, page):
        """
        查找二维码图片
        返回二维码URL和过期时间，同时将图片数据保存到 _qr_code_image
        """
        try:
            await page.wait_for_selector("iframe", timeout=5000)
            iframe_element = await page.query_selector("iframe")
            if not iframe_element:
                logger.warning("未找到iframe元素")
                return None, None
            frame = await iframe_element.content_frame()
            if not frame:
                logger.warning("无法获取iframe内容")
                return None, None
            qr_code_element = await frame.query_selector("img.qrcode_login_img")
            if qr_code_element:
                qr_code_url = await qr_code_element.get_attribute('src')
                if qr_code_url.startswith("/"):
                    qr_code_url = "https://work.weixin.qq.com" + qr_code_url
                async with aiohttp.ClientSession() as session:
                    async with session.get(qr_code_url) as resp:
                        qr_code_data = await resp.read()
                self._qr_code_image = io.BytesIO(qr_code_data)
                refuse_time = (datetime.now() + timedelta(seconds=self.QR_CODE_EXPIRE_SECONDS + self.QR_CODE_REFUSE_OFFSET)).strftime("%Y-%m-%d %H:%M:%S")
                return qr_code_url, refuse_time
            else:
                logger.warning("未找到二维码")
                return None, None
        except asyncio.TimeoutError:
            logger.debug("iframe 等待超时（正常）")
            return None, None
        except Exception as e:
            logger.warning(f"查找二维码异常: {e}")
            return None, None

    async def ChangeIP(self):
        """
        修改可信IP
        若二维码出现说明cookie失效，转通知用户；否则直接修改
        """
        logger.info("开始请求企业微信管理更改可信IP")
        context = None
        try:
            context = await self._launch_browser_context_with_retry(headless=True)
            cookie = await self.get_cookie_async()
            if cookie:
                await context.add_cookies(cookie)
            page = await context.new_page()
            await page.goto(self._wechatUrl)
            await asyncio.sleep(3)
            img_src, refuse_time = await self.find_qrc(page)
            if img_src:
                if self._my_send:
                    self._ip_changed = False
                    await self._send_cookie_false()
                    logger.info("已尝试发送cookie失效通知")
                else:
                    self._ip_changed = False
                    self._cookie_valid = False
                    self._cookie_invalid_notified = False
                    logger.info("cookie已失效,且没有配置通知方式,本次修改可信IP失败")
            else:
                logger.info("尝试cookie登录")
                if await self.check_login_status(page, ""):
                    await self.click_app_management_buttons(page)
                else:
                    logger.info("发生了意料之外的错误,请附上配置信息到github反馈")
                    await self._send_cookie_false()
                    self._ip_changed = False
        except Exception as e:
            self._ip_changed = False
            logger.error(f"更改可信IP失败: {e}")
        finally:
            if context:
                await context.close()
                await asyncio.sleep(0.5)

    async def _update_cookie(self, page, context):
        """
        更新cookie（使用线程锁保护文件操作）
        先从浏览器获取当前cookie，然后重置生命周期并同步到CookieCloud
        """
        self._future_timestamp = 0
        # 1. 先从浏览器获取cookie（即使云端更新失败，也标记cookie有效）
        try:
            current_url = page.url
            current_cookies = await context.cookies(current_url)
            if current_cookies:
                self._saved_cookie = current_cookies
                self._cookie_valid = True
                self._cookie_invalid_notified = False
                self._is_special_upload = True
                logger.info("从浏览器获取cookie成功")
            else:
                logger.error("无法从内置浏览器获取 cookies")
                self._cookie_valid = False
                self._cookie_invalid_notified = False
                return
        except Exception as e:
            logger.error(f"获取浏览器cookie失败: {e}")
            self._cookie_valid = False
            self._cookie_invalid_notified = False
            return
        # 2. 重置Cookie生命周期（可选步骤，超时不阻断）
        if await self._acquire_file_lock():
            try:
                await PyCookieCloud.save_cookie_lifetime_async(self._settings_file_path, 0)
            finally:
                self._file_lock.release()
        else:
            logger.warning("获取文件锁超时，跳过Cookie生命周期重置")
        # 3. 更新到CookieCloud（如果启用）
        if self._use_cookiecloud:
            if not self._cc_server:
                await self.try_connect_cc_async()
                if self._cc_server is None:
                    logger.warning("CookieCloud不可用，但本地cookie已保存")
                    return
            try:
                if not await self._cc_server.check_connection_async():
                    logger.error(f"连接 CookieCloud 失败: {self._cc_server.url}")
                    return
                formatted_cookies = {}
                for cookie in current_cookies:
                    domain = cookie.get('domain')
                    if domain is None:
                        continue
                    if domain not in formatted_cookies:
                        formatted_cookies[domain] = []
                    formatted_cookies[domain].append(cookie)
                update_success = await asyncio.to_thread(self._cc_server.update_cookie, formatted_cookies)
                if update_success:
                    logger.info("更新 CookieCloud 成功")
                    self._is_special_upload = True
                else:
                    logger.error("更新 CookieCloud 失败，但本地cookie已有效")
                    self._is_special_upload = False
            except Exception as e:
                logger.error(f"CookieCloud更新 cookie 发生错误: {e}")
        else:
            self._is_special_upload = True  # 不用cookiecloud 也显示cookie寿命
            logger.info("更新本地 Cookie成功")

    async def _send_cookie_false(self):
        """
        发送cookie失效通知（异步版本），线程安全去重
        同时尝试：1. MoviePilot内置WeChat通知  2. 所有第三方通知通道
        至少一个成功就标记为已通知。
        """
        with self._notify_lock:
            if getattr(self, "_cookie_invalid_notified", False):
                return None
            # 占位，防止并发
            self._cookie_invalid_notified = True
            self._cookie_valid = False

        notified = False
        try:
            success_count = 0
            fail_count = 0

            # 1. 尝试MoviePilot内置通知（由 use_mp_notify 控制，MP管理所有渠道）
            if self._use_mp_notify:
                try:
                    await asyncio.to_thread(
                        self.post_message,
                        mtype=MessageType.Plugin,
                        title="cookie已失效,请及时更新",
                        text="请在企业微信应用发送/push_qr, 验证码以'？'结束发送到企业微信应用。"
                    )
                    success_count += 1
                    logger.info("MP内置通知发送成功")
                except Exception as e:
                    logger.error(f"MP内置通知发送失败：{e}")
                    fail_count += 1

            # 2. 遍历所有第三方通知通道（由 notification_token 配置）
            if self._my_send and self._my_send.other_channel:
                for channel, token in self._my_send.other_channel:
                    try:
                        error = await asyncio.to_thread(
                            self._my_send.send,
                            title="cookie已失效,请及时更新",
                            content="请在企业微信应用发送/push_qr, 验证码以'？'结束发送到企业微信应用。",
                            image=None, force_send=False, diy_channel=channel, diy_token=token
                        )
                        if error:
                            logger.error(f"第三方通道 {channel} 发送失败，原因：{error}")
                            fail_count += 1
                        else:
                            success_count += 1
                            logger.info(f"第三方通道 {channel} 发送成功")
                    except Exception as e:
                        logger.error(f"第三方通道 {channel} 发送异常：{e}")
                        fail_count += 1

            # 汇总结果
            if success_count > 0:
                notified = True
                logger.info(f"cookie失效通知发送完成：成功 {success_count} 个，失败 {fail_count} 个")
            elif not self._use_mp_notify and (not self._my_send or not self._my_send.other_channel):
                logger.warning("cookie已失效，但未配置任何通知方式，用户可能无法及时感知")
                self.systemmessage.put("cookie已失效，请及时更新，当前未配置通知方式")
                notified = True
            else:
                self.systemmessage.put("cookie已失效，且所有通知方式均发送失败，请手动更新cookie")
                notified = True

            return None
        finally:
            if not notified:
                with self._notify_lock:
                    self._cookie_invalid_notified = False

    async def _push_qr_code_async(self, event: Event = None):
        """
        异步推送二维码（使用线程锁保护状态）
        生成二维码并通过配置的通知渠道发送给用户
        同时尝试：1. MoviePilot内置WeChat通知  2. 所有第三方通知通道
        """
        if not self._enabled or not event:
            return
        if not self._qr_lock.acquire(blocking=False):
            logger.info("二维码推送任务正在执行，忽略重复触发")
            return
        try:
            self._qr_running = True
            context = None
            try:
                context = await self._launch_browser_context_with_retry(headless=True)
                page = await context.new_page()
                await page.goto(self._wechatUrl)
                await asyncio.sleep(3)
                image_src, refuse_time = await self.find_qrc(page)
                if image_src:
                    if self._my_send:
                        success_count = 0
                        fail_count = 0

                        # 1. 尝试MoviePilot内置通知（由 use_mp_notify 控制，MP管理所有渠道）
                        if self._use_mp_notify:
                            try:
                                await asyncio.to_thread(
                                    self.post_message,
                                    mtype=MessageType.Plugin,
                                    title="企业微信登录二维码",
                                    image=image_src
                                )
                                success_count += 1
                                logger.info("MP内置通知推送二维码成功")
                            except Exception as e:
                                logger.error(f"MP内置通知推送二维码失败：{e}")
                                fail_count += 1

                        # 2. 遍历所有第三方通知通道（由 notification_token 配置）
                        if self._my_send and self._my_send.other_channel:
                            for channel, token in self._my_send.other_channel:
                                try:
                                    error = await asyncio.to_thread(
                                        self._my_send.send,
                                        title="企业微信登录二维码",
                                        image=image_src, diy_channel=channel, diy_token=token
                                    )
                                    if error:
                                        logger.error(f"第三方通道 {channel} 推送二维码失败，原因：{error}")
                                        fail_count += 1
                                    else:
                                        success_count += 1
                                        logger.info(f"第三方通道 {channel} 推送二维码成功")
                                except Exception as e:
                                    logger.error(f"第三方通道 {channel} 推送二维码异常：{e}")
                                    fail_count += 1

                        # 汇总结果
                        if success_count == 0:
                            logger.warning("所有通知通道推送二维码均失败")
                            logger.info("----------------------本次任务结束----------------------")
                            return

                        logger.info(f"二维码推送完成：成功 {success_count} 个，失败 {fail_count} 个")
                        # 发送成功，开始等待扫码
                        logger.info("远程推送任务: 二维码发送成功,等待用户 80 秒内扫码登录。V2'微信通知'的用户,此消息并不准确")
                        for attempt in range(self.QR_CODE_MAX_ATTEMPTS):
                            # 短轮询检查停止信号
                            for _ in range(self.QR_CODE_CHECK_INTERVAL):
                                if self._stopping:
                                    logger.debug("收到停止信号，退出扫码等待")
                                    return
                                await asyncio.sleep(1)
                            if await self.check_login_status(page, 'push_qr_code'):
                                await self._update_cookie(page, context)
                                await self.click_app_management_buttons(page)
                                break
                            else:
                                logger.info("用户可能没有扫码或登录失败")
                    else:
                        logger.warning("远程推送任务: 没有找到可用的通知方式")
                else:
                    logger.warning("远程推送任务: 未找到二维码")
                logger.info("----------------------本次任务结束----------------------")
            except Exception as e:
                logger.error(f"远程推送任务失败: {e}")
            finally:
                if context:
                    await context.close()
                    await asyncio.sleep(0.5)
                self._qr_running = False
        finally:
            self._qr_lock.release()

    async def get_cookie_async(self):
        """
        异步获取企业微信 Cookie
        优先使用本地缓存，否则从CookieCloud下载
        """
        if self._saved_cookie and self._cookie_valid:
            return self._saved_cookie
        try:
            if not self._use_cookiecloud:
                return None
            result = await asyncio.to_thread(self._cookiecloud.download)
            # 兼容不同版本的CookieCloudHelper返回格式
            if isinstance(result, tuple):
                cookies, msg = result[0], result[1] if len(result) > 1 else ""
            else:
                cookies, msg = result, ""
            if not cookies:
                logger.error(f"CookieCloud获取cookie失败,失败原因：{msg}")
                return None
            cookie_header = ''
            for domain, cookie in cookies.items():
                if domain.lstrip(".").lower() == "work.weixin.qq.com":
                    cookie_header = cookie
                    break
            if cookie_header == '':
                cookie_header = self._cookie_header
            cookie = self.parse_cookie_header(cookie_header)
            return cookie
        except Exception as e:
            logger.error(f"从CookieCloud获取cookie错误,错误原因:{e}")
            return None

    def parse_cookie_header(self, cookie_header):
        """解析cookie头，返回格式化的cookie列表"""
        cookies = []
        self._is_special_upload = False
        if not cookie_header:
            return cookies
        for item in cookie_header.split(';'):
            item = item.strip()
            if not item or '=' not in item:
                continue
            name, value = item.split('=', 1)
            if name == '_upload_type' and value == 'A':
                self._is_special_upload = True
                continue
            cookies.append({
                'name': name,
                'value': value,
                'domain': '.work.weixin.qq.com',
                'path': '/'
            })
        return cookies

    async def refresh_cookie(self):
        """
        保活：刷新cookie（增强重试逻辑）
        若本地cookie失效，从CookieCloud获取新cookie；若仍无效，根据 _await_ip 决定是否立即通知
        """
        context = None
        try:
            context = await self._launch_browser_context_with_retry(headless=True)
            cookie_used = False
            # 尝试使用本地保存的cookie
            if self._saved_cookie:
                await context.add_cookies(self._saved_cookie)
                page = await context.new_page()
                await page.goto(self._wechatUrl)
                await asyncio.sleep(3)
                result = await self.check_login_status(page, task='refresh_cookie')
                if result is True:
                    self._cookie_valid = True
                    self._cookie_invalid_notified = False
                    cookie_used = True
                    self._last_keepalive_ok = True
                    self._last_keepalive_note = "本地Cookie校验有效"
                    self._waiting_captcha = False
                    logger.info("本地缓存 Cookie 有效")
                    self._none_streak = 0
                elif result is False:
                    self._cookie_valid = False
                    self._saved_cookie = None
                    self._last_keepalive_ok = False
                    self._last_keepalive_note = "本地Cookie已失效"
                    self._waiting_captcha = False
                    # 本地失效，若启用CookieCloud则暂不通知，等待云端尝试
                    if self._use_cookiecloud:
                        logger.info("本地缓存 Cookie 失效，尝试从 CookieCloud 获取")
                    elif self._await_ip:
                        logger.info("Cookie失效，等待公网IP变动后再通知")
                    else:
                        logger.info("本地缓存 Cookie 失效，发送通知")
                        await self._send_cookie_false()
                else:
                    self._cookie_valid = False
                    self._saved_cookie = None
                    reason = getattr(self, '_last_check_result', 'unknown')
                    self._none_streak = getattr(self, '_none_streak', 0) + 1
                    self._last_keepalive_ok = None
                    self._last_keepalive_note = self._translate_check_result(reason)
                    reason_text = {
                        'stopped': '插件正在重启或停用',
                        'timeout': '15秒内页面未给出登录/未登录信号（网络慢或企业微信页面结构变化）',
                        'captcha_incomplete': '扫码后的验证码流程未完成',
                        'captcha_btn_error': '验证码确认环节页面异常',
                    }.get(reason, f'未知原因({reason})')
                    logger.info(
                        f"本次 Cookie 校验无结论（{reason_text}），已尝试用 CookieCloud 备份 cookie 复核；"
                        f"若复核仍无效将发送失效通知，请留意后续消息。"
                    )
                    if self._none_streak >= 3:
                        logger.warning(
                            f"Cookie 校验已连续 {self._none_streak} 次无结论，此期间 Cookie 真实失效将无法被及时发现。"
                            f"请检查容器到 work.weixin.qq.com 的网络连通性；若网络正常则可能是企业微信后台改版，需等待插件更新。"
                                )
            # 若本地cookie无效，尝试从CookieCloud获取
            if not cookie_used and self._use_cookiecloud:
                logger.info("开始从 CookieCloud 获取 Cookie")
                cookie = await self.get_cookie_async()
                if cookie:
                    await context.add_cookies(cookie)
                    page = await context.new_page()
                    await page.goto(self._wechatUrl)
                    await asyncio.sleep(3)
                    if await self.check_login_status(page, task='refresh_cookie'):
                        self._cookie_valid = True
                        self._cookie_invalid_notified = False
                        self._saved_cookie = await context.cookies()
                        self._last_keepalive_ok = True
                        self._last_keepalive_note = "CookieCloud Cookie校验有效"
                        self._none_streak = 0
                    else:
                        self._cookie_valid = False
                        self._saved_cookie = None
                        self._last_keepalive_ok = False
                        self._last_keepalive_note = "CookieCloud Cookie已失效"
                        if self._await_ip:
                            logger.info("CookieCloud Cookie失效，等待公网IP变动后再通知")
                        else:
                            logger.info("CookieCloud Cookie失效，发送通知")
                            await self._send_cookie_false()
                else:
                    self._cookie_valid = False
                    self._saved_cookie = None
                    self._last_keepalive_ok = False
                    self._last_keepalive_note = "CookieCloud获取Cookie失败"
                    if self._await_ip:
                        logger.info("CookieCloud获取失败，等待公网IP变动后再通知")
                    else:
                        logger.info("CookieCloud获取失败，发送通知")
                        await self._send_cookie_false()
            # 如果cookie有效，延长生命周期
            if self._cookie_valid:
                if self._my_send:
                    self._my_send.reset_limit()
                if await self._acquire_file_lock():
                    try:
                        await PyCookieCloud.increase_cookie_lifetime_async(self._settings_file_path, 600)
                    finally:
                        self._file_lock.release()
                else:
                    logger.warning("获取文件锁超时，跳过增加Cookie生命周期")
                self._cookie_lifetime = await PyCookieCloud.load_cookie_lifetime_async(self._settings_file_path)
                logger.info(f"Cookie 保活成功，当前生命周期: {self._cookie_lifetime} 秒")
        except Exception as e:
            logger.error(f"cookie 校验过程中发生异常: {e}")
        finally:
            if context:
                await context.close()
                await asyncio.sleep(0.5)

    async def check_login_status(self, page, task):
        """
        检查登录状态，支持短信验证码输入。
        采用"成功信号 vs 失败信号（登录二维码）"竞速轮询，兼容慢网络与页面 DOM 变化。

        返回值（三态，调用方必须区分处理）:
          True  - 确认已登录
          False - 确认未登录（页面出现登录二维码，或验证码流程已走完且失败）
          None  - 检查无结论（预算内超时 / 页面异常 / 收到停止信号），
                  调用方不得据此修改 _cookie_valid、不得发送失效通知

        副作用：
          self._last_check_result   - 本次检查的最终结论原因，供调用方记录/描述：
              'logged_in' / 'qr_visible' / 'captcha_no_code' / 'captcha_failed'
              / 'timeout' / 'captcha_incomplete' / 'stopped'
              / 'captcha_btn_error'
          self._login_confirmed_by  - 登录由哪种信号确认：'url' / 'selector' / 'captcha'

        :param page:  当前浏览器页面
        :param task:  任务类型（refresh_cookie / local_scanning / push_qr_code 等）
        """
        if task != 'refresh_cookie':
            logger.info("检查登录状态...")
        else:
            logger.info("检查登录状态（保活）...")

        # 成功信号：多个备选选择器（任一命中即视为已登录），URL 作为不依赖 DOM 的兜底
        success_selectors = [
            "//div[contains(@class, 'js_show_ipConfig_dialog')]//a[contains(@class, '_mod_card_operationLink') and text()='配置']",
            '#_hmt_click > div.index_colRight > div > div.index_info > div > a',
            '#_hmt_click > div.index_colLeft > div.index_greeting.index_explore_text > div:nth-child(1)'
        ]
        CHECK_BUDGET_SECONDS = 15   # 登录态判定总预算
        POLL_INTERVAL = 1.0

        async def _poll_logged_in() -> Optional[str]:
            """
            非阻塞探测是否已登录。
            返回 'url' / 'selector' 表示命中的成功信号；None 表示未命中或本回合无法判断。
            """
            try:
                if 'wework_admin/frame' in page.url:
                    return 'url'
                for selector in success_selectors:
                    try:
                        if await page.query_selector(selector):
                            return 'selector'
                    except Exception as e:
                        logger.debug(f"选择器查询异常: {e}")
            except Exception as e:
                logger.debug(f"登录状态探测异常: {e}")
            return None

        async def _qr_visible() -> bool:
            """轻量探测登录二维码是否可见（不下载图片、不带阻塞等待）"""
            try:
                iframe = await page.query_selector("iframe")
                if not iframe:
                    return False
                frame = await iframe.content_frame()
                if not frame:
                    return False
                return bool(await frame.query_selector("img.qrcode_login_img"))
            except Exception:
                return False

        async def _handle_captcha_panel() -> Optional[bool]:
            """
            处理短信验证码面板（按插件流程仅扫码登录时会出现）。
            返回 True/False；被停止或页面异常时返回 None，交回主流程按无结论处理。
            """
            if task == 'local_scanning':
                await asyncio.sleep(3)
            else:
                logger.info("等待30秒,请将短信验证码请以'？'结束,发送到<企业微信应用> 如： 110301？")
                self._waiting_captcha = True
                try:
                    for _ in range(30):
                        if self._stopping:
                            self._last_check_result = 'stopped'
                            return None
                        if self._verification_code:
                            break
                        await asyncio.sleep(1)
                finally:
                    self._waiting_captcha = False
            if not self._verification_code:
                logger.error(
                    "未收到短信验证码，请以问号结尾发送到企业微信应用。如：510010? 使用全局AI助手需使用/wxcode 510010的格式发送验证码")
                self._last_check_result = 'captcha_no_code'
                return False
            # 输入验证码并确认
            for digit in self._verification_code:
                await page.keyboard.press(digit)
                await asyncio.sleep(0.3)
            try:
                confirm_button = await page.wait_for_selector('.confirm_btn', timeout=5000)
                if confirm_button:
                    await confirm_button.click()
            except Exception as e:
                logger.warning(f"点击验证码确认按钮失败: {e}")
                self._last_check_result = 'captcha_btn_error'
                return None
            # 确认后短轮询登录结果（兼容提交后的页面跳转延迟）
            for _ in range(6):
                if await _poll_logged_in():
                    self._verification_code = None
                    self._last_check_result = 'logged_in'
                    self._login_confirmed_by = 'captcha'
                    logger.info("验证码登录成功！")
                    return True
                await asyncio.sleep(1)
            logger.warning("验证码已提交但未确认登录成功")
            self._last_check_result = 'captcha_failed'
            return False

        # ---------- 主竞速轮询 ----------
        deadline = asyncio.get_event_loop().time() + CHECK_BUDGET_SECONDS
        captcha_seen = False
        while asyncio.get_event_loop().time() < deadline:
            if self._stopping:
                logger.debug("收到停止信号，登录状态检查中止")
                self._last_check_result = 'stopped'
                return None
            # 1) 成功信号
            hit = await _poll_logged_in()
            if hit:
                self._last_check_result = 'logged_in'
                self._login_confirmed_by = hit
                if task != 'refresh_cookie':
                    logger.info("登录成功！")
                return True
            # 2) 验证码面板（扫码登录成功后的二次短信验证）
            try:
                if await page.query_selector('.receive_captcha_panel'):
                    captcha_seen = True
                    result = await _handle_captcha_panel()
                    if result is not None:
                        return result
                    break  # 验证码流程无结论，不再继续轮询
            except Exception as e:
                logger.debug(f"验证码面板探测异常: {e}")
            # 3) 失败信号：登录二维码可见 = 确定未登录
            if await _qr_visible():
                if task not in ['refresh_cookie', 'local_scanning']:
                    logger.warning("用户没有扫描二维码")
                self._last_check_result = 'qr_visible'
                return False
            await asyncio.sleep(POLL_INTERVAL)

        # 预算耗尽仍无结论
        self._last_check_result = 'timeout' if not captcha_seen else 'captcha_incomplete'
        if captcha_seen:
            logger.warning("验证码流程未走完，本次登录检查无结论")
        else:
            logger.warning(f"{CHECK_BUDGET_SECONDS}秒内未能确认登录状态，本次检查无结论")
        return None


    async def click_app_management_buttons(self, page):
        """
        点击应用管理按钮，填入可信IP
        多WAN口时将所有出口IP用分号拼接，符合企业微信支持多IP的格式（最多120个）
        若获取IP失败则中止更新
        """
        self._cookie_valid = True
        self._cookie_invalid_notified = False
        bash_url = "https://work.weixin.qq.com/wework_admin/frame#apps/modApiApp/"
        buttons = [
            ("//div[contains(@class, 'js_show_ipConfig_dialog')]//a[contains(@class, '_mod_card_operationLink') and text()='配置']", "配置")
        ]
        # 获取当前IP地址，多WAN时加锁读取
        company_domain = str(getattr(self, "_company_domain", "") or "").strip()
        if company_domain:
            merged, ok_domains, failed_domains = await asyncio.to_thread(
                self.resolve_domains, company_domain)
            if not merged:
                # 全部域名都失败时不静默回退到其他来源，避免写错 IP
                self._ip_changed = False
                logger.error(f"DDNS 域名全部解析失败（{company_domain}），取消更新可信IP")
                self.systemmessage.put("DDNS域名全部解析失败，取消更新可信IP")
                return
            self._current_ip_address = merged
            logger.info(f"DDNS 解析到 {len(merged.split(';'))} 个IP（域名：{','.join(ok_domains)}）")
        elif self.wan2:
            ips_str = ""
            if await self._acquire_file_lock():
                try:
                    ips_str = await self.wan2.read_ips_async("ips")
                finally:
                    self._file_lock.release()
            else:
                logger.warning("获取文件锁超时，重新获取公网IP")
            ips_list = [ip for ip in ips_str.split(";") if ip] if ips_str else []
            if ips_list:
                self._current_ip_address = ";".join(ips_list)
                logger.info(f"多WAN口检测到 {len(ips_list)} 个出口IP，全部填入可信IP")
            else:
                _, self._current_ip_address = await self.get_ip_from_url()
                logger.warning("多WAN口未检测到有效IP，重新获取")
        else:
            _, self._current_ip_address = await self.get_ip_from_url()

        # 校验IP有效性
        ip_values = [ip for ip in str(self._current_ip_address).split(";") if ip]
        if not ip_values or self._current_ip_address == "获取IP失败":
            self._ip_changed = False
            logger.error("未获取到有效公网IP，取消更新可信IP")
            self.systemmessage.put("未获取到有效公网IP，取消更新可信IP，请检查网络或稍后重试")
            return

        # 解析应用ID列表（迁移后字段已纯净，兼容旧值仍含 || 后缀的情况）
        input_id_list = str(self._input_id_list or "")
        if "||" in input_id_list:
            input_id_list = input_id_list.split("||", 1)[0]
        id_list = [a for a in input_id_list.split(",") if a.strip()]
        app_urls = [f"{bash_url}{app_id.strip()}" for app_id in id_list]
        # 合并固定可信IP与当前检测到的IP
        fill_ips = self._merge_pinned_ips(self._current_ip_address)
        for app_url in app_urls:
            app_id = app_url.split("/")[-1]
            if app_id.startswith("100000") and len(app_id) == 7:
                self._ip_changed = False
                logger.warning("请根据 https://github.com/RamenRa/MoviePilot-Plugins 的说明进行配置应用ID")
                return
            await page.goto(app_url)
            await asyncio.sleep(2)
            for xpath, name in buttons:
                try:
                    button = await page.wait_for_selector(xpath, timeout=5000)
                    await button.click()
                    await page.wait_for_selector('textarea.js_ipConfig_textarea', timeout=5000)
                    input_area = page.locator('textarea.js_ipConfig_textarea')
                    confirm = page.locator('.js_ipConfig_confirmBtn')
                    await input_area.fill(fill_ips)
                    await confirm.click()
                    await asyncio.sleep(3)
                    self._ip_changed = True
                except Exception as e:
                    logger.error(f"未能找打开{app_url}或点击 '{name}' 按钮异常: {e}")
                    self._ip_changed = False
                    if "disabled" in str(e):
                        logger.info(f"应用{app_id} 已被禁用,可能是没有设置接收api")
            if self._ip_changed:
                # 保存到配置文件
                if await self._acquire_file_lock():
                    try:
                        await self.cfg.aupdate("WECHAT_NOW_IP", self._current_ip_address)
                    finally:
                        self._file_lock.release()
                else:
                    logger.warning("获取文件锁超时，跳过更新本地配置")
                self._send_notification = False
                masked_ips = [self.mask_ip(ip) for ip in fill_ips.split(';')]
                masked_ip_string = ";".join(masked_ips)
                logger.info(f"应用: {app_id} 输入IP：" + fill_ips)
                # IP 修改成功通知：MP内置通知 + 第三方通知
                if self._use_mp_notify:
                    try:
                        await asyncio.to_thread(
                            self.post_message,
                            mtype=MessageType.Plugin,
                            title="企业微信可信IP修改通知",
                            text=f"应用: {app_id} 修改成功，IP: {masked_ip_string}"
                        )
                    except Exception as e:
                        logger.error(f"MP内置通知发送失败：{e}")
                if self._my_send and not self._my_send.quiet_flag and self._my_send.other_channel:
                    for channel, token in self._my_send.other_channel:
                        await asyncio.to_thread(
                            self._my_send.send,
                            title="企业微信可信IP修改通知",
                            content=f"应用: {app_id} 修改成功，IP: {masked_ip_string}",
                            force_send=True, diy_channel=channel, diy_token=token
                        )

    def _merge_pinned_ips(self, detected_ips: str) -> str:
        """将固定可信IP与检测到的IP合并去重，固定IP始终保留"""
        pinned = [ip.strip() for ip in str(self._pinned_ips or '').split(',') if ip.strip()]
        detected = [ip.strip() for ip in str(detected_ips or '').split(';') if ip.strip()]
        seen = set()
        merged = []
        for ip in pinned + detected:
            if ip and ip not in seen:
                seen.add(ip)
                merged.append(ip)
        return ';'.join(merged)

    @staticmethod
    def mask_ip(ip):
        """IP地址脱敏，保留第一段和最后一段，中间用星号代替"""
        ip_parts = ip.split('.')
        if len(ip_parts) == 4:
            masked_ip = f"{ip_parts[0]}.{len(ip_parts[1]) * '*'}.{len(ip_parts[2]) * '*'}.{ip_parts[3]}"
            return masked_ip
        return ip

    def _page_snapshot(self) -> Dict[str, Any]:
        """
        汇总详情页所需的只读状态快照。
        纯读方法：不修改任何实例状态、不做IO、不发通知，可被 get_page 安全多次调用。
        各字段含义与四态文案的对应关系见 REDESIGN_REQUIREMENTS.md 状态矩阵。
        """
        snap: Dict[str, Any] = {}
        # --- 总开关与必填前置 ---
        snap["enabled"] = bool(self._enabled)
        snap["has_app_id"] = bool(str(self._input_id_list or "").strip())
        snap["cron"] = str(self._cron or "").strip()
        snap["cron_valid"] = False
        if snap["cron"]:
            try:
                CronTrigger.from_crontab(snap["cron"])
                snap["cron_valid"] = True
            except Exception:
                snap["cron_valid"] = False
        # --- Cookie 登录态 ---
        snap["cookie_valid"] = bool(self._cookie_valid)
        snap["cookie_lifetime"] = int(getattr(self, "_cookie_lifetime", 0) or 0)
        # 「是否曾经登录过」：扫码登录/CookieCloud 写回成功（_is_special_upload）、
        # 本地存有 Cookie、或寿命计数大于0，任一成立即视为登录过——
        # 只看 _is_special_upload 会把「登录过但 Cookie 已失效」误判成「从未登录」。
        snap["has_cookie_ever"] = bool(
            getattr(self, "_is_special_upload", False)
            or getattr(self, "_saved_cookie", None)
            or int(getattr(self, "_cookie_lifetime", 0) or 0) > 0
        )
        snap["none_streak"] = int(getattr(self, "_none_streak", 0) or 0)
        # --- 两个循环的上次结果 ---
        snap["keepalive_ok"] = getattr(self, "_last_keepalive_ok", None)
        snap["keepalive_note"] = str(getattr(self, "_last_keepalive_note", "") or "")
        snap["ip_check_ok"] = getattr(self, "_last_ip_check_ok", None)
        snap["ip_check_note"] = str(getattr(self, "_last_ip_check_note", "") or "")
        snap["ip_changed"] = bool(self._ip_changed)
        snap["current_ip_masked"] = ";".join(
            self.mask_ip(ip) for ip in str(self._current_ip_address or "").split(";") if ip
        )
        # --- 二维码任务 ---
        snap["qr_running"] = bool(getattr(self, "_qr_running", False))
        snap["qr_future_timestamp"] = int(getattr(self, "_future_timestamp", 0) or 0)
        snap["qr_has_image"] = self._qr_code_image is not None
        # --- 验证码等待 ---
        snap["waiting_captcha"] = bool(getattr(self, "_waiting_captcha", False))
        # --- 通知通道 ---
        snap["use_mp_notify"] = bool(self._use_mp_notify)
        channels = []
        if self._my_send and self._my_send.other_channel:
            channels = [channel for channel, _ in self._my_send.other_channel]
        snap["third_channels"] = channels
        snap["third_token_present"] = bool(str(self._notification_token or "").strip())
        snap["await_ip"] = bool(self._await_ip)
        # --- IP 来源 ---
        snap["company_domain"] = str(getattr(self, "_company_domain", "") or "").strip()
        snap["ddns_ok"] = getattr(self, "_last_ddns_ok", None)
        snap["ddns_ip_masked"] = ";".join(
            self.mask_ip(ip) for ip in str(getattr(self, "_last_ddns_ip", "") or "").split(";") if ip
        )
        snap["wan_mode"] = self.wan2 is not None
        snap["pinned_ips"] = str(getattr(self, "_pinned_ips", "") or "")
        pinned_list = [ip for ip in snap["pinned_ips"].split(",") if ip.strip()]
        snap["pinned_valid"] = all(self._is_ipv4(ip.strip()) for ip in pinned_list) if pinned_list else None
        snap["pinned_count"] = len(pinned_list)
        # --- CookieCloud ---
        snap["use_cookiecloud"] = bool(self._use_cookiecloud)
        snap["cc_key_present"] = bool(settings.COOKIECLOUD_KEY and settings.COOKIECLOUD_PASSWORD)
        snap["cc_local"] = bool(settings.COOKIECLOUD_ENABLE_LOCAL)
        snap["cc_server_ok"] = self._cc_server is not None
        return snap

    @staticmethod
    def _is_ipv4(ip: str) -> bool:
        """判断字符串是否为合法 IPv4 地址"""
        return re.match(r'^\d{1,3}(\.\d{1,3}){3}$', str(ip).strip()) is not None

    def __update_config(self):
        """保存插件配置到系统"""
        self.update_config({
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "cron": self._cron,
            "notification_token": self._notification_token,
            "use_mp_notify": self._use_mp_notify,
            "await_ip": self._await_ip,
            "forced_update": self._forced_update,
            "local_scan": self._local_scan,
            "input_id_list": self._input_id_list,
            "company_domain": self._company_domain,
            "cookie_header": self._cookie_header,
            "use_cookiecloud": self._use_cookiecloud,
            "pinned_ips": self._pinned_ips,
            "wan_enabled": getattr(self, "_wan_enabled", False),
            "wan_max_ips": getattr(self, "_wan_max_ips", ""),
            "custom_ip_urls": getattr(self, "_custom_ip_urls", ""),
        })

    def get_state(self) -> bool:
        """返回插件启用状态"""
        return self._enabled

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，返回页面JSON和默认模型。
        布局为 VCard 卡片分区（每区一张卡：标题+副标题+内部字段行），
        宿主对 get_form 内 VCard 有一等支持（参照 tunnelyield 的 section 模式）。
        """
        third_channels = []
        if self._my_send and self._my_send.other_channel:
            third_channels = [c for c, _ in self._my_send.other_channel]
        third_token_present = bool(str(self._notification_token or "").strip())

        def _col(md: int, control: dict) -> dict:
            return {'component': 'VCol', 'props': {'cols': 12, 'md': md}, 'content': [control]}

        def _row(*cols: dict) -> dict:
            return {'component': 'VRow', 'content': list(cols)}

        def _card(title: str, subtitle: str, rows: List[dict]) -> dict:
            """一张功能分区卡：标题 + 一句副标题 + 字段行"""
            return {
                'component': 'VCard',
                'props': {'variant': 'outlined', 'class': 'mb-4'},
                'content': [
                    {
                        'component': 'VCardText',
                        'content': [
                            {
                                'component': 'div',
                                'props': {'class': 'text-subtitle-1 font-weight-medium mb-1'},
                                'text': title,
                            },
                            {
                                'component': 'div',
                                'props': {'class': 'text-caption text-medium-emphasis mb-3'},
                                'text': subtitle,
                            },
                            *rows,
                        ],
                    }
                ],
            }

        return [
            {
                'component': 'VForm',
                'content': [
                    # ---------- 卡片 1 · 基础 ----------
                    _card(
                        '基础',
                        '启用插件、触发一次检测或强制更新；检测周期与应用ID是必填项',
                        [
                            _row(
                                _col(4, {'component': 'VSwitch', 'props': {'model': 'enabled', 'label': '启用插件'}}),
                                _col(4, {'component': 'VSwitch', 'props': {'model': 'onlyonce', 'label': '立即检测一次'}}),
                                _col(4, {'component': 'VSwitch', 'props': {'model': 'forced_update', 'label': '强制更新IP'}}),
                            ),
                            _row(
                                _col(12, {'component': 'VAlert', 'props': {'type': 'info', 'variant': 'tonal',
                                         'text': '「立即检测一次」「强制更新IP」是触发器：保存后执行一次并自动复位，不是常开开关'}}),
                            ),
                            _row(
                                _col(6, {'component': 'VTextField', 'props': {'model': 'cron', 'label': '检测周期（必填）', 'placeholder': '0 * * * *'}}),
                                _col(6, {'component': 'VTextarea', 'props': {'model': 'input_id_list',
                                         'label': '应用ID（必填）—— 企业微信应用页面URL末尾获取，多个用英文逗号分隔；不要填100000x开头的自建应用ID',
                                         'rows': 1, 'placeholder': '如 1021042,1052986'}}),
                            ),
                        ],
                    ),
                    # ---------- 卡片 2 · 扫码登录 ----------
                    _card(
                        '扫码登录',
                        '首次使用或Cookie失效时在这里重新登录；二维码出现在插件详情页',
                        [
                            _row(
                                _col(12, {'component': 'VSwitch', 'props': {'model': 'local_scan',
                                         'label': '本地扫码修改IP —— 勾选并保存后，打开插件详情页查看二维码'}}),
                            ),
                            *([{
                                'component': 'VRow',
                                'content': [
                                    _col(12, {'component': 'VAlert', 'props': {'type': 'warning', 'variant': 'tonal',
                                             'text': '扫码任务进行中：保存后请尽快打开详情页扫码（二维码约110秒过期），过期后刷新详情页可看新码'}}),
                                ],
                            }] if getattr(self, "_qr_running", False) else []),
                        ],
                    ),
                    # ---------- 卡片 3 · IP 来源 ----------
                    _card(
                        'IP 来源',
                        '决定填入可信IP的是哪些地址：检测来源按优先级只取一个，固定可信IP始终额外保留',
                        [
                            _row(
                                _col(12, {'component': 'VAlert', 'props': {'type': 'info', 'variant': 'tonal',
                                         'text': '优先级从高到低：① DDNS域名（填了就用它）② 多WAN出口（开了就用它）③ 公网IP探测（默认）。固定可信IP与所选检测来源合并后一起填入'}}),
                            ),
                            _row(
                                _col(12, {'component': 'VTextField', 'props': {'model': 'company_domain',
                                         'label': 'DDNS域名（可选·优先级最高，多个用英文逗号分隔）',
                                         'placeholder': '如 home.oicp.net,backup.myqnapcloud.com —— 所有域名都会解析，结果合并去重'}}),
                            ),
                            _row(
                                _col(4, {'component': 'VSwitch', 'props': {'model': 'wan_enabled', 'label': '多WAN多出口'}}),
                                _col(8, {'component': 'VTextField', 'props': {'model': 'wan_max_ips',
                                         'label': '最多保留出口IP数（仅在开启多WAN时生效）', 'placeholder': '留空默认 3'}}),
                            ),
                            _row(
                                _col(12, {'component': 'VTextField', 'props': {'model': 'pinned_ips',
                                         'label': '固定可信IP（可选·始终保留，多个用英文逗号分隔）',
                                         'placeholder': '如 203.0.113.10,198.51.100.7'}}),
                            ),
                            _row(
                                _col(12, {'component': 'VTextarea', 'props': {'model': 'custom_ip_urls',
                                         'label': '自定义公网IP探测地址（可选·仅单IP模式生效，多个用英文逗号分隔）',
                                         'rows': 1, 'placeholder': '留空使用内置探测站；填写后优先用这些地址获取公网IP'}}),
                            ),
                        ],
                    ),
                    # ---------- 卡片 4 · 通知 ----------
                    _card(
                        '通知',
                        'Cookie失效和IP更新时如何告诉你；两种通知独立工作',
                        [
                            _row(
                                _col(4, {'component': 'VSwitch', 'props': {'model': 'use_mp_notify', 'label': 'MP内置通知'}}),
                                _col(4, {'component': 'VSwitch', 'props': {'model': 'await_ip', 'label': 'IP变动后通知'}}),
                                _col(4, {'component': 'VBtn', 'props': {'color': 'primary', 'variant': 'flat'}, 'text': '测试通知推送',
                                      'events': {'click': {'api': 'plugin/DynamicWeChat/test_notify', 'method': 'get'}}}),
                            ),
                            *([{
                                'component': 'VRow',
                                'content': [
                                    _col(12, {'component': 'VAlert', 'props': {'type': 'warning', 'variant': 'tonal',
                                             'text': '「IP变动后通知」已开启，但下方未填写第三方通知Token，保存后该开关会被自动关闭。如需此功能请先填写Token'}}),
                                ],
                            }] if self._await_ip and not third_token_present else []),
                            _row(
                                _col(12, {'component': 'VTextarea', 'props': {'model': 'notification_token',
                                         'label': '第三方通知Token（可选）', 'rows': 1,
                                         'placeholder': '支持Server酱（sct开头）、IYUU（含iyuu）、PushPlus；多个Token用||分隔；结尾加||Q表示改IP成功时不发通知'}}),
                            ),
                            _row(
                                _col(12, {'component': 'VAlert', 'props': {'type': 'info', 'variant': 'tonal',
                                         'text': (('已识别第三方通道：' + '、'.join(third_channels) + '。修改Token后需保存，此提示才会更新') if third_channels
                                                 else '第三方通知未配置或无法识别Token（保存后此提示更新）。MP内置通知由MoviePilot统一发送，是否送达本页无法查询，可用「测试通知推送」按钮验证')}}),
                            ),
                        ],
                    ),
                    # ---------- 卡片 5 · 高级 ----------
                    _card(
                        '高级',
                        '进阶选项 —— 保持默认即可，不改不影响正常使用',
                        [
                            _row(
                                _col(12, {'component': 'VSwitch', 'props': {'model': 'use_cookiecloud', 'label': '使用CookieCloud（跨设备备份Cookie，建议开启）'}}),
                            ),
                        ],
                    ),
                ]
            }
        ], {
            "enabled": False,
            "cron": "",
            "onlyonce": False,
            "forced_update": False,
            "use_cookiecloud": True,
            "local_scan": False,
            "use_mp_notify": True,
            "await_ip": False,
            "cookie_header": "",
            "notification_token": "",
            "input_id_list": "",
            "pinned_ips": "",
            "company_domain": "",
            "wan_enabled": False,
            "wan_max_ips": "",
            "custom_ip_urls": ""
        }
    def get_page(self) -> List[dict]:
        """
        生成插件详情页（只读状态总览 + 扫码区）
        纯渲染方法：不修改任何实例状态（多次调用结果一致）。
        状态条文案与配色见 REDESIGN_REQUIREMENTS.md 状态矩阵。
        """
        snap = self._page_snapshot()
        now_ts = datetime.now().timestamp()

        def _banner(text: str, bg: str) -> dict:
            """一行状态条：纯文本 + 背景色（灰#bbbbbb/绿#40bb45/橙#e69b00/红#ff0000/黄#d4a017）"""
            return {
                "component": "div",
                "text": text,
                "props": {
                    "style": {
                        "fontSize": "16px",
                        "color": "#ffffff",
                        "backgroundColor": bg,
                        "padding": "8px",
                        "borderRadius": "5px",
                        "textAlign": "center",
                        "display": "inline-block",
                        "maxWidth": "100%",
                        "wordBreak": "break-all"
                    }
                }
            }

        banners: List[dict] = []
        # ---- 插件总开关 ----
        # 绿条绑定"上一次保活校验实际成功"，而非仅仅字段非空——
        # 应用ID被静默拒绝时用户不该在绿条下等一个永不发生的结果
        if not snap["enabled"]:
            banners.append(_banner("【插件未启用】所有自动任务停止，保存配置开启后才会运行", "#bbbbbb"))
        elif not snap["has_app_id"]:
            banners.append(_banner("【已启用，但未填写应用ID】不会执行任何检测，请到配置页填写", "#e69b00"))
        elif snap["keepalive_ok"] is False:
            banners.append(_banner("【插件已启用，但登录校验未通过】任务在跑，可信IP不会更新；见下方Cookie状态", "#ff0000"))
        elif snap["keepalive_ok"] is None and not snap["keepalive_note"]:
            banners.append(_banner("插件已启用，等待第一轮校验结果（约10分钟内）", "#bbbbbb"))
        else:
            banners.append(_banner("插件已启用，后台任务运行中", "#40bb45"))
        # ---- Cookie 登录态 ----
        if snap["enabled"] and not snap["has_app_id"]:
            pass  # 总开关条已表达缺前置，Cookie 条不再重复
        elif not snap["enabled"]:
            banners.append(_banner("Cookie：插件未启用，不会保活", "#bbbbbb"))
        elif not snap["has_cookie_ever"]:
            banners.append(_banner(
                "【尚未登录过】请到配置页勾选「本地扫码修改IP」保存，然后回到本页扫码",
                "#e69b00"))
        elif snap["cookie_valid"]:
            lifetime = snap["cookie_lifetime"]
            days = lifetime // 86400
            hours = (lifetime % 86400) // 3600
            minutes = (lifetime % 3600) // 60
            banners.append(_banner(
                f"【Cookie 有效】已保活 {days}天{hours}小时{minutes}分钟", "#40bb45"))
        elif snap["none_streak"] >= 3:
            banners.append(_banner(
                f"【连续 {snap['none_streak']} 次无法确认登录状态】可能是网络不通或企业微信页面改版，"
                "期间Cookie真实失效不能及时发现；请检查服务器到 work.weixin.qq.com 的连通性",
                "#e69b00"))
        else:
            banners.append(_banner(
                "【Cookie 已失效】自动恢复失败；失效期间公网IP一旦变化，企业微信应用的通知将发送失败。"
                "请尽快到配置页勾选「本地扫码修改IP」重新扫码",
                "#ff0000"))
        # ---- 保活循环 ----
        # ok=None 有两种含义：真的没跑过（note 空）与跑了但无结论（note 是转译后的原因）——
        # 把后者显示成"还没跑过"会让网络故障的中间态变成谎言
        if snap["enabled"] and snap["has_app_id"]:
            if snap["keepalive_ok"] is True:
                banners.append(_banner(f"保活校验：正常（{snap['keepalive_note']}）", "#40bb45"))
            elif snap["keepalive_ok"] is None and snap["keepalive_note"]:
                banners.append(_banner(
                    f"【保活校验无结论】{snap['keepalive_note']}；每10分钟自动重试，"
                    "连续多次无结论说明网络或企业微信页面异常", "#e69b00"))
            elif snap["keepalive_ok"] is None:
                banners.append(_banner("保活校验：还没跑过第一轮（每10分钟自动校验一次）", "#bbbbbb"))
            else:
                banners.append(_banner(
                    f"保活校验：{snap['keepalive_note']}；下轮将自动重试或通知", "#ff0000"))
        # ---- IP 检测循环 ----
        if snap["enabled"] and snap["has_app_id"]:
            if not snap["cron"]:
                banners.append(_banner("【未配置检测周期】IP变化不会被自动更新，请到配置页填写", "#e69b00"))
            elif not snap["cron_valid"]:
                banners.append(_banner(
                    f"【检测周期格式错误】「{snap['cron']}」不是合法的 cron 表达式，IP 检测不会运行",
                    "#ff0000"))
            else:
                note = snap["ip_check_note"] or "还没跑过第一轮"
                color = "#bbbbbb" if snap["ip_check_ok"] is None else ("#40bb45" if snap["ip_check_ok"] else "#ff0000")
                banners.append(_banner(
                    f"IP检测（{snap['cron']}）：{note}；当前可信IP：{snap['current_ip_masked'] or '未记录'}",
                    color))
        # ---- DDNS ----
        # 补齐正常态/未配置态，与失败红条构成完整三态（此前只有失败分支）
        if snap["company_domain"]:
            if snap["ddns_ok"] is False:
                banners.append(_banner(
                    f"【DDNS域名全部解析失败】{snap['company_domain']} 本轮未改动可信IP，请检查域名或DNS", "#ff0000"))
            elif snap["ddns_ok"] is True and snap["ddns_ip_masked"]:
                count = len([ip for ip in str(snap["company_domain"]).split(",") if ip.strip()])
                banners.append(_banner(
                    f"DDNS正常：{count} 个域名解析到 {snap['ddns_ip_masked']}，已合并填入可信IP", "#40bb45"))
            else:
                banners.append(_banner(f"DDNS：已配置 {snap['company_domain']}，等待首次解析", "#bbbbbb"))
        # ---- 固定可信IP ----
        # 快照已算好 pinned_valid/pinned_count，此前从未渲染（机械核查确认的死字段）
        if snap["pinned_ips"].strip():
            if snap["pinned_valid"] is False:
                banners.append(_banner(
                    "【固定可信IP格式不对】含非IP格式的内容，更新可信IP时会被忽略；请检查是否误填了域名", "#e69b00"))
            else:
                banners.append(_banner(
                    f"固定可信IP：{snap['pinned_count']} 个，每次更新可信IP都会保留它们", "#40bb45"))

        # ---- 二维码区（三态分离 + 图片有无两态，无写副作用） ----
        # 页面是进入时快照：等待出码的用户需要知道"刷新本页"才能看到新状态
        qr_valid = snap["qr_future_timestamp"] > now_ts
        if qr_valid:
            qr_text = f"二维码有效，过期时间: {datetime.fromtimestamp(snap['qr_future_timestamp']).strftime('%Y-%m-%d %H:%M:%S')}。过期后请刷新本页查看新码"
            qr_color = "#40bb45"
        elif snap["qr_running"] and snap["qr_has_image"]:
            qr_text = "二维码已过期。请刷新本页查看是否已生成新码；没有新码就到配置页重新勾选「本地扫码修改IP」保存"
            qr_color = "#d4a017"
        elif snap["qr_running"]:
            qr_text = "扫码任务运行中，二维码生成后本页不会自动出现——请每隔几秒刷新本页查看"
            qr_color = "#d4a017"
        else:
            qr_text = "当前没有扫码任务。需要时到配置页勾选「本地扫码修改IP」保存，或发送 /push_qr 命令"
            qr_color = "#bbbbbb"
        if snap["qr_has_image"] and qr_valid:
            qr_image_data = self._qr_code_image.getvalue()
            base64_image = base64.b64encode(qr_image_data).decode('utf-8')
            img_component = {
                "component": "img",
                "props": {
                    "src": f"data:image/png;base64,{base64_image}",
                    "style": {
                        "width": "auto",
                        "height": "auto",
                        "maxWidth": "100%",
                        "maxHeight": "100%",
                        "display": "block",
                        "margin": "0 auto"
                    }
                }
            }
        else:
            img_component = {
                "component": "div",
                "text": "登录二维码会在此展示；生成后需刷新本页",
                "props": {
                    "style": {
                        "fontSize": "16px",
                        "color": "#888888",
                        "textAlign": "center",
                        "margin": "10px"
                    }
                }
            }
        # ---- 验证码等待条 ----
        captcha_component = None
        if snap["waiting_captcha"]:
            captcha_component = _banner(
                "【正在等待短信验证码】请在企业微信应用发送 6 位数字并以？结尾（如 110301？），"
                "或发送命令 /wxcode 110301",
                "#d4a017")

        return [
            {
                "component": "div",
                "props": {"style": {"textAlign": "center"}},
                "content": [
                    {
                        "component": "div",
                        "props": {
                            "style": {
                                "display": "flex",
                                "justifyContent": "center",
                                "alignItems": "center",
                                "flexDirection": "column",
                                "gap": "8px"
                            }
                        },
                        "content": [
                            *banners,
                            _banner(qr_text, qr_color),
                        ]
                    },
                    img_component,
                    *( [captcha_component] if captcha_component else [] ),
                ]
            }
        ]

    async def _test_notify_async(self):
        """
        测试消息推送
        同时尝试：1. MoviePilot内置通知  2. 所有第三方通知通道
        """
        success_count = 0
        fail_count = 0

        # 1. 尝试MoviePilot内置通知（MP管理所有渠道）
        if self._use_mp_notify:
            try:
                await asyncio.to_thread(
                    self.post_message,
                    mtype=MessageType.Plugin,
                    title="动态企微可信IP - 测试通知",
                    text="这是一条测试通知，用于验证通知配置是否正常。"
                )
                success_count += 1
                logger.info("MP内置通知测试成功")
            except Exception as e:
                logger.error(f"MP内置通知测试失败：{e}")
                fail_count += 1

        # 2. 遍历所有第三方通知通道
        if self._my_send and self._my_send.other_channel:
            for channel, token in self._my_send.other_channel:
                try:
                    error = await asyncio.to_thread(
                        self._my_send.send,
                        title="动态企微可信IP - 测试通知",
                        content="这是一条测试通知，用于验证通知配置是否正常。",
                        image=None, force_send=True, diy_channel=channel, diy_token=token
                    )
                    if error:
                        logger.error(f"第三方通道 {channel} 测试失败，原因：{error}")
                        fail_count += 1
                    else:
                        success_count += 1
                        logger.info(f"第三方通道 {channel} 测试成功")
                except Exception as e:
                    logger.error(f"第三方通道 {channel} 测试异常：{e}")
                    fail_count += 1

        # 汇总结果
        if success_count > 0:
            self.systemmessage.put(f"通知测试完成：成功 {success_count} 个，失败 {fail_count} 个")
            logger.info(f"通知测试完成：成功 {success_count} 个，失败 {fail_count} 个")
        else:
            self.systemmessage.put("通知测试失败：所有通道均发送失败")
            logger.warning("通知测试失败：所有通道均发送失败")

    # ---------- 统一事件入口 ----------
    @eventmanager.register(EventType.PluginAction)
    def dynamicwechat_event(self, event: Event = None):
        """
        统一事件分发入口，根据 sub_action 调用不同方法
        """
        if not self._enabled or not event:
            return
        event_data = event.event_data
        if not event_data or event_data.get("action") != "dynamicwechat":
            return
        sub_action = event_data.get("sub_action", "check")
        if sub_action == "forced_change":
            self._start_bg_task(self.forced_change(None))
        elif sub_action == "local_scanning":
            self._start_bg_task(self.local_scanning(None))
        elif sub_action == "write_wan2_ip":
            self._start_bg_task(self.write_wan2_ip(None))
        elif sub_action == "wxcode":
            raw = event_data.get("arg_str") or ""
            match = re.search(r"\d{6}", raw)
            if match and self._qr_running:
                code = match.group(0)
                if getattr(self, "_last_code", None) != code:
                    self._last_code = code
                    self._verification_code = code
                    # 安全：不记录验证码明文
                    logger.info("收到验证码")
        else:
            self._start_bg_task(self.check(None))

    @eventmanager.register(EventType.PluginAction)
    def push_qr_code_event(self, event: Event = None):
        """
        立即推送二维码的事件入口
        """
        if not self._enabled or not event:
            return
        event_data = event.event_data
        if not event_data or event_data.get("action") != "push_qrcode":
            return
        self._start_bg_task(self._push_qr_code_async(event))

    @eventmanager.register(EventType.UserMessage)
    def talk(self, event: Event):
        """
        监听用户消息，接收验证码（以问号结尾）
        """
        if not self._enabled:
            return
        if not self._qr_running:
            return
        text = (event.event_data or {}).get("text") or ""
        # 严格匹配以 ? 或 ？ 结尾的6位数字验证码
        match = re.fullmatch(r"(\d{6})[?？]", text.strip())
        if match:
            code = match.group(1)
            if code != self._last_code:
                self._verification_code = code
                self._last_code = code
                # 安全：仅记录收到验证码，不输出明文
                logger.info("收到验证码")

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        注册插件命令
        """
        return [
            {
                "cmd": "/push_qr",
                "event": EventType.PluginAction,
                "desc": "立即推送登录二维码",
                "category": "",
                "data": {"action": "push_qrcode"}
            },
            {
                "cmd": "/wxcode",
                "event": EventType.PluginAction,
                "desc": "提交企业微信验证码",
                "category": "",
                "data": {"action": "dynamicwechat", "sub_action": "wxcode"}
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/test_notify",
                "endpoint": self._test_notify,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "测试通知推送",
                "description": "测试所有配置的通知渠道"
            }
        ]

    def _test_notify(self):
        """API端点：测试通知推送"""
        self._start_bg_task(self._test_notify_async())
        return {"success": True, "message": "测试通知已发送"}

    def get_service(self) -> List[Dict[str, Any]]:
        return []

    def stop_service(self) -> bool:
        """
        停止所有后台任务和线程。
        对于当前事件循环中的任务，取消并加入 pending，确保旧任务清理完成前不会启动新循环。
        返回 True 表示认为所有任务已清理（可重载），False 表示仍有残留。
        """
        self._stopping = True

        # 检测当前事件循环
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        # 收集按事件循环分组的未完成任务
        tasks_by_loop = {}
        for task in list(getattr(self, "_bg_tasks", []) or []):
            if not task.done():
                try:
                    loop = task.get_loop()
                    tasks_by_loop.setdefault(loop, []).append(task)
                except RuntimeError:
                    # 无法获取循环，直接取消并视为 pending
                    task.cancel()
                    if not task.done():
                        tasks_by_loop.setdefault(None, []).append(task)

        pending_tasks = []
        async def cancel_and_wait(tasks):
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        for loop, tasks in tasks_by_loop.items():
            if loop is None or loop.is_closed() or not loop.is_running():
                # 循环不可用，仅取消
                for task in tasks:
                    task.cancel()
                pending_tasks.extend([task for task in tasks if not task.done()])
                continue

            if loop is current_loop:
                # 当前循环无法同步等待，保留为 pending，避免旧任务清理完成前启动新循环
                for task in tasks:
                    def cleanup(t):
                        try:
                            if t in self._bg_tasks:
                                self._bg_tasks.remove(t)
                        except ValueError:
                            pass
                    task.cancel()
                    task.add_done_callback(cleanup)
                pending_tasks.extend([task for task in tasks if not task.done()])
                continue

            # 不同循环，可安全等待
            try:
                future = asyncio.run_coroutine_threadsafe(cancel_and_wait(tasks), loop)
                future.result(timeout=self.BACKUP_TASK_JOIN_TIMEOUT)
            except Exception:
                pending_tasks.extend([task for task in tasks if not task.done()])

        self._bg_tasks = pending_tasks

        # 等待后台线程退出
        alive_threads = []
        for thread in list(getattr(self, "_bg_threads", []) or []):
            if thread.is_alive():
                thread.join(timeout=self.BACKUP_TASK_JOIN_TIMEOUT)
            if thread.is_alive():
                alive_threads.append(thread)
        self._bg_threads = alive_threads

        if pending_tasks:
            logger.warning(f"{len(pending_tasks)} 个异步任务尚未完成取消")
        if alive_threads:
            logger.warning(f"{len(alive_threads)} 个后台线程未在超时时间内退出")
        if pending_tasks or alive_threads:
            return False
        return True

    async def _launch_browser_context_with_retry(self, headless: bool = True):
        """
        使用 CloakBrowser 异步启动企业微信页面上下文，支持重试机制。
        使用类级别锁串行化环境变量修改，避免并发冲突。
        锁等待时间计入总超时预算。
        """
        last_exception = None
        env_lock = self.__class__._browser_env_lock
        for attempt in range(1, self.BROWSER_RETRY_COUNT + 1):
            lock_acquired = False
            original_dbus = None
            try:
                loop = asyncio.get_running_loop()
                deadline = loop.time() + self.BROWSER_LAUNCH_TIMEOUT
                # 非阻塞轮询获取锁，计入超时预算
                while not env_lock.acquire(blocking=False):
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise asyncio.TimeoutError
                    await asyncio.sleep(min(0.1, remaining))
                lock_acquired = True
                # 计算剩余超时预算
                remaining_timeout = deadline - loop.time()
                if remaining_timeout <= 0:
                    raise asyncio.TimeoutError
                # 临时置空 D-Bus 地址，避免 Docker 中无服务报错
                original_dbus = os.environ.get('DBUS_SESSION_BUS_ADDRESS')
                os.environ['DBUS_SESSION_BUS_ADDRESS'] = ''
                # 启动浏览器
                context = await asyncio.wait_for(
                    launch_context_async(
                        headless=headless,
                        args=['--lang=zh-CN'],
                        extra_http_headers={'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.1'}
                    ),
                    timeout=remaining_timeout
                )
                if attempt > 1:
                    logger.info(f"浏览器启动成功 (第 {attempt} 次尝试)")
                return context
            except asyncio.TimeoutError:
                last_exception = Exception("浏览器启动超时（30秒）")
                logger.warning(f"浏览器启动超时 (尝试 {attempt}/{self.BROWSER_RETRY_COUNT})")
            except Exception as e:
                last_exception = e
                logger.warning(f"浏览器启动失败 (尝试 {attempt}/{self.BROWSER_RETRY_COUNT}): {e}")
            finally:
                if lock_acquired:
                    # 恢复 D-Bus 环境变量
                    if original_dbus is not None:
                        os.environ['DBUS_SESSION_BUS_ADDRESS'] = original_dbus
                    else:
                        os.environ.pop('DBUS_SESSION_BUS_ADDRESS', None)
                    env_lock.release()
            if attempt < self.BROWSER_RETRY_COUNT:
                await asyncio.sleep(self.BROWSER_RETRY_DELAY)
                logger.info(f"等待 {self.BROWSER_RETRY_DELAY} 秒后重试...")
        logger.error(f"浏览器启动失败，已重试 {self.BROWSER_RETRY_COUNT} 次: {last_exception}")
        raise last_exception
