# -*- coding: utf-8 -*-
"""
鱼力max · 说到做到（AstrBot 插件）：机器人说出口的事，插件替它做到。

机器人嘴上答应「明天提醒你」「等会帮你查」「我去睡了 / 我潜水了」，转头就忘、或者说完「睡了」接着聊 ——
说的话（模型写的字）和做的事（代码执行的动作）原来没绑在一起。这个插件从它自己说出去的话里认出答应了什么：
  ① 到点的事（承诺表）：到点用它自己的口吻去做（群里 @ 那个人）；晚了补、补不上记着欠一个道歉
  ② 一段时间的约束：说了去睡 / 潜水 / 不说了 / 不理你 / 不发表情包，那个对话里就真的做到
     （v0.1.1 起默认「有人找就醒」：去睡 / 离开 / 潜水以后不接没叫它的话，有人 @ 它 / 叫它 / 私聊它照常回；
      「一直叫才醒」的硬睡是可选档 wake.mode = hard，硬睡档挡住人要发一句系统提示）
  ③ 没说时间的答应：他下次来找它时让它知道还欠着

钩子顺序（排死在这里）：
  要叫模型之前（sys.maxsize - 10）  约束：这一条该不该回（叫醒也在这儿算）；不回就先替天使之心收口再停
                                    （排在认 AI 之后、活人感攒一攒之前：要拦就早拦，别让它白等）
  回话请求（30）                    这一轮的临时状态：答应过他的事 / 欠的道歉 / 刚回来 / 能做到什么；
                                    不发表情包期间把「找表情」那种工具从这一轮拿掉
  发送前（-1000）                   它刚说了要走、这条还在路上 → 不发；不发表情包 → 拿掉表情包图（表情包插件加完图之后才看）
  发完（-1000）                     读它刚说出去的话 → 规则先筛 → 筛中了后台调一次模型抽成 JSON → 进表 / 记约束
后台每 20 秒（modules/runner.py）：约束到点、承诺表到点去做。
纯逻辑在 core/（不依赖 AstrBot，有单测），跟 AstrBot 打交道的在 modules/。
"""

import os
import sys
import time
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, ResultContentType, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, StarTools
import astrbot.api.message_components as Comp

try:  # 加给模型的那段状态（这一轮临时的，不进聊天记录）
    from astrbot.core.agent.message import TextPart
except Exception:  # pragma: no cover
    TextPart = None

from .core import cmd as cmdtext
from .core import sticker
from .core.angel import release_angel
from .core.clock import Clock, fmt, make_tz
from .core.conf import Sub, id_list, num, truthy
from .core.extract import prefilter
from .core.hold import KINDS, Holds
from .core.scene import held_line, turn_block
from .core.store import Store
from .core.table import Table
from .modules.bridge import Bridge
from .modules.runner import Runner

PLUGIN_NAME = "astrbot_plugin_fatfish_promise"
VERSION = "0.1.1"
TAG = "[说到做到]"
GATE_PRIORITY = sys.maxsize - 10
REQ_PRIORITY = 30
DECO_PRIORITY = -1000
SENT_PRIORITY = -1000
CMD = "说到做到"
# 端到端测试的钩子：只有设了这个环境变量，面板接口才让拨「现在几点」
TEST_ENV = "FATFISH_PROMISE_TEST"
SHOWN_KEY = "_fatfish_promise_shown"
DONE_KEY = "_fatfish_promise_consumed"
WOKE_KEY = "_fatfish_promise_woke"


def conv_of(event):
    """这个对话的钥匙：群 = 平台:GroupMessage:群号；私聊 = 平台:FriendMessage:QQ号。
    不用 unified_msg_origin：开了「会话隔离」时群里每个人一个 umo，可「我去睡了」说的是整个群"""
    pid = event.get_platform_id()
    gid = event.get_group_id()
    if gid and not event.is_private_chat():
        return f"{pid}:GroupMessage:{gid}", "group"
    return f"{pid}:FriendMessage:{event.get_sender_id()}", "private"


def plain_of(chain):
    return "".join(c.text for c in chain or [] if isinstance(c, Comp.Plain)).strip()


def _model_result(res):
    try:
        return res.is_llm_result() or res.result_content_type == ResultContentType.STREAMING_FINISH
    except Exception:
        return False


class FatfishPromise(Star):
    """鱼力max · 说到做到。指令：/说到做到（看自己的）、/说到做到 取消 <编号>；管理员：/说到做到 全部、/说到做到 叫醒"""

    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config if config is not None else {}
        try:
            self.data_dir = Path(StarTools.get_data_dir(PLUGIN_NAME))
        except Exception:
            self.data_dir = Path(os.getcwd()) / "data" / "plugin_data" / PLUGIN_NAME
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.test = os.environ.get(TEST_ENV) == "1"
        self.clock = Clock(num(os.environ.get(TEST_ENV + "_OFFSET"), 0.0) if self.test else 0.0)
        self.store = Store(self.data_dir / "promise.json", warn=lambda m: logger.warning(f"{TAG} {m}"))
        self._tz_name = None
        self.tz, self.tz_label = None, ""
        self._set_tz()
        log = lambda m: logger.info(f"{TAG} {m}")  # noqa: E731
        self.table = Table(self.store.data["table"], self.tz, self._table_conf(), log)
        self.holds = Holds(self.store.data["holds"], self.tz, self._hold_conf(), log)
        self.bridge = Bridge(self)
        self.runner = Runner(self)
        self._held_log = {}
        self._register_web()

    async def initialize(self):
        self.runner.start()
        logger.info(
            f"{TAG} v{VERSION} 已启用" + ("" if self.on() else "（总开关关着）")
            + f"：到点的事{'开' if self.tasks_on() else '关'} · 约束{'开' if self.holds.c['enable'] else '关'} · 时区 {self.tz_label}"
            + (" · 测试模式（能拨钟）" if self.test else "")
        )

    async def terminate(self):
        self.runner.stop()
        self.save(force=True)

    # ───────── 配置 ─────────
    def c(self, group, key, default):
        v = Sub(self.config, group).get(key, default)
        if isinstance(default, bool):
            return truthy(v, default)
        if isinstance(default, (int, float)):
            return num(v, default)
        return v if v is not None else default

    def _set_tz(self):
        name = self.c("basic", "tz", "Asia/Shanghai")
        if name == self._tz_name:
            return
        self._tz_name = name
        self.tz, self.tz_label, ok = make_tz(name)
        if not ok:
            logger.warning(f"{TAG} 认不出时区「{name}」（Asia/Shanghai 以外的名字要装 tzdata；也可以写 UTC+8 这种）：先按北京时间算")
        for x in (getattr(self, "table", None), getattr(self, "holds", None)):
            if x is not None:
                x.tz = self.tz

    def _table_conf(self):
        return {
            "max_pending": num(self.c("tasks", "max_pending", 5), 5, 1, 100),
            "max_daily": num(self.c("tasks", "max_daily", 10), 10, 1, 1000),
            "admin_unlimited": self.c("tasks", "admin_unlimited", True),
            "grace_min": num(self.c("tasks", "grace_min", 60), 60, 1, 1440),
        }

    def _hold_conf(self):
        h = lambda k, d, lo, hi: num(self.c("hold", k, d), d, lo, hi)  # noqa: E731
        w = lambda k, d, lo, hi: num(self.c("wake", k, d), d, lo, hi)  # noqa: E731
        return {
            "enable": self.c("hold", "enable", True),
            "sleep_nap_min": h("sleep_nap_min", 30, 0, 720),
            "night_from": h("night_from", 23, 0, 23),
            "wake_hour": h("wake_hour", 8, 0, 23),
            "away_min": h("away_min", 45, 0, 720),
            "lurk_min": h("lurk_min", 25, 0, 720),
            "quiet_min": h("quiet_min", 30, 0, 720),
            "ignore_min": h("ignore_min", 8, 0, 720),
            "nosticker_min": h("nosticker_min", 90, 0, 720),
            "stated_max_min": h("stated_max_min", 720, 3, 1440),
            "wake_admin_ats": w("admin_ats", 2, 0, 20),
            "wake_people": w("people", 3, 0, 50),
            "wake_window_min": w("window_min", 5, 1, 120),
            "wake_private_msgs": w("private_msgs", 3, 0, 50),
            "wake_floor_min": w("floor_min", 2, 0, 60),
            # （11-10 v0.1.1 审查 VP1-15）soft = 有人找就醒（默认；老配置里没有这一项也走这个）/ hard = 硬睡
            "wake_mode": str(self.c("wake", "mode", "soft") or "soft"),
        }

    def reload_conf(self):
        """配置在 WebUI 里改了：下一圈就用新的（不用重启）"""
        self._set_tz()
        self.table.configure(self._table_conf())
        self.holds.configure(self._hold_conf())

    def on(self):
        return self.c("basic", "enabled", True)

    def tasks_on(self):
        return self.on() and self.c("tasks", "enable", True)

    def promise_on(self):
        return self.c("tasks", "promise_enable", True)

    def fallback_on(self):
        return self.c("tasks", "fallback", True)

    def here(self, conv, scene):
        if scene == "group":
            gs = id_list(self.c("basic", "groups", []))
            return not gs or str(conv).rsplit(":", 1)[-1] in gs
        return self.c("basic", "private", True)

    def now(self):
        return self.clock()

    def tick_sec(self):
        if self.test:
            return num(os.environ.get(TEST_ENV + "_TICK"), 20.0, 0.2, 60)
        return 20.0

    def save(self, force=False):
        if self.table.dirty or self.holds.dirty or self.store.dirty:
            if self.store.save(force):
                self.table.dirty = self.holds.dirty = False

    # ───────── 这条消息的几样事实 ─────────
    def _admin(self, event):
        try:
            if event.is_admin():
                return True
        except Exception:
            pass
        try:
            return str(event.get_sender_id()) in {str(x) for x in (self.context.get_config().get("admins_id") or [])}
        except Exception:
            return False

    @staticmethod
    def _directed(event):
        """这条在找它：@ / 引用 / 唤醒词 / 私聊。活人感「接话」替它接的那种（没人点它名）不算"""
        if not getattr(event, "is_at_or_wake_command", False):
            return False
        try:
            return event.get_extra("fatfish_kind") not in ("follow", "chat")
        except Exception:
            return True

    def _log_held(self, conv, name, r):
        """「它说了要走、不回」一个对话一分钟最多写一行日志"""
        now = time.time()
        if now - self._held_log.get(conv, 0) < 60:
            return
        self._held_log[conv] = now
        rec = r.get("rec") or {}
        left = max(0, int((float(rec.get("until") or self.now()) - self.now()) // 60))
        logger.info(
            f"{TAG} {conv}「{name}」的消息不回：它说了「{str(rec.get('say') or '')[:20]}」"
            f"（{KINDS.get(rec.get('kind'), ('?',))[0]}，还剩 {left} 分钟）" + (f"；{r['why']}" if r.get("why") else "")
        )

    # ───────── 钩子 ─────────
    @filter.on_waiting_llm_request(priority=GATE_PRIORITY)
    async def gate(self, event: AstrMessageEvent):
        """要叫模型回这条之前：它说过的约束挡不挡（叫醒也在这儿算）"""
        try:
            if not self.on():
                return
            conv, scene = conv_of(event)
            if not self.here(conv, scene):
                return
            now = self.now()
            if not self.holds.live(conv, now):
                return
            uid = str(event.get_sender_id())
            if uid == str(event.get_self_id()):
                return
            name = event.get_sender_name() or uid
            r = self.holds.gate(
                conv,
                scene,
                uid,
                name,
                self._directed(event),
                self._admin(event),
                self.bridge.is_ai(uid),
                event.message_str or "",
                now,
            )
            if r["woke"]:
                event.set_extra(WOKE_KEY, True)
                self.store.event("woke", f"{conv}「{name}」把它叫回来了（{r['why']}）", now)
            if r["block"]:
                release_angel(self.context, event, "说到做到：" + KINDS.get((r.get("rec") or {}).get("kind"), ("约束",))[0])
                event.stop_event()
                self._log_held(conv, name, r)
            if r["block"] and r.get("tell"):
                self.runner.spawn(self._tell_held(conv, scene, uid, name, r["rec"]))  # 在后台发，不耽误这个钩子
            self.save()
        except Exception as e:
            logger.warning(f"{TAG} 看约束出错（这条照常）：{e!r}"[:300])

    async def _tell_held(self, conv, scene, uid, name, rec):
        """（11-10 v0.1.1 审查 VP1-15）硬睡档第一次挡住找它的人：发一句固定的系统提示（群里 @ 他；不叫模型、不进对话记录）。
        同一个人只说一次（core/hold.py 的 _tell 记着）；发不出去只记日志，不重试"""
        try:
            ok, why, _ = await self.bridge.send(conv, held_line(rec, self.now(), self.tz), uid if scene == "group" else None)
        except Exception as e:
            ok, why = False, repr(e)
        logger.info(f"{TAG} {conv} 硬睡档挡住了「{name}」：" + ("跟他说了一声（系统提示）" if ok else f"想跟他说一声，没发出去（{why}）")[:200])
        if ok:
            self.store.event("held_tell", f"{conv} 硬睡档挡住了「{name}」，发了一句系统提示", self.now())
            self.save()

    @filter.on_llm_request(priority=REQ_PRIORITY)
    async def on_req(self, event: AstrMessageEvent, req: ProviderRequest):
        """这一轮的临时状态（只给这一轮，不进聊天记录、不动系统提示）"""
        try:
            if not self.on() or TextPart is None:
                return
            conv, scene = conv_of(event)
            if not self.here(conv, scene):
                return
            now = self.now()
            uid = str(event.get_sender_id())
            if self.holds.has(conv, "nosticker", now):
                n = sticker.drop_tools(req)
                if n:
                    logger.info(f"{TAG} {conv} 说了不发表情包：这一轮拿掉 {n} 个找表情的工具")
            st = self.table.state_for(uid, conv, now, self._admin(event)) if self.tasks_on() else {}
            if st and not self.promise_on():
                st["promises"] = []
            ai = self.bridge.is_ai(uid)
            text, shown = turn_block(
                st,
                self.holds.live(conv, now),
                self.holds.backs_for(conv, uid),
                now,
                self.tz,
                self.tz_label,
                uid,
                event.message_str or "",
                ai_name=(event.get_sender_name() or uid) if ai else "",
            )
            if not text:
                return
            req.extra_user_content_parts.append(TextPart(text=text).mark_as_temp())
            event.set_extra(SHOWN_KEY, shown)
        except Exception as e:
            logger.warning(f"{TAG} 加这一轮的状态出错（这一轮不加）：{e!r}"[:300])

    @filter.on_decorating_result(priority=DECO_PRIORITY)
    async def on_deco(self, event: AstrMessageEvent):
        """发出去之前：它刚说了要走 → 还在路上的这条不发；不发表情包 → 拿掉表情包图"""
        try:
            if not self.on():
                return
            res = event.get_result()
            if res is None or not res.chain or not _model_result(res):
                return
            conv, scene = conv_of(event)
            if not self.here(conv, scene):
                return
            now = self.now()
            if not self.holds.live(conv, now):
                return
            if not event.get_extra(WOKE_KEY):
                uid = event.get_sender_id()
                rec = self.holds.would_block(conv, uid, self._directed(event), now, ai=self.bridge.is_ai(uid))
                if rec:
                    release_angel(self.context, event, "说到做到：它刚说了要走")
                    event.clear_result()
                    logger.info(
                        f"{TAG} {conv} 它刚说了「{str(rec.get('say'))[:20]}」（{KINDS[rec['kind']][0]}），还在路上的这条回复不发了"
                    )
                    return
            if self.holds.has(conv, "nosticker", now):
                keep, n = sticker.strip(res.chain, event.get_extra(sticker.MEME_REGISTRY))
                for k in sticker.MEME_EXTRAS:
                    if event.get_extra(k):
                        event.set_extra(k, None)
                        n += 1
                if n:
                    res.chain = keep
                    logger.info(f"{TAG} {conv} 说了不发表情包：这条拿掉了表情包")
                    if not keep:
                        release_angel(self.context, event, "说到做到：只有表情包，不发")
                        event.clear_result()
        except Exception as e:
            logger.warning(f"{TAG} 发送前复查出错（这条照常发）：{e!r}"[:300])

    @filter.after_message_sent(priority=SENT_PRIORITY)
    async def after_sent(self, event: AstrMessageEvent):
        """它刚说出去的话：这一轮给它看过的状态算用过了；规则筛中了 → 后台抽它答应了什么"""
        try:
            if not self.on():
                return
            res = event.get_result()
            if res is None or not _model_result(res):
                return
            conv, scene = conv_of(event)
            if not self.here(conv, scene):
                return
            now = self.now()
            uid = str(event.get_sender_id())
            admin = self._admin(event)
            shown = event.get_extra(SHOWN_KEY)
            if shown and not event.get_extra(DONE_KEY):
                event.set_extra(DONE_KEY, True)
                self.table.consume(uid, shown, now)
                self.holds.consume_backs(shown.get("backs"))
                self.save()
            bot = plain_of(res.chain)
            # （11-10 v0.1.1 审查 VP1-13）活人感「叫停 / 刹车」会丢掉没发出去的后半段，并在事件上留下真发出去的字
            # （alive_sent_text；一个字都没发出去时是空字）→ 只从真发出去的字里认。没装活人感 / 没留这个字段 → 照旧用整段
            try:
                cut = event.get_extra("alive_sent_text")
            except Exception:
                cut = None
            if isinstance(cut, str):
                if cut.strip() != bot:
                    logger.info(f"{TAG} {conv} 这句只发出去了一部分（活人感叫停 / 刹车）：只从发出去的那部分里认")
                bot = cut.strip()
            if not bot:
                return
            user = event.message_str or ""
            ai = self.bridge.is_ai(uid)
            mine = self.table.mine(uid, conv, admin) if self.tasks_on() else []
            # 跟别人家的 AI 约的事反正不进表：只筛「我去睡了」这类约束，不为它花抽取的钱
            hit, why = prefilter(bot, user, bool(mine), tasks=self.tasks_on() and not ai, holds=self.holds.c["enable"])
            if not hit:
                return
            name = event.get_sender_name() or uid
            x = {
                "conv": conv,
                "umo": event.unified_msg_origin,
                "scene": scene,
                "uid": uid,
                "name": name,
                "admin": admin,
                "ai": ai,
                "bot": bot,
                "user": user,
                "now": now,
                "mine": [{k: t.get(k) for k in ("n", "kind", "due", "what", "repeat")} for t in mine[:12]],
            }
            logger.debug(f"{TAG} {conv} 筛中了（{why}）：{bot[:40]}")
            self.runner.spawn(self.runner.extract(x))
        except Exception as e:
            logger.warning(f"{TAG} 读它说的话出错（这句不记）：{e!r}"[:300])

    # ───────── 指令 ─────────
    @filter.command(CMD)
    async def cmd(self, event: AstrMessageEvent, op: str = "", arg: str = ""):
        """看机器人答应你的事：/说到做到；取消：/说到做到 取消 <编号>；管理员：/说到做到 全部 | 叫醒"""
        try:
            text = self.cmd_text(event, str(op or "").strip(), str(arg or "").strip())
        except Exception as e:
            logger.warning(f"{TAG} 指令出错：{e!r}"[:300])
            text = "出错了，没看成（日志里有原因）。"
        yield event.plain_result(text)

    def cmd_text(self, event, op, arg):
        """回话在 core/cmd.py（单测测得到）：群里只列这个群的、不带 QQ 号；跨对话的只在私聊里给管理员看"""
        if not self.on():
            return "说到做到的总开关关着。"
        conv, _ = conv_of(event)
        uid = str(event.get_sender_id())
        now = self.now()
        text, ev = cmdtext.run(
            op,
            arg,
            table=self.table,
            holds=self.holds,
            conv=conv,
            uid=uid,
            name=event.get_sender_name() or uid,
            admin=self._admin(event),
            now=now,
            tz=self.tz,
            label=self.tz_label,
        )
        if ev:
            self.store.event("cmd", ev, now)
            self.save(force=True)
        return text

    # ───────── 面板（AstrBot WebUI → 插件 → 打开页面）─────────
    def _register_web(self):
        try:
            import importlib.util

            if importlib.util.find_spec("astrbot.api.web") is None:  # 4.29 以后才有：老版本就不开面板
                return
        except Exception:
            return
        self.context.register_web_api(f"/{PLUGIN_NAME}/state", self.web_state, ["GET"], "说到做到：状态")
        self.context.register_web_api(f"/{PLUGIN_NAME}/action", self.web_action, ["POST"], "说到做到：取消 / 标做完 / 结束约束")

    def snapshot(self):
        now = self.now()
        tb = self.table.snapshot(now)
        return {
            "version": VERSION,
            "enabled": self.on(),
            "tasks_on": self.tasks_on(),
            "holds_on": self.holds.c["enable"],
            "now": now,
            "now_text": fmt(now, self.tz, "%m-%d %H:%M"),
            "tz": self.tz_label,
            **tb,
            "holds": self.holds.snapshot(now),
            "events": list(self.store.data.get("events") or [])[-60:][::-1],
            "caps": {k: self.table.c[k] for k in ("max_pending", "max_daily", "grace_min")},
            "test": self.test,
            "offset": self.clock.offset if self.test else 0,
        }

    async def web_state(self):
        try:
            return {"status": "ok", "data": self.snapshot()}
        except Exception as e:
            logger.warning(f"{TAG} 面板读状态出错：{e!r}"[:300])
            return {"status": "error", "message": "读状态出错（日志里有原因）"}

    async def web_action(self):
        from astrbot.api.web import request

        try:
            body = await request.json({}) or {}
            body = body if isinstance(body, dict) else {}
            op, now = str(body.get("op") or ""), self.now()
            if op in ("cancel", "done"):
                t = self.table.find(body.get("n"))
                if t is None or t.get("status") != "pending":
                    return {"status": "error", "message": "没找到还没做的这一件"}
                if op == "cancel":
                    self.table.cancel(t, "面板", now)
                    self.store.event("cancel", f"#{t['n']} 面板里取消了", now)
                else:
                    self.table.done(t, "（面板里打的勾）", now, by="panel")
                    self.store.event("done", f"#{t['n']} 面板里标成做了", now)
            elif op == "end_hold":
                if not self.holds.release(rid=str(body.get("id") or ""), by="面板", now=now):
                    return {"status": "error", "message": "没找到正在生效的这一条"}
                self.store.event("hold_end", "面板里结束了一条约束", now)
            elif op == "test_clock" and self.test:
                self.clock.offset = num(body.get("offset"), 0.0)
                logger.info(f"{TAG} 测试：把钟拨到 {fmt(self.now(), self.tz, '%m-%d %H:%M:%S')}")
            else:
                return {"status": "error", "message": "不认识的操作"}
            self.save(force=True)
            return {"status": "ok", "data": self.snapshot()}
        except Exception as e:
            logger.warning(f"{TAG} 面板操作出错：{e!r}"[:300])
            return {"status": "error", "message": "出错了（日志里有原因）"}
