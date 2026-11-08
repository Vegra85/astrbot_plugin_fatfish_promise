# -*- coding: utf-8 -*-
"""「明早 8 点」「半小时后」「每周三晚上」→ 时间戳（纯函数，不依赖 AstrBot）。

模型只负责把原话里的时间说法抄出来，算成几点是这里的事：模型算日期、算星期常出错，
规则算得准、还能单测。说不清的（「等会」「回头」「看心情」）一律返回 None —— 不记，比记错强。

跟作者自己机器人里原来的那版比多了三处（都有单测）：
  - 「1 小时 30 分钟后」整段相加（以前只认到「30 分钟后」）；光写「10 分钟」「过半小时」也算从现在起。
  - 光说「8 点 / 12 点半」（或者「今天 8 点」）取最近的将来：下午说「8 点」= 今晚 8 点；晚上 10 点说「12 点」= 半夜 0 点、
    不是明天中午；下午说「今天 8 点」= 今晚 8 点（以前算成已经过了、不记）。
  - 「快一点」「一点点」里的「一点」不当成 1 点。
"""

import re
import time
from calendar import monthrange
from datetime import timedelta

from .clock import BEIJING, dt

_FW = str.maketrans("０１２３４５６７８９：－／．　", "0123456789:-/. ")
_CN = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
WD = re.compile(r"(下下|下个?|这个?|本)?(?:周|星期|礼拜)([1-7日天])")
DAYS = (
    ("大后天", 3),
    ("后天", 2),
    ("明天", 1),
    ("明早", 1),
    ("明晚", 1),
    ("明儿", 1),
    ("明日", 1),
    ("今天", 0),
    ("今早", 0),
    ("今晚", 0),
    ("今夜", 0),
    ("今日", 0),
)
DOM = re.compile(r"(?<![\d:./-])(\d{1,2})\s*[号日](?![\d楼线房后内])")
PARTS = (("早", 8), ("上午", 9), ("中午", 12), ("下午", 15), ("傍晚", 18), ("晚", 20), ("夜", 22), ("凌晨", 1))
PART_WORDS = re.compile(r"早|上午|中午|下午|傍晚|晚|夜|凌晨")

# 一段时长：「10 分钟」「1 个半小时」「半天」「两周」「一刻钟」
_UNIT = r"(?:分钟|分|小时|钟头|刻钟|天|周|星期|礼拜)"
_ONE = r"(?:(?:\d+(?:\.\d+)?)\s*个?\s*半?|半)\s*个?\s*" + _UNIT
_DURS = r"(" + _ONE + r"(?:\s*零?\s*" + _ONE + r")*)"
# 前面紧挨着数字 / 点 / 冒号的不算（「8 点 30 分以后」是钟点，不是 30 分钟后）
_REL = re.compile(r"(?<![\d点:時时.])" + _DURS + r"\s*(?:以后|之后|过后|以内|之内|后|内)")
_PASS = re.compile(r"过\s*" + _DURS)
_BARE = re.compile(r"^\s*(?:再|大概|大约|差不多)?\s*" + _DURS + r"\s*(?:左右|吧|啊|哦|嗯)?\s*$")
_UNIT_MIN = {"分钟": 1, "分": 1, "小时": 60, "钟头": 60, "刻钟": 15, "天": 1440, "周": 10080, "星期": 10080, "礼拜": 10080}
_DUR_SEG = re.compile(r"(\d+(?:\.\d+)?)?\s*个?\s*(半)?\s*个?\s*(分钟|分|小时|钟头|刻钟|天|周|星期|礼拜)")

REPEATS = [
    ("工作日", "weekdays"),
    ("weekday", "weekdays"),
    ("每周", "weekly"),
    ("每星期", "weekly"),
    ("每礼拜", "weekly"),
    ("weekly", "weekly"),
    ("每月", "monthly"),
    ("每个月", "monthly"),
    ("monthly", "monthly"),
    ("每年", "yearly"),
    ("yearly", "yearly"),
    ("每天", "daily"),
    ("天天", "daily"),
    ("每日", "daily"),
    ("每晚", "daily"),
    ("每早", "daily"),
    ("每天早上", "daily"),
    ("daily", "daily"),
]
REPEAT_TEXT = {"daily": "每天", "weekdays": "工作日", "weekly": "每周", "monthly": "每月", "yearly": "每年"}

# 原话里有没有说清楚什么时候（「5 分钟后」「明早 8 点」「今晚」「周三」「每天」）——「回头」「一会儿」「醒了」不算。
# 模型写的时间、原话里却没有 → 不当成到点的事（模型不许自己编时间）
CLEAR_TIME = re.compile(
    r"(?<![快慢多少好大小轻重近远有差这那早晚])\d{1,2}\s*[:：点](?!点)"
    r"|(\d+(\.\d+)?|半|几)\s*个?\s*(秒钟?|分钟|小时|钟头|刻钟)"
    r"|\d+\s*天(以?后|之后)|今晚|今早|今天(早上|上午|中午|下午|傍晚|晚上)|明早|明晚|明天|明儿|明日|后天"
    r"|(下下|下个?|这个?|本)?(周|星期|礼拜)[1-7日天一二三四五六]|\d{1,2}\s*[-/月]\s*\d{1,2}"
    r"|(?<![\d.])\d{1,2}\s*[号日](?![子常记])"
    r"|每天|每晚|每早|每周|每星期|每月|每年|工作日"
)


# 口头的「待会 / 晚点 / 过两天」不是时间：先去掉再看剩下的（「晚点」里的「晚」会被当成晚上 8 点、「过两天」会被当成 2 天后）
VAGUE = re.compile(
    r"过两天|过几天|晚一点|晚点|晚些|早一点|早点|等一会儿?|等会儿?|待会儿?|一会儿?|回头|改天|稍后|过会儿?|有空|找时间|下次|下回"
)


def zh_digits(s):
    """「八点半」→「8点半」、「十二」→「12」、「两个」→「2个」"""

    def conv(m):
        t = m.group(0)
        if "十" not in t:
            return "".join(str(_CN[c]) for c in t)
        a, _, b = t.partition("十")
        return str((_CN.get(a[-1:], 1) if a else 1) * 10 + (_CN.get(b[:1], 0) if b else 0))

    return re.sub(r"[零〇一二两三四五六七八九十]+", conv, s)


_YD_PRE = ("凌晨", "早上", "上午", "中午", "下午", "晚上", "夜里", "半夜", "今天", "明天", "后天", "今晚", "明晚", "今早",
           "明早", "到", "在", "是", "于", "周", "号", "日", "点", ":", "：")
_YD_POST = re.compile(r"\s*(?:半|一刻|三刻|钟|零|[0-9]|[一二三四五]?十?[一二三四五六七八九]?\s*分)")


def _tame(s):
    """「快一点」「少说一点」「一点也不」里的「一点」不是 1 点：换成「一些」。
    前面是早晚 / 哪天 / 「到」「在」、或者后面跟着「半 / 刻 / 钟 / 几分」、或者在开头的，才当成钟点"""
    out, last = [], 0
    for m in re.finditer("一点", s):
        pre, post = s[: m.start()].rstrip(), s[m.end() :]
        numeral = bool(pre) and (pre[-1].isdigit() or pre[-1] in "零〇一二两三四五六七八九十")  # 「十一点」「二十一点」
        if pre and not numeral and not pre.endswith(_YD_PRE) and not _YD_POST.match(post):
            out.append(s[last : m.start()] + "一些")
            last = m.end()
    return "".join(out) + s[last:]


def norm(s):
    return zh_digits(_tame(str(s or "").translate(_FW))).strip()


def _num(x):
    if isinstance(x, bool) or x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        m = re.search(r"\d+(?:\.\d+)?", str(x))
        if not m:
            return None
        v = float(m.group(0))
    return v if 0 < v < 1e7 else None


def dur(x):
    """多久 → 分钟：「1小时」「2个小时」「半小时」「一个半小时」「1小时30分钟」「两天」「30」；看不懂 → None"""
    if not isinstance(x, str):
        return _num(x)
    s = norm(x)
    ms = [m for m in _DUR_SEG.finditer(s) if m.group(1) or m.group(2)]
    if ms:
        v = sum((float(m.group(1) or 0) + (0.5 if m.group(2) else 0)) * _UNIT_MIN[m.group(3)] for m in ms)
        return v if 0 < v < 1e7 else None
    return _num(s) if re.fullmatch(r"\s*\d+(?:\.\d+)?\s*", s) else None


def has_time(text):
    s = str(text or "")
    return bool(s.strip()) and bool(CLEAR_TIME.search(norm(s)) or CLEAR_TIME.search(s))


def repeat_of(x):
    """「每天」「工作日」「每周三」→ daily / weekdays / weekly …；不重复 → None"""
    s = str(x or "").strip().lower()
    if not s or s in ("不重复", "一次", "once", "no", "none", "false", "null"):
        return None
    if s in REPEAT_TEXT:
        return s
    return next((v for k, v in REPEATS if k in s), None)


def dom_of(at):
    """at 里单独写的「几号」→ 那个数（「每月 31 号」排到 30 天的月份也记得是 31 号）"""
    m = DOM.search(norm(at))
    return int(m.group(1)) if m else None


def _relative(s):
    """从现在起多少分钟（「10 分钟后」「过半小时」「1 小时 30 分钟后」「两个钟头」）；不是 → None"""
    for rx in (_REL, _PASS, _BARE):
        m = rx.search(s)
        if m:
            v = dur(m.group(1))
            if v:
                return v
    if re.search(r"半(个)?小时(以?后|之后)", s):
        return 30.0
    return None


def parse_when(at=None, mins=None, now=None, tz=None):
    """时间的说法 → 时间戳（按 tz 算）；看不懂 / 说不清 / 说的那天已经过了 → None。
    mins：几分钟后（数字或「半小时」）；at：「21:00」「九点半」「明天上午十点」「后天晚上 9 点」「11-12 18:00」
    「2026-11-12 18:00」「下周四晚上」「周五」「每月 15 号」「10 分钟后」…"""
    now = float(now if now is not None else time.time())
    tz = tz or BEIJING
    if mins not in (None, "", 0, "0") and not isinstance(mins, bool):
        m = dur(mins)
        if m:
            return now + max(0.5, m) * 60
    s = norm(VAGUE.sub(" ", str(at or "")))
    if not s:
        return None
    # 「8 点一刻 / 三刻」= 8:15 / 8:45；「差一刻 9 点」= 8:45（不然「1 刻」的 1 会被当成分钟）
    s = re.sub(r"([点時时])\s*过\s*(?=[123]\s*刻)", r"\1", s)
    s = re.sub(
        r"差\s*1\s*刻\s*(\d{1,2})\s*([点時时])|(\d{1,2})\s*([点時时])\s*差\s*1\s*刻",
        lambda m: f"{(int(m.group(1) or m.group(3)) - 1) % 24}{m.group(2) or m.group(4)}45",
        s,
    )
    s = re.sub(r"([点時时])\s*([123])\s*刻(?!钟)", lambda m: m.group(1) + {"1": "15", "2": "30", "3": "45"}[m.group(2)], s)
    rel = _relative(s)
    if rel is not None:
        return now + max(0.5, rel) * 60
    # 「明早 8.30」是 8:30，不是 8 月 30 号（前面有早晚 / 哪天 / 周几才这么认）
    hm = re.search(r"(?<![\d.:/-])(\d{1,2})\.(\d{2})(?![\d.:/\-号日])", s)
    pre = s[: hm.start()] if hm else ""
    if (
        hm
        and int(hm.group(1)) <= 23
        and int(hm.group(2)) < 60
        and not re.search(r"\d\s*[:点時时]", s[: hm.start()] + s[hm.end() :])
        and (re.search(r"早|晚|上午|下午|中午|凌晨|夜", pre) or any(w in pre for w, _ in DAYS) or WD.search(pre))
    ):
        s = s[: hm.start()] + f"{hm.group(1)}:{hm.group(2)}" + s[hm.end() :]
    base = dt(now, tz)
    y = mo = d = dom = None
    year_given = False
    mm = re.search(r"(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})", s)
    if mm:
        y, mo, d, year_given = int(mm.group(1)), int(mm.group(2)), int(mm.group(3)), True
        rest = s[: mm.start()] + " " + s[mm.end() :]
    else:
        mm = re.search(r"(?<![\d:])(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*[日号]?(?![\d:])", s)
        if mm:
            mo, d = int(mm.group(1)), int(mm.group(2))
            rest = s[: mm.start()] + " " + s[mm.end() :]
        else:
            dm = DOM.search(s)
            dom = int(dm.group(1)) if dm else None
            rest = s[: dm.start()] + " " + s[dm.end() :] if dm else s
    tm = re.search(r"(?<![快慢多少好大小轻重近远有这那])(\d{1,2})\s*[:点時时](?!点)\s*(\d{1,2})?\s*(半|一刻|1刻|三刻|3刻)?", rest)
    hh = mi = None
    night = False  # 「晚上 1 点」「今晚 3 点」= 那天夜里 = 日历上的第二天凌晨
    plain = False  # 没说早晚、没说日期 / 周几（光说「8 点」，或者「今天 8 点」）
    if tm:
        hh, mi = int(tm.group(1)), int(tm.group(2) or 0)
        mi = {"半": 30, "一刻": 15, "1刻": 15, "三刻": 45, "3刻": 45}.get(tm.group(3) or "", mi)
    if hh is not None:
        if re.search(r"凌晨", rest) and hh == 12:
            hh = 0
        elif re.search(r"晚上|半夜|夜里|今晚|明晚", rest) and hh == 12:
            hh = 24  # 晚上 12 点 = 半夜（第二天 00:00）
        elif hh <= 4 and re.search(r"晚|夜", rest) and not re.search(r"傍晚|下午", rest):
            night = True  # 0~4 点不加 12（「晚上一点」不是下午一点）
        elif re.search(r"下午|晚上|傍晚|今晚|明晚|夜里|晚", rest) and hh < 12:
            hh += 12
        elif re.search(r"中午", rest) and hh < 11:
            hh += 12
        plain = mo is None and dom is None and not WD.search(rest) and not PART_WORDS.search(rest)
    else:  # 只说了哪天：按说的时段，没说时段就早上 9 点；连哪天都没说（「看心情」）→ 看不懂
        part = next(((h, 0) for w, h in PARTS if w in rest), None)
        if part is None and mo is None and dom is None and not WD.search(rest) and not any(w in rest for w, _ in DAYS):
            return None
        hh, mi = part or (9, 0)
    if not (0 <= hh <= 24 and 0 <= mi < 60):
        return None
    extra = 1 if hh == 24 or night else 0
    hh %= 24
    try:
        if mo is not None:
            t = base.replace(year=y or base.year, month=mo, day=d, hour=hh, minute=mi, second=0, microsecond=0)
            t += timedelta(days=extra)
            if t.timestamp() < now - 60:
                if year_given:
                    return None
                t = t.replace(year=t.year + 1)  # 「1-5」说的是明年一月
            return t.timestamp()
        if dom is not None:  # 「31 号」：这个月的那天，过了就下个月；没有那天的月份用月底
            if not 1 <= dom <= 31:
                return None
            yy, m2 = base.year, base.month
            t = None
            for _ in range(2):
                t = base.replace(
                    year=yy, month=m2, day=min(dom, monthrange(yy, m2)[1]), hour=hh, minute=mi, second=0, microsecond=0
                ) + timedelta(days=extra)
                if t.timestamp() >= now - 60:
                    break
                yy, m2 = (yy + 1, 1) if m2 == 12 else (yy, m2 + 1)
            return t.timestamp()
        w = WD.search(rest)
        if w:
            target = 7 if w.group(2) in "日天" else int(w.group(2))
            p = w.group(1) or ""
            if p.startswith("下下"):
                delta = (7 - base.weekday()) + 7 + (target - 1)
            elif p.startswith("下"):
                delta = (7 - base.weekday()) + (target - 1)
            else:
                delta = (target - 1 - base.weekday()) % 7
            t = (base + timedelta(days=delta + extra)).replace(hour=hh, minute=mi, second=0, microsecond=0)
            if t.timestamp() < now - 60:
                t += timedelta(days=7)
            return t.timestamp()
        shift = next((n for w2, n in DAYS if w2 in rest), None)
        if night and base.hour < 5:
            extra = 0  # 凌晨说的「今晚 / 晚上 3 点」= 今天凌晨 3 点（一天 5 点才算完）
        elif shift and base.hour < 5:  # 凌晨三四点说「明早」= 睡醒以后的那个白天 = 日历上的今天
            t1 = (base + timedelta(days=shift - 1 + extra)).replace(hour=hh, minute=mi, second=0, microsecond=0)
            if t1.timestamp() > now + 60:
                shift -= 1
        t = (base + timedelta(days=(shift or 0) + extra)).replace(hour=hh, minute=mi, second=0, microsecond=0)
        if plain and shift in (None, 0) and 1 <= hh <= 12 and not extra:
            # 光说「8 点 / 12 点半」、或者「今天 8 点」：早上那个、晚上那个（12 点的晚上那个 = 半夜 0 点）、
            # （光说点钟的还有）明天早上那个 —— 取最近的将来。下午说「8 点」= 今晚；22 点说「12 点」= 半夜不是明天中午；
            # 下午说「今天 8 点」= 今晚 8 点；晚上 9 点以后说「今天 8 点」→ 都过了，不记
            cands = [t, t + timedelta(hours=12)] + ([t + timedelta(days=1)] if shift is None else [])
            return next((c.timestamp() for c in cands if c.timestamp() >= now - 60), None)
        if t.timestamp() < now - 60:
            if shift is not None:
                return None  # 「今天上午 8 点」「明天…」（凌晨改过的）已经过了
            t += timedelta(days=1)  # 光说了几点、已经过了 → 明天这个点
        return t.timestamp()
    except (ValueError, OverflowError):
        return None


def advance(due, rep, tz=None, dom=None):
    """重复的下一次（同一个钟点）。dom：每月 / 每年的原来是几号（31 号过了二月还回到 31 号）"""
    tz = tz or BEIJING
    d = dt(due, tz)
    dd = d.day
    if dom and d.day == min(int(dom), monthrange(d.year, d.month)[1]):
        dd = int(dom)
    if rep == "daily":
        n = d + timedelta(days=1)
    elif rep == "weekdays":
        n = d + timedelta(days=1)
        while n.weekday() >= 5:
            n += timedelta(days=1)
    elif rep == "weekly":
        n = d + timedelta(days=7)
    elif rep == "monthly":
        y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
        n = d.replace(year=y, month=m, day=min(dd, monthrange(y, m)[1]))
    elif rep == "yearly":
        y = d.year + 1
        n = d.replace(year=y, day=min(dd, monthrange(y, d.month)[1]))
    else:
        return None
    return n.timestamp()


def next_after(due, rep, now, tz=None, dom=None):
    """重复的：下一个还没到的那次（机器人关了好几天，中间那几次就算了）"""
    n = advance(due, rep, tz, dom)
    for _ in range(4000):
        if n is None or n > now:
            return n
        n = advance(n, rep, tz, dom)
    return n


def first_weekday(due, tz=None):
    """工作日的第一次落在周末 → 顺延到周一（周五晚上说的「工作日早上叫我」，周六不叫）"""
    d = dt(due, tz or BEIJING)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.timestamp()
