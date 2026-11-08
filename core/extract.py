# -*- coding: utf-8 -*-
"""从机器人自己说出去的话里认它答应了什么（不依赖 AstrBot）。

两步：
  1. 便宜的规则先筛（prefilter，几条见下面）：要有明确的「提醒你 / 叫醒你」、或者时间词 + 要替他做的事、
     或者「回头 / 等会」+ 要做的事、或者它说自己要去睡 / 潜水 / 不理你。日常闲聊不筛，没筛中一分钱不花。
  2. 筛中了才调一次模型，让它把这句话抽成 JSON（build_system / build_prompt），再逐项核对（validate）：
     抄的原话得真在机器人那句里、时间得是原话里说了的、编号得是对方自己挂着的 —— 对不上的一律不进表。
     时间由 when.parse_when 算，模型只负责把说法抄出来（模型算日期常错）。
"""

import json
import re

from .hold import GONE, KINDS
from .table import ref_num
from .when import dom_of, dur, has_time, parse_when, repeat_of

# ───────── 1. 先筛 ─────────
# 只有这几种才调模型（README「会多花钱吗」写的就是这几条）：
#   a. 明确的「到点替你做」：提醒你 / 叫醒你 / 叫你起床 / 催你 / 定个闹钟（不用带时间）
#   b. 说了时间、又带着要替他做的事：「明天帮你问」「10 分钟后叫你」（光有时间不算：「明天见」）
#   c. 「回头 / 等会 / 到时候」+ 要替他做的事：「等会帮你查」「回头告诉你」（没说时间的答应）
#   d. 他要它到点做事（他的话里有时间 + 提醒我 / 叫我…），它答应了（「好」「记下了」）
#   e. 它说自己要走 / 不说 / 少说 / 不理 / 不发表情包（「你快去睡吧」「你睡了吗」说的是对方，不算）
#   f. 他有挂着的事、在说「不用了 / 改到几点」
# 「我告诉你个秘密」「记住了」「到时候再说」「我帮你看看」这种日常的话一律不调。
COMMIT = re.compile(r"提醒你|叫醒你|喊醒你|叫你起床|喊你起床|催你|定个闹钟|设个闹钟|定个提醒|设个提醒")
TIMED_DO = re.compile(r"提醒|叫你|喊你|叫醒|告诉你|通知你|催你|发你|发给你|找你|帮你|给你|带给你")
VAGUE_DO = re.compile(
    r"(?:等会|待会|一会儿?|回头|晚点|稍后|改天|下次|过会儿?|有空|到时候)\S{0,8}?(?:帮你|给你|告诉你|发你|跟你说|找你|提醒你|叫你|查|补|唱|讲|弄|做)"
)
AGREE = re.compile(r"好|行|嗯|可以|没问题|收到|记下|记住|放心|妥|包在我身上|一定|ok", re.I)
LEAVE = re.compile(
    r"睡了|睡觉了|睡觉去|去睡觉|去睡啦|先睡|要睡了|睡会儿|睡一会|眯一会|躺了|下线了|"
    r"潜水|潜了|先潜|不说了|不聊了|不说话了|闭嘴了|先撤|撤了|溜了|先走了|"
    r"去忙了|忙去了|去吃饭|吃饭去|去洗澡|洗澡去|出门了|"
    r"少说两句|少说几句|少说点|不插嘴|不插话|不理你|不想理你|不理他|不发表情|不发图|不斗图"
)
SECOND = re.compile(r"[你您他她]|大家")
CANCEL_EDIT = re.compile(
    r"不用(?:了|提醒|叫|喊|查|催)|别(?:提醒|叫|喊|催)|取消|算了|不需要|改(?:到|成|为|一下|时间)|推迟|提前|延后|往后|挪到|换个时间|晚点再|早点叫"
)
REQUEST = re.compile(r"提醒我|叫我|喊我|记得|到时候|帮我|告诉我|通知我|催我|别忘了|闹钟|定时|叫醒")
# 「那就不提醒了」「别叫你了」是不做，不是答应做：先去掉再看（他有挂着的事时，取消那条路另外会筛中）
NEG_COMMIT = re.compile(r"不(?:用|再|会|必)?(?:提醒|叫|喊|催)|别(?:再)?(?:提醒|叫|喊|催)")


def _self_leave(b):
    """它说的是自己要走 / 不说 / 不理（说对方的、问句不算）"""
    for m in LEAVE.finditer(b):
        pre, post = b[max(0, m.start() - 3) : m.start()], b[m.end() : m.end() + 2]
        if re.match(r"\s*(?:吗|么|没|\?|？)", post):
            continue  # 「你睡了吗」「潜水了？」是在问
        if SECOND.search(pre):
            continue  # 「你快去睡吧」「你少说两句」「他溜了」说的是别人（「我不理你了」的「你」在词里面，不受影响）
        return True
    return False


def prefilter(bot, user="", has_mine=False, tasks=True, holds=True):
    """→ (要不要调模型, 为什么)。tasks / holds：到点的事、约束这两块开没开（关着的那块的词不筛，省一次调用）"""
    b, u = str(bot or ""), str(user or "")
    if not b.strip():
        return False, ""
    if holds and _self_leave(b):
        return True, "说了自己要走 / 不说 / 不理 / 不发"
    if not tasks:
        return False, ""
    b2 = NEG_COMMIT.sub(" ", b)
    if COMMIT.search(b2):
        return True, "答应了到点替他做（提醒 / 叫醒 / 催）"
    if has_time(b) and TIMED_DO.search(b2):
        return True, "说了时间、带着要替他做的事"
    if VAGUE_DO.search(b2):
        return True, "没说时间的答应（回头 / 等会 + 要做的事）"
    if REQUEST.search(u) and has_time(u) and AGREE.search(b2):
        return True, "他要它到点做事、它答应了"
    if has_mine and (CANCEL_EDIT.search(u) or CANCEL_EDIT.search(b)):
        return True, "他在改 / 取消挂着的事"
    return False, ""


# ───────── 2. 抽 ─────────
SYSTEM = """你是记录员：帮一个 QQ 聊天机器人记下它自己说出口、之后要兑现的事，交给程序去执行。
你会看到现在的时间、对方刚说的话、机器人回的话、对方还挂着的事（带编号）。只看「机器人回的话」里机器人自己答应 / 宣布的事。
只输出一个 JSON 对象，不要别的字：{"items": [...]}；没有就输出 {"items": []}。

每一项是下面五种之一：
1. 到点去做的事（机器人答应在某个时间提醒 / 叫 / 告诉对方）：
   {"type": "task", "what": "到点要做什么，写清楚，比如：提醒他交作业", "when": "时间，照抄原话里的说法，比如：明天早上8点 / 10分钟后 / 每天晚上11点", "repeat": "每天|工作日|每周|每月|每年，不重复就写空字符串", "via": "对方要求私聊才写 私聊，否则写空字符串", "quote": "机器人原话里答应这件事的那几个字，照抄"}
2. 没说时间的答应（等会帮你查 / 回头告诉你）：
   {"type": "promise", "what": "答应了什么，写清楚", "quote": "照抄"}
3. 取消对方挂着的某件事（对方说不用了，机器人也答应了）：
   {"type": "cancel", "id": 编号, "quote": "照抄"}
4. 改对方挂着的某件事：
   {"type": "edit", "id": 编号, "when": "新的时间，照抄原话；不改时间写空字符串", "shift_min": 推迟写正的分钟数、提前写负的，没有写 0, "what": "新的内容；不改写空字符串", "quote": "照抄"}
5. 机器人说自己接下来一段时间要怎样：
   {"type": "hold", "kind": "sleep|away|lurk|quiet|ignore|nosticker", "minutes": 说了多久就写分钟数，没说写 null, "quote": "照抄"}
   sleep=它去睡觉；away=它离开、去忙、去吃饭、去洗澡；lurk=它潜水、不说话了；quiet=它少说两句、少插嘴；ignore=它不理对方了；nosticker=它不发表情包了

规矩：
- 只算机器人自己要做的。叫对方去做的、跟对方道晚安、叫对方快去睡、转述别人、开玩笑的反话、问句（要不要我提醒你）、假设，都不算。
- 时间只能来自原话（对方的话或机器人的话），不许自己推算或编；原话里没有明确时间的答应写成 promise。
- 只能取消 / 修改「对方挂着的事」里列出来的编号；对不上就不写。
- ignore 只算不理正在说话的这个人。只说这一次不发表情包的，不算 nosticker。
- 拿不准就不写。"""


def build_prompt(now_text, scene, name, user, bot, mine_lines):
    return (
        f"现在：{now_text}\n"
        f"在哪：{'群聊' if scene == 'group' else '私聊'}\n"
        f"对方（{str(name or '对方')[:20]}）刚说：「{str(user or '')[-300:]}」\n"
        f"机器人回：「{str(bot or '')[:600]}」\n"
        "对方挂着的事：\n" + ("\n".join(mine_lines) if mine_lines else "没有")
    )


def parse(raw):
    """模型的回答 → items 列表；看不懂 → None"""
    s = re.sub(r"<(think|thinking)>.*?</\1>", "", str(raw or ""), flags=re.S | re.I)
    s = re.sub(r"```(?:json)?", "", s)
    m = re.search(r"\{.*\}|\[.*\]", s, re.S)
    if not m:
        return None
    try:
        js = json.loads(m.group(0))
    except ValueError:
        return None
    if isinstance(js, dict):
        js = js.get("items")
    return js if isinstance(js, list) else None


# ───────── 3. 核对 ─────────
TYPE_ALIAS = {
    "提醒": "task",
    "到点": "task",
    "定时": "task",
    "答应": "promise",
    "取消": "cancel",
    "改": "edit",
    "改时间": "edit",
    "约束": "hold",
}
KIND_ALIAS = {
    "睡觉": "sleep",
    "睡": "sleep",
    "离开": "away",
    "走开": "away",
    "潜水": "lurk",
    "少说": "quiet",
    "不理": "ignore",
    "不发表情包": "nosticker",
    "不发表情": "nosticker",
}
NOT_LEAVING = re.compile(r"不(?:睡|走|离开|下线|潜|撤|溜)|(?:睡|走|撤)不了|还不睡|睡不着")
ONE_SHOT = re.compile(r"这轮|这次|这一条|这条|这张|这回")
STICKER_SAY = re.compile(r"表情|图|斗图|贴纸")
DUR_SAID = re.compile(r"(?:\d+(?:\.\d+)?|半|[一二两三四五六七八九十]+)\s*个?\s*半?\s*(?:分钟|分|小时|钟头|天)")
PRIVATE_SAID = re.compile(r"私聊|私信|单独|小窗")


def _norm(s):
    return re.sub(r"[\s\W_]+", "", str(s or "")).lower()


def _bigrams(s):
    return {s[i : i + 2] for i in range(len(s) - 1)}


def said(quote, text):
    """模型抄的那句真在原话里（允许它抄得不太准：四个字以上的，六成的两字词对得上就算）"""
    q, t = _norm(quote), _norm(text)
    if not q:
        return False
    if q in t:
        return True
    if len(q) < 4:
        return False
    qb = _bigrams(q)
    return len(qb & _bigrams(t)) >= 0.6 * len(qb)


def _clean(x, n=120):
    return re.sub(r"\s+", " ", str(x or "")).strip()[:n]


def validate(items, bot, user, now, tz=None, mine=()):
    """模型抽出来的 → (要做的动作, 不要的 [(那项, 为什么, 要不要告诉模型)])。
    mine：对方自己挂着的编号（取消 / 改只认这些）"""
    acts, rej = [], []
    origin = f"{user or ''} {bot or ''}"
    mine = {int(x) for x in mine or ()}
    for it in list(items or [])[:6]:
        if not isinstance(it, dict):
            rej.append((it, "格式不对", False))
            continue
        typ = str(it.get("type") or "").strip().lower()
        typ = TYPE_ALIAS.get(typ, typ)
        quote = _clean(it.get("quote"), 80)
        if typ in ("task", "promise", "hold") and not said(quote, bot):
            rej.append((it, "它抄的那句在机器人的话里找不到", False))
            continue
        if typ == "task":
            what = _clean(it.get("what"))
            if not what:
                rej.append((it, "没写到点做什么", False))
                continue
            when = _clean(it.get("when"), 60)
            if not has_time(origin):
                # 原话里根本没说时间（模型自己编的）→ 不当成到点的事，当成没说时间的答应
                acts.append({"op": "promise", "what": what, "quote": quote, "why": "原话里没说时间"})
                continue
            due = parse_when(when, None, now, tz) if when else None
            if due is None:
                due = parse_when(bot, None, now, tz) or parse_when(user, None, now, tz)
            if due is None:
                rej.append((it, f"时间没看懂（{when or '没写'}）", True))
                continue
            if due < now - 60:
                rej.append((it, "那个时间已经过了", True))
                continue
            if due > now + 400 * 86400:
                rej.append((it, "时间太远了", True))
                continue
            rep = repeat_of(it.get("repeat")) or repeat_of(when)
            if rep and repeat_of(origin) != rep:
                rep = None  # 原话里没说「每天 / 每周」→ 只做一次（不然模型多写一个字就天天发）
            via = "private" if "私" in str(it.get("via") or "") and PRIVATE_SAID.search(origin) else ""
            acts.append(
                {
                    "op": "task",
                    "what": what,
                    "due": due,
                    "repeat": rep,
                    "via": via,
                    "quote": quote,
                    "when": when,
                    "dom": dom_of(when) if rep in ("monthly", "yearly") else None,
                }
            )
        elif typ == "promise":
            what = _clean(it.get("what"))
            if not what:
                rej.append((it, "没写答应了什么", False))
                continue
            acts.append({"op": "promise", "what": what, "quote": quote})
        elif typ in ("cancel", "edit"):
            n = ref_num(it.get("id") if it.get("id") is not None else it.get("n"))
            if n is None or n not in mine:
                rej.append((it, f"编号 {it.get('id')} 不是他挂着的", False))
                continue
            if typ == "cancel":
                acts.append({"op": "cancel", "n": n, "quote": quote})
                continue
            when = _clean(it.get("when"), 60)
            due = None
            if when:
                if not has_time(origin):
                    rej.append((it, "新的时间原话里没说", False))
                    continue
                due = parse_when(when, None, now, tz)
                if due is None:
                    rej.append((it, f"新的时间没看懂（{when}）", True))
                    continue
            try:
                shift = float(it.get("shift_min") or 0)
            except (TypeError, ValueError):
                shift = 0.0
            if shift and (abs(shift) > 7 * 1440 or not DUR_SAID.search(origin)):
                shift = 0.0  # 推迟多久原话里没说 → 不推
            what = _clean(it.get("what"))
            if due is None and not shift and not what:
                rej.append((it, "没说改成什么", False))
                continue
            acts.append({"op": "edit", "n": n, "due": due, "shift": shift, "what": what, "quote": quote})
        elif typ == "hold":
            kind = str(it.get("kind") or "").strip().lower()
            kind = KIND_ALIAS.get(kind, kind)
            if kind not in KINDS:
                rej.append((it, f"不认识的约束「{kind}」", False))
                continue
            if kind in GONE and NOT_LEAVING.search(quote):
                rej.append((it, "说的是不走 / 不睡", False))
                continue
            if kind == "nosticker" and (ONE_SHOT.search(quote) or not STICKER_SAY.search(quote)):
                rej.append((it, "只说这一次、或者没提表情包", False))
                continue
            mins = it.get("minutes")
            mins = dur(mins) if mins not in (None, "", 0, "0", "null") else None
            if mins and not DUR_SAID.search(str(bot or "")):
                mins = None  # 它没说多久、模型自己写了个数 → 按默认
            acts.append({"op": "hold", "kind": kind, "minutes": mins, "quote": quote})
        else:
            rej.append((it, f"不认识的种类「{typ}」", False))
    return acts, rej
