# -*- coding: utf-8 -*-
"""给模型看的文字（不依赖 AstrBot）。

规矩（鱼力max E1）：插件只给事实 / 状态 / 规矩，怎么说由模型自己定 —— 这里不写示范句、不写「你可以说……」、
不定语气。插件自己直接发出去的只有一种：模型叫不通时的那句「（系统提示）到点了：……」，能关。
"""

import re

from .clock import fmt, now_text, span, when_text
from .hold import KINDS, VERB
from .when import REPEAT_TEXT

HEAD = "# 说到做到（插件记的状态，不是谁说的话）"
CAN = (
    "- 插件能替你做到的：说清楚时间的提醒（几点 / 几分钟后 / 每天几点），到点会以你的口吻在这里发一条（群里 @ 他；他要私聊就私聊）。"
    "做不到的：打电话、转账、替人私聊别人、去别的群发消息；没说时间的「等会 / 回头」不会到点自己去做。"
)
# 他这句像在要它答应点什么：才把「能做到什么」那行带上（每轮都带太费 token）
ASKING = re.compile(
    r"提醒|叫我|喊我|记得|到时候|帮我|告诉我|通知|催我|别忘|闹钟|定时|几点|明天|明早|今晚|等会|待会|一会|回头|"
    r"打电话|转账|私聊|私信|告诉他|跟他说|转告"
)


def _where(t):
    return "私聊发给他" if t.get("via") == "private" else ("在这里 @ 他" if t.get("scene") == "group" else "私聊发给他")


def turn_block(state, holds, backs, now, tz, label, uid, user_text="", always_can=False, ai_name=""):
    """这一轮给模型的临时段 → (文字, 给它看了哪些)。没东西可说 → ("", {})
    ai_name：说话的这个是认 AI 插件认出来的别人家的 AI（跟它约的事插件不记）"""
    lines = []
    shown = {"apo": [], "prom": [], "notes": [], "backs": []}
    st = state or {}
    asking = bool(ASKING.search(str(user_text or "")))
    if ai_name and asking:
        lines.append(f"- 「{ai_name}」是别人家的 AI（认 AI 插件认出来的）：跟它约的事插件不记、不会到点去做")
    for t in st.get("here") or []:
        lines.append(
            f"- 你答应他的、还没做的 #{t['n']}：{when_text(t['due'], now, tz)}（{label}）{t['what']}"
            + (f"（{REPEAT_TEXT[t['repeat']]}）" if t.get("repeat") in REPEAT_TEXT else "")
            + f" —— 到点插件以你的口吻{_where(t)}"
            + ("（这次到点没发出去，正在补）" if t.get("tries") else "")
        )
    if st.get("elsewhere"):
        lines.append(f"- 你在别的地方还答应过他 {st['elsewhere']} 件到点的事（不是在这儿答应的，内容不在这儿说）")
    for t in st.get("done") or []:
        last = (t.get("hist") or [{}])[-1]
        lines.append(f"- #{t['n']}「{t['what']}」：{fmt(last.get('at') or now, tz, '%H:%M')} 已经按约定{_where(t)}发过了")
    for t in st.get("apology") or []:
        lines.append(
            f"- 你答应他的 #{t['n']}「{t['what']}」（{fmt(t.get('apo_for') or t.get('due') or now, tz)}）没做成"
            f"（{t.get('apo_why') or '没发出去'}）：还欠他一个道歉，还没跟他说过"
        )
        shown["apo"].append(t["n"])
    for p in st.get("promises") or []:
        lines.append(
            f"- 你 {span(now - float(p.get('created') or now))}前答应过他「{p['what']}」（没说时间，插件不会到点去做）"
            + (f"；他当时说「{p['ask'][-40:]}」" if p.get("ask") else "")
        )
        shown["prom"].append(p["n"])
    for x in st.get("notes") or []:
        lines.append(f"- {x['text']}")
        shown["notes"].append(x["id"])
    if st.get("full"):
        lines.append(f"- 他已经挂着 {st['full']} 件到点的事（满了），再答应新的会记不上")
    for r in holds or []:
        h = KINDS.get(r.get("kind"), ("", ""))[1]
        ago, left = span(now - float(r["t0"])), span(float(r["until"]) - now)
        if h == "direct":
            lines.append(f"- 你 {ago}前在这里说了「{r.get('say')}」（少说）：还有 {left}，这期间没 @ 你的话插件不让你回")
        elif h == "person" and r.get("who") != str(uid):
            lines.append(f"- 你 {ago}前说了「{r.get('say')}」，正晾着「{r.get('who_name') or '他'}」（还有 {left}）：他的话插件不让你回")
        elif h == "mod":
            lines.append(f"- 你 {ago}前说了「{r.get('say')}」：还有 {left}，这期间你发的表情包会被插件拿掉")
    for b in backs or []:
        lines.append(back_line(b, now))
        shown["backs"].append(b)
    if lines or always_can or asking:
        lines.append(CAN)
    if not lines:
        return "", {}
    return HEAD + f"\n现在 {now_text(now, tz, label)}。\n" + "\n".join(lines), shown


def back_line(b, now):
    k = b.get("kind")
    gone = span(float(b.get("end") or now) - float(b.get("t0") or now))
    if k == "ignore":
        return f"- {span(now - float(b.get('t0') or now))}前你说了「{b.get('say')}」，晾了「{b.get('who_name') or '他'}」{gone}，现在结束了"
    if b.get("how") == "woke":
        how = f"是「{b.get('by') or '有人'}」" + ("（管理员）" if b.get("by_admin") else "") + "叫回来的"
    elif b.get("how") == "off":
        how = "是管理员让你回来的"
    else:
        how = "到点自己醒的" if k == "sleep" else "到点自己回来的"
    n = int(b.get("n") or 0)
    return (
        f"- 你刚回来：{span(now - float(b.get('t0') or now))}前你在这里说了「{b.get('say')}」，然后真的{VERB.get(k, '走开了')}"
        f"（{gone}）；{how}" + (f"；这期间这里有 {n} 条要回的消息你没回" if n else "")
    )


def speak_prompt(t, now, tz, label, late=0.0, late_why="", gone=None):
    """到点了：给模型这一件事的状态，让它自己写要发的那句（插件负责发、负责 @）"""
    nm = t.get("who_name") or "他"
    created = float(t.get("created") or now)
    lines = [
        f"现在是 {now_text(now, tz, label)}。",
        f"你 {fmt(created, tz)}（{span(now - created)}前）在{'群里' if t.get('scene') == 'group' else '私聊里'}答应了「{nm}」：{t['what']}"
        + (f"（{REPEAT_TEXT[t['repeat']]}都要做）" if t.get("repeat") in REPEAT_TEXT else "")
        + "。",
    ]
    if t.get("ask"):
        lines.append(f"他当时说：「{t['ask']}」")
    if t.get("say"):
        lines.append(f"你当时回的：「{t['say']}」")
    via = t.get("via") == "private" or t.get("scene") != "group"
    lines.append("现在到点了。插件会把你写的这句" + ("私聊发给他。" if via else "发到那个群里，前面自动 @ 他。"))
    if late >= 120:
        lines.append(f"已经晚了 {span(late)}（{late_why or '那会儿没发出去'}）。")
    if gone:
        lines.append(
            f"你这会儿在{KINDS.get(gone.get('kind'), ('', ''))[0]}（{span(now - float(gone.get('t0') or now))}前你说了「{gone.get('say')}」），"
            f"发完这句插件接着替你{KINDS.get(gone.get('kind'), ('', ''))[0]}。"
        )
    lines.append("只写要发出去的那句话本身：不加引号、不加说明、不写 @。")
    return "\n".join(lines)


def fallback_line(t, tz):
    """模型叫不通时插件自己发的（系统口吻，能关）"""
    return f"（系统提示）到点了：{t['what']}（{fmt(float(t.get('created') or 0), tz)} 答应的）"


def clean_line(text, max_chars=300):
    """模型写的那句 → 能发的（去掉思考、引号、自己写的 @、[[不说]]）；空的 → ""。"""
    s = re.sub(r"<(think|thinking)>.*?</\1>", "", str(text or ""), flags=re.S | re.I)
    s = s.replace("[[不说]]", "")
    lines = [x.strip() for x in s.splitlines() if x.strip()]
    s = "\n".join(lines[:4]).strip()
    s = re.sub(r"^(?:@\S+\s*)+", "", s).strip()
    s = s.strip("「」\"'“” ")
    if len(s) > max_chars:
        s = s[:max_chars].rstrip("，,、 ") + "…"
    return s
