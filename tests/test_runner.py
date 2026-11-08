#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""到点去做的那一下（modules/runner.py）单测：不装 AstrBot 也能跑 —— 用一个假的 astrbot.api.logger、假的宿主和假的 QQ 桥，
把插件的钟一秒一秒往前拨，数它叫了几次模型、发了几次、打了几行日志：python tests/test_runner.py [插件目录 默认上一层]
  - 发不出去（QQ 拒收）一整个宽限：模型只叫 1 次（写好的那句存着，重试只重发），试的次数越隔越久，日志不刷屏，最后记成没做成
  - QQ 一直没连上：模型一次都不叫
  - 先没连上、后来连上：补发，发的是第一次写好的那句
  - 不是好友（私聊）/ 被禁言（群里）/ 发送时 QQ 明确拒了：直接记成没做成，不再试，不叫模型
  - 群里答应、要私聊发、他不是好友：退回群里 @ 他
  - 禁言在宽限内解：到点再发一次，中间不试
"""

import asyncio
import importlib
import sys
import time
import types
from datetime import datetime
from pathlib import Path

d = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent).resolve()
LOGS = []


class _Logger:
    def info(self, m):
        LOGS.append(str(m))

    def warning(self, m):
        LOGS.append(str(m))

    def debug(self, m):
        pass


# 假的 astrbot：runner 只用到 astrbot.api.logger
_ab = types.ModuleType("astrbot")
_api = types.ModuleType("astrbot.api")
_api.logger = _Logger()
_ab.api = _api
sys.modules["astrbot"] = _ab
sys.modules["astrbot.api"] = _api
sys.path.insert(0, str(d.parent))
R = importlib.import_module(f"{d.name}.modules.runner")
F = importlib.import_module(f"{d.name}.core.failure")
T = importlib.import_module(f"{d.name}.core.table")
Hd = importlib.import_module(f"{d.name}.core.hold")
ck = importlib.import_module(f"{d.name}.core.clock")

RES = []
BJ = ck.BEIJING
G1 = "napcat:GroupMessage:7001"
P1 = "napcat:FriendMessage:10001"
AMU = "10001"
NOW = datetime(2026, 11, 8, 15, 0, tzinfo=BJ).timestamp()


def check(c, m, why=""):
    RES.append((bool(c), m))
    print(("  [过]   " if c else "  [没过] ") + m + ("" if c or not why else f"\n           {str(why)[:700]}"))


class Bridge:
    def __init__(self):
        self.llm_calls = 0
        self.sends = []  # (umo, 话, @谁)
        self.connected_v = True
        self.pre = {}  # "private" / "group" → (原因, 明确发不了, 禁言到几点)
        self.send_result = (True, "", False)

    def is_ai(self, uid):
        return False

    def connected(self, umo):
        return self.connected_v

    async def precheck(self, kind, umo, uid=None):
        return self.pre.get(kind, ("", False, 0.0))

    async def llm_allowed(self, umo):
        return True

    async def provider_id(self, conf, umo):
        return "fake"

    async def persona(self, umo):
        return ""

    async def llm(self, pid, system, prompt, timeout=30):
        self.llm_calls += 1
        return f"到点啦（第{self.llm_calls}次写的）"

    async def send(self, umo, text, at=None):
        self.sends.append((umo, text, at))
        r = self.send_result(umo) if callable(self.send_result) else self.send_result
        return r

    async def remember(self, umo, hint, line):
        pass


class Store:
    def __init__(self):
        self.events = []

    def event(self, kind, text, now=None):
        self.events.append((kind, text))


class Host:
    def __init__(self, grace=60):
        self.t = NOW
        self.tz, self.tz_label = BJ, "北京时间"
        self.table = T.Table({}, BJ, {"grace_min": grace})
        self.holds = Hd.Holds({}, BJ)
        self.bridge = Bridge()
        self.store = Store()

    def now(self):
        return self.t

    def c(self, group, key, default):
        return default

    def on(self):
        return True

    def tasks_on(self):
        return True

    def promise_on(self):
        return True

    def fallback_on(self):
        return True

    def reload_conf(self):
        pass

    def save(self, force=False):
        pass

    def tick_sec(self):
        return 20.0


def task(h, conv=G1, scene="group", via="at", what="提醒他关火", due=None):
    t, _ = h.table.add_task(conv, conv, scene, AMU, "阿木", what, due or NOW + 60, via=via, now=NOW)
    return t


def run_until(h, r, t, end, step=5.0):
    """插件的钟从现在往前拨到 end，每 step 秒跑一圈（跟后台每 20 秒一圈一样，只是更密）"""
    while h.t <= end and t["status"] == "pending":
        asyncio.run(r.round())
        h.t += step


print("[1 QQ 一直拒收（不是明确发不了）：一整个宽限]")
h = Host()
r = R.Runner(h)
t = task(h)
h.bridge.send_result = (False, F.REFUSED, False)
LOGS.clear()
run_until(h, r, t, NOW + 60 + 2 * 3600)
check(t["status"] == "missed" and t["apology"] == "owed", "过了宽限：记成没做成、欠一个道歉")
check(h.bridge.llm_calls == 1, f"回退检查：模型只叫了 {h.bridge.llm_calls} 次（写好的那句存着，重试只重发；以前每次重试都重写）")
check(len(h.bridge.sends) <= 9, f"回退检查：一小时里只试发了 {len(h.bridge.sends)} 次（1、2、5、10 分钟……越隔越久；以前每分钟一次）")
check(len({x[1] for x in h.bridge.sends}) == 1, "每次重发的都是第一次写好的那句")
lines = [x for x in LOGS if f"#{t['n']}" in x]
check(len(lines) <= 4, f"回退检查：这件事的日志只有 {len(lines)} 行（同一个原因 10 分钟一行；以前每次两行）", lines)

print("\n[2 QQ 一直没连上]")
h = Host()
r = R.Runner(h)
t = task(h)
h.bridge.connected_v = False
run_until(h, r, t, NOW + 60 + 2 * 3600)
check(t["status"] == "missed" and h.bridge.llm_calls == 0 and not h.bridge.sends, "回退检查：连不上就不叫模型、不发；过了宽限记成没做成", (h.bridge.llm_calls, len(h.bridge.sends)))
check(t["apo_why"] == F.OFFLINE and t["tries"] <= 12, f"原因写的是 QQ 没连上；一小时里看了 {t['tries']} 次（先密后疏）")

print("\n[3 开头没连上、后来连上了：补发第一次写好的那句]")
h = Host()
r = R.Runner(h)
t = task(h)
h.bridge.connected_v = False
asyncio.run(r.round())
check(t["status"] == "pending" and t["tries"] == 0, "还没到点：不动")
h.t = NOW + 61
asyncio.run(r.round())
check(t["tries"] == 1 and h.bridge.llm_calls == 0, "到点了没连上：记一次，不叫模型")
h.bridge.connected_v = True
h.bridge.send_result = (False, F.REFUSED, False)
h.t = NOW + 61 + 16
asyncio.run(r.round())
check(h.bridge.llm_calls == 1 and len(h.bridge.sends) == 1, "15 秒后连上了：写一次、发一次（QQ 拒了）")
h.bridge.send_result = (True, "", False)
h.t += 60
asyncio.run(r.round())
check(t["status"] == "pending" and len(h.bridge.sends) == 1, "没到下一次（第二次没成 → 隔 2 分钟）：不试")
h.t += 70
asyncio.run(r.round())
check(t["status"] == "done" and h.bridge.sends[-1][1] == "到点啦（第1次写的）" and h.bridge.llm_calls == 1, "补发成了：发的是第一次写好的那句，模型还是只叫了 1 次", h.bridge.sends)

print("\n[4 明确发不了：不再试]")
h = Host()
r = R.Runner(h)
t = task(h, conv=P1, scene="private", via="private")
h.bridge.pre = {"private": (F.NOT_FRIEND, True, 0.0)}
h.t = NOW + 61
asyncio.run(r.round())
check(t["status"] == "missed" and h.bridge.llm_calls == 0 and not h.bridge.sends and "好友" in t["apo_why"],
      "回退检查：私聊里的、他不是好友 → 直接记成没做成（不叫模型、不发、不再试）")
h = Host()
r = R.Runner(h)
t = task(h)
h.bridge.pre = {"group": (F.MUTED, True, time.time() + 5 * 3600)}
h.t = NOW + 61
asyncio.run(r.round())
check(t["status"] == "missed" and not h.bridge.sends and "禁言" in t["apo_why"], "回退检查：群里被禁言、宽限内解不了 → 直接记成没做成")
h = Host()
r = R.Runner(h)
t = task(h)
h.bridge.send_result = (False, F.NOT_IN_GROUP, True)
h.t = NOW + 61
asyncio.run(r.round())
check(t["status"] == "missed" and len(h.bridge.sends) == 1, "发的时候 QQ 明确拒了（机器人不在群里）→ 记成没做成，不再试")

print("\n[5 群里答应、要私聊发、他不是好友 → 退回群里 @ 他]")
h = Host()
r = R.Runner(h)
t = task(h, via="private")
h.bridge.pre = {"private": (F.NOT_FRIEND, True, 0.0)}
h.t = NOW + 61
asyncio.run(r.round())
check(t["status"] == "done" and h.bridge.sends == [(G1, "到点啦（第1次写的）", AMU)], "私聊那条路不走，改在原来的群里 @ 他", h.bridge.sends)

print("\n[6 禁言在宽限内解：到点再发一次，中间不试]")
h = Host()
r = R.Runner(h)
t = task(h)
h.bridge.pre = {"group": (F.MUTED, True, time.time() + 600)}
h.t = NOW + 61
asyncio.run(r.round())
check(t["status"] == "pending" and t["tries"] == 1 and abs(t["next_try"] - (NOW + 61 + 605)) < 3, "知道 10 分钟后解禁：排到解禁以后", t.get("next_try"))
for _ in range(10):
    h.t += 55
    asyncio.run(r.round())
check(t["status"] == "pending" and not h.bridge.sends and h.bridge.llm_calls == 0, "解禁之前一次都不试、不叫模型")
h.bridge.pre = {}
h.t = NOW + 61 + 610
asyncio.run(r.round())
check(t["status"] == "done" and len(h.bridge.sends) == 1, "解禁以后：发了一次")

print("\n[7 写的时候他改了时间：这次不发，上次写的作废]")
h = Host()
r = R.Runner(h)
t = task(h)
orig = h.bridge.llm


async def edit_while_writing(pid, system, prompt, timeout=30):
    out = await orig(pid, system, prompt, timeout)
    h.table.edit(t, due=NOW + 3 * 3600, now=h.t)
    return out


h.bridge.llm = edit_while_writing
h.t = NOW + 61
asyncio.run(r.round())
check(t["status"] == "pending" and not h.bridge.sends and T.Table.draft(t) is None, "改过时间：旧的那句不发、不存成待发的")

ok = sum(1 for c_, _ in RES if c_)
bad = [m for c_, m in RES if not c_]
print("\n" + "=" * 50 + f"\n  结果：{ok} 项过了" + (f"，{len(bad)} 项没过" if bad else "，全过"))
for m in bad:
    print("    -", m)
sys.exit(1 if bad else 0)
