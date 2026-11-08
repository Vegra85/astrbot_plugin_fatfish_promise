# -*- coding: utf-8 -*-
"""跟 AstrBot 打交道的几样小事：叫模型、找人格、主动发消息、记进对话记录、问别的鱼力max 插件。

别的鱼力max 插件一律 duck typing：get_registered_star(名字).star_cls 上的公开方法，try/except；
没装、没开、它改了接口 → 当没有，不报错、不 import 它。
"""

import asyncio
import re
import time

from astrbot.api import logger
from astrbot.api.event import MessageChain
import astrbot.api.message_components as Comp

from ..core.failure import MUTED, NOT_FRIEND, OFFLINE, Throttle, classify

try:  # 别跟正在进行的那一轮抢着写对话记录
    from astrbot.core.utils.session_lock import session_lock_manager
except Exception:  # pragma: no cover
    session_lock_manager = None
try:
    from astrbot.core.star.session_llm_manager import SessionServiceManager
except Exception:  # pragma: no cover
    SessionServiceManager = None

AIGUARD = "astrbot_plugin_fatfish_aiguard"
ALIVE = "astrbot_plugin_fatfish_alive"
_THINK = re.compile(r"<(think|thinking)>.*?</\1>", re.S | re.I)


class Bridge:
    def __init__(self, host):
        self.h = host
        self._friends = {}  # 平台 → (查的时间, {好友 QQ})
        self._me = {}  # 平台 → 机器人自己的 QQ
        self._logs = Throttle(600)

    @property
    def ctx(self):
        return self.h.context

    # ───────── 别的鱼力max 插件 ─────────
    def peer(self, name):
        try:
            md = self.ctx.get_registered_star(name)
        except Exception:
            return None
        if md is None or not getattr(md, "activated", True):
            return None
        return getattr(md, "star_cls", None)

    def is_ai(self, uid):
        """认 AI 插件认出来的别人家的机器人（它的公开方法 is_bot）；它说是真人的（is_human，含管理员）不算。没装 → 都不是"""
        uid = str(uid or "")
        if not uid:
            return False
        p = self.peer(AIGUARD)
        fn = getattr(p, "is_bot", None)
        if not callable(fn):
            return False
        try:
            if not fn(uid):
                return False
            hn = getattr(p, "is_human", None)
            return not (callable(hn) and hn(uid))
        except Exception:
            return False

    def record_usage(self, resp):
        """自己调模型用掉的 token 记进活人感的省 token（装了才记）"""
        fn = getattr(self.peer(ALIVE), "record_usage", None)
        if callable(fn):
            try:
                fn(resp)
            except Exception:
                pass

    # ───────── 模型 ─────────
    async def provider_id(self, configured, umo):
        pid = str(configured or "").strip()
        if pid:
            return pid
        return await self.ctx.get_current_chat_provider_id(umo)

    async def llm(self, pid, system, prompt, timeout=30.0):
        resp = await asyncio.wait_for(
            self.ctx.llm_generate(chat_provider_id=pid, prompt=prompt, system_prompt=system or None),
            float(timeout),
        )
        self.record_usage(resp)
        return _THINK.sub("", getattr(resp, "completion_text", "") or "").strip()

    async def persona(self, umo):
        """这个对话的默认人格（AstrBot 配置里选的那个）；拿不到 → 空"""
        try:
            p = await self.ctx.persona_manager.get_default_persona_v3(umo)
            return str((p or {}).get("prompt") or "")
        except Exception:
            return ""

    async def llm_allowed(self, umo):
        """管理员在这个会话里关了模型 → 到点那句不叫模型写（换系统提示或者不发）"""
        try:
            if not (self.ctx.get_config(umo=umo).get("provider_settings") or {}).get("enable", True):
                return False
        except Exception:
            pass
        if SessionServiceManager is not None:
            try:
                if not await SessionServiceManager.is_session_enabled(umo):
                    return False
                if not await SessionServiceManager.is_llm_enabled_for_session(umo):
                    return False
            except Exception:
                pass
        return True

    # ───────── 发之前先看一眼（QQ 连着没有 / 明确发不了的）─────────
    def _bot(self, umo):
        """这个对话所在平台的 aiocqhttp 客户端；不是 aiocqhttp / 拿不到 → None"""
        try:
            inst = self.ctx.get_platform_inst(str(umo).split(":", 1)[0])
        except Exception:
            return None
        bot = getattr(inst, "bot", None)
        return bot if callable(getattr(bot, "call_action", None)) else None

    def connected(self, umo):
        """NapCat 连着没有：连着 / 看不出来 → True；明确没连上 → False（不叫模型、不发，过一会儿再看）"""
        bot = self._bot(umo)
        if bot is None:
            return True
        cl = getattr(bot, "_wsr_api_clients", None)
        return bool(cl) if isinstance(cl, dict) else True

    async def _call(self, bot, action, **kw):
        return await asyncio.wait_for(bot.call_action(action, **kw), 10)

    async def _friend_set(self, bot, pid):
        t, fs = self._friends.get(pid, (0.0, None))
        if fs is None or time.time() - t > 300:  # 好友列表 5 分钟查一次
            data = await self._call(bot, "get_friend_list")
            if isinstance(data, dict):
                data = data.get("data")
            if not isinstance(data, list):
                return None
            fs = {str(x.get("user_id")) for x in data if isinstance(x, dict)}
            self._friends[pid] = (time.time(), fs)
        return fs

    async def precheck(self, kind, umo, uid=None):
        """→ (原因, 是不是明确发不了, 禁言到几点（真实时间戳，0 = 不知道 / 没禁言）)。原因空 = 没看出问题，照常发。
        私聊：他不是好友 → 明确发不了；群里：机器人被禁言了 → 明确发不了（知道几点解）。查不了就当没问题，发的时候再看"""
        bot = self._bot(umo)
        if bot is None:
            return "", False, 0.0
        pid = str(umo).split(":", 1)[0]
        try:
            if kind == "private":
                fs = await self._friend_set(bot, pid)
                if fs is not None and str(uid) not in fs:
                    return NOT_FRIEND, True, 0.0
                return "", False, 0.0
            me = self._me.get(pid)
            if not me:
                info = await self._call(bot, "get_login_info")
                me = str((info or {}).get("user_id") or "")
                if me:
                    self._me[pid] = me
            if me:
                gid = int(str(umo).rsplit(":", 1)[-1])
                info = await self._call(bot, "get_group_member_info", group_id=gid, user_id=int(me), no_cache=True)
                until = float((info or {}).get("shut_up_timestamp") or 0)
                if until > time.time():
                    return MUTED, True, until
        except Exception as e:
            why, definitive = classify(e)
            if definitive:
                return why, True, 0.0
        return "", False, 0.0

    # ───────── 发 / 记 ─────────
    async def send(self, umo, text, at_uid=None):
        """主动发一条 → (发出去了没有, 为什么没发出去, 是不是明确发不了)。
        原因换成人话（会写进给模型看的状态里），原样的报错只进日志（同一个地方同一个原因 10 分钟一行）"""
        chain = [Comp.At(qq=str(at_uid)), Comp.Plain(text=str(text))] if at_uid else [Comp.Plain(text=str(text))]
        try:
            ok = await self.ctx.send_message(umo, MessageChain(chain=chain))
        except Exception as e:
            why, definitive = classify(e)
            if self._logs.ok(str(umo), why, time.time()):
                logger.info(f"[说到做到] 主动发消息没成（{why}）：{e!r}"[:200])
            return False, why, definitive
        return (True, "", False) if ok else (False, OFFLINE, False)

    async def remember(self, umo, hint, line):
        """主动发的这句也记进 AstrBot 的对话记录（不然它下一轮不知道自己刚提醒过）"""
        try:
            cm = self.ctx.conversation_manager
            cid = await cm.get_curr_conversation_id(umo)
            if not cid:
                return
            pair = ({"role": "user", "content": hint}, {"role": "assistant", "content": line})
            if session_lock_manager is not None:
                async with session_lock_manager.acquire_lock(umo):
                    await cm.add_message_pair(cid, *pair)
            else:
                await cm.add_message_pair(cid, *pair)
        except Exception as e:
            logger.debug(f"[说到做到] 记进对话记录失败：{e!r}")
