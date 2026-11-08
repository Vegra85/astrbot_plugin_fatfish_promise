#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""承诺表单测（不用装 AstrBot）：python tests/test_table.py [插件目录 默认上一层]
测 core/table.py：记 / 去重 / 每人上限 / 每天上限 / 管理员不限、到点 / 重试 / 宽限 / 没做成 / 开机补不补、
重复的排下一次、欠着的道歉、没说时间的答应、没记上的、谁看得到（私聊的不进群）、谁能改、同一个地方隔 20 秒。"""

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

d = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(d))
from core import clock as ck  # noqa: E402
from core.store import Store  # noqa: E402
from core.table import Gap, Table, ref_num, same_thing, seen_in  # noqa: E402

RES = []
BJ = ck.BEIJING
G1 = "aiocqhttp:GroupMessage:7001"
G2 = "aiocqhttp:GroupMessage:7002"
AMU, XC, LW = "10001", "20002", "30003"  # 阿木、小橙、老王（编的）
P_AMU = f"aiocqhttp:FriendMessage:{AMU}"


def check(c, m, why=""):
    RES.append((bool(c), m))
    print(("  [过]   " if c else "  [没过] ") + m + ("" if c or not why else f"\n           {str(why)[:600]}"))


def at(y, mo, d_, h, mi):
    return datetime(y, mo, d_, h, mi, tzinfo=BJ).timestamp()


NOW = at(2026, 11, 8, 21, 30)
H = 3600


def fresh(**conf):
    logs = []
    return Table({}, BJ, conf, logs.append), logs


def add(tb, who=AMU, what="提醒他交作业", due=NOW + H, conv=G1, now=NOW, **kw):
    kw.setdefault("by", who)
    return tb.add_task(conv, conv, "group" if "Group" in conv else "private", who, {"10001": "阿木"}.get(who, who), what, due, now=now, **kw)


print("[1 记一件]")
tb, logs = fresh()
t, why = add(tb, say="好 明天早上8点提醒你", ask="明天早上8点提醒我交作业")
check(t and why == "" and t["n"] == 1 and t["status"] == "pending" and t["kind"] == "task", "记上了：编号 1、等着")
check(t["who"] == AMU and t["conv"] == G1 and t["via"] == "at" and t["scene"] == "group", "谁、在哪、群里 @ 他")
check(t["say"] == "好 明天早上8点提醒你" and t["ask"] == "明天早上8点提醒我交作业", "原话出处（它说的、他说的）都记着")
check(any("记下 #1" in x for x in logs), "日志写了一行", logs)
check(add(tb, who="", what="x")[0] is None and add(tb, what="")[0] is None, "不知道给谁 / 做什么 → 不记")
check(add(tb, due=None)[1] == "时间没看懂" and add(tb, due=NOW - 600)[1] == "那个时间已经过了", "没时间 / 时间过了 → 不记，带原因")

print("\n[2 去重：同一个人、同一个对话、10 分钟以内 → 同一件（只更新说法）]")
t2, why2 = add(tb, due=NOW + H + 300, what="提醒他交作业")
check(t2 is t and why2 == "dup" and len(tb.pending()) == 1, "同一件事说第二遍（时间差 5 分钟）→ 还是那一件，表里只有 1 件", len(tb.pending()))
tb, _ = fresh()
up, _ = add(tb, what="提醒他起床", due=NOW + 10 * H, say="好 明早8点提醒你起床")
up2, why = add(tb, what="叫他起床", due=NOW + 10 * H, say="行 叫你起床")
check(up2 is up and why == "dup" and len(tb.pending()) == 1, "回退检查：「提醒他起床」「叫他起床」同一时刻 → 同一件（不会到点 @ 他两次）", [x["what"] for x in tb.pending()])
up3, _ = add(tb, what="叫他起床", due=NOW + 10 * H + 240, say="记着呢 明早8点叫你", ask="别忘了啊")
check(up3 is up and len(tb.pending()) == 1 and up["say"] == "记着呢 明早8点叫你" and up["ask"] == "别忘了啊",
      "回退检查：机器人复述「记着呢 明早8点叫你」→ 不新增，说法更新成最新的", up)
add(tb, what="叫他起床去上第一节数学课", due=NOW + 10 * H)
check(up["what"] == "叫他起床去上第一节数学课" and len(tb.pending()) == 1, "新说法更具体：换上（还是那一件）", up["what"])
add(tb, what="起床", due=NOW + 10 * H)
check(up["what"] == "叫他起床去上第一节数学课", "新说法更笼统：留着原来那个")
t3, _ = add(tb, due=NOW + 10 * H + 1200, what="叫他起床")
check(t3 is not up and len(tb.pending()) == 2, "时间差 20 分钟 → 算两件")
t5, _ = add(tb, who=XC, due=NOW + 10 * H, what="叫他起床")
check(t5 is not up, "同一时刻、别的人 → 各算各的")
t6, _ = add(tb, due=NOW + 10 * H, what="叫他起床", conv=G2)
check(t6 is not up, "同一时刻、别的群 → 各算各的")
t7, _ = add(tb, due=NOW + 10 * H + 60, what="每天叫他起床", repeat="daily")
check(t7 is not up and t7["repeat"] == "daily", "一个是每天的、一个是一次的 → 各算各的（不把每天那串吞掉）")
check(same_thing("提醒他交作业", "提醒他交作业。") and same_thing("提醒他交数学作业", "交数学作业") and not same_thing("喝水", "吃饭"), "同一件事的认法")

print("\n[3 每人上限 / 每天上限 / 管理员不限]")
tb, _ = fresh(max_pending=5, max_daily=10)
for i in range(5):
    add(tb, what=f"第{i}件", due=NOW + H * (i + 1))
t6, why6 = add(tb, what="第6件", due=NOW + 9 * H)
check(t6 is None and "5 件" in why6, "回退检查：同时挂着 5 件 → 第 6 件记不上，原因写明满了", why6)
st = tb.state_for(AMU, G1, NOW)
check(st["full"] == 5, "状态里写着他满了")
t7, _ = add(tb, what="第6件", due=NOW + 9 * H, admin=True)
check(t7 is not None, "管理员不限")
tb2, _ = fresh(max_pending=5, admin_unlimited=False)
for i in range(5):
    add(tb2, what=f"第{i}件", due=NOW + H * (i + 1), admin=True)
check(add(tb2, what="再一件", due=NOW + 9 * H, admin=True)[0] is None, "配置成管理员也限 → 管理员也记不上")
tb3, _ = fresh(max_pending=50, max_daily=3)
for i in range(3):
    x, _ = add(tb3, what=f"件{i}", due=NOW + H * (i + 1))
    tb3.cancel(x, "测试", NOW)  # 取消了也算今天加过的
t8, why8 = add(tb3, what="第4件", due=NOW + 9 * H)
check(t8 is None and "今天" in why8, "每天新加 3 件的上限（取消的也算）→ 第 4 件记不上", why8)
check(add(tb3, what="第4件", due=NOW + 9 * H, now=at(2026, 11, 9, 0, 1))[0] is not None, "过了零点（北京时间）换天 → 又能加")
t9, _ = add(tb3, who=XC, by=AMU, what="替小橙定的", due=NOW + 9 * H, now=at(2026, 11, 9, 0, 2))
check(t9 is not None and t9["by"] == AMU and t9["who"] == XC, "替别人定的：按让它定的人算名额")
tbp, _ = fresh(max_pending=1)
add(tbp, what="一件")
check(tbp.add_task(G1, G1, "group", AMU, "阿木", "面板加的", NOW + 2 * H, now=NOW, src="panel")[0] is not None, "面板加的不限")

print("\n[4 到点 / 重试 / 宽限 / 没做成]")
tb, logs = fresh(grace_min=60)
t, _ = add(tb, due=NOW + 60)
check(tb.due_now(NOW) == [], "没到点：不做")
check(tb.due_now(NOW + 61) == [t], "到点了：该做")
r = tb.failed(t, "QQ 没连上", NOW + 61)
check(r == "retry" and t["tries"] == 1 and t["status"] == "pending", "宽限内没发出去 → 过一会儿再试")
check(tb.due_now(NOW + 90) == [] and tb.due_now(NOW + 125) == [t], "隔 1 分钟才再试")
tb.failed(t, "QQ 拒收了", NOW + 125)
check(tb.due_now(NOW + 125 + 110) == [] and tb.due_now(NOW + 125 + 121) == [t], "第二次没成：隔 2 分钟")
tb.done(t, "到点啦", NOW + 600)
check(t["status"] == "done" and t["hist"][-1]["ok"] and t["hist"][-1]["late"] == 540, "补上了 → 做了，记着晚了多久")
t, _ = add(tb, due=NOW + 60, what="提醒他关火")
r = tb.failed(t, "群里被禁言了", NOW + 60 + 3700)
check(r == "missed" and t["status"] == "missed" and t["apology"] == "owed" and t["apo_why"] == "群里被禁言了", "晚过宽限 → 没做成，欠一个道歉，原因记着")
check(tb.due_now(NOW + 9 * H) == [], "没做成的不再去做")
tb.d["tasks"][-1]["status"] = "pending"
tb.d["tasks"][-1]["apology"] = ""
check(tb.overdue(t, NOW + 60 + 3601) and not tb.overdue(t, NOW + 60 + 3500), "宽限按配置的 60 分钟算")

print("\n[5 开机：过点很久的不补]")
tb, _ = fresh(grace_min=60)
old, _ = add(tb, what="很久以前的", due=NOW + 60)
near, _ = add(tb, what="刚过点的", due=NOW + 60 + 900)
fut, _ = add(tb, what="还没到的", due=NOW + 9 * H)
gone = tb.sweep(NOW + 60 + 900 + 70 * 60)  # 开机时：第一件晚了 85 分钟、第二件晚了 70 分钟 —— 都晚过 1 小时
check([x["what"] for x in gone] == ["很久以前的", "刚过点的"], "开机时晚过 1 小时的：不补，直接记成没做成", [x["what"] for x in gone])
check(old["status"] == "missed" and old["apology"] == "owed" and "没开着" in old["apo_why"] and fut["status"] == "pending", "原因写的是那会儿机器人没开着；还没到的不动")
tb, _ = fresh(grace_min=60)
a1, _ = add(tb, what="晚了40分钟的", due=NOW + 60)
check(tb.sweep(NOW + 60 + 40 * 60) == [] and tb.due_now(NOW + 60 + 40 * 60) == [a1], "开机时晚了 40 分钟（宽限内）→ 不记没做成，照常去补")
check("没开着" in a1.get("late_why", ""), "补的时候知道晚了是因为机器人没开着")
tb.failed(a1, "QQ 没连上", NOW + 60 + 41 * 60, offline=True)
check(a1["late_why"].startswith("到点那会儿机器人没开着") and tb.due_now(NOW + 60 + 41 * 60 + 16) == [a1],
      "开机时 QQ 还没连上：晚的原因还是第一个（没开着），15 秒后就再试（不用等 1 分钟）")
tb.done(a1, "补上了", NOW + 60 + 42 * 60)
check(a1["late_why"] == "" and a1["status"] == "done", "补上以后清掉")
a2, _ = add(tb, what="刚到点的", due=NOW + 6 * H)
tb.sweep(NOW + 6 * H + 20)
check(not a2.get("late_why"), "开机时才过点 20 秒的：不算「机器人没开着」")
tb.failed(a2, "他不是机器人的 QQ 好友（私聊发不过去）", NOW + 6 * H + 30, final=True)
check("好友" in a2["apo_why"], "明确发不了的：道歉的原因写这次的（不是好友），不写更早的")

print("\n[5b 发不出去：越隔越久、写好的那句只写一次、明确发不了的不再试、日志不刷屏]")
tb, logs = fresh(grace_min=60)
t, _ = add(tb, what="提醒他关火", due=NOW + 60)
tries, now = 0, NOW + 60
while t["status"] == "pending" and now < NOW + 3 * H:
    if tb.due_now(now) == [t]:
        tb.failed(t, "QQ 拒收了", now)
        tries += 1
    now += 5
check(t["status"] == "missed" and tries <= 9, f"回退检查：1 小时宽限里发不出去只试了 {tries} 次（1、2、5、10 分钟……；以前每分钟一次、60 次）", tries)
fails = [x for x in logs if "#" + str(t["n"]) in x and "没做成" in x]
check(len(fails) == 2, f"回退检查：同一个原因的日志只记第一次（+ 最后记成没做成那一行），不是每次一行（{len(fails)} 行）", fails)
tb, _ = fresh(grace_min=60)
t, _ = add(tb, what="提醒他关火", due=NOW + 60)
tries, now = 0, NOW + 60
while t["status"] == "pending" and now < NOW + 3 * H:
    if tb.due_now(now) == [t]:
        tb.failed(t, "QQ 没连上", now, offline=True)
        tries += 1
    now += 5
check(tries <= 12, f"QQ 一直没连上：先密后疏（15 秒、30 秒、1、2、5、10 分钟……），一小时 {tries} 次", tries)
tb, _ = fresh(grace_min=60)
t, _ = add(tb, what="提醒他关火", due=NOW + 60)
tb.save_draft(t, "关火啦", "模型写的")
check(Table.draft(t) == ("关火啦", "模型写的"), "写好的那句存在这件事上（重试只重发）")
tb.failed(t, "QQ 拒收了", NOW + 70)
check(Table.draft(t) == ("关火啦", "模型写的"), "没发出去：写好的还在")
tb.edit(t, due=NOW + 2 * H, now=NOW + 80)
check(Table.draft(t) is None, "改了时间：上次写的那句不能再用")
tb.save_draft(t, "关火啦", "模型写的")
tb.done(t, "关火啦", NOW + 2 * H)
check(Table.draft(t) is None and "draft" not in t, "做完了清掉")
d2, _ = add(tb, what="每天提醒他吃药", due=NOW + 3 * H, repeat="daily")
tb.save_draft(d2, "该吃药了", "模型写的")
tb.failed(d2, "x", NOW + 5 * H, final=True)
check(Table.draft(d2) is None, "每天的：这一次没做成，下一次重新写")
t, _ = add(tb, what="提醒他喝水", due=NOW + 4 * H)
check(tb.failed(t, "他不是机器人的 QQ 好友（私聊发不过去）", NOW + 4 * H, final=True) == "missed" and t["status"] == "missed"
      and t["apology"] == "owed" and "好友" in t["apo_why"], "回退检查：明确发不了（不是好友）→ 直接记成没做成，不再试")
t, _ = add(tb, what="提醒他喝口水", due=NOW + 5 * H)
check(tb.failed(t, "机器人在这个群被禁言了", NOW + 5 * H, retry_at=NOW + 5 * H + 900) == "retry" and t["next_try"] == NOW + 5 * H + 900
      and tb.due_now(NOW + 5 * H + 600) == [], "禁言 15 分钟后解：到点再发一次，中间不试")
t, _ = add(tb, what="提醒他喝杯水", due=NOW + 6 * H)
check(tb.failed(t, "机器人在这个群被禁言了", NOW + 6 * H, retry_at=NOW + 9 * H) == "missed", "禁言要过了宽限才解：直接记成没做成")

print("\n[6 重复的]")
tb, _ = fresh()
dl, _ = add(tb, what="催他睡觉", due=at(2026, 11, 8, 23, 0), repeat="daily")
tb.done(dl, "该睡了", at(2026, 11, 8, 23, 0))
check(dl["status"] == "pending" and ck.fmt(dl["due"], BJ, "%m-%d %H:%M") == "11-09 23:00", "每天的：做完排到明天同一时间")
r = tb.failed(dl, "QQ 没连上", at(2026, 11, 10, 1, 0))
check(r == "missed" and dl["status"] == "pending" and dl["apology"] == "owed" and ck.fmt(dl["due"], BJ, "%m-%d %H:%M") == "11-10 23:00",
      "每天的：这一次没做成 → 欠道歉，下一次照常排")
wk, _ = add(tb, what="周末也不叫", due=at(2026, 11, 14, 7, 0), repeat="weekdays", now=at(2026, 11, 13, 22, 0))
check(ck.fmt(wk["due"], BJ, "%a %H:%M") == "Mon 07:00", "工作日的第一次落在周六 → 顺延到周一")
mo, _ = add(tb, what="交房租", due=at(2026, 11, 30, 9, 0), repeat="monthly", dom=31)
check(mo["dom"] == 31, "每月的记着原来是几号")

print("\n[7 每轮的状态：答应过他的 / 别处的 / 刚做的 / 道歉 / 没记上的]")
tb, _ = fresh()
a, _ = add(tb, what="提醒他交作业", due=NOW + 2 * H)
b, _ = add(tb, what="私聊里答应的", due=NOW + 3 * H, conv=P_AMU)
c, _ = add(tb, what="二群里答应的", due=NOW + 4 * H, conv=G2)
st = tb.state_for(AMU, G1, NOW)
check([x["n"] for x in st["here"]] == [a["n"]] and st["elsewhere"] == 2, "群 1 里：只给看群 1 的；私聊的、群 2 的只说有几件（不带内容）", st)
st = tb.state_for(AMU, P_AMU, NOW)
check(sorted(x["n"] for x in st["here"]) == sorted([a["n"], b["n"], c["n"]]), "私聊里：私聊的和群里的都给看（群里的大家本来就看得到）")
check(seen_in(G1, P_AMU) and not seen_in(P_AMU, G1) and not seen_in(G2, G1), "谁看得到：群→私聊可以；私聊→群、A 群→B 群不行")
check(tb.state_for(XC, G1, NOW)["here"] == [], "别人的不给看")
tb.done(a, "交作业啦", NOW + 2 * H)
st = tb.state_for(AMU, G1, NOW + 2 * H + 600)
check([x["n"] for x in st["done"]] == [a["n"]], "两小时内做过的：告诉它不用再做一遍")
check(tb.state_for(AMU, G1, NOW + 5 * H)["done"] == [], "过了两小时不提")
x, _ = add(tb, what="提醒他关火", due=NOW + 60)
tb.failed(x, "QQ 没连上", NOW + 2 * H, final=True)
st = tb.state_for(AMU, G1, NOW + 2 * H)
check([y["n"] for y in st["apology"]] == [x["n"]], "没做成的：给「欠着一个道歉」的状态")
check(tb.state_for(AMU, G2, NOW + 2 * H)["apology"] == [], "群 1 的道歉不进群 2")
tb.consume(AMU, {"apo": [x["n"]]}, NOW + 2 * H + 10)
check(x["apology"] == "told" and tb.state_for(AMU, G1, NOW + 3 * H)["apology"] == [], "回退检查：它说过一次以后不再提（只算这一轮真给它看过的）")
tb.consume(AMU, {"apo": [999]}, NOW)
n1 = tb.note(AMU, G1, "你答应他的「每天提醒他早睡」没记上：满了", NOW)
n2 = tb.note(AMU, P_AMU, "私聊里没记上的", NOW)
st = tb.state_for(AMU, G1, NOW)
check([y["id"] for y in st["notes"]] == [n1["id"]], "没记上的：在哪答应的就在哪说（私聊的不进群）")
tb.consume(AMU, {"notes": [n1["id"]]}, NOW)
check(tb.state_for(AMU, G1, NOW)["notes"] == [] and len(tb.d["notes"]) == 1, "说过一次就拿掉，别处的留着")
for i in range(6):
    tb.note(XC, G1, f"第{i}条", NOW)
check(len([y for y in tb.d["notes"] if y["uid"] == XC]) == 4, "没记上的每人最多留 4 条")

print("\n[8 没说时间的答应]")
tb, _ = fresh(promise_after_min=30, promise_gap_min=90, promise_shows=3, promise_days=3)
p, why = tb.add_promise(G1, G1, "group", AMU, "阿木", "帮他查明天的天气", "等会帮你查", "明天天气怎么样", NOW)
check(p and p["kind"] == "promise" and p["due"] is None and why == "", "记上了（没有时间）")
check(tb.add_promise(G1, G1, "group", AMU, "阿木", "帮他查明天的天气", now=NOW + 60)[1] == "dup", "同一件不重复记")
check(tb.due_now(NOW + 9 * H) == [], "没说时间的不会到点去做")
check(tb.state_for(AMU, G1, NOW + 600)["promises"] == [], "刚答应完的那段聊天里不提（30 分钟内）")
st = tb.state_for(AMU, G1, NOW + 40 * 60)
check([y["n"] for y in st["promises"]] == [p["n"]], "过了 30 分钟他再来：提一下")
tb.consume(AMU, {"prom": [p["n"]]}, NOW + 40 * 60)
check(tb.state_for(AMU, G1, NOW + 60 * 60)["promises"] == [] and tb.state_for(AMU, G1, NOW + 131 * 60)["promises"] != [], "提过一次隔 90 分钟才再提")
tb.consume(AMU, {"prom": [p["n"]]}, NOW + 131 * 60)
tb.consume(AMU, {"prom": [p["n"]]}, NOW + 240 * 60)
tb.prune(NOW + 241 * 60)
check(p["status"] == "expired", "提满 3 次 → 过期")
q, _ = tb.add_promise(G1, G1, "group", AMU, "阿木", "回头唱给他听", now=NOW)
tb.prune(NOW + 4 * 86400)
check(q["status"] == "expired", "挂满 3 天 → 过期")
tb, _ = fresh(promise_max=5)
ps = [tb.add_promise(G1, G1, "group", AMU, "阿木", f"答应的第{i}件事情", now=NOW + i)[0] for i in range(7)]
check(len(tb.pending("promise", who=AMU)) == 5 and ps[0]["status"] == "expired", "同一个人挂太多：丢最早的，最多 5 件")
check(tb.mine(AMU, G1)[0]["kind"] == "promise", "没说时间的也有编号，能取消")

print("\n[9 取消 / 改：只有本人或管理员]")
tb, logs = fresh()
t, _ = add(tb, what="提醒他交作业", due=NOW + 2 * H)
o, _ = add(tb, who=XC, what="小橙的事", due=NOW + 2 * H)
check(Table.can_edit(t, AMU) and not Table.can_edit(t, XC) and Table.can_edit(t, XC, admin=True), "本人能改、别人不能、管理员能")
check([x["n"] for x in tb.mine(AMU, G1)] == [t["n"]] and len(tb.mine(LW, G1, admin=True)) == 2, "抽取时只给他看自己的编号；管理员看这个对话里所有的")
check(tb.mine(AMU, G2) == [], "别的群里看不到这个群的编号")
check(tb.cancel(t, "阿木", NOW) and t["status"] == "cancelled" and not tb.cancel(t, "阿木", NOW), "取消：只取消一次")
check(tb.due_now(NOW + 3 * H) == [o], "取消了的不再去做")
o2, why = tb.edit(o, due=NOW + 5 * H, now=NOW)
check(o2 is o and o["due"] == NOW + 5 * H and o["tries"] == 0, "改时间")
check(tb.edit(o, due=NOW - 3600, now=NOW)[0] is None, "改到已经过了的时间 → 不改")
check(tb.edit(o, what="小橙的新事", now=NOW)[0]["what"] == "小橙的新事", "改内容")
check(tb.edit(t, due=NOW + H, now=NOW)[0] is None, "取消了的不能改")
check(ref_num("#3") == 3 and ref_num("编号 12") == 12 and ref_num("x") is None, "编号的认法")

print("\n[10 别人家的 AI / 清理]")
tb, _ = fresh(keep_days=30)
t, _ = add(tb, who=LW, what="跟它约的", due=NOW + H)
u, _ = add(tb, who=AMU, by=LW, what="它替别人定的", due=NOW + H)
v, _ = add(tb, who=AMU, what="真人的事", due=NOW + 2 * H)
gone = tb.drop_person(LW, "对方是别人家的 AI", NOW)
check({x["n"] for x in gone} == {t["n"], u["n"]} and v["status"] == "pending", "后来被认出是 AI：答应它的、它让定的都划掉，别人的不动")
tb.done(v, "做了", NOW + 2 * H)
tb.prune(NOW + 40 * 86400)
check(tb.find(v["n"]) is None and tb.find(t["n"]) is None, "做完 / 取消的留 30 天就清掉")
w, _ = add(tb, what="欠着道歉的", due=NOW + 41 * 86400, now=NOW + 41 * 86400 - 60)
tb.failed(w, "x", NOW + 42 * 86400, final=True)
tb.prune(NOW + 80 * 86400)
check(tb.find(w["n"]) is not None, "还欠着道歉的不清")

print("\n[11 同一个地方隔 20 秒]")
g = Gap(20)
check(g.ok(G1, 100.0), "第一条：发")
g.mark(G1, 100.0)
check(not g.ok(G1, 110.0) and g.ok(G2, 110.0), "回退检查：同一个群 10 秒后不发（别的群照发）")
check(g.ok(G1, 120.0), "20 秒后发")

print("\n[12 存档：重启不丢]")
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "promise.json"
    s = Store(p)
    tb = Table(s.data["table"], BJ)
    t, _ = add(tb, what="重启以后还在", due=NOW + H)
    s.event("add", "记下 #1", NOW)
    check(s.save(force=True) and p.exists(), "存下来了")
    s2 = Store(p)
    tb2 = Table(s2.data["table"], BJ)
    check([x["what"] for x in tb2.pending()] == ["重启以后还在"] and tb2.d["seq"] == 1, "重新读：表还在、编号接着往下")
    t2, _ = add(tb2, what="第二件", due=NOW + 2 * H)
    check(t2["n"] == 2, "新的编号是 2")
    p.write_text("{坏了", encoding="utf-8")
    warns = []
    s3 = Store(p, warn=warns.append)
    check(s3.data["table"] == {} and warns and list(Path(td).glob("promise.broken-*.json")), "文件坏了：改名留着，从空表开始（不拿空表覆盖）", warns)
    json.loads(json.dumps(s.data))
    check(True, "存档能被 json 原样读写")

ok = sum(1 for c_, _ in RES if c_)
bad = [m for c_, m in RES if not c_]
print("\n" + "=" * 50 + f"\n  结果：{ok} 项过了" + (f"，{len(bad)} 项没过" if bad else "，全过"))
for m in bad:
    print("    -", m)
sys.exit(1 if bad else 0)
