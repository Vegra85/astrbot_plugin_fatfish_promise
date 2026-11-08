#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""指令单测（不用装 AstrBot）：python tests/test_cmd.py [插件目录 默认上一层]
测 core/cmd.py：/说到做到 看自己的、取消（只有本人或管理员）、管理员看全部、叫醒；
隐私：群里只列这个群的、不带 QQ 号；别人私聊里的事只在私聊里给管理员看；群里取消别处答应的不带内容。"""

import re
import sys
from datetime import datetime
from pathlib import Path

d = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(d))
from core import clock as ck  # noqa: E402
from core import cmd as cm  # noqa: E402
from core.hold import Holds  # noqa: E402
from core.table import Table  # noqa: E402

RES = []
BJ = ck.BEIJING
G1 = "aiocqhttp:GroupMessage:7001"
G2 = "aiocqhttp:GroupMessage:7002"
AMU, XC, BOSS = "10001", "20002", "90009"  # 阿木、小橙、管理员（编的）
P_AMU = f"aiocqhttp:FriendMessage:{AMU}"
P_XC = f"aiocqhttp:FriendMessage:{XC}"
P_BOSS = f"aiocqhttp:FriendMessage:{BOSS}"
NOW = datetime(2026, 11, 8, 15, 0, tzinfo=BJ).timestamp()
QQ = re.compile(r"(?<!\d)\d{5}(?!\d)")


def check(c, m, why=""):
    RES.append((bool(c), m))
    print(("  [过]   " if c else "  [没过] ") + m + ("" if c or not why else f"\n           {str(why)[:700]}"))


def fresh():
    tb = Table({}, BJ)
    hd = Holds({}, BJ)
    a, _ = tb.add_task(G1, G1, "group", AMU, "阿木", "提醒他交作业", NOW + 3600, now=NOW)
    b, _ = tb.add_task(P_XC, P_XC, "private", XC, "小橙", "提醒他吃药", NOW + 7200, now=NOW)
    c, _ = tb.add_task(G2, G2, "group", XC, "小橙", "提醒他收快递", NOW + 5400, now=NOW)
    e, _ = tb.add_task(P_AMU, P_AMU, "private", AMU, "阿木", "提醒他看医生", NOW + 9000, now=NOW)
    return tb, hd, a, b, c, e


def run(tb, hd, conv, uid, op="", arg="", admin=False, name=""):
    return cm.run(op, arg, table=tb, holds=hd, conv=conv, uid=uid, name=name or uid, admin=admin, now=NOW, tz=BJ, label="北京时间")


print("[1 管理员看全部：群里只列本群的，跨对话的只在私聊里]")
tb, hd, a, b, c, e = fresh()
txt, _ = run(tb, hd, G1, BOSS, "全部", admin=True)
check("提醒他交作业" in txt and "阿木" in txt, "群里：列出这个群的（谁、做什么）", txt)
check("吃药" not in txt and "看医生" not in txt and "收快递" not in txt, "回退检查：别人私聊里的、别的群的内容不贴进群", txt)
check(not QQ.search(txt) and "FriendMessage" not in txt, "群里的回话不带 QQ 号", txt)
check("请私聊我发 /说到做到 全部" in txt, "告诉管理员跨对话的要私聊看")
txt, _ = run(tb, hd, P_BOSS, BOSS, "全部", admin=True)
check(all(x in txt for x in ("交作业", "吃药", "收快递", "看医生")) and XC in txt and "私聊 20002" in txt, "私聊里：管理员看得到全部（带 QQ 号、在哪）", txt)
check(run(tb, hd, G1, XC, "全部")[0] == "只有管理员能看全部。" and run(tb, hd, P_XC, XC, "全部")[0] == "只有管理员能看全部。", "不是管理员：群里私聊里都看不了全部")

print("\n[2 看自己的]")
txt, _ = run(tb, hd, G1, AMU)
check("提醒他交作业" in txt and "看医生" not in txt, "回退检查：群里只列这个群答应他的（他私聊里的不贴进群）", txt)
check("别处" not in txt, "群里连「别处还有几件」都不说")
txt, _ = run(tb, hd, P_AMU, AMU)
check("交作业" in txt and "看医生" in txt, "私聊里：他自己在群里和私聊里的都列出来", txt)
txt, _ = run(tb, hd, G2, AMU)
check("机器人在这儿没有答应你" in txt and "交作业" not in txt, "A 群答应的不在 B 群列出来", txt)

print("\n[3 取消]")
txt, ev = run(tb, hd, G1, AMU, "取消", str(e["n"]))
check(e["status"] == "cancelled" and "看医生" not in txt and "别处答应的" in txt and ev, "回退检查：群里取消自己私聊里那件 → 取消了，回话不带内容", txt)
txt, _ = run(tb, hd, G1, AMU, "取消", str(c["n"]))
check(c["status"] == "pending" and "不是你的" in txt and "收快递" not in txt, "别人的取消不了（回话也不带内容）", txt)
txt, _ = run(tb, hd, G1, AMU, "取消", f"#{a['n']}")
check(a["status"] == "cancelled" and "提醒他交作业" in txt, "本群的：取消了、说是哪件")
txt, _ = run(tb, hd, G2, BOSS, "取消", str(c["n"]), admin=True)
check(c["status"] == "cancelled", "管理员能取消别人的")
check("没找到" in run(tb, hd, G1, AMU, "取消", "999")[0] and "没找到" in run(tb, hd, G1, AMU, "取消", "")[0], "编号不对 / 没写 → 没找到")

print("\n[4 叫醒 / 用法]")
hd.declare(G1, G1, "group", "sleep", "我去睡了", None, now=NOW)
hd.declare(G2, G2, "group", "lurk", "我潜了", None, now=NOW)
check(run(tb, hd, G1, AMU, "叫醒")[0] == "只有管理员能叫醒。" and hd.gone(G1, NOW), "不是管理员叫不醒")
txt, ev = run(tb, hd, G1, BOSS, "叫醒", admin=True)
check("1 条约束结束了" in txt and hd.gone(G1, NOW) is None and hd.gone(G2, NOW), "管理员叫醒：只结束这个群的", txt)
check("用法" in run(tb, hd, G1, AMU, "乱写")[0], "不认识的写法 → 用法")

ok = sum(1 for c_, _ in RES if c_)
bad = [m for c_, m in RES if not c_]
print("\n" + "=" * 50 + f"\n  结果：{ok} 项过了" + (f"，{len(bad)} 项没过" if bad else "，全过"))
for m in bad:
    print("    -", m)
sys.exit(1 if bad else 0)
