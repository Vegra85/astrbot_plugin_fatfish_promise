#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""时间解析单测（不用装 AstrBot，几秒钟）：python tests/test_when.py [插件目录 默认上一层]
测 core/when.py（parse_when / has_time / dur / 重复）和 core/clock.py（时区 / 时间的说法）。
「回退检查」那几项在老的解析里会失败（比如下午说「8 点」被算成明早 8 点），用来证明新加的东西真在起作用。"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

d = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(d))
from core import clock as ck  # noqa: E402
from core import when as wh  # noqa: E402

RES = []
BJ = ck.BEIJING


def check(c, m, why=""):
    RES.append((bool(c), m))
    print(("  [过]   " if c else "  [没过] ") + m + ("" if c or not why else f"\n           {str(why)[:600]}"))


def at(y, mo, d_, h, mi, tz=BJ):
    return datetime(y, mo, d_, h, mi, tzinfo=tz).timestamp()


def show(ts, tz=BJ):
    return None if ts is None else ck.fmt(ts, tz, "%Y-%m-%d %H:%M")


def case(now, text, want, note=""):
    got = show(wh.parse_when(text, None, now, BJ))
    check(got == want, f"「{text}」→ {want}" + (f"（{note}）" if note else ""), f"实际 {got}")


N1 = at(2026, 11, 8, 15, 0)  # 周日 15:00
N2 = at(2026, 11, 8, 21, 30)  # 周日 21:30
N3 = at(2026, 11, 9, 3, 30)  # 周一凌晨 03:30
N4 = at(2026, 11, 13, 22, 0)  # 周五 22:00

print("[1 几分钟 / 几小时以后]（现在 11-08 周日 15:00）")
case(N1, "10分钟后", "2026-11-08 15:10")
case(N1, "十分钟以后", "2026-11-08 15:10")
case(N1, "半小时后", "2026-11-08 15:30")
case(N1, "过半小时", "2026-11-08 15:30")
case(N1, "两个钟头", "2026-11-08 17:00", "光写时长也算从现在起")
case(N1, "一个半小时后", "2026-11-08 16:30")
case(N1, "1小时30分钟后", "2026-11-08 16:30", "回退检查：两段加起来，老的只认到 30 分钟")
case(N1, "一刻钟后", "2026-11-08 15:15")
case(N1, "3天后", "2026-11-11 15:00")
check(show(wh.parse_when(None, 30, N1, BJ)) == "2026-11-08 15:30", "mins=30 → 半小时后")
check(show(wh.parse_when(None, "1小时", N1, BJ)) == "2026-11-08 16:00", "mins=「1小时」→ 1 小时后（不是 1 分钟）")
check(show(wh.parse_when(None, "半小时", N1, BJ)) == "2026-11-08 15:30", "mins=「半小时」")

print("\n[2 几点]")
case(N1, "8点", "2026-11-08 20:00", "回退检查：下午说 8 点 = 今晚 8 点，老的算成明早")
case(N1, "8点半", "2026-11-08 20:30")
case(N1, "早上8点", "2026-11-09 08:00", "说了早上：早上的过了 → 明早")
case(N1, "下午四点", "2026-11-08 16:00")
case(N1, "中午1点", "2026-11-09 13:00")
case(N1, "12点", "2026-11-09 00:00", "下午 3 点说 12 点：最近的将来是半夜 0 点（不是明天中午）")
case(N1, "八点过一刻", "2026-11-08 20:15")
case(N1, "八点三刻", "2026-11-08 20:45")
case(N1, "差一刻九点", "2026-11-08 20:45")
case(N1, "九点差一刻", "2026-11-08 20:45")
case(N1, "十点零五", "2026-11-08 22:05")
case(N1, "二十一点", "2026-11-08 21:00")
case(N1, "21:00", "2026-11-08 21:00")
case(N1, "２１：３０", "2026-11-08 21:30", "全角数字")
case(N1, "8点30分以后", "2026-11-08 20:30", "「30 分以后」前面是钟点，不是 30 分钟后")
case(N2, "8点", "2026-11-09 08:00", "晚上 9 点半说 8 点：早晚的都过了 → 明天 8 点（光说点钟已过 → 明天）")
case(N2, "10点", "2026-11-08 22:00")
case(N2, "早上7点", "2026-11-09 07:00")

print("\n[2b 光说点钟 / 今天几点：取最近的将来（含跨午夜）]")
N22 = at(2026, 11, 8, 22, 0)
case(N22, "12点提醒我睡觉", "2026-11-09 00:00", "回退检查：晚上 10 点说「12 点」= 半夜 0 点，老的算成明天中午")
case(at(2026, 11, 8, 23, 30), "12点半", "2026-11-09 00:30", "回退检查：23:30 说「12 点半」= 半夜 0:30，老的算成明天 12:30")
case(at(2026, 11, 8, 10, 0), "12点", "2026-11-08 12:00", "上午说 12 点 = 今天中午")
case(at(2026, 11, 9, 0, 20), "12点", "2026-11-09 12:00", "半夜 0:20 说 12 点 = 今天中午（跨过午夜了）")
case(N1, "今天8点", "2026-11-08 20:00", "回退检查：下午说「今天 8 点」= 今晚 8 点，老的当成已经过了、不记")
case(at(2026, 11, 8, 7, 0), "今天8点", "2026-11-08 08:00", "早上 7 点说「今天 8 点」= 今早 8 点")
case(at(2026, 11, 8, 21, 0), "今天8点", None, "晚上 9 点说「今天 8 点」：早晚的都过了 → 不记（不挪到明天）")
case(at(2026, 11, 8, 23, 30), "今天12点", "2026-11-09 00:00", "23:30 说「今天 12 点」= 今天结束的那个半夜")
case(at(2026, 11, 8, 23, 59), "1点", "2026-11-09 01:00", "23:59 说「1 点」= 一个钟头以后（跨午夜）")
case(at(2026, 11, 8, 23, 50), "0点10分", "2026-11-09 00:10", "23:50 说「0 点 10 分」= 20 分钟以后")
case(at(2026, 11, 8, 13, 0), "中午12点", "2026-11-09 12:00", "说了「中午」：今天中午过了 → 明天中午")
case(N1, "明天8点", "2026-11-09 08:00", "说了明天：明早 8 点（不挪到晚上）")

print("\n[3 早晚 / 哪天]")
case(N1, "明天早上八点", "2026-11-09 08:00")
case(N1, "明早8.30", "2026-11-09 08:30", "明早 8.30 是 8:30 不是 8 月 30 号")
case(N1, "明晚", "2026-11-09 20:00")
case(N1, "明天", "2026-11-09 09:00", "只说哪天：早上 9 点")
case(N1, "后天下午3点", "2026-11-10 15:00")
case(N1, "大后天", "2026-11-11 09:00")
case(N1, "今天晚上9点", "2026-11-08 21:00")
case(N1, "今天上午9点", None, "说了今天、已经过了 → 不记")
case(N1, "今天", None)
case(N1, "晚上12点", "2026-11-09 00:00", "晚上 12 点 = 半夜")
case(N1, "今晚1点", "2026-11-09 01:00", "今晚 1 点 = 日历上的明天凌晨")
case(N1, "凌晨2点", "2026-11-09 02:00")
case(N2, "今晚11点", "2026-11-08 23:00")
case(N3, "明早8点", "2026-11-09 08:00", "凌晨三点半说明早 = 睡醒的那个白天 = 今天")
case(N3, "明天", "2026-11-09 09:00", "凌晨说明天 = 今天白天")
case(N3, "今晚4点", "2026-11-09 04:00", "凌晨说「今晚 4 点」= 今天凌晨 4 点")

print("\n[4 周几 / 几号 / 日期]")
case(N1, "周五", "2026-11-13 09:00")
case(N1, "星期五晚上8点", "2026-11-13 20:00")
case(N1, "下周三晚上8点", "2026-11-11 20:00", "周日说下周三 = 后天那个周三")
case(N1, "下下周一", "2026-11-16 09:00")
case(N2, "周日", "2026-11-15 09:00", "今天就是周日、9 点过了 → 下周日")
case(N2, "这周日晚上10点", "2026-11-08 22:00")
case(N1, "11-12", "2026-11-12 09:00")
case(N1, "11月12日下午3点", "2026-11-12 15:00")
case(N1, "2026-11-12 08:00", "2026-11-12 08:00")
case(N1, "2025-11-12 08:00", None, "写了年份、已经过了 → 不记")
case(N1, "1-5", "2027-01-05 09:00", "没写年份、过了 → 明年")
case(N1, "每月15号", "2026-11-15 09:00")
case(N1, "15号晚上8点", "2026-11-15 20:00")
case(N1, "3号", "2026-12-03 09:00", "这个月 3 号过了 → 下个月")

print("\n[5 说不清的不记]")
for s in ("等会", "待会儿", "一会儿", "回头", "改天", "看心情", "有空", "下次", "你说呢", ""):
    case(N1, s, None)
case(N1, "晚点", None, "回退检查：老的把「晚点」里的「晚」当成晚上 8 点")
case(N1, "过两天", None, "回退检查：「过两天」是口头说法，老的会算成 2 天后")
case(N1, "快一点", None, "回退检查：「快一点」不是 1 点")
case(N1, "一点点", None)
case(N1, "晚点8点", "2026-11-08 20:00", "去掉口头的「晚点」以后还有时间：照常认")
case(N1, "一点", "2026-11-09 01:00", "开头的「一点」是钟点")
case(N1, "下午一点十分", "2026-11-09 13:10")
check(wh.parse_when("25点", None, N1, BJ) is None, "「25 点」不存在 → 不记")

print("\n[6 has_time：原话里说没说清楚时间]")
for s in ("明天早上8点提醒你", "10分钟后叫你", "每天提醒你", "周三见", "8点", "两分钟后", "11-12", "15号", "今晚", "工作日"):
    check(wh.has_time(s), f"「{s}」说了时间")
for s in ("等会帮你查", "回头告诉你", "我少说一点", "好 我快一点", "一会儿就好", "", "晚安"):
    check(not wh.has_time(s), f"「{s}」没说时间")

print("\n[7 dur / 重复 / 几号]")
for x, want in (("1小时30分钟", 90), ("半小时", 30), ("30", 30), (45, 45), ("两天", 2880), ("一刻钟", 15), ("1个半小时", 90)):
    check(wh.dur(x) == want, f"dur({x!r}) = {want}", wh.dur(x))
check(wh.dur("abc") is None and wh.dur(None) is None and wh.dur(True) is None, "看不懂的 → None")
for x, want in (("每天", "daily"), ("每天晚上", "daily"), ("天天", "daily"), ("工作日", "weekdays"), ("每周三", "weekly"),
                ("每月", "monthly"), ("每年", "yearly"), ("daily", "daily"), ("", None), ("不重复", None), ("明天", None)):
    check(wh.repeat_of(x) == want, f"repeat_of({x!r}) = {want}", wh.repeat_of(x))
check(wh.dom_of("每月31号") == 31 and wh.dom_of("明天") is None, "dom_of：每月 31 号 → 31")

print("\n[8 重复的下一次]")
j31 = at(2026, 1, 31, 8, 0)
f28 = wh.advance(j31, "monthly", BJ, 31)
m31 = wh.advance(f28, "monthly", BJ, 31)
check(show(f28) == "2026-02-28 08:00" and show(m31) == "2026-03-31 08:00", "每月 31 号：二月是 28 号，三月回到 31 号", (show(f28), show(m31)))
fri = at(2026, 11, 13, 7, 0)
check(show(wh.advance(fri, "weekdays", BJ)) == "2026-11-16 07:00", "工作日：周五的下一次是周一")
check(show(wh.advance(N1, "weekly", BJ)) == "2026-11-15 15:00", "每周：+7 天")
check(show(wh.advance(at(2028, 2, 29, 9, 0), "yearly", BJ, 29)) == "2029-02-28 09:00", "每年 2 月 29 号：平年是 28 号")
nx = wh.next_after(at(2026, 11, 1, 8, 0), "daily", N1, BJ)
check(show(nx) == "2026-11-09 08:00", "机器人关了一周：每天的下一次是明天，中间那几次不补", show(nx))
sat = wh.parse_when("工作日早上7点", None, N4, BJ)
check(show(sat) == "2026-11-14 07:00" and show(wh.first_weekday(sat, BJ)) == "2026-11-16 07:00", "周五晚上说「工作日早上 7 点」：第一次顺延到周一")

print("\n[9 时区]")
tz, label, ok = ck.make_tz("Asia/Shanghai")
check(tz is BJ and label == "北京时间" and ok, "Asia/Shanghai = 北京时间（不用 tzdata）")
check(ck.make_tz("UTC+8")[0] is BJ and ck.make_tz("prc")[0] is BJ, "UTC+8 / PRC 也是北京时间")
t5, l5, ok5 = ck.make_tz("UTC-5")
check(ok5 and l5 == "UTC-5" and t5.utcoffset(None) == timedelta(hours=-5), "UTC-5 认得")
tbad, lbad, okbad = ck.make_tz("Nowhere/Nothing")
check(tbad is BJ and not okbad, "认不出的时区 → 北京时间 + 告诉你认不出")
check(ck.make_tz("")[1] == "服务器时间", "留空 = 跟服务器")
ny = timezone(timedelta(hours=-5))
N5 = at(2026, 11, 8, 21, 0)  # 北京 21:00 = 纽约 08:00（两边都是白天）
t_bj = wh.parse_when("明天早上8点", None, N5, BJ)
t_ny = wh.parse_when("明天早上8点", None, N5, ny)
check(show(t_bj) == "2026-11-09 08:00" and ck.fmt(t_ny, ny, "%Y-%m-%d %H:%M") == "2026-11-09 08:00" and t_ny - t_bj == 13 * 3600,
      "同一句「明天早上 8 点」按配置的时区算（纽约的 8 点比北京晚 13 小时）", (show(t_bj), ck.fmt(t_ny, ny, "%Y-%m-%d %H:%M")))
t_ny2 = wh.parse_when("明天早上8点", None, N1, ny)  # 北京 15:00 = 纽约凌晨 2 点
check(ck.fmt(t_ny2, ny, "%Y-%m-%d %H:%M") == "2026-11-08 08:00", "纽约凌晨 2 点说「明天早上」= 睡醒的那个早上（凌晨的规矩按配置的时区算）")
check(ck.day(at(2026, 11, 9, 7, 59), BJ) == "2026-11-09" and ck.day(at(2026, 11, 9, 7, 59), timezone.utc) == "2026-11-08",
      "换天按时区算：北京 11-09 早上 7:59 在 UTC 还是 11-08")

print("\n[10 时间的说法]")
check(ck.when_text(at(2026, 11, 8, 20, 0), N1, BJ) == "今天 20:00", "今天")
check(ck.when_text(at(2026, 11, 9, 8, 0), N1, BJ) == "明天 08:00", "明天")
check(ck.when_text(at(2026, 11, 10, 8, 0), N1, BJ) == "后天 08:00", "后天")
check(ck.when_text(at(2026, 11, 7, 8, 0), N1, BJ) == "昨天 08:00", "昨天")
check(ck.when_text(at(2026, 11, 12, 8, 0), N1, BJ) == "11-12（周四）08:00", "再远写日期和周几", ck.when_text(at(2026, 11, 12, 8, 0), N1, BJ))
check(ck.when_text(at(2027, 1, 5, 9, 0), N1, BJ) == "2027-01-05 09:00", "跨年写年份")
check([ck.span(x) for x in (30, 300, 5400, 3 * 86400)] == ["1 分钟", "5 分钟", "1.5 小时", "3 天"], "多久的说法")
c = ck.Clock()
c2 = ck.Clock(3600)
check(abs(c2() - c() - 3600) < 1, "测试钩子：Clock(offset) 把「现在」拨快")

ok = sum(1 for c_, _ in RES if c_)
bad = [m for c_, m in RES if not c_]
print("\n" + "=" * 50 + f"\n  结果：{ok} 项过了" + (f"，{len(bad)} 项没过" if bad else "，全过"))
for m in bad:
    print("    -", m)
sys.exit(1 if bad else 0)
