#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""约束单测（不用装 AstrBot）：python tests/test_hold.py [插件目录 默认上一层]
测 core/hold.py：走多久（说了多久 / 默认 / 夜里睡到早上 / 白天小睡）、挡什么（全不回 / 只回 @ 的 / 只不回那个人）、
叫醒（管理员 @ 两次、几个不同的真人、私聊连发、刚说完只有管理员、晚安不算、别人家的 AI 叫不醒）、回来以后的那句、
还在路上的回复、表情包、关掉的种类。
v0.1.1 起默认是「有人找就醒」（第 11 节）；上面「叫醒」那一套是可选的硬睡档，第 2 ~ 6、8 节里测它的地方都写明了 wake_mode="hard"；
硬睡档挡住人要说一声在第 12 节。"""

import random
import sys
from datetime import datetime
from pathlib import Path

d = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(d))
from core import clock as ck  # noqa: E402
from core import sticker  # noqa: E402
from core.hold import BYE, KINDS, Holds  # noqa: E402

RES = []
BJ = ck.BEIJING
G1 = "aiocqhttp:GroupMessage:7001"
G2 = "aiocqhttp:GroupMessage:7002"
P1 = "aiocqhttp:FriendMessage:10001"
AMU, XC, LW, AZ, BOSS, BOT = "10001", "20002", "30003", "40004", "90009", "60006"


def check(c, m, why=""):
    RES.append((bool(c), m))
    print(("  [过]   " if c else "  [没过] ") + m + ("" if c or not why else f"\n           {str(why)[:600]}"))


def at(y, mo, d_, h, mi):
    return datetime(y, mo, d_, h, mi, tzinfo=BJ).timestamp()


DAY = at(2026, 11, 8, 15, 0)
NIGHT = at(2026, 11, 8, 23, 40)


def fresh(**conf):
    logs = []
    return Holds({}, BJ, conf, logs.append, rng=random.Random(7)), logs


def gate(h, uid, now, directed=True, admin=False, ai=False, text="在吗", conv=G1, scene="group"):
    return h.gate(conv, scene, uid, {AMU: "阿木", XC: "小橙", LW: "老王", AZ: "阿珍", BOSS: "管理员"}.get(uid, uid), directed, admin, ai, text, now)


print("[1 走多久]")
h, logs = fresh()
sec, why = h.plan("lurk", 40, DAY)
check(38 * 60 <= sec <= 42 * 60 and "40 分钟" in why, "它说了 40 分钟：就按 40 分钟（±5%）", (sec, why))
sec, why = h.plan("away", 2000, DAY)
check(abs(sec - 720 * 60) <= 0.05 * 720 * 60 + 1, "说三十几个小时：最多按 12 小时", sec)
sec, _ = h.plan("away", 1, DAY)
check(sec >= 3 * 60 * 0.95, "说 1 分钟：最少按 3 分钟", sec)
for kind, base in (("away", 45), ("lurk", 25), ("quiet", 30), ("ignore", 8), ("nosticker", 90)):
    xs = [h.plan(kind, None, DAY)[0] / 60 for _ in range(40)]
    check(all(base * 0.85 - 0.01 <= x <= base * 1.15 + 0.01 for x in xs) and max(xs) - min(xs) > 0.5,
          f"没说多久的「{KINDS[kind][0]}」：默认 {base} 分钟 ±15%（不是每次都一样）", (min(xs), max(xs)))
sec, why = h.plan("sleep", None, DAY)
check(30 * 0.85 * 60 <= sec <= 30 * 1.15 * 60 and "小睡" in why, "白天说要睡：小睡 30 分钟左右", why)
sec, why = h.plan("sleep", None, NIGHT)
wake = ck.dt(NIGHT + sec, BJ)
check(wake.day == 9 and wake.hour == 8 and wake.minute <= 10 and "睡到" in why, "夜里 23:40 说要睡：睡到早上 8 点出头", (wake, why))
sec, _ = h.plan("sleep", None, at(2026, 11, 9, 2, 0))
check(ck.dt(at(2026, 11, 9, 2, 0) + sec, BJ).hour == 8, "凌晨 2 点说要睡：也是睡到 8 点")
sec, _ = h.plan("sleep", 20, NIGHT)
check(19 * 60 <= sec <= 21 * 60, "夜里说「睡 20 分钟」：按它说的", sec)
h2, _ = fresh(night_from=8, wake_hour=8)
check(not h2.in_night(NIGHT) and "小睡" in h2.plan("sleep", None, NIGHT)[1], "夜里和早上填一样：不分夜里白天，都是小睡")
h3, _ = fresh(night_from=1, wake_hour=6)
check(h3.in_night(at(2026, 11, 9, 3, 0)) and not h3.in_night(NIGHT), "夜里不跨零点（1 点到 6 点）也认得")

print("\n[2 记一条 / 挡什么]")
h, logs = fresh(wake_mode="hard")  # （v0.1.1）「一个人 @ 也不回」是硬睡档的行为；默认档见第 11 节
r, why = h.declare(G1, G1, "group", "sleep", "我去睡了 晚安", None, now=DAY)
check(r and r["kind"] == "sleep" and r["until"] > DAY and why == "", "记上了")
check(any("真的睡觉" in x for x in logs), "日志写了一行", logs)
out = gate(h, AMU, DAY + 10, directed=False)
check(out["block"] and out["rec"] is r, "回退检查：说了去睡 → 没 @ 它的消息不回")
out = gate(h, AMU, DAY + 20, directed=True)
check(out["block"] and not out["woke"], "硬睡档：一个人 @ 一次也不回（叫不醒）")
check(not gate(h, AMU, DAY + 20, conv=G2)["block"], "别的群照常")
check(not gate(h, AMU, DAY + 20, conv=P1, scene="private")["block"], "私聊照常")
r2, _ = h.declare(G1, G1, "group", "lurk", "我先潜水了", None, now=DAY + 30)
check(len(h.live(G1, DAY + 31)) == 1 and h.live(G1, DAY + 31)[0]["kind"] == "lurk", "睡觉 / 离开 / 潜水一个群里只留最新的一条")
h, _ = fresh()
h.declare(G1, G1, "group", "quiet", "我少说两句", None, now=DAY)
check(gate(h, AMU, DAY + 5, directed=False)["block"] and not gate(h, AMU, DAY + 6, directed=True)["block"], "少说：没 @ 的不回，@ 它的照常回")
h, _ = fresh()
h.declare(G1, G1, "group", "ignore", "不理你了", None, who=AMU, who_name="阿木", now=DAY)
check(gate(h, AMU, DAY + 5)["block"] and not gate(h, XC, DAY + 5)["block"], "不理某人：只不回他，别人照常")
check(h.declare(G1, G1, "group", "ignore", "不理他了", None, now=DAY)[0] is None, "认不出不理谁 → 不记")
h, _ = fresh()
h.declare(G1, G1, "group", "nosticker", "不发表情包了", None, now=DAY)
check(not gate(h, AMU, DAY + 5, directed=False)["block"] and h.has(G1, "nosticker", DAY + 5), "不发表情包：照常回话，只是不发表情包")
h, _ = fresh(lurk_min=0)
check(h.declare(G1, G1, "group", "lurk", "我潜了", None, now=DAY)[0] is None and not h.kind_on("lurk"), "配置成 0 分钟 = 不管这一种")
h, _ = fresh(enable=False)
check(h.declare(G1, G1, "group", "sleep", "睡了", None, now=DAY)[0] is None, "约束总开关关着：不记")
h, _ = fresh()
h.declare(G1, G1, "group", "sleep", "我去睡了", None, now=DAY)
h.declare(G2, G2, "group", "nosticker", "不发表情包了", None, now=DAY)
h.configure({"enable": False})
check(not gate(h, AMU, DAY + 60, directed=False)["block"] and h.would_block(G1, AMU, False, DAY + 60) is None
      and h.gone(G1, DAY + 60) is None and h.has(G2, "nosticker", DAY + 60) is None and h.snapshot(DAY + 60)["live"] == [],
      "回退检查：已经在睡的时候把约束总开关关掉 → 马上照常回（挡消息、发送前复查、表情包、面板都不算它）")
h.configure({"enable": True})
check(gate(h, AMU, DAY + 70, directed=False)["block"], "再打开（还没到点）→ 接着挡")
h.configure({"sleep_nap_min": 0})
check(not gate(h, AMU, DAY + 80, directed=False)["block"] and h.has(G2, "nosticker", DAY + 80),
      "回退检查：把「睡觉」的时长填 0 → 已经在睡的也不挡；别的种类照常")

print("\n[3 硬睡档的叫醒：管理员 @ 两次]")
h, _ = fresh(wake_mode="hard")
r, _ = h.declare(G1, G1, "group", "sleep", "我去睡了", None, now=DAY)
o1 = gate(h, BOSS, DAY + 30, admin=True)
check(o1["block"] and not o1["woke"], "管理员 @ 第一次：还不回")
o2 = gate(h, BOSS, DAY + 50, admin=True)
check(o2["woke"] is r and not o2["block"] and h.live(G1, DAY + 51) == [], "回退检查：管理员 @ 第二次 → 醒了，这条照常回")
b = h.backs_for(G1)
check(len(b) == 1 and b[0]["how"] == "woke" and b[0]["by"] == "管理员" and b[0]["by_admin"] and b[0]["n"] == 1, "回来以后的那句：谁叫醒的、这期间没回几条（叫醒它的那条不算）", b)
h, _ = fresh(wake_mode="hard", wake_admin_ats=0)
h.declare(G1, G1, "group", "sleep", "我去睡了", None, now=DAY)
for i in range(5):
    gate(h, BOSS, DAY + 10 * i, admin=True)
check(h.live(G1, DAY + 60), "配置成 0：管理员也叫不醒")

print("\n[4 硬睡档的叫醒：几分钟里几个不同的真人 @]")
h, _ = fresh(wake_mode="hard", wake_people=3, wake_window_min=5, wake_floor_min=2)
r, _ = h.declare(G1, G1, "group", "away", "我先去吃饭了", None, now=DAY)
gate(h, AMU, DAY + 200)
gate(h, AMU, DAY + 210)
gate(h, AMU, DAY + 220)
check(h.live(G1, DAY + 221), "同一个人 @ 三次：不算三个人，不醒")
gate(h, XC, DAY + 230)
o = gate(h, LW, DAY + 240)
check(o["woke"] is r and not o["block"], "第三个不同的人 @ → 醒了")
check(h.backs_for(G1)[0]["by"] == "老王", "记着是谁叫醒的")
h, _ = fresh(wake_mode="hard", wake_people=3, wake_window_min=5)
h.declare(G1, G1, "group", "lurk", "潜了", None, now=DAY)
gate(h, AMU, DAY + 200)
gate(h, XC, DAY + 300)
o = gate(h, LW, DAY + 200 + 6 * 60)
check(o["block"] and not o["woke"], "三个人隔得太久（超过 5 分钟）：不算")
h, _ = fresh(wake_mode="hard")
h.declare(G1, G1, "group", "sleep", "睡了", None, now=DAY)
for u in (AMU, XC):
    gate(h, u, DAY + 200)
o = gate(h, LW, DAY + 210, ai=True)
check(o["block"] and not o["woke"] and "AI" in o["why"], "别人家的 AI @ 它：叫不醒（不算人）", o)
check(len(h.live(G1, DAY + 211)[0]["calls"]) == 2, "AI 的那条连「谁叫过它」都不记")

print("\n[5 硬睡档刚说完：只有管理员叫得醒；晚安不算叫]")
h, _ = fresh(wake_mode="hard", wake_floor_min=2, wake_people=3)
r, _ = h.declare(G1, G1, "group", "sleep", "我去睡了", None, now=DAY)
for u in (AMU, XC, LW):
    o = gate(h, u, DAY + 30, text="别睡啊")
check(o["block"] and not o["woke"], "刚说完 2 分钟内三个人叫：不醒")
h, _ = fresh(wake_mode="hard", wake_floor_min=2, wake_people=2)
h.declare(G1, G1, "group", "sleep", "我去睡了", None, now=DAY)
gate(h, AMU, DAY + 20, text="晚安")
gate(h, XC, DAY + 25, text="好梦~")
o = gate(h, LW, DAY + 130, text="诶你先别睡")
check(o["block"] and not o["woke"], "回退检查：刚说完时回的「晚安」「好梦」不算叫它（不然晚安来回停不下来）", (h.live(G1, DAY + 131) or [{}])[0].get("calls"))
o = gate(h, AZ, DAY + 140, text="快起来看这个")
check(o["woke"], "过了 2 分钟两个人真在叫 → 醒")
check(BYE.match("晚安啦") and BYE.match("好的") and BYE.match("[表情]") and not BYE.match("晚安前帮我看下这个"), "随口应一声（晚安、好的、表情）的认法")

print("\n[6 硬睡档私聊里叫醒]")
h, _ = fresh(wake_mode="hard", wake_private_msgs=3, wake_floor_min=2)
r, _ = h.declare(P1, P1, "private", "sleep", "我睡了", None, now=DAY)
for i in range(2):
    o = gate(h, AMU, DAY + 200 + i, conv=P1, scene="private", text=f"醒醒{i}")
check(o["block"], "私聊里发了 2 条：不醒")
o = gate(h, AMU, DAY + 210, conv=P1, scene="private", text="醒醒")
check(o["woke"] is r, "私聊里连着发 3 条 → 醒")
h, _ = fresh(wake_mode="hard", wake_private_msgs=0)
h.declare(P1, P1, "private", "sleep", "我睡了", None, now=DAY)
for i in range(6):
    gate(h, AMU, DAY + 200 + i, conv=P1, scene="private")
check(h.live(P1, DAY + 300), "配置成 0：私聊里叫不醒")

print("\n[7 到点 / 管理员关掉 / 回来以后的那句]")
h, logs = fresh()
r, _ = h.declare(G1, G1, "group", "lurk", "我先潜了", 10, now=DAY)
gate(h, AMU, DAY + 60, directed=False)
ended = h.tick(DAY + 11 * 60)
check(len(ended) == 1 and ended[0]["how"] == "time" and h.live(G1, DAY + 11 * 60) == [], "到点了：结束")
check(not gate(h, AMU, DAY + 11 * 60 + 1, directed=False)["block"], "结束以后照常回")
bs = h.backs_for(G1, XC)
check(len(bs) == 1 and bs[0]["n"] == 1, "回来以后：这个群下次说话时告诉它（谁来说都给）")
h.consume_backs(bs)
check(h.backs_for(G1, XC) == [], "说过一次就不再提")
h, _ = fresh()
h.declare(G1, G1, "group", "ignore", "不理你了", None, who=AMU, who_name="阿木", now=DAY)
h.tick(DAY + 40 * 60)
check(h.backs_for(G1, XC) == [] and len(h.backs_for(G1, AMU)) == 1, "「不理」结束：只在那个人来说话时告诉它")
h, _ = fresh()
h.declare(G1, G1, "group", "sleep", "睡了", None, now=DAY)
h.declare(G2, G2, "group", "lurk", "潜了", None, now=DAY)
check(h.release(conv=G1, by="管理员", now=DAY + 60) == 1 and h.live(G2, DAY + 60), "管理员让它在这个群回来：只结束这个群的")
check(h.backs_for(G1)[0]["how"] == "off", "回来的原因写的是管理员让回来的")
rid = h.live(G2, DAY + 60)[0]["id"]
check(h.release(rid=rid, now=DAY + 61) == 1 and h.live(G2, DAY + 62) == [], "面板按编号结束一条")
h, _ = fresh()
h.declare(G1, G1, "group", "sleep", "睡了", None, now=DAY)
h.tick(DAY + 13 * 3600)
check(h.backs_for(G1) == [], "回来以后 12 小时都没人说话：那句作废")

print("\n[8 还在路上的回复（发送前复查；硬睡档 —— 默认档见第 11 节）]")
h, _ = fresh(wake_mode="hard")
check(h.would_block(G1, AMU, True, DAY) is None, "没有约束：照常发")
h.declare(G1, G1, "group", "sleep", "我去睡了", None, now=DAY)
check(h.would_block(G1, AMU, True, DAY + 5) is not None, "回退检查：刚说完要睡、还在路上的那条回复 → 不发")
check(h.gone(G1, DAY + 5)["kind"] == "sleep" and h.gone(G2, DAY + 5) is None, "gone：这个群它在不在")
n_before = int(h.live(G1, DAY + 5)[0]["n"])
h.would_block(G1, AMU, True, DAY + 6)
check(int(h.live(G1, DAY + 6)[0]["n"]) == n_before, "只看不记（不算它错过了一条）")

print("\n[9 表情包的认法]")


class Image:
    def __init__(self, file="", path="", url="", subType=None):
        self.file, self.path, self.url, self.subType = file, path, url, subType


class Plain:
    def __init__(self, text):
        self.text = text


meme = Image(file="file:///data/plugin_data/astrbot_plugin_meme_manager/memes/happy/1.gif", path="/data/memes/happy/1.gif")
shot = Image(file="file:///tmp/screenshot.png", path="/tmp/screenshot.png")
qq = Image(file="abc.image", subType=1)
b64 = Image(file="base64://AAAA")
reg = {id(b64): {"source": "x"}}
check(sticker.is_sticker(meme) and sticker.is_sticker(qq) and sticker.is_sticker(b64, reg), "表情包：表情包插件的文件夹 / QQ 标的表情包 / 表情包插件登记过的")
check(not sticker.is_sticker(shot) and not sticker.is_sticker(b64) and not sticker.is_sticker(Plain("表情")), "截图、普通图、文字：不动")
keep, n = sticker.strip([Plain("哈哈"), meme, shot], None)
check(n == 1 and len(keep) == 2 and keep[1] is shot, "只拿掉表情包那张")


class TS:
    def __init__(self, names):
        self.tools = list(names)

    def names(self):
        return list(self.tools)

    def remove_tool(self, n):
        self.tools.remove(n)


class Req:
    pass


rq = Req()
shared = TS(["search_memes", "web_search", "send_sticker"])
rq.func_tool = shared
check(sticker.drop_tools(rq) == 2 and rq.func_tool.names() == ["web_search"] and shared.names() == ["search_memes", "web_search", "send_sticker"],
      "这一轮拿掉找表情的工具；共享的那份不动")
rq2 = Req()
rq2.func_tool = None
check(sticker.drop_tools(rq2) == 0, "没有工具：不报错")

print("\n[10 面板]")
h, _ = fresh()
h.declare(G1, G1, "group", "sleep", "我去睡了", None, now=DAY)
sn = h.snapshot(DAY + 60)
check(len(sn["live"]) == 1 and sn["live"][0]["name"] == "睡觉" and sn["live"][0]["left_min"] > 0, "面板：正在生效的约束、还剩多久")

# ───────── v0.1.1（11-10）：默认「有人找就醒」；硬睡是可选档，挡住人要说一声 ─────────
print("\n[11 默认档：说了去睡 / 离开 / 潜水 → 不接没叫它的话，有人找它就醒]")
h, logs = fresh()
r, _ = h.declare(G1, G1, "group", "sleep", "困了我去睡了", None, now=NIGHT)
o = gate(h, LW, NIGHT + 600, directed=False)
check(o["block"] and not o["woke"] and not o.get("tell"), "没叫它的话：不接（也不提示）")
o = gate(h, AMU, NIGHT + 1200, directed=True, text="帮我看看这个")
check(o["woke"] is r and not o["block"] and h.live(G1, NIGHT + 1201) == [], "回退检查：夜里一个人 @ 它一次 → 醒了，这条照常回（老的要 3 个人 / 管理员两次）", o)
b = h.backs_for(G1)
check(len(b) == 1 and b[0]["how"] == "woke" and b[0]["by"] == "阿木" and b[0]["n"] == 1, "回来以后给模型的那句：谁叫醒的、这期间没回几条", b)
check(not gate(h, LW, NIGHT + 1300, directed=False)["block"], "醒了以后照常")
h, _ = fresh()
r, _ = h.declare(P1, P1, "private", "sleep", "我先睡了", None, now=NIGHT)
o = gate(h, AMU, NIGHT + 20, conv=P1, scene="private", text="等等我还有事")
check(o["woke"] is r and not o["block"], "回退检查：私聊里它说完「我先睡了」20 秒，他说「等等我还有事」→ 照常回（老的头 2 分钟谁都叫不醒）", o)
h, _ = fresh()
r, _ = h.declare(G1, G1, "group", "sleep", "我去睡了", None, now=NIGHT)
o = gate(h, AMU, NIGHT + 20, text="晚安")
check(o["block"] and not o["woke"] and not o.get("tell") and h.live(G1, NIGHT + 21), "刚说完那两分钟里回一句「晚安」：不算找它（不然晚安来回停不下来）")
o = gate(h, XC, NIGHT + 30, text="先别睡 帮我看个东西")
check(o["woke"] is r, "回退检查：刚说完那两分钟里真有事找它 → 也醒", o)
h, _ = fresh()
h.declare(G1, G1, "group", "sleep", "我去睡了", None, now=NIGHT)
o = gate(h, LW, NIGHT + 600, ai=True)
check(o["block"] and not o["woke"] and h.live(G1, NIGHT + 601), "别人家的 AI @ 它：叫不醒")
for kind, say in (("lurk", "不说了不说了"), ("away", "我先去吃饭了")):
    h, _ = fresh()
    r, _ = h.declare(G1, G1, "group", kind, say, None, now=DAY)
    blocked = gate(h, LW, DAY + 60, directed=False)["block"]
    o = gate(h, AMU, DAY + 300, text="帮我看看这个")
    check(blocked and o["woke"] is r and not o["block"], f"回退检查：「{KINDS[kind][0]}」也一样：没叫它的不接，@ 它一次就回", o)
h, _ = fresh()
h.declare(G1, G1, "group", "ignore", "不理你了", None, who=AMU, who_name="阿木", now=DAY)
check(gate(h, AMU, DAY + 5)["block"] and h.live(G1, DAY + 6), "「不理你了」照旧：那个人 @ 也不回（别人照常）")
h, _ = fresh()
h.declare(G1, G1, "group", "sleep", "我去睡了", None, now=NIGHT)
check(h.would_block(G1, AMU, True, NIGHT + 5) is None, "回退检查：它刚说完要睡、还在路上的那条回复是回 @ 它的人的 → 照常发")
check(h.would_block(G1, AMU, False, NIGHT + 5) is not None, "还在路上的那条是接没叫它的话 → 不发")
try:
    wb = h.would_block(G1, AMU, True, NIGHT + 5, ai=True)
except TypeError:  # 0.1.0 的 would_block 没有 ai 这个参数
    wb = None
check(wb is not None, "还在路上的那条是回别人家的 AI 的 → 不发")
h, _ = fresh(wake_mode="乱填的")
r, _ = h.declare(G1, G1, "group", "sleep", "我去睡了", None, now=NIGHT)
check(gate(h, AMU, NIGHT + 600)["woke"] is r, "回退检查：这一项填了不认识的值 → 按默认（有人找就醒）")
h, _ = fresh()
h.declare(G1, G1, "group", "sleep", "我去睡了", None, now=NIGHT)
h.configure({"wake_mode": "hard"})
o = gate(h, AMU, NIGHT + 600)
check(o["block"] and not o["woke"], "已经在睡的时候改成硬睡档：马上按硬睡算")
h.configure({"wake_mode": "soft"})
check(gate(h, AMU, NIGHT + 700)["woke"], "回退检查：再改回默认档 → 下一个找它的人就叫醒")

print("\n[12 硬睡档（可选）：照以前那样挡，但第一次挡住找它的人要说一声]")
h, _ = fresh(wake_mode="hard")
r, _ = h.declare(G1, G1, "group", "sleep", "困了我去睡了", None, now=NIGHT)
o = gate(h, AMU, NIGHT + 300)
check(o["block"] and not o["woke"] and o.get("tell") is True and o["rec"] is r, "回退检查：硬睡档第一次挡住找它的人 → 要给他一句提示（老的无声无息）", o)
o = gate(h, AMU, NIGHT + 400)
check(o["block"] and not o.get("tell"), "同一个人再找：还是不回，但不再提示")
o = gate(h, XC, NIGHT + 410)
check(o["block"] and o.get("tell") is True, "回退检查：另一个人第一次被挡 → 也提示他一次", o)
check(not gate(h, LW, NIGHT + 420, directed=False).get("tell"), "没叫它的话被挡：不提示")
check(not gate(h, AZ, NIGHT + 430, ai=True).get("tell"), "别人家的 AI 被挡：不提示")
h, _ = fresh(wake_mode="hard")
h.declare(G1, G1, "group", "sleep", "我去睡了", None, now=NIGHT)
check(not gate(h, AMU, NIGHT + 20, text="晚安").get("tell"), "刚说完时回的「晚安」：不提示")
o = gate(h, AMU, NIGHT + 40, text="等下 我还有事")
check(o["block"] and o.get("tell") is True, "回退检查：刚说完的两分钟里真有事找它、被挡 → 提示", o)
h, _ = fresh(wake_mode="hard")
r, _ = h.declare(G1, G1, "group", "sleep", "我去睡了", None, now=NIGHT)
gate(h, AMU, NIGHT + 300)
check(h.release(conv=G1, by="管理员", now=NIGHT + 600) == 1, "（准备）管理员把它叫醒")
r2, _ = h.declare(G1, G1, "group", "sleep", "我又去睡了", None, now=NIGHT + 1200)
o = gate(h, AMU, NIGHT + 1500)
check(o["block"] and not o.get("tell"), "同一晚它醒了又睡：告诉过的人不再提示（一晚一次）", o)
h.tick(r2["until"] + 60)
r3, _ = h.declare(G1, G1, "group", "sleep", "我去睡了", None, now=NIGHT + 86400)
o = gate(h, AMU, NIGHT + 86400 + 300)
check(o["block"] and o.get("tell") is True, "回退检查：第二天晚上它又睡了 → 再提示一次", o)
h2 = Holds(h.d, BJ, {"wake_mode": "hard"}, rng=random.Random(7))
check(not gate(h2, AMU, NIGHT + 86400 + 400).get("tell"), "重启以后还记得告诉过谁")
h, _ = fresh(wake_mode="hard")
r, _ = h.declare(G1, G1, "group", "sleep", "我去睡了", None, now=DAY)
gate(h, BOSS, DAY + 300, admin=True)
o = gate(h, BOSS, DAY + 320, admin=True)
check(o["woke"] is r and not o["block"] and not o.get("tell"), "硬睡档：管理员 @ 两次照旧叫得醒（叫醒的那条不提示）")
h, _ = fresh(wake_mode="hard")
h.declare(G1, G1, "group", "sleep", "我去睡了", None, now=NIGHT)
check(h.would_block(G1, AMU, True, NIGHT + 5) is not None, "硬睡档：还在路上的回复照旧不发（@ 它的也不发）")
old = {"holds": [{"id": "h1", "kind": "sleep", "conv": G1, "umo": G1, "scene": "group", "say": "我去睡了", "t0": NIGHT,
                  "until": NIGHT + 8 * 3600, "plan": "", "who": "", "who_name": "", "calls": [], "n": 0}], "hist": [], "backs": [], "seq": 1}
h = Holds(old, BJ, {"wake_mode": "hard"}, rng=random.Random(7))
o = gate(h, AMU, NIGHT + 300)
check(o["block"] and o.get("tell") is True, "回退检查：老版本留下的存档（没有「告诉过谁」这一栏）：不出错，照样提示", o)
h = Holds(old, BJ, None, rng=random.Random(7))
check(gate(h, XC, NIGHT + 400)["woke"], "回退检查：老版本留下的、正在睡的那条：升级后按新默认，有人找就醒")

ok = sum(1 for c_, _ in RES if c_)
bad = [m for c_, m in RES if not c_]
print("\n" + "=" * 50 + f"\n  结果：{ok} 项过了" + (f"，{len(bad)} 项没过" if bad else "，全过"))
for m in bad:
    print("    -", m)
sys.exit(1 if bad else 0)
