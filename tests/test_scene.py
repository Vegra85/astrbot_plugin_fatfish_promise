#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给模型看的文字单测（不用装 AstrBot）：python tests/test_scene.py [插件目录 默认上一层]
测 core/scene.py：每轮的临时状态（答应过他的 / 别处的 / 刚做的 / 欠的道歉 / 没说时间的 / 没记上的 / 满了 / 约束 / 刚回来 / 能做到什么）、
到点那句给模型的状态（谁、哪天答应的、原话、现在几点、晚了多久、在睡觉）、系统提示那句、模型写的那句怎么清理。
E1：只写事实 / 状态 / 规矩 —— 不写示范句、不写「你可以说」、不定语气。"""

import re
import sys
from datetime import datetime
from pathlib import Path

d = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(d))
from core import clock as ck  # noqa: E402
from core import scene as sc  # noqa: E402
from core.hold import Holds  # noqa: E402
from core.table import Table  # noqa: E402

RES = []
BJ = ck.BEIJING
G1 = "aiocqhttp:GroupMessage:7001"
G2 = "aiocqhttp:GroupMessage:7002"
AMU = "10001"
# 「替它写台词 / 定语气」的说法：给模型的字里一个都不能有
SCRIPT = re.compile(
    r"你可以说|可以这样说|比如说|例如：|示范|语气要|俏皮|可爱一点|撒娇|像这样|参考回复|回复模板|"
    r"不用再|别再|不要再|你应该|应该去|一定要|记得要|你要先|先跟他"
)


def check(c, m, why=""):
    RES.append((bool(c), m))
    print(("  [过]   " if c else "  [没过] ") + m + ("" if c or not why else f"\n           {str(why)[:800]}"))


def at(y, mo, d_, h, mi):
    return datetime(y, mo, d_, h, mi, tzinfo=BJ).timestamp()


NOW = at(2026, 11, 8, 21, 30)
H = 3600

print("[1 每轮的临时状态]")
tb = Table({}, BJ)
a, _ = tb.add_task(G1, G1, "group", AMU, "阿木", "提醒他交作业", NOW + 10.5 * H, now=NOW, say="好 明天早上8点提醒你", ask="明天8点提醒我交作业")
b, _ = tb.add_task(G2, G2, "group", AMU, "阿木", "二群里的私事", NOW + 3 * H, now=NOW)
c, _ = tb.add_task(G1, G1, "group", AMU, "阿木", "提醒他关火", NOW + 60, now=NOW)
tb.failed(c, "QQ 没连上", NOW + 2 * H, final=True)
p, _ = tb.add_promise(G1, G1, "group", AMU, "阿木", "帮他查明天的天气", "等会帮你查", "明天下雨吗", NOW - 2 * H)
note = tb.note(AMU, G1, "你答应他的「每天提醒他早睡」没记上：他已经挂着 5 件到点的事（每人最多 5 件）", NOW)
st = tb.state_for(AMU, G1, NOW)
text, shown = sc.turn_block(st, [], [], NOW, BJ, "北京时间", AMU, "在吗")
check(text.startswith(sc.HEAD) and "现在 11-08（周日）21:30（北京时间）" in text, "开头写明是插件记的状态、现在几点")
check(f"#{a['n']}：明天 08:00（北京时间）提醒他交作业" in text and "在这里 @ 他" in text, "答应他的、还没做的：编号、时间、怎么发", text)
check("别的地方还答应过他 1 件" in text and "二群里的私事" not in text, "别处的只说几件，不带内容（隐私）")
check("没做成（QQ 没连上）：还欠他一个道歉" in text and shown["apo"] == [c["n"]], "欠着的道歉（原因照实写）")
check("帮他查明天的天气" in text and "没说时间" in text and shown["prom"] == [p["n"]], "没说时间的答应")
check("没记上：他已经挂着 5 件" in text and shown["notes"] == [note["id"]], "没记上的")
check(sc.CAN in text, "有状态时带上「能做到什么」")
check(not SCRIPT.search(text), "E1：一句台词 / 语气都没有", SCRIPT.findall(text))

tb2 = Table({}, BJ)
dn, _ = tb2.add_task(G1, G1, "group", AMU, "阿木", "提醒他交作业", NOW + 600, now=NOW)
tb2.done(dn, "交作业啦", NOW + 600)
td, _ = sc.turn_block(tb2.state_for(AMU, G1, NOW + 1200), [], [], NOW + 1200, BJ, "北京时间", AMU, "")
check(f"#{dn['n']}「提醒他交作业」：21:40 已经按约定在这里 @ 他发过了" in td, "刚做过的：只写「几点已经按约定发过了」这件事实", td)
check("不用再" not in td and not SCRIPT.search(td), "回退检查（E1）：不写「这件不用再做一遍」这种替它拿主意的话", td)

print("\n[2 什么时候带「能做到什么」]")
empty = Table({}, BJ).state_for(AMU, G1, NOW)
check(sc.turn_block(empty, [], [], NOW, BJ, "北京时间", AMU, "今天好热啊") == ("", {}), "没东西、他也没在要它答应什么 → 什么都不加（省 token）")
t2, _ = sc.turn_block(empty, [], [], NOW, BJ, "北京时间", AMU, "明天早上提醒我交作业")
check(sc.CAN in t2 and "打电话、转账、替人私聊别人" in t2, "他在要它答应（提醒我）→ 带上能做到 / 做不到的事实")
t3, _ = sc.turn_block(empty, [], [], NOW, BJ, "北京时间", AMU, "你帮我给他打个电话")
check(sc.CAN in t3, "要它打电话 → 也带上（做不到的写着）")
t4, _ = sc.turn_block(empty, [], [], NOW, BJ, "北京时间", AMU, "明天提醒我", ai_name="隔壁的机器人")
check("「隔壁的机器人」是别人家的 AI" in t4 and "插件不记" in t4, "对方是别人家的 AI：告诉它跟 AI 约的不记")
check(not SCRIPT.search(sc.CAN), "E1：「能做到什么」那行没有台词")

print("\n[3 约束 / 刚回来]")
hd = Holds({}, BJ)
hd.declare(G1, G1, "group", "quiet", "我少说两句", 30, now=NOW - 600)
hd.declare(G1, G1, "group", "nosticker", "不发表情包了", 60, now=NOW - 600)
hd.declare(G1, G1, "group", "ignore", "不理你了", 20, who="20002", who_name="小橙", now=NOW - 300)
t5, _ = sc.turn_block(empty, hd.live(G1, NOW), [], NOW, BJ, "北京时间", AMU, "")
check("说了「我少说两句」（少说）" in t5 and "没 @ 你的话插件不让你回" in t5, "少说：还剩多久、没 @ 的不让回", t5)
check("正晾着「小橙」" in t5 and "说了「不发表情包了」" in t5 and "表情包会被插件拿掉" in t5, "不理谁、不发表情包")
t6, _ = sc.turn_block(empty, hd.live(G1, NOW), [], NOW, BJ, "北京时间", "20002", "")
check("正晾着" not in t6, "被晾着的那个人自己来说话：不给这行（他的消息本来就不回）")
hd2 = Holds({}, BJ)
r, _ = hd2.declare(G1, G1, "group", "sleep", "我去睡了 晚安", 120, now=NOW - 40 * 60)
hd2.gate(G1, "group", "90009", "管理员", True, True, False, "醒醒", NOW - 60)
hd2.gate(G1, "group", "90009", "管理员", True, True, False, "醒醒", NOW - 30)
backs = hd2.backs_for(G1)
t7, sh7 = sc.turn_block(empty, [], backs, NOW, BJ, "北京时间", AMU, "")
check("你刚回来：40 分钟前你在这里说了「我去睡了 晚安」，然后真的去睡了" in t7, "刚回来：多久以前说了什么、真的去睡了", t7)
check("是「管理员」（管理员）叫回来的" in t7 and "有 1 条要回的消息你没回" in t7, "谁叫醒的、这期间没回几条", t7)
check(sh7["backs"] == backs, "记着给它看了哪句（发出去以后作废）")
check(not SCRIPT.search(t5 + t7), "E1：约束和刚回来的那几行也没有台词")
b_time = {"kind": "lurk", "say": "我先潜了", "t0": NOW - 3600, "end": NOW - 600, "how": "time", "n": 0}
check("到点自己回来的" in sc.back_line(b_time, NOW), "到点自己回来的")
b_ign = {"kind": "ignore", "say": "不理你了", "t0": NOW - 900, "end": NOW - 300, "how": "time", "who_name": "小橙"}
check("晾了「小橙」" in sc.back_line(b_ign, NOW) and "现在结束了" in sc.back_line(b_ign, NOW), "「不理」结束了")

print("\n[4 到点那句：给模型的状态]")
t = tb.find(a["n"])
due = float(t["due"])
s1 = sc.speak_prompt(t, due + 30, BJ, "北京时间")
check("现在是 11-09（周一）08:00（北京时间）" in s1, "现在几点", s1)
check("11-08 21:30" in s1 and "10.5 小时前" in s1 and "群里答应了「阿木」：提醒他交作业" in s1, "谁、哪天答应的、答应了什么", s1)
check("他当时说：「明天8点提醒我交作业」" in s1 and "你当时回的：「好 明天早上8点提醒你」" in s1, "原话（他的、它的）")
check("前面自动 @ 他" in s1 and "晚了" not in s1, "群里：插件会 @ 他；没晚")
check("只写要发出去的那句话本身" in s1 and not SCRIPT.search(s1), "E1：只给格式规矩，不给示范句")
s2 = sc.speak_prompt(t, due + 25 * 60, BJ, "北京时间", late=25 * 60, late_why="QQ 没连上")
check("已经晚了 25 分钟（QQ 没连上）" in s2, "晚了多久、为什么", s2)
gone = {"kind": "sleep", "say": "我去睡了", "t0": due - 7 * H}
s3 = sc.speak_prompt(t, due + 30, BJ, "北京时间", gone=gone)
check("你这会儿在睡觉（7 小时前你说了「我去睡了」）" in s3 and "接着替你睡觉" in s3, "它那会儿在睡觉：照样做，做完接着睡", s3)
pv = dict(t, scene="private")
check("私聊发给他" in sc.speak_prompt(pv, due, BJ, "北京时间"), "私聊的：私聊发给他")
rp = dict(t, repeat="daily")
check("（每天都要做）" in sc.speak_prompt(rp, due, BJ, "北京时间"), "每天的写明每天都要做")

print("\n[5 系统提示那句 / 清理模型写的]")
fb = sc.fallback_line(t, BJ)
check(fb.startswith("（系统提示）到点了：提醒他交作业") and "11-08 21:30 答应的" in fb, "模型叫不通时：系统口吻", fb)
check(sc.clean_line("<think>想想</think>「交作业时间到啦」") == "交作业时间到啦", "去掉思考和引号")
check(sc.clean_line("@阿木 交作业啦") == "交作业啦", "去掉它自己写的 @（插件会 @）")
check(sc.clean_line("[[不说]]") == "" and sc.clean_line("   ") == "", "空的 / 不说 → 空")
check(len(sc.clean_line("啊" * 1000)) <= 301, "太长截断")
check(sc.clean_line("第一行\n\n第二行\n第三行\n第四行\n第五行") == "第一行\n第二行\n第三行\n第四行", "最多 4 行")

print("\n[6 scene.py 里所有写给模型的字都过一遍 E1]")
src = (d / "core" / "scene.py").read_text(encoding="utf-8")
strings = re.findall(r'"([^"\n]{6,})"', src)
check(strings and not any(SCRIPT.search(x) for x in strings), "core/scene.py 里没有台词 / 语气的说法", [x for x in strings if SCRIPT.search(x)])

ok = sum(1 for c_, _ in RES if c_)
bad = [m for c_, m in RES if not c_]
print("\n" + "=" * 50 + f"\n  结果：{ok} 项过了" + (f"，{len(bad)} 项没过" if bad else "，全过"))
for m in bad:
    print("    -", m)
sys.exit(1 if bad else 0)
