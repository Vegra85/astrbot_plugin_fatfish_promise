# -*- coding: utf-8 -*-
"""后台干活的：每 20 秒看一次（约束到点了没、承诺表里有没有到点的事）；机器人说完话以后在后台抽它答应了什么。

到点那一下：
  - 给模型这一件事的状态（谁、哪天答应的、原话、现在几点、晚了多久）让它自己写那句，插件发到那个对话（群里 @ 那个人）；
  - 同一个地方（群 / 私聊）两条至少隔 20 秒，没轮到的下一圈再发；
  - 先看发不发得出去（不叫模型）：QQ 没连上 → 过一会儿再看；不是好友 / 机器人被禁言 → 明确发不了，直接记成没做成
    （禁言知道几点解、又在宽限内的，到点再发一次）；
  - 那句只写一次：写好存在这件事上，没发出去的重试只重发、不再叫模型；重试越隔越久（1、2、5、10 分钟……），
    补上时状态里写晚了多久；过了宽限（默认 1 小时）→ 记成没做成，他下次来找机器人时告诉模型欠着一个道歉
    （插件不会自己跑去道歉）；同一件事同一个原因的日志 10 分钟一行；
  - 模型叫不通：发一句系统口吻的「（系统提示）到点了：……」（能关）；
  - 开机时已经过点很久（超过宽限）的不补，直接记成没做成。
"""

import asyncio
import time

from astrbot.api import logger

from ..core.clock import now_text, when_text
from ..core.extract import SYSTEM, build_prompt, parse, validate
from ..core.failure import OFFLINE, Throttle
from ..core.scene import clean_line, fallback_line, speak_prompt
from ..core.table import Gap, is_group
from ..core.when import REPEAT_TEXT

TAG = "[说到做到]"


def private_umo(t):
    pid = str(t.get("conv") or "").split(":", 1)[0] or "aiocqhttp"
    return f"{pid}:FriendMessage:{t.get('who')}"


def dest_of(t):
    """这件事发到哪（排队用）：群里 @ → 那个群；私聊发 → 那个人"""
    if t.get("via") == "private" or not is_group(t.get("conv")):
        return private_umo(t)
    return str(t.get("conv"))


class Runner:
    def __init__(self, host):
        self.h = host
        self.gap = Gap(20.0)
        self.loop_task = None
        self.jobs = set()
        self.swept = False
        self.firing = set()
        self.logs = Throttle(600)

    # ───────── 后台任务 ─────────
    def start(self):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self.loop_task is None or self.loop_task.done():
            self.loop_task = loop.create_task(self._loop())

    def stop(self):
        if self.loop_task:
            self.loop_task.cancel()
        for j in list(self.jobs):
            j.cancel()

    def spawn(self, coro):
        try:
            j = asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            coro.close()
            return None
        self.jobs.add(j)
        j.add_done_callback(self.jobs.discard)
        return j

    async def _loop(self):
        await asyncio.sleep(min(3.0, self.h.tick_sec()))
        while True:
            try:
                await self.round()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"{TAG} 后台出错（下一圈照常）：{e!r}"[:300])
            await asyncio.sleep(self.h.tick_sec())

    async def round(self):
        h = self.h
        h.reload_conf()
        if not h.on():
            return
        now = h.now()
        if not self.swept:  # 开机第一圈：过点很久的不补，直接记成没做成
            self.swept = True
            for t in h.table.sweep(now):
                h.store.event("missed", f"#{t['n']}「{t['what'][:30]}」开机时已经过点很久了，记成没做成", now)
        for b in h.holds.tick(now):
            h.store.event("hold_end", f"{b.get('conv')} {b.get('say', '')[:20]} 到点结束", now)
        h.table.prune(now)
        if h.tasks_on():
            for t in h.table.due_now(now):
                if t.get("n") in self.firing:
                    continue
                self.firing.add(t.get("n"))
                try:
                    await self.fire(t)
                except Exception as e:
                    if self.logs.ok(t.get("n"), "出错", time.time()):
                        logger.warning(f"{TAG} #{t.get('n')} 到点去做出错（过一会儿再试）：{e!r}"[:300])
                    h.table.failed(t, "出错了", h.now())
                finally:
                    self.firing.discard(t.get("n"))
        h.save()

    # ───────── 到点去做 ─────────
    def _say_fail(self, t, kind, why):
        """「没发出去」的日志：同一件事、同一个原因 10 分钟最多一行"""
        if self.logs.ok(t.get("n"), why, time.time()):
            logger.info(f"{TAG} #{t.get('n')} {'私聊' if kind == 'private' else '群里'}没发出去（{why}）")

    def _missed(self, t, why, now, note):
        h = self.h
        if h.table.failed(t, why, now, final=True) == "missed":
            h.store.event("missed", f"#{t['n']}「{t['what'][:30]}」{note}，记成没做成（{why}）", now)

    async def fire(self, t):
        h = self.h
        now = h.now()
        dest = dest_of(t)
        if not self.gap.ok(dest, time.time()):
            return False  # 同一个地方刚发过：下一圈再发
        if h.bridge.is_ai(t.get("who")) or (str(t.get("by")) != str(t.get("who")) and h.bridge.is_ai(t.get("by"))):
            for x in h.table.drop_person(t.get("who"), "对方是别人家的 AI", now):
                h.store.event("cancel", f"#{x['n']} 划掉：对方后来被认出是别人家的 AI", now)
            return False
        if h.table.overdue(t, now):
            self._missed(t, t.get("why") or "到点那会儿没发出去", now, "晚过宽限还没做成")
            return False
        group = is_group(t.get("conv"))
        ways = []
        if t.get("via") == "private" or not group:
            ways.append(("private", private_umo(t), None))
        if group:
            ways.append(("group", str(t.get("conv")), t.get("who")))  # 私聊发不出去（不是好友）→ 回原来的群 @ 他
        # 1. 先看发不发得出去（不叫模型）：QQ 没连上 → 过一会儿再看；不是好友 / 被禁言 → 这条路不走
        if not h.bridge.connected(ways[0][1]):
            self._say_fail(t, ways[0][0], OFFLINE)
            h.table.failed(t, OFFLINE, now, offline=True)
            return False
        usable, why0, until = [], "", 0.0
        for kind, umo, at in ways:
            why, definitive, mute_until = await h.bridge.precheck(kind, umo, t.get("who"))
            if definitive:
                self._say_fail(t, kind, why)
                why0, until = why0 or why, max(until, float(mute_until or 0))
                continue
            usable.append((kind, umo, at))
        if not usable:
            back = until - time.time() + now + 5 if until else 0.0  # 禁言几点解（换成插件的钟）
            limit = float(t.get("due") or now) + float(h.table.c["grace_min"]) * 60
            if back and back <= limit:
                h.table.failed(t, why0, now, retry_at=back)  # 宽限内能解禁：到点再发一次，中间不试
            else:
                self._missed(t, why0, now, "明确发不了")
            return False
        # 2. 写那句：这一次（同一个 due）写过了就用写好的 —— 重试只重发，不再叫模型
        d = h.table.draft(t)
        if d:
            text, by = d
        else:
            due0, what0 = t.get("due"), t.get("what")
            late = max(0.0, now - float(t.get("due") or now))
            if not t.get("tries") and late < 600:
                late = 0.0  # 排队 / 刚开机耽误了几分钟：不算晚（别让它为这几分钟找理由）
            gone = h.holds.gone(t.get("conv"), now)
            text, by = await self.compose(t, now, late, gone), "模型写的"
            if not text and h.fallback_on():
                text, by = fallback_line(t, h.tz), "系统提示"
            if t.get("status") != "pending" or t.get("due") != due0 or t.get("what") != what0:
                return False  # 写的这几秒里他取消了 / 改了时间：这次不发，照改过的来
            if not text:
                if h.table.failed(t, "模型没写出要说的话", now) == "missed":
                    h.store.event("missed", f"#{t['n']}「{t['what'][:30]}」模型一直没写出来，记成没做成", now)
                return False
            h.table.save_draft(t, text, by)
        # 3. 发
        ok, why, where, hopeless = False, "", "", True
        for kind, umo, at in usable:
            ok, why, definitive = await h.bridge.send(umo, text, at)
            if ok:
                where = kind
                break
            hopeless = hopeless and definitive
            self._say_fail(t, kind, why)
        now2 = h.now()
        if not ok:
            if hopeless:
                self._missed(t, why or "发不出去", now2, "明确发不了")
            elif h.table.failed(t, why or "发不出去", now2, offline=why == OFFLINE) == "missed":
                h.store.event("missed", f"#{t['n']}「{t['what'][:30]}」一直发不出去，记成没做成", now2)
            return False
        self.gap.mark(dest, time.time())
        h.table.done(t, text, now2, by)
        h.store.event(
            "done",
            f"#{t['n']} 到点{'私聊发给' if where == 'private' else '在群里 @ '}「{t.get('who_name') or t.get('who')}」：{text[:40]}"
            + ("（系统提示）" if by == "系统提示" else ""),
            now2,
        )
        logger.info(f"{TAG} #{t['n']} 到点做了 → {text[:60]}")
        umo = private_umo(t) if where == "private" else str(t.get("umo") or t.get("conv"))
        line = (f"@{t.get('who_name') or t.get('who')} " if where == "group" else "") + text
        await h.bridge.remember(umo, "（到点了：你之前答应的事）", line)
        h.save(force=True)
        return True

    async def compose(self, t, now, late, gone):
        """让模型用自己的话写到点那句；叫不通 / 没写出来 → None"""
        h = self.h
        umo = str(t.get("umo") or t.get("conv"))
        try:
            if not await h.bridge.llm_allowed(umo):
                return None
            pid = await h.bridge.provider_id(h.c("tasks", "speak_provider_id", ""), umo)
            persona = await h.bridge.persona(umo)
            prompt = speak_prompt(t, now, h.tz, h.tz_label, late, t.get("late_why") or t.get("why") or "", gone)
            raw = await h.bridge.llm(pid, persona, prompt, 60)
            return clean_line(raw) or None
        except Exception as e:
            logger.warning(f"{TAG} #{t.get('n')} 到点那句模型没写成：{e!r}"[:200])
            return None

    # ───────── 机器人说完话：抽它答应了什么 ─────────
    async def extract(self, x):
        """x：从事件上抄下来的 {conv, umo, scene, uid, name, admin, ai, bot, user, now, mine}"""
        h = self.h
        try:
            pid = await h.bridge.provider_id(h.c("extract", "provider_id", ""), x["umo"])
            lines = [self._mine_line(t, x["now"]) for t in x["mine"]]
            prompt = build_prompt(now_text(x["now"], h.tz, h.tz_label), x["scene"], x["name"], x["user"], x["bot"], lines)
            raw = await h.bridge.llm(pid, SYSTEM, prompt, h.c("extract", "timeout_sec", 30))
        except Exception as e:
            logger.warning(f"{TAG} 抽取没调成（这句不记）：{e!r}"[:200])
            return
        items = parse(raw)
        if items is None:
            logger.warning(f"{TAG} 抽取的回答看不懂（这句不记）：{str(raw)[:120]}")
            return
        acts, rej = validate(items, x["bot"], x["user"], x["now"], h.tz, [t["n"] for t in x["mine"]])
        for it, why, tell in rej:
            logger.info(f"{TAG} {x['conv']} 不记：{why}（{str(it)[:80]}）")
            if tell and isinstance(it, dict) and h.tasks_on() and not x["ai"]:
                what = str(it.get("what") or it.get("when") or "那件事")[:30]
                h.table.note(x["uid"], x["conv"], f"你答应他的「{what}」没记上：{why}", x["now"])
        for a in acts:
            try:
                self.apply(a, x)
            except Exception as e:
                logger.warning(f"{TAG} 记一条出错（别的照记）：{e!r}"[:200])
        h.save(force=True)

    def _mine_line(self, t, now):
        if t.get("kind") == "promise":
            return f"#{t['n']} 没说时间：{t['what']}"
        return f"#{t['n']} {when_text(t['due'], now, self.h.tz)} {t['what']}" + (
            f"（{REPEAT_TEXT[t['repeat']]}）" if t.get("repeat") in REPEAT_TEXT else ""
        )

    def apply(self, a, x):
        h = self.h
        op, now, conv, uid, name = a["op"], x["now"], x["conv"], x["uid"], x["name"]
        if op in ("task", "promise", "cancel", "edit") and not h.tasks_on():
            return
        if op in ("task", "promise") and x["ai"]:
            logger.info(f"{TAG} {conv} 跟「{name}」约的「{a.get('what', '')[:30]}」—— 对方是别人家的 AI，不进表")
            h.store.event("skip", f"跟别人家的 AI「{name}」约的「{a.get('what', '')[:30]}」不进表", now)
            return
        if op == "task":
            via = a.get("via") or (h.c("tasks", "group_via", "at") if x["scene"] == "group" else "private")
            t, why = h.table.add_task(
                conv,
                x["umo"],
                x["scene"],
                uid,
                name,
                a["what"],
                a["due"],
                a.get("repeat"),
                "private" if via == "private" else "at",
                by=uid,
                say=a.get("quote") or x["bot"][:80],
                ask=x["user"],
                now=now,
                admin=x["admin"],
                dom=a.get("dom"),
            )
            if t is None:
                h.table.note(uid, conv, f"你答应他的「{a['what'][:30]}」没记上：{why}", now)
                h.store.event("reject", f"「{name}」的「{a['what'][:30]}」没记上：{why}", now)
            elif why != "dup":
                h.store.event("add", f"#{t['n']} 记下：{a['what'][:30]}（「{name}」）", now)
        elif op == "promise":
            if not h.promise_on():
                return
            p, why = h.table.add_promise(conv, x["umo"], x["scene"], uid, name, a["what"], a.get("quote") or "", x["user"], now)
            if p is not None and why != "dup":
                h.store.event("add", f"#{p['n']} 记下（没说时间）：{a['what'][:30]}（「{name}」）", now)
        elif op in ("cancel", "edit"):
            t = h.table.find(a["n"])
            if not t or not h.table.can_edit(t, uid, x["admin"]):
                logger.info(f"{TAG} {conv}「{name}」想改 #{a['n']}，不是他的 → 不改")
                return
            if op == "cancel":
                if h.table.cancel(t, name or uid, now):
                    h.store.event("cancel", f"#{t['n']} 取消了（「{name}」说不用了）", now)
                return
            due = a.get("due")
            if due is None and a.get("shift") and t.get("due"):
                due = max(float(t["due"]) + float(a["shift"]) * 60, now + 60)
            r, why = h.table.edit(t, due, a.get("what") or None, now, name or uid)
            if r is None:
                h.table.note(uid, conv, f"你答应他改的 #{t['n']} 没改成：{why}", now)
            else:
                h.store.event("edit", f"#{t['n']} 改了（「{name}」）", now)
        elif op == "hold":
            kind = a["kind"]
            rec, why = h.holds.declare(
                conv,
                x["umo"],
                x["scene"],
                kind,
                a.get("quote") or x["bot"][:60],
                a.get("minutes"),
                who=uid if kind == "ignore" else "",
                who_name=name if kind == "ignore" else "",
                now=now,
            )
            if rec is None:
                logger.info(f"{TAG} {conv} 约束不记：{why}")
            else:
                h.store.event("hold", f"{conv} 机器人说「{rec['say'][:24]}」→ {rec['plan']}", now)
