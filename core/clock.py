# -*- coding: utf-8 -*-
"""时区和时间的说法（不依赖 AstrBot，单测直接用）。

为什么自己做时区：服务器常在国外、Docker 默认 UTC，「明早 8 点」要按用户那边的钟算才对。
中国 1991 年以后没有夏令时，北京时间就是固定的 UTC+8，所以常用的几个名字直接写死偏移，
不用装 tzdata（Windows 上常常没有）；别的名字才去找 zoneinfo，找不到退回北京时间。
"""

import re
import time
from datetime import datetime, timedelta, timezone

BEIJING = timezone(timedelta(hours=8), "北京时间")
_FIXED = {
    "asia/shanghai": 8,
    "asia/chongqing": 8,
    "asia/harbin": 8,
    "asia/urumqi": 8,
    "prc": 8,
    "asia/hong_kong": 8,
    "asia/macau": 8,
    "asia/taipei": 8,
    "asia/singapore": 8,
    "asia/tokyo": 9,
    "asia/seoul": 9,
    "utc": 0,
    "gmt": 0,
    "etc/utc": 0,
}
_OFFSET = re.compile(r"^(?:utc|gmt)?\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?$")
WEEK = "一二三四五六日"


def make_tz(name):
    """配置里的时区 → (tzinfo, 怎么叫它, 认没认出来)。
    留空 = 跟服务器（取服务器现在的偏移，夏令时切换要重启才跟上）；认不出 → 北京时间"""
    s = str(name or "").strip()
    if not s:
        return datetime.now().astimezone().tzinfo, "服务器时间", True
    k = s.lower().replace(" ", "")
    if k in _FIXED:
        off = _FIXED[k]
        if off == 8:
            return BEIJING, "北京时间", True
        return timezone(timedelta(hours=off), s), s, True
    m = _OFFSET.match(k)
    if m:
        h, mi = int(m.group(2)), int(m.group(3) or 0)
        if h <= 14 and mi < 60:
            off = timedelta(hours=h, minutes=mi) * (1 if m.group(1) == "+" else -1)
            if off == timedelta(hours=8):
                return BEIJING, "北京时间", True
            label = f"UTC{m.group(1)}{h}" + (f":{mi:02d}" if mi else "")
            return timezone(off, label), label, True
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(s), s, True
    except Exception:  # 没装 tzdata / 写错了
        return BEIJING, "北京时间", False


def dt(ts, tz):
    return datetime.fromtimestamp(float(ts), tz or BEIJING)


def fmt(ts, tz, f="%m-%d %H:%M"):
    return dt(ts, tz).strftime(f)


def day(ts, tz):
    """某个时刻在这个时区是哪一天（每天的名额按它换天）"""
    return fmt(ts, tz, "%Y-%m-%d")


def when_text(ts, now, tz):
    """「今天 08:00」「明天 08:00」「11-12（周三）08:00」—— 给模型看、给人看都用这个"""
    a, b = dt(ts, tz), dt(now, tz)
    days = (a.date() - b.date()).days
    hm = a.strftime("%H:%M")
    if days == 0:
        return f"今天 {hm}"
    if days == 1:
        return f"明天 {hm}"
    if days == 2:
        return f"后天 {hm}"
    if days == -1:
        return f"昨天 {hm}"
    if a.year == b.year:
        return a.strftime("%m-%d") + f"（周{WEEK[a.weekday()]}）{hm}"
    return a.strftime("%Y-%m-%d") + f" {hm}"


def now_text(now, tz, label=""):
    """「11-08（周六）21:30」+ 时区名"""
    a = dt(now, tz)
    s = a.strftime("%m-%d") + f"（周{WEEK[a.weekday()]}）" + a.strftime("%H:%M")
    return f"{s}（{label}）" if label else s


def span(sec):
    """秒 → 「5 分钟」「1.5 小时」「3 天」"""
    sec = max(0, int(sec))
    if sec < 3600:
        return f"{max(1, round(sec / 60))} 分钟"
    if sec < 86400 * 2:
        h = round(sec / 3600, 1)
        return f"{int(h) if h == int(h) else h} 小时"
    return f"{round(sec / 86400)} 天"


class Clock:
    """插件的「现在几点」。offset 是留给端到端测试的钩子：把钟拨快，看到点了会不会去做。
    平时 offset 永远是 0（只有设了测试环境变量，面板接口才让改）。"""

    def __init__(self, offset=0.0):
        self.offset = float(offset or 0)

    def __call__(self):
        return time.time() + self.offset
