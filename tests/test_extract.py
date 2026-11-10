#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抽取单测（不用装 AstrBot）：python tests/test_extract.py [插件目录 默认上一层]
测 core/extract.py：规则先筛（筛中才花钱）、模型回的 JSON 怎么读、逐项核对 ——
抄的原话得真在机器人那句里、时间得是原话说了的（模型编的不算）、缺字段 / 乱写时间 / 编号不是他的 → 不进表。"""

import json
import sys
from datetime import datetime
from pathlib import Path

d = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(d))
from core import clock as ck  # noqa: E402
from core import extract as ex  # noqa: E402

RES = []
BJ = ck.BEIJING


def check(c, m, why=""):
    RES.append((bool(c), m))
    print(("  [过]   " if c else "  [没过] ") + m + ("" if c or not why else f"\n           {str(why)[:600]}"))


NOW = datetime(2026, 11, 8, 21, 30, tzinfo=BJ).timestamp()


def show(ts):
    return ck.fmt(ts, BJ, "%Y-%m-%d %H:%M") if ts else None


def v(items, bot, user="", mine=()):
    return ex.validate(items, bot, user, NOW, BJ, mine)


print("[1 规则先筛：筛中才调模型]")
hits = [
    ("好 明天早上 8 点提醒你", "明天早上8点提醒我交作业"),
    ("行，10 分钟后叫你", ""),
    ("等会帮你查一下", "明天会下雨吗"),
    ("回头告诉你", "那首歌叫啥"),
    ("我去睡了 晚安", "晚安"),
    ("我先潜水了", ""),
    ("不说了不说了", ""),
    ("哼 不理你了", ""),
    ("好吧 我不发表情包了", ""),
    ("我少说两句", ""),
    ("先去吃饭了", ""),
    ("记下了", "每天晚上11点叫我睡觉"),
    ("好 8点", "8点叫我起床"),
]
for bot, user in hits:
    hit, why = ex.prefilter(bot, user)
    check(hit, f"筛中：「{bot}」（{why}）")
misses = [
    ("哈哈哈哈 你太逗了", "我今天摔了一跤"),
    ("明天见呀", "我先走啦"),
    ("今天天气不错", "今天热吗"),
    ("8点的电影好看吗", "我8点去看电影"),
    ("晚安~", "晚安"),
    ("我觉得可以", "这个方案行吗"),
    ("", "提醒我"),
]
for bot, user in misses:
    check(not ex.prefilter(bot, user)[0], f"不筛：「{bot}」（他：「{user}」）")
chatter = [
    ("我告诉你一个秘密", "什么秘密"),
    ("记住了，下次注意", "你又说错了"),
    ("到时候再说吧", "周末出去玩吗"),
    ("我帮你看看这段代码", "这段代码报错了"),
    ("给你看个好东西", ""),
    ("你快去睡吧 都这么晚了", "我还不困"),
    ("你睡了吗", ""),
    ("你先睡吧 我还要再玩会", ""),
    ("你去忙吧", "我先去开会"),
    ("你少说两句", ""),
    ("别不理我嘛", ""),
    ("我记得你说过这个", ""),
    ("我们下次再聊", ""),
    ("你吃饭了吗", ""),
    ("他刚才溜了", ""),
    ("好的好的", "我觉得这个不错"),
]
for bot, user in chatter:
    check(not ex.prefilter(bot, user)[0], f"回退检查：日常闲聊不调模型：「{bot}」", ex.prefilter(bot, user))
for bot, user in (("我去睡觉了", ""), ("我也去洗澡了", ""), ("我先走了 拜拜", ""), ("到时候告诉你", "结果出来了吗"), ("明天我帮你问问", "")):
    check(ex.prefilter(bot, user)[0], f"该筛的照样筛：「{bot}」")
check(ex.prefilter("好的", "不用提醒我了", has_mine=True)[0], "他有挂着的事、说「不用提醒了」→ 筛（要认取消）")
check(not ex.prefilter("好的 那就不提醒了", "不用提醒我了", has_mine=False)[0], "回退检查：机器人说「那就不提醒了」、他又没挂着事 → 不筛（「不提醒」不是答应）")
check(ex.prefilter("不提醒你了 明天 8 点直接叫你", "", has_mine=False)[0], "「不提醒你了」后面又答应了「叫你」→ 照样筛")
check(not ex.prefilter("好的", "不用提醒我了", has_mine=False)[0], "他没挂着的事：「不用了」不筛（没东西可取消）")
check(ex.prefilter("好 改到九点", "改到九点吧", has_mine=True)[0], "改时间 → 筛")
check(not ex.prefilter("我去睡了", "", holds=False)[0], "约束关着：「我去睡了」不筛（省一次调用）")
check(not ex.prefilter("好 明天 8 点提醒你", "", tasks=False)[0] and ex.prefilter("我去睡了", "", tasks=False)[0], "到点的事关着：只筛约束")

print("\n[2 模型回的 JSON 怎么读]")
check(ex.parse('{"items": [{"type": "task"}]}') == [{"type": "task"}], "标准的")
check(ex.parse('<think>想一想 {"a":1}</think>\n```json\n{"items": []}\n```') == [], "带思考、带代码块")
check(ex.parse('[{"type": "promise"}]') == [{"type": "promise"}], "直接给了列表")
check(ex.parse("好的，这句没有承诺") is None and ex.parse('{"items": 3}') is None and ex.parse("{坏了") is None, "看不懂 → None（这句不记）")

print("\n[3 到点的事：核对]")
bot, user = "好 明天早上 8 点提醒你交作业", "明天早上8点提醒我交作业"
ok_item = {"type": "task", "what": "提醒他交作业", "when": "明天早上8点", "repeat": "", "via": "", "quote": "明天早上 8 点提醒你交作业"}
acts, rej = v([ok_item], bot, user)
check(len(acts) == 1 and acts[0]["op"] == "task" and show(acts[0]["due"]) == "2026-11-09 08:00" and not rej, "对的：明天 08:00 提醒他交作业", (acts, rej))
check(acts[0]["repeat"] is None and acts[0]["via"] == "", "不重复、没说私聊")
a2, r2 = v([dict(ok_item, quote="我会准时叫你起床的")], bot, user)
check(not a2 and r2 and "找不到" in r2[0][1], "回退检查：它抄的那句机器人根本没说 → 不进表", r2)
a3, _ = v([dict(ok_item, quote="明天早上8点提醒你交作业啦")], bot, user)
check(len(a3) == 1, "抄得不太准（多了个字、少了空格）也认")
a4, r4 = v([dict(ok_item, what="")], bot, user)
check(not a4 and r4, "缺 what → 不进表")
a5, r5 = v([dict(ok_item, when="明天早上8点", quote="到时候提醒你")], "好 到时候提醒你", "到时候提醒我")
check(a5 and a5[0]["op"] == "promise", "回退检查：原话里没说时间、模型写了个时间 → 不当成到点的事（当成没说时间的答应）", (a5, r5))
a6, r6 = v([dict(ok_item, when="下下下个月某天", quote="几分钟后提醒你")], "好 几分钟后提醒你交作业", "过会儿提醒我")
check(not a6 and r6 and r6[0][2] is True and "时间没看懂" in r6[0][1], "原话有时间但模型写的看不懂、原话也算不出 → 不进表，下一轮告诉它没记上", r6)
a7, _ = v([dict(ok_item, when="")], bot, user)
check(a7 and show(a7[0]["due"]) == "2026-11-09 08:00", "模型没写 when：从原话里算")
a8, r8 = v([dict(ok_item, when="今天早上8点")], "好 今天早上8点提醒你", "今天早上8点提醒我")
check(not a8 and r8, "时间已经过了 → 不进表")
a9, _ = v([dict(ok_item, repeat="每天")], bot, user)
check(a9 and a9[0]["repeat"] is None, "回退检查：原话里没说「每天」、模型写了每天 → 只做一次（不然天天发）")
a10, _ = v([dict(ok_item, when="每天晚上11点", repeat="每天", what="催他睡觉", quote="每天晚上11点催你睡觉")],
           "好 以后每天晚上11点催你睡觉", "以后每天晚上11点催我睡觉")
check(a10 and a10[0]["repeat"] == "daily" and show(a10[0]["due"]) == "2026-11-08 23:00", "原话说了每天 → 每天的", a10)
a11, _ = v([dict(ok_item, via="私聊")], bot, user)
check(a11 and a11[0]["via"] == "", "没人说私聊、模型写了私聊 → 照常在群里")
a12, _ = v([dict(ok_item, via="私聊")], "好 明天早上 8 点私聊提醒你交作业", "明天早上8点私聊提醒我交作业")
check(a12 and a12[0]["via"] == "private", "他说了私聊 → 私聊发")
a13, _ = v([dict(ok_item, when="10分钟后", quote="10 分钟后叫你")], "行 10 分钟后叫你", "10分钟后叫我")
check(a13 and abs(a13[0]["due"] - NOW - 600) < 1, "10 分钟后")
a14, _ = v([dict(ok_item, when="每月15号", repeat="每月", quote="每月15号提醒你")], "好 每月15号提醒你交房租", "每月15号提醒我交房租")
check(a14 and a14[0]["repeat"] == "monthly" and a14[0]["dom"] == 15, "每月 15 号：记着几号")
a15, _ = v([dict(ok_item, type="提醒")], bot, user)
check(len(a15) == 1, "type 写成中文「提醒」也认")

print("\n[4 没说时间的答应]")
a, r = v([{"type": "promise", "what": "帮他查明天的天气", "quote": "等会帮你查"}], "等会帮你查一下", "明天会下雨吗")
check(a and a[0]["op"] == "promise" and a[0]["what"] == "帮他查明天的天气", "等会帮你查 → 没说时间的答应")
a, r = v([{"type": "promise", "what": "", "quote": "等会帮你查"}], "等会帮你查一下", "")
check(not a and r, "缺 what → 不记")

print("\n[5 取消 / 改：只认他自己挂着的编号]")
a, r = v([{"type": "cancel", "id": 3, "quote": "好"}], "好 那就不提醒了", "不用提醒了", mine=[3, 5])
check(a == [{"op": "cancel", "n": 3, "quote": "好"}], "取消 #3（他挂着的）")
a, r = v([{"type": "cancel", "id": 9, "quote": "好"}], "好 那就不提醒了", "不用提醒了", mine=[3])
check(not a and r and "不是他挂着的" in r[0][1], "回退检查：#9 不是他的 → 不取消")
a, r = v([{"type": "cancel", "id": "#3"}], "好", "不用了", mine=[3])
check(a and a[0]["n"] == 3, "编号写成「#3」也认")
a, r = v([{"type": "edit", "id": 3, "when": "九点", "quote": "改到九点"}], "好 改到九点", "改到九点吧", mine=[3])
check(a and a[0]["op"] == "edit" and show(a[0]["due"]) == "2026-11-09 09:00", "改到九点（晚上 9 点半说的九点 → 明早 9 点）", a)
a, r = v([{"type": "edit", "id": 3, "when": "", "shift_min": 10, "quote": "推迟10分钟"}], "好 推迟10分钟", "推迟10分钟", mine=[3])
check(a and a[0]["shift"] == 10 and a[0]["due"] is None, "推迟 10 分钟（在原来的时间上加，由表去算）")
a, r = v([{"type": "edit", "id": 3, "when": "", "shift_min": 60, "quote": "好"}], "好 晚点", "晚点再叫我", mine=[3])
check(not a and r, "推迟多久原话里没说、也没别的改动 → 不改")
a, r = v([{"type": "edit", "id": 3, "when": "明天", "quote": "好"}], "好的", "那就推一推吧", mine=[3])
check(not a and r and "原话里没说" in r[0][1], "新时间原话里没说 → 不改")

print("\n[6 约束]")
a, r = v([{"type": "hold", "kind": "sleep", "minutes": None, "quote": "我去睡了"}], "我去睡了 晚安", "晚安")
check(a == [{"op": "hold", "kind": "sleep", "minutes": None, "quote": "我去睡了"}], "我去睡了 → 睡觉（没说多久）")
a, r = v([{"type": "hold", "kind": "lurk", "minutes": 30, "quote": "潜水半小时"}], "我先潜水半小时", "")
check(a and a[0]["minutes"] == 30, "说了半小时 → 30 分钟")
a, r = v([{"type": "hold", "kind": "lurk", "minutes": 120, "quote": "我先潜了"}], "我先潜了", "")
check(a and a[0]["minutes"] is None, "它没说多久、模型自己写了 120 → 按默认")
a, r = v([{"type": "hold", "kind": "sleep", "minutes": None, "quote": "我才不睡"}], "我才不睡 还早呢", "")
check(not a and r, "回退检查：「我才不睡」不算去睡")
a, r = v([{"type": "hold", "kind": "nosticker", "minutes": None, "quote": "这次不发表情包了"}], "这次不发表情包了", "")
check(not a and r, "只说这一次 → 不算一阵子不发")
a, r = v([{"type": "hold", "kind": "nosticker", "minutes": None, "quote": "不发了"}], "好好好 不发了", "别发了")
check(not a and r, "没提表情包 → 不算")
a, r = v([{"type": "hold", "kind": "nosticker", "minutes": None, "quote": "不发表情包了"}], "好吧 不发表情包了", "")
check(a and a[0]["kind"] == "nosticker", "不发表情包了 → 记")
a, r = v([{"type": "hold", "kind": "睡觉", "minutes": None, "quote": "我去睡了"}], "我去睡了", "")
check(a and a[0]["kind"] == "sleep", "kind 写成中文也认")
a, r = v([{"type": "hold", "kind": "fly", "minutes": None, "quote": "我去睡了"}], "我去睡了", "")
check(not a and r, "不认识的种类 → 不记")
a, r = v([{"type": "hold", "kind": "sleep", "minutes": None, "quote": "我去睡了"}], "你快去睡吧", "我困了")
check(not a and r, "机器人根本没说自己去睡（是叫对方去睡）→ 抄的原话对不上，不记")

print("\n[7 乱七八糟的回答]")
a, r = v(["睡觉", 3, None, {"type": "explode"}], "我去睡了", "")
check(not a and len(r) == 4, "不是 dict / 不认识的种类：一律不进表", r)
items = [dict(ok_item, quote="明天早上 8 点提醒你交作业")] * 10
a, r = v(items, bot, user)
check(len(a) + len(r) == 6, "一句话最多看 6 项（模型乱写一大串也不会刷爆表）")
check(ex.validate(None, "x", "y", NOW, BJ) == ([], []), "items 是 None：什么都不做")

print("\n[8 给模型的提示]")
p = ex.build_prompt("11-08（周日）21:30（北京时间）", "group", "阿木", "明天8点提醒我", "好 明天8点提醒你", ["#3 明天 08:00 提醒他交作业"])
check("阿木" in p and "明天8点提醒我" in p and "好 明天8点提醒你" in p and "#3 明天 08:00" in p and "群聊" in p, "提示里有：现在几点、谁、他说的、机器人回的、他挂着的编号")
check("没有" in ex.build_prompt("x", "private", "阿木", "a", "b", []) and "私聊" in ex.build_prompt("x", "private", "a", "a", "b", []), "没挂着的写「没有」；私聊写私聊")
check('{"items"' in ex.SYSTEM and "不许自己推算或编" in ex.SYSTEM, "系统提示要求只输出 JSON、时间不许编")
json.dumps(ex.SYSTEM)

# ───────── v0.1.1（11-10）：时间算不出来的不许悄悄记成别的日子 ─────────
print("\n[9 时间说法从头走一遍（现在 11-08 周日 21:30）]")


def flow(user_, bot_, when_):
    it = {"type": "task", "what": "提醒他", "when": when_, "repeat": "", "via": "", "quote": bot_}
    return v([it], bot_, user_)


a, r = flow("下个月第二个周五提醒我交房租", "好，下个月第二个周五提醒你交房租", "下个月第二个周五")
check(not a and r and r[0][2] is True and "时间没看懂" in r[0][1],
      "回退检查：「下个月第二个周五」算不出来 → 不进表、下一轮告诉模型没记上（老的悄悄记成这周五）", (a, r))
a, r = flow("下个月5号提醒我还信用卡", "行，下个月5号提醒你", "下个月5号")
check(a and a[0]["op"] == "task" and show(a[0]["due"]) == "2026-12-05 09:00", "「下个月 5 号」→ 12-05", (a, r))
a, r = flow("下个月20号提醒我还信用卡", "行，下个月20号提醒你", "下个月20号")
check(a and a[0]["op"] == "task" and show(a[0]["due"]) == "2026-12-20 09:00", "回退检查：「下个月 20 号」→ 12-20（老的记成这个月 20 号）", (a, r))
a, r = flow("周五8点叫我", "好 周五8点叫你", "周五8点")
check(a and show(a[0]["due"]) == "2026-11-13 08:00", "回退检查：「周五 8 点」→ 周五 08:00（老的读成 58 点、没记上）", (a, r))
a, r = flow("三天后早上8点叫我", "好的，三天后早上8点叫你", "三天后早上8点")
check(a and show(a[0]["due"]) == "2026-11-11 08:00", "回退检查：「三天后早上 8 点」→ 11-11 08:00（老的记成 21:30）", (a, r))
a, r = flow("周末早上9点叫我起床", "好 周末早上9点叫你", "周末早上9点")
check(a and show(a[0]["due"]) == "2026-11-14 09:00", "回退检查：周日晚上说「周末早上 9 点」→ 下一个周六（老的记成明天）", (a, r))
a, r = flow("月底晚上8点提醒我交房租", "好 月底晚上8点提醒你交房租", "月底晚上8点")
check(a and show(a[0]["due"]) == "2026-11-30 20:00", "回退检查：「月底晚上 8 点」→ 11-30 20:00（老的记成明晚）", (a, r))
a, r = v([{"type": "task", "what": "提醒他交房租", "when": "每个月底晚上8点", "repeat": "每月", "via": "", "quote": "每个月底晚上8点提醒你交房租"}],
         "好 每个月底晚上8点提醒你交房租", "每个月底晚上8点提醒我交房租")
check(a and show(a[0]["due"]) == "2026-11-30 20:00" and a[0]["repeat"] == "monthly" and a[0]["dom"] == 31,
      "回退检查：「每个月底晚上 8 点」→ 11-30 20:00、每月、记着是月底（老的记成今晚、之后每月 8 号）", (a, r))
a, r = flow("明年12月25号提醒我", "好，明年12月25号提醒你", "明年12月25号")
check(not a and r and r[0][2] is True and "太远" in r[0][1], "回退检查：「明年 12 月 25 号」→ 太远了不进表、告诉模型（老的记成今年的）", (a, r))
a, r = flow("下周8点提醒我开会", "好 下周8点提醒你开会", "下周8点")
check(not a and r and r[0][2] is True, "回退检查：「下周 8 点」没说周几 → 不进表、告诉模型（老的记成明早 8 点）", (a, r))
a, r = flow("国庆节早上8点叫我", "好 国庆节早上8点叫你", "国庆节早上8点")
check(not a and r and r[0][2] is True, "回退检查：节日算不出来 → 不进表、告诉模型", (a, r))
a, r = flow("下个月第二个周五提醒我交房租", "好，下个月第二个周五提醒你交房租", "")
check(not a and r and r[0][2] is True, "回退检查：模型没写 when、从原话里算也算不出 → 不进表（不拿原话里的「周五」凑一个）", (a, r))
a, r = v([{"type": "edit", "id": 3, "when": "下个月第二个周五", "shift_min": 0, "what": "", "quote": "改到下个月第二个周五"}],
         "好 改到下个月第二个周五", "改到下个月第二个周五吧", mine=[3])
check(not a and r and r[0][2] is True, "回退检查：改时间改成算不出来的 → 不改、告诉模型（老的悄悄改成这周五）", (a, r))
a, r = v([{"type": "edit", "id": 3, "when": "下个月5号", "shift_min": 0, "what": "", "quote": "改到下个月5号"}],
         "好 改到下个月5号", "改到下个月5号吧", mine=[3])
check(a and show(a[0]["due"]) == "2026-12-05 09:00", "改到「下个月 5 号」→ 12-05", (a, r))

ok = sum(1 for c_, _ in RES if c_)
bad = [m for c_, m in RES if not c_]
print("\n" + "=" * 50 + f"\n  结果：{ok} 项过了" + (f"，{len(bad)} 项没过" if bad else "，全过"))
for m in bad:
    print("    -", m)
sys.exit(1 if bad else 0)
