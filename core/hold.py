# -*- coding: utf-8 -*-
"""一段时间的约束（不依赖 AstrBot）：机器人说了「我去睡了 / 先潜水 / 不说了 / 不理你了 / 不发表情包了」，就在那个对话里真的做到。

每个群、每个私聊各算各的：在 A 群说了要睡，B 群和私聊照常。

走多久：
  - 它自己说了多久就按说的（3 分钟 ~ 12 小时）。
  - 没说：按种类给默认（配置里改），±15% 随机（真人哪有掐着表回来的）。
  - 睡觉：夜里（默认 23 点到早上 8 点）说要睡 = 睡到早上 8 点左右；白天说要睡 = 小睡（默认 30 分钟）。
  作者自己的机器人原来还按「这个对话最近 30 分钟多热闹、它是不是话题中心、最近食言过几次」去伸缩时长，
  插件里简化掉了（每个群的热闹程度差太多，默认值不好定），只留基础时长。

叫醒（只管睡觉 / 离开 / 潜水这三种「人不在」的）：
（11-10 v0.1.1 审查 VP1-15）默认档 wake_mode = soft「有人找就醒」：它说了去睡 / 离开 / 潜水以后不接没叫它的话，
  但有人 @ 它 / 叫它 / 私聊它，马上算叫醒、这条照常回（刚说完那几分钟里只回一句「晚安 / 好的」的不算；别人家的 AI 叫不醒）。
  以前（0.1.0）默认是下面这套「一直叫才醒」：夜里一句「我去睡了」整个群到早上谁 @ 都不回、被挡的人也没有任何提示，
  装在别人的机器人上像是插件把机器人搞坏了；作者自己的机器人早就改成有人找就醒了。
  下面这套留成可选的硬睡档 wake_mode = hard；硬睡档第一次挡住找它的人要说一声（gate 返回 tell，main.py 发一句固定的系统提示；
  同一个人在它说的那个回来的时间之前只提示一次）：
  - 管理员 @ 它够次数（默认 2 次）→ 醒；
  - 群里几分钟里（默认 5 分钟）被够多不同的真人 @（默认 3 个人）→ 醒；
  - 私聊里他几分钟里连着发够条数（默认 3 条）→ 醒；
  - 刚说完的头几分钟（默认 2 分钟）只有管理员叫得醒；这几分钟里回一句「晚安 / 好的 / 嗯」不算叫它（不然晚安来回停不下来）；
  - 别人家的 AI 叫不醒（认 AI 插件认出来的）。
醒了 / 到点了：下次在这个对话里说话时告诉模型「N 分钟前你说了『…』然后真的去睡了，谁叫醒的」。
"""

import random
import re
from datetime import timedelta

from .clock import dt, fmt, span

# kind → (给人看的名字, 挡什么)
#   all = 这个对话里一句都不回（v0.1.1 默认档：没叫它的不接、找它的就把它叫醒，见上面「叫醒」）/ direct = 只回 @ 它的 /
#   person = 只不回那一个人 / mod = 不发某种东西
KINDS = {
    "sleep": ("睡觉", "all"),
    "away": ("离开", "all"),
    "lurk": ("潜水", "all"),
    "quiet": ("少说", "direct"),
    "ignore": ("不理", "person"),
    "nosticker": ("不发表情包", "mod"),
}
GONE = ("sleep", "away", "lurk")
VERB = {"sleep": "去睡了", "away": "走开了", "lurk": "潜水了"}
DEFAULTS = {
    "enable": True,
    "sleep_nap_min": 30,  # 白天说要睡 = 小睡几分钟（0 = 不管「睡觉」）
    "night_from": 23,  # 夜里从几点算起
    "wake_hour": 8,  # 夜里说要睡 → 睡到几点
    "away_min": 45,
    "lurk_min": 25,
    "quiet_min": 30,
    "ignore_min": 8,
    "nosticker_min": 90,
    "stated_max_min": 720,
    "wake_admin_ats": 2,
    "wake_people": 3,
    "wake_window_min": 5,
    "wake_private_msgs": 3,
    "wake_floor_min": 2,
    "wake_mode": "soft",  # （11-10 v0.1.1）soft = 有人找就醒（默认）/ hard = 硬睡：一直叫才醒
}
JITTER = 0.15
BACK_HOURS = 12  # 「你刚回来」那句：回来以后这么久都没人跟它说话 → 作废
# 刚说完要睡的那几分钟里，对方只是应一声（晚安、好的、发个表情）—— 不算叫它
BYE = re.compile(
    r"^(?:[\W_]*(?:晚安+(?:啦|呀|哦|安)?|安安|好梦|做个好梦|睡吧|快睡吧?|去睡吧|早点睡|早睡|拜拜|再见|bye|88+6?|嗯+|好+的?|好哒|ok|行|"
    r"知道了|去吧|\[表情\]|\[图片\]|\[动画表情\])[\W_]*)+$",
    re.I,
)


class Holds:
    def __init__(self, data, tz=None, conf=None, log=None, rng=None):
        self.d = data if isinstance(data, dict) else {}
        for k, v in (("holds", []), ("hist", []), ("backs", [])):
            if not isinstance(self.d.get(k), list):
                self.d[k] = v
        if not isinstance(self.d.get("told"), dict):  # （11-10 v0.1.1）硬睡档告诉过谁：{对话|QQ: 告诉他的那个「几点回来」}
            self.d["told"] = {}
        self.tz = tz
        self.c = dict(DEFAULTS)
        self.configure(conf)
        self.log = log or (lambda m: None)
        self.rng = rng or random.Random()
        self.dirty = False

    def configure(self, conf=None):
        for k, v in (conf or {}).items():
            if k in DEFAULTS and v is not None:
                self.c[k] = type(DEFAULTS[k])(v)

    def soft(self):
        """（11-10 v0.1.1）有人找就醒（默认）。只有明确填了 hard 才是硬睡；没填 / 填了别的 → 默认"""
        return str(self.c.get("wake_mode") or "").strip().lower() != "hard"

    def kind_on(self, kind):
        if not self.c["enable"] or kind not in KINDS:
            return False
        key = "sleep_nap_min" if kind == "sleep" else f"{kind}_min"
        return float(self.c.get(key) or 0) > 0

    # ───────── 走多久 ─────────
    def in_night(self, now):
        nf, wh = int(self.c["night_from"]) % 24, int(self.c["wake_hour"]) % 24
        if nf == wh:
            return False
        h = dt(now, self.tz).hour
        return (h >= nf or h < wh) if nf > wh else (nf <= h < wh)

    def plan(self, kind, stated=None, now=0.0):
        """→ (秒, 怎么算的)"""
        if stated:
            m = max(3.0, min(float(self.c["stated_max_min"]), float(stated)))
            return m * 60 * (1 + self.rng.uniform(-0.05, 0.05)), f"它自己说的 {round(float(stated))} 分钟"
        if kind == "sleep" and self.in_night(now):
            d = dt(now, self.tz)
            w = d.replace(hour=int(self.c["wake_hour"]) % 24, minute=0, second=0, microsecond=0)
            if w.timestamp() <= now:
                w += timedelta(days=1)
            until = w.timestamp() + self.rng.uniform(0, 10) * 60
            sec = max(180.0, until - now)
            return sec, f"夜里说要睡 → 睡到 {fmt(now + sec, self.tz, '%H:%M')} 左右"
        base = float(self.c["sleep_nap_min"] if kind == "sleep" else self.c.get(f"{kind}_min") or 30)
        sec = base * 60 * (1 + self.rng.uniform(-JITTER, JITTER))
        return sec, ("白天说要睡 = 小睡" if kind == "sleep" else "没说多久，按默认") + f" {round(base)} 分钟"

    # ───────── 记一条 ─────────
    def declare(self, conv, umo, scene, kind, say, stated=None, who="", who_name="", now=0.0):
        """→ (那条, "") / (None, 为什么没记)"""
        if not self.kind_on(kind):
            return None, f"「{KINDS.get(kind, (kind,))[0]}」这一种没开"
        hold = KINDS[kind][1]
        if hold == "person" and not who:
            return None, "认不出不理谁"
        for r in self.live(conv, now):
            # 同一种的换成新的；睡觉 / 离开 / 潜水是同一类「人不在」，一个对话里只留最新的一条
            same = r["kind"] == kind and (hold != "person" or r.get("who") == str(who))
            if same or (kind in GONE and r["kind"] in GONE):
                self._drop(r)
        sec, why = self.plan(kind, stated, now)
        self.d["seq"] = int(self.d.get("seq") or 0) + 1
        rec = {
            "id": f"h{self.d['seq']}",
            "kind": kind,
            "conv": str(conv),
            "umo": str(umo or conv),
            "scene": "group" if scene == "group" else "private",
            "say": str(say or "")[:60],
            "t0": float(now),
            "until": float(now) + sec,
            "plan": why,
            "who": str(who or "") if hold == "person" else "",
            "who_name": str(who_name or "")[:20] if hold == "person" else "",
            "calls": [],
            "n": 0,
        }
        self.d["holds"].append(rec)
        self.dirty = True
        self.log(
            f"{conv} 机器人说「{rec['say'][:30]}」→ 真的{KINDS[kind][0]}"
            + (f"（不理「{rec['who_name'] or rec['who']}」）" if hold == "person" else "")
            + f" {span(sec)}（{why}）"
        )
        return rec, ""

    def _drop(self, rec):
        if rec in self.d["holds"]:
            self.d["holds"].remove(rec)
            self.dirty = True

    # ───────── 查 ─────────
    def live(self, conv, now):
        """这个对话里正在生效的。约束总开关关了、或者这一种的时长填了 0：已经记着的也不挡
        （挡消息、发送前复查、表情包、每轮的状态都走这里，所以关掉马上照常回）"""
        return [
            r
            for r in self.d["holds"]
            if r.get("conv") == str(conv) and float(r.get("until") or 0) > now and self.kind_on(r.get("kind"))
        ]

    def has(self, conv, kind, now):
        return next((r for r in self.live(conv, now) if r["kind"] == kind), None)

    def gone(self, conv, now):
        """这个对话里它是不是「人不在」（睡觉 / 离开 / 潜水）→ 那条 / None"""
        return next((r for r in self.live(conv, now) if r["kind"] in GONE), None)

    # ───────── 每条要回的消息过一下 ─────────
    def gate(self, conv, scene, uid, name, directed, admin=False, ai=False, text="", now=0.0):
        """→ {"block": 不回, "woke": 被这条叫醒的那条, "why", "rec"}
        directed：这条在找它（群里 @ / 引用 / 叫名字；私聊每条都算）—— 只有这种才算叫它"""
        out = {"block": False, "woke": None, "why": "", "rec": None}
        uid = str(uid)
        for rec in self.live(conv, now):
            hold = KINDS[rec["kind"]][1]
            if hold == "all":
                self.dirty = True
                if directed and not ai:
                    early = now - float(rec["t0"]) < float(self.c["wake_floor_min"]) * 60
                    bye = early and not admin and bool(BYE.match(str(text or "").strip()))
                    if not bye:
                        rec["calls"] = (rec.get("calls") or [])[-39:] + [
                            {"uid": uid, "name": str(name or "")[:20], "ts": float(now), "admin": bool(admin), "text": str(text or "")[:60]}
                        ]
                    if self.soft():  # （11-10 v0.1.1 审查 VP1-15）默认：有人找它就醒（刚说完时只回一句晚安的不算）
                        woke, why = (False, "刚说完时回的「晚安 / 好的」不算找它") if bye else (True, "有人找它就醒")
                    else:
                        woke, why = self._wake(rec, scene, now)
                    if woke:
                        self.end(rec, now, "woke", by=name or uid, by_admin=admin, why=why)
                        out["woke"], out["why"] = rec, why
                        continue
                    out["why"] = why
                    if not bye and not self.soft() and self._tell(rec, uid, now):
                        out["tell"] = True  # 硬睡档：第一次挡住找它的这个人 → 让 main.py 说一声
                elif directed and ai:
                    out["why"] = "别人家的 AI 叫不醒"
                rec["n"] = int(rec.get("n") or 0) + 1  # 它错过了几条（叫醒它的那条不算：那条照常回）
                out["block"], out["rec"] = True, rec
            elif hold == "person" and uid == rec.get("who"):
                out["block"], out["rec"], out["why"] = True, rec, "说了不理他"
            elif hold == "direct" and not directed and not out["block"]:
                out["block"], out["rec"], out["why"] = True, rec, "说了少说：没 @ 它的不回"
        return out

    def would_block(self, conv, uid, directed, now, ai=False):
        """只看不记：这一条现在该不该回（发送前复查用：它刚说了要走，还在路上的那条回复别发了）→ 挡它的那条 / None
        （11-10 v0.1.1）默认档（有人找就醒）：还在路上的那条是回找它的人的（不是别人家的 AI）→ 照常发"""
        for rec in self.live(conv, now):
            hold = KINDS[rec["kind"]][1]
            if hold == "all" and directed and not ai and self.soft():
                continue
            if hold == "all" or (hold == "person" and str(uid) == rec.get("who")) or (hold == "direct" and not directed):
                return rec
        return None

    def _tell(self, rec, uid, now):
        """（11-10 v0.1.1）硬睡档：这个人要不要说一声 → True 只给一次。
        记的是「告诉过他几点回来」：那个点之前不再说（它中途被叫醒又去睡，同一晚也不重复）；过了那个点下次再挡住他才再说"""
        key = f"{rec.get('conv')}|{uid}"
        if float(self.d["told"].get(key) or 0) > now:
            return False
        self.d["told"][key] = float(rec.get("until") or now)
        self.dirty = True
        return True

    def _wake(self, rec, scene, now):
        c = self.c
        calls = [x for x in rec.get("calls") or [] if now - float(x.get("ts") or 0) <= float(c["wake_window_min"]) * 60]
        boss = [x for x in calls if x.get("admin")]
        if int(c["wake_admin_ats"]) > 0 and len(boss) >= int(c["wake_admin_ats"]):
            return True, f"管理员 {c['wake_window_min']} 分钟里叫了 {len(boss)} 次"
        if now - float(rec["t0"]) < float(c["wake_floor_min"]) * 60:
            return False, f"刚说完 {c['wake_floor_min']} 分钟内只有管理员叫得醒"
        if scene == "group":
            people = {x["uid"] for x in calls}
            if int(c["wake_people"]) > 0 and len(people) >= int(c["wake_people"]):
                return True, f"{c['wake_window_min']} 分钟里 {len(people)} 个人 @ 它"
            return False, f"{c['wake_window_min']} 分钟里 {len(people)} 个人 @ 它（要 {c['wake_people']} 个才醒）"
        mine = [x for x in calls if not x.get("admin")]
        if int(c["wake_private_msgs"]) > 0 and len(mine) >= int(c["wake_private_msgs"]):
            return True, f"他 {c['wake_window_min']} 分钟里连着发了 {len(mine)} 条"
        return False, f"他 {c['wake_window_min']} 分钟里发了 {len(mine)} 条（要 {c['wake_private_msgs']} 条才醒）"

    # ───────── 结束 ─────────
    def end(self, rec, now, how="time", by="", by_admin=False, why=""):
        """how：time 到点 / woke 被叫醒 / off 管理员关掉 → 记进历史；「人不在」和「不理」的留一句给下次说话"""
        self._drop(rec)
        b = {
            "conv": rec.get("conv"),
            "kind": rec.get("kind"),
            "say": rec.get("say", ""),
            "t0": rec.get("t0"),
            "end": float(now),
            "planned": float(rec.get("until") or now) - float(rec.get("t0") or now),
            "how": how,
            "by": str(by or "")[:20],
            "by_admin": bool(by_admin),
            "n": int(rec.get("n") or 0),
            "who": rec.get("who", ""),
            "who_name": rec.get("who_name", ""),
            "why": str(why or "")[:60],
        }
        self.d["hist"] = (self.d.get("hist") or [])[-29:] + [b]
        if KINDS.get(rec.get("kind"), ("", ""))[1] in ("all", "person"):
            self.d["backs"] = [x for x in self.d["backs"] if not (x.get("conv") == b["conv"] and x.get("kind") == b["kind"])][-40:] + [b]
        self.dirty = True
        what = {"woke": f"被「{by}」叫回来了", "off": "被关掉了"}.get(how, "到点了")
        self.log(
            f"{rec.get('conv')} {KINDS.get(rec.get('kind'), ('?',))[0]}结束：{what}（「{str(rec.get('say'))[:24]}」"
            f"过了 {span(now - float(rec.get('t0') or now))}"
            + (f"，本来要 {span(b['planned'])}" if how != "time" else "")
            + (f"，这期间没回 {b['n']} 条" if b["n"] else "")
            + (f"；{why}" if why else "")
            + "）"
        )
        return b

    def tick(self, now):
        """到点的约束结束 → 结束了的那几条"""
        out = []
        for r in list(self.d["holds"]):
            if float(r.get("until") or 0) <= now:
                # 按它本来该结束的时候记（机器人关着那阵子过了点，回来才看到，不能算成刚刚才回来）
                out.append(self.end(r, float(r["until"]), "time"))
        backs = [x for x in self.d["backs"] if now - float(x.get("end") or 0) < BACK_HOURS * 3600]
        if len(backs) != len(self.d["backs"]):
            self.d["backs"][:] = backs
            self.dirty = True
        for k in [k for k, v in self.d["told"].items() if float(v or 0) <= now]:  # （11-10 v0.1.1）过了点的「告诉过谁」清掉
            del self.d["told"][k]
            self.dirty = True
        return out

    def release(self, conv=None, rid=None, by="管理员", now=0.0):
        """管理员 / 面板让它回来 → 结束了几条"""
        n = 0
        for r in list(self.d["holds"]):
            if (rid and r.get("id") == rid) or (not rid and conv and r.get("conv") == conv):
                if float(r.get("until") or 0) > now:
                    self.end(r, now, "off", by=by, by_admin=True)
                    n += 1
        return n

    # ───────── 回来以后 ─────────
    def backs_for(self, conv, uid=""):
        """这个对话里刚结束、还没告诉模型的（「不理」那种只在那个人来说话时给）"""
        return [
            b
            for b in self.d["backs"]
            if b.get("conv") == str(conv) and (KINDS.get(b.get("kind"), ("", ""))[1] != "person" or b.get("who") == str(uid))
        ]

    def consume_backs(self, shown):
        ids = {(b.get("conv"), b.get("kind"), b.get("end")) for b in shown or ()}
        keep = [b for b in self.d["backs"] if (b.get("conv"), b.get("kind"), b.get("end")) not in ids]
        if len(keep) != len(self.d["backs"]):
            self.d["backs"][:] = keep
            self.dirty = True

    def drop_person(self, uid):
        """他后来被认出是别人家的 AI：他叫过它的记录拿掉（不算数）"""
        for r in self.d["holds"]:
            before = len(r.get("calls") or [])
            r["calls"] = [x for x in r.get("calls") or [] if x.get("uid") != str(uid)]
            if len(r["calls"]) != before:
                self.dirty = True

    # ───────── 面板 ─────────
    def snapshot(self, now):
        return {
            "live": [
                {
                    "id": r["id"],
                    "kind": r["kind"],
                    "name": KINDS[r["kind"]][0],
                    "conv": r["conv"],
                    "say": r.get("say", ""),
                    "t0": r["t0"],
                    "until": r["until"],
                    "left_min": round((float(r["until"]) - now) / 60),
                    "plan": r.get("plan", ""),
                    "who": r.get("who", ""),
                    "who_name": r.get("who_name", ""),
                    "calls": len(r.get("calls") or []),
                    "n": int(r.get("n") or 0),
                }
                for r in self.d["holds"]
                if float(r.get("until") or 0) > now and self.kind_on(r.get("kind"))
            ],
            "hist": list(self.d.get("hist") or [])[-30:][::-1],
        }
