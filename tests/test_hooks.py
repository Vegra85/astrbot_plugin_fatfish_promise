#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""main.py 那几个钩子的单测（不用装 AstrBot）：python tests/test_hooks.py [插件目录 默认上一层]
用一套假的 astrbot（只有 main.py / modules 用到的那几个名字）、假的事件、假的模型，把插件的钟钉死，直接调钩子：
  - v0.1.1 默认「有人找就醒」：它说了去睡以后，没叫它的话挡下；@ 它 / 私聊它的照常回，不发任何提示
  - 硬睡档（配置 wake.mode = hard）：照以前那样挡，但第一次挡住找它的人要发一句固定的系统提示（同一个人一晚一次）
  - 老用户的配置里没有 wake.mode 这一项 → 走新默认
  - 跟活人感一起装：它「叫停 / 刹车」以后在事件上留了「实际发出去的字」（alive_sent_text）→ 只从发出去的字里认承诺和「我去睡了」；
    没留这个字段 → 照旧用整段
这里的事件 / 模型都是假的：AstrBot 的钩子顺序、活人感真的会不会留这个字段，这个文件验不了（要看 tests/e2e_astrbot.py 和真机）。
"""

import asyncio
import importlib
import json
import shutil
import sys
import tempfile
import types
from datetime import datetime
from pathlib import Path

d = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent).resolve()
LOGS = []
TMP = Path(tempfile.mkdtemp(prefix="promise_hooks_"))


class _Logger:
    def info(self, m):
        LOGS.append(str(m))

    def warning(self, m):
        LOGS.append("WARN " + str(m))

    def debug(self, m):
        pass


class _Filter:
    """假的 filter：装饰器原样放行"""

    def __getattr__(self, name):
        def deco(*a, **k):
            return lambda fn: fn

        return deco


class Plain:
    def __init__(self, text=""):
        self.text = text


class At:
    def __init__(self, qq=""):
        self.qq = qq


class MessageChain:
    def __init__(self, chain=None):
        self.chain = list(chain or [])


class _RCT:
    STREAMING_FINISH = "streaming_finish"


class Star:
    def __init__(self, context):
        self.context = context


class StarTools:
    @staticmethod
    def get_data_dir(name):
        p = TMP / f"{name}_{len(list(TMP.iterdir()))}"
        p.mkdir(parents=True, exist_ok=True)
        return p


def _mod(name, **kw):
    m = types.ModuleType(name)
    m.__dict__.update(kw)
    sys.modules[name] = m
    return m


_comp = _mod("astrbot.api.message_components", Plain=Plain, At=At)
_api = _mod("astrbot.api", logger=_Logger(), AstrBotConfig=dict, message_components=_comp)
_mod("astrbot.api.event", AstrMessageEvent=object, ResultContentType=_RCT, filter=_Filter(), MessageChain=MessageChain)
_mod("astrbot.api.provider", ProviderRequest=object)
_mod("astrbot.api.star", Context=object, Star=Star, StarTools=StarTools)
_mod("astrbot", api=_api)
sys.path.insert(0, str(d.parent))
M = importlib.import_module(f"{d.name}.main")
ck = importlib.import_module(f"{d.name}.core.clock")

RES = []
BJ = ck.BEIJING
G1, P1 = "napcat:GroupMessage:7001", "napcat:FriendMessage:10001"
AMU, XC, LW, BOSS, BOT = "10001", "20002", "30003", "90009", "60006"
NAMES = {AMU: "阿木", XC: "小橙", LW: "老王", BOSS: "管理员"}
NIGHT = datetime(2026, 11, 8, 23, 40, tzinfo=BJ).timestamp()


def check(c, m, why=""):
    RES.append((bool(c), m))
    print(("  [过]   " if c else "  [没过] ") + m + ("" if c or not why else f"\n           {str(why)[:700]}"))


class Resp:
    def __init__(self, text):
        self.completion_text = text


class Ctx:
    def __init__(self):
        self.sent = []  # 插件自己主动发出去的 (umo, 文字, @谁)
        self.prompts = []  # 抽取时给模型的提示
        self.reply = '{"items": []}'

    def get_registered_star(self, name):
        return None

    def get_config(self, umo=None):
        return {"admins_id": [BOSS]}

    async def get_current_chat_provider_id(self, umo):
        return "fake"

    async def llm_generate(self, chat_provider_id=None, prompt=None, system_prompt=None):
        self.prompts.append(str(prompt))
        return Resp(self.reply)

    async def send_message(self, umo, chain):
        text = "".join(c.text for c in chain.chain if isinstance(c, Plain))
        at = next((c.qq for c in chain.chain if isinstance(c, At)), None)
        self.sent.append((umo, text, at))
        return True

    def register_web_api(self, *a, **k):
        pass


class Res:
    def __init__(self, text):
        self.chain = [Plain(text)]
        self.result_content_type = None

    def is_llm_result(self):
        return True


class Ev:
    def __init__(self, uid, text="", gid="7001", directed=True, reply=None, extra=None):
        self.uid, self.gid, self.message_str = uid, gid, text
        self.is_at_or_wake_command = directed
        self._extra = dict(extra or {})
        self._res = Res(reply) if reply is not None else None
        self.stopped = False
        self.unified_msg_origin = f"napcat:GroupMessage:{gid}" if gid else f"napcat:FriendMessage:{uid}"

    def get_platform_id(self):
        return "napcat"

    def get_group_id(self):
        return self.gid

    def is_private_chat(self):
        return not self.gid

    def get_sender_id(self):
        return self.uid

    def get_self_id(self):
        return BOT

    def get_sender_name(self):
        return NAMES.get(self.uid, self.uid)

    def is_admin(self):
        return self.uid == BOSS

    def get_extra(self, k, default=None):
        return self._extra.get(k, default)

    def set_extra(self, k, v):
        self._extra[k] = v

    def stop_event(self):
        self.stopped = True

    def get_result(self):
        return self._res

    def clear_result(self):
        self._res = None


def plugin(conf=None, now=NIGHT):
    ctx = Ctx()
    p = M.FatfishPromise(ctx, conf if conf is not None else {})
    box = {"t": now}
    p.clock = lambda: box["t"]
    return p, ctx, box


def sleep_in(p, conv, scene, now, say="困了我去睡了"):
    rec, why = p.holds.declare(conv, conv, scene, "sleep", say, None, now=now)
    assert rec, why
    return rec


async def drain(p):
    for _ in range(5):
        jobs = list(p.runner.jobs)
        if not jobs:
            break
        await asyncio.gather(*jobs, return_exceptions=True)


async def main():
    print("[1 默认配置（没有 wake.mode 这一项）：它说了去睡 → 没叫它的不接，找它的照常回，不发提示]")
    for label, conf in (("配置是空的（老用户升级上来）", {}), ("配置里只有老的那几项", {"wake": {"admin_ats": 2, "people": 3}, "hold": {"enable": True}})):
        p, ctx, box = plugin(conf)
        sleep_in(p, G1, "group", NIGHT)
        box["t"] = NIGHT + 1200
        e0 = Ev(LW, "今天好冷", directed=False)
        await p.gate(e0)
        check(e0.stopped and not ctx.sent, f"{label}：没叫它的话 → 挡下（不叫模型），不发提示", (e0.stopped, ctx.sent))
        e1 = Ev(AMU, "帮我看看这个")
        await p.gate(e1)
        check(not e1.stopped and not ctx.sent and not p.holds.live(G1, box["t"]),
              f"回退检查：{label}：夜里有人 @ 它一次 → 不挡、照常回（老的不回、也没有任何提示）", (e1.stopped, ctx.sent))
        e2 = Ev(XC, "那我也问一个")
        await p.gate(e2)
        check(not e2.stopped, f"{label}：醒了以后别人找它也照常")
    p, ctx, box = plugin({})
    sleep_in(p, P1, "private", NIGHT, "我先睡了")
    box["t"] = NIGHT + 20
    e = Ev(AMU, "等等我还有事", gid="")
    await p.gate(e)
    check(not e.stopped and not ctx.sent, "回退检查：私聊里它说完「我先睡了」20 秒，他说「等等我还有事」→ 照常回", (e.stopped, ctx.sent))
    p, ctx, box = plugin({})
    sleep_in(p, G1, "group", NIGHT)
    box["t"] = NIGHT + 5
    e = Ev(AMU, "顺便问一下明天几点开会", reply="明天十点")
    await p.on_deco(e)
    check(e.get_result() is not None, "回退检查：它刚说完要睡、还在路上的那条是回 @ 它的人的 → 照常发出去")
    e = Ev(LW, "哈哈哈", directed=False, reply="笑死")
    await p.on_deco(e)
    check(e.get_result() is None, "还在路上的那条是接没叫它的话的 → 不发")

    print("\n[2 硬睡档（wake.mode = hard）：照以前那样挡，第一次挡住找它的人发一句系统提示]")
    p, ctx, box = plugin({"wake": {"mode": "hard"}})
    rec = sleep_in(p, G1, "group", NIGHT)
    box["t"] = NIGHT + 1200
    e = Ev(AMU, "帮我看看这个")
    await p.gate(e)
    await drain(p)
    check(e.stopped and p.holds.live(G1, box["t"]), "硬睡档：一个人 @ 它 → 不回（照以前）")
    wake_at = ck.fmt(rec["until"], BJ, "%H:%M")
    check(len(ctx.sent) == 1 and ctx.sent[0][0] == G1 and ctx.sent[0][2] == AMU and "系统提示" in ctx.sent[0][1]
          and wake_at in ctx.sent[0][1] and "睡" in ctx.sent[0][1],
          f"回退检查：被挡的人收到一句系统提示（群里 @ 他；写着它睡了、大概 {wake_at} 回来）（老的无声无息）", ctx.sent)
    check("困了我去睡了" in (ctx.sent[0][1] if ctx.sent else ""), "提示里带着它当时说的那句", ctx.sent)
    e = Ev(AMU, "人呢")
    await p.gate(e)
    await drain(p)
    check(e.stopped and len(ctx.sent) == 1, "同一个人再找：还是不回，不再提示", ctx.sent)
    e = Ev(LW, "今天好冷", directed=False)
    await p.gate(e)
    await drain(p)
    check(e.stopped and len(ctx.sent) == 1, "没叫它的话被挡：不提示", ctx.sent)
    e = Ev(XC, "它怎么不理人")
    await p.gate(e)
    await drain(p)
    check(e.stopped and len(ctx.sent) == 2 and ctx.sent[1][2] == XC, "回退检查：另一个人第一次被挡 → 也提示他一次", ctx.sent)
    check(not ctx.prompts, "这些提示是固定的字，没有叫模型", ctx.prompts)
    p, ctx, box = plugin({"wake": {"mode": "hard"}})
    sleep_in(p, P1, "private", NIGHT, "我先睡了")
    box["t"] = NIGHT + 20
    e = Ev(AMU, "等等我还有事", gid="")
    await p.gate(e)
    await drain(p)
    check(e.stopped and len(ctx.sent) == 1 and ctx.sent[0][0] == P1 and ctx.sent[0][2] is None and "系统提示" in ctx.sent[0][1],
          "回退检查：硬睡档私聊里被挡 → 私聊里给他一句提示（不 @）", ctx.sent)
    p, ctx, box = plugin({"wake": {"mode": "hard"}})
    sleep_in(p, G1, "group", NIGHT)

    async def boom(umo, chain):
        raise RuntimeError("QQ 拒收")

    ctx.send_message = boom
    box["t"] = NIGHT + 1200
    e = Ev(AMU, "在吗")
    await p.gate(e)
    await drain(p)
    check(e.stopped, "提示发不出去：不影响挡（不报错）")

    print("\n[3 跟活人感一起装：只从真发出去的字里认]")
    full = "好 明早8点叫你起床 我先去睡了"
    task = {"type": "task", "what": "叫他起床", "when": "明早8点", "repeat": "", "via": "", "quote": "明早8点叫你起床"}
    hold = {"type": "hold", "kind": "sleep", "minutes": None, "quote": "我先去睡了"}
    DAY = datetime(2026, 11, 8, 15, 0, tzinfo=BJ).timestamp()

    async def said(extra, reply=full, user="明早8点叫我起床"):
        p, ctx, box = plugin({}, DAY)
        ctx.reply = json.dumps({"items": [task, hold]}, ensure_ascii=False)
        e = Ev(AMU, user, reply=reply, extra=extra)
        await p.after_sent(e)
        await drain(p)
        return p, ctx

    p, ctx = await said({})
    check(len(p.table.pending()) == 1 and p.holds.live(G1, DAY + 1), "（对照）没装活人感 / 没留这个字段：照旧从整段里认（记下叫醒、记下去睡）",
          (p.table.pending(), p.holds.live(G1, DAY + 1)))
    p, ctx = await said({"alive_sent_text": None})
    check(len(p.table.pending()) == 1 and p.holds.live(G1, DAY + 1), "字段在但是 None：照旧用整段")
    p, ctx = await said({"alive_sent_text": ""})
    check(not p.table.pending() and not p.holds.live(G1, DAY + 1) and not ctx.prompts,
          "回退检查：活人感叫停、一个字都没发出去（留的是空字）→ 什么都不认，连模型都不叫（老的照样记下叫醒和去睡）",
          (p.table.pending(), p.holds.live(G1, DAY + 1), ctx.prompts))
    p, ctx = await said({"alive_sent_text": "好 明早8点叫你起床"})
    check(len(p.table.pending()) == 1 and not p.holds.live(G1, DAY + 1),
          "回退检查：只发出去前半段「好 明早 8 点叫你起床」、后半段「我先去睡了」被叫停 → 记下叫醒，不记去睡",
          (p.table.pending(), p.holds.live(G1, DAY + 1)))
    check(ctx.prompts and "我先去睡了" not in ctx.prompts[-1], "回退检查：给抽取模型看的也只有发出去的那半段", ctx.prompts[-1:] if ctx.prompts else "")
    p, ctx = await said({"alive_sent_text": "我先去睡了"}, reply="我先去睡了 对了明早8点叫你起床")
    check(not p.table.pending() and p.holds.live(G1, DAY + 1), "回退检查：发出去的只有「我先去睡了」→ 只记去睡，没发出去的那句叫醒不记",
          (p.table.pending(), p.holds.live(G1, DAY + 1)))
    p, ctx = await said({"alive_sent_text": 12345})
    check(len(p.table.pending()) == 1, "字段里不是字（别的插件乱写）：当它没有，照旧用整段")

    class BadEv(Ev):
        def get_extra(self, k, default=None):
            if k == "alive_sent_text":
                raise RuntimeError("x")
            return super().get_extra(k, default)

    p, ctx, box = plugin({}, DAY)
    ctx.reply = json.dumps({"items": [task]}, ensure_ascii=False)
    e = BadEv(AMU, "明早8点叫我起床", reply=full)
    await p.after_sent(e)
    await drain(p)
    check(len(p.table.pending()) == 1, "读这个字段时出错：当它没有，照旧用整段（不因为它丢掉这句）")


asyncio.run(main())
shutil.rmtree(TMP, ignore_errors=True)  # 假的插件数据目录：用完就删
ok = sum(1 for c_, _ in RES if c_)
bad = [m for c_, m in RES if not c_]
print("\n" + "=" * 50 + f"\n  结果：{ok} 项过了" + (f"，{len(bad)} 项没过" if bad else "，全过"))
for m in bad:
    print("    -", m)
sys.exit(1 if bad else 0)
