# -*- coding: utf-8 -*-
"""指令 /说到做到 的回话（不依赖 AstrBot，单测直接用）。

隐私：群里发的指令只列这个群的事，不带 QQ 号；跨对话的列表（别的群、别人私聊里答应的）只在私聊里给管理员看。
在群里取消一件别处答应的事，回话里不带它的内容（不然私聊里的提醒会被贴进群）。
"""

from .clock import fmt, span, when_text
from .hold import KINDS
from .table import is_group, ref_num, seen_in
from .when import REPEAT_TEXT

CMD = "说到做到"


def where_label(conv):
    p = str(conv or "").split(":")
    if len(p) >= 3 and p[1] == "GroupMessage":
        return f"群 {p[2]}"
    if len(p) >= 3 and p[1] == "FriendMessage":
        return f"私聊 {p[2]}"
    return str(conv or "")


def item_line(t, now, tz):
    if t.get("kind") == "promise":
        return f"#{t['n']} 没说时间：{t['what']}"
    return (
        f"#{t['n']} {when_text(t['due'], now, tz)} {t['what']}"
        + (f"（{REPEAT_TEXT[t['repeat']]}）" if t.get("repeat") in REPEAT_TEXT else "")
        + f" → {'私聊' if t.get('via') == 'private' or t.get('scene') != 'group' else '群里 @'}"
    )


def _order(t):
    return (t.get("kind") != "task", float(t.get("due") or 0), t.get("n", 0))


def run(op, arg, *, table, holds, conv, uid, name, admin, now, tz, label):
    """→ (回话, 要记进「最近发生的」的那一句 / None)"""
    op, arg, uid = str(op or "").strip(), str(arg or "").strip(), str(uid)
    group = is_group(conv)
    if op in ("取消", "cancel", "删", "删除"):
        n = ref_num(arg)
        t = table.find(n) if n is not None else None
        if t is None or t.get("status") != "pending":
            return f"没找到还没做的 #{arg or '?'}（用法：/{CMD} 取消 <编号>，编号看 /{CMD}）", None
        if not table.can_edit(t, uid, admin):
            return f"#{t['n']} 不是你的：只有本人或管理员能取消。", None
        table.cancel(t, f"{name or uid}（指令）", now)
        if seen_in(t.get("conv"), conv):
            return f"好，#{t['n']} 取消了：{t['what']}", f"#{t['n']} 用指令取消了"
        return f"好，#{t['n']} 取消了（是在别处答应的，内容不在这儿说）。", f"#{t['n']} 用指令取消了"
    if op in ("全部", "all"):
        if not admin:
            return "只有管理员能看全部。", None
        if group:
            pend = sorted((t for t in table.pending(kind=None) if t.get("conv") == conv), key=_order)
            lines = [f"{item_line(t, now, tz)}（{t.get('who_name') or '某人'}）" for t in pend[:30]]
            lines += [
                f"约束：{KINDS[h['kind']][0]}「{h['say'][:20]}」还有 {span(float(h['until']) - now)}" for h in holds.live(conv, now)
            ]
            head = "这个群还没做的：\n" if lines else "这个群现在没有还没做的事，也没有正在生效的约束。\n"
            return head + "\n".join(lines) + ("\n" if lines else "") + f"别的群和私聊里的：请私聊我发 /{CMD} 全部", None
        pend = sorted(table.pending(kind=None), key=_order)
        lines = [f"{item_line(t, now, tz)}（{t.get('who_name') or t.get('who')} {t.get('who')}，{where_label(t.get('conv'))}）" for t in pend[:40]]
        live = holds.snapshot(now)["live"]
        lines += [f"约束：{where_label(h['conv'])} {h['name']}「{h['say'][:20]}」还有 {h['left_min']} 分钟" for h in live[:20]]
        return ("全部还没做的：\n" + "\n".join(lines)) if lines else "现在没有还没做的事，也没有正在生效的约束。", None
    if op in ("叫醒", "wake"):
        if not admin:
            return "只有管理员能叫醒。", None
        n = holds.release(conv=conv, by=name or uid, now=now)
        return (f"好，这里的 {n} 条约束结束了。", f"{where_label(conv)} 管理员用指令让它回来了") if n else ("这里没有正在生效的约束。", None)
    if op:
        return f"用法：/{CMD}（看机器人答应你的事）· /{CMD} 取消 <编号>" + (f" · /{CMD} 全部 · /{CMD} 叫醒" if admin else ""), None
    here = sorted(
        (t for t in table.pending(kind=None) if str(t.get("who")) == uid and seen_in(t.get("conv"), conv)), key=_order
    )
    past = [
        t
        for t in table.tasks
        if str(t.get("who")) == uid and t.get("status") in ("done", "missed") and seen_in(t.get("conv"), conv)
    ][-3:]
    lines = [item_line(t, now, tz) for t in here[:12]]  # 群里只列这个群的；私聊里还有他在各个群里的（群里本来就看得到）
    if past:
        lines.append("最近：" + "；".join(f"#{t['n']} {t['what'][:16]}（{'做了' if t['status'] == 'done' else '没做成'}）" for t in past))
    live = holds.live(conv, now)
    if live:
        lines.append(
            "这里正在生效的：" + "；".join(f"{KINDS[h['kind']][0]}「{h['say'][:16]}」还有 {span(float(h['until']) - now)}" for h in live)
        )
    head = f"机器人答应你的事（{label}，现在 {fmt(now, tz, '%H:%M')}）：\n" if here else "机器人在这儿没有答应你、还没做的事。\n"
    tail = f"\n取消：/{CMD} 取消 <编号>" + (f"；管理员：/{CMD} 全部 · /{CMD} 叫醒" if admin else "")
    return head + "\n".join(lines) + tail, None
