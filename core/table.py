# -*- coding: utf-8 -*-
"""承诺表（不依赖 AstrBot）：机器人答应过谁、在哪、什么时候做什么。

两种都记在这张表里，编号共用：
  task    到点要做的事（说清楚了时间：「明早 8 点提醒你」「每晚十点半叫你去睡」）—— 到点插件替它去做
  promise 没说时间的答应（「等会帮你查」「回头告诉你」）—— 不会到点去做，只在他下次来找它时让它知道还欠着

为什么要表：机器人说的话是模型写的字，做的事是代码执行的动作，两边原来没绑在一起。
说了就进表 → 到点去做 → 做成 / 没做成都写回来 → 下次说话时它看得到。
"""

import re

from .clock import day, fmt, span, when_text
from .failure import retry_after
from .when import REPEAT_TEXT, first_weekday, next_after

DEFAULTS = {
    "max_pending": 5,  # 每人同时最多挂几件到点的事（按「谁让定的」算）
    "max_daily": 10,  # 每人每天最多新加几件
    "admin_unlimited": True,  # 管理员不限
    "grace_min": 60,  # 到点没做成：这么多分钟内补上；再晚记成没做成
    "keep_days": 30,  # 做完 / 取消 / 没做成的留几天（面板看得到）
    "done_note_hours": 2,  # 做完以后多久内，跟他说话时告诉模型这件刚做过
    "dedupe_sec": 600,  # 同一个人、同一个对话、时间差不到这么多秒 → 算同一件（「提醒他起床」「叫他起床」不会 @ 他两次）
    "promise_days": 3,  # 没说时间的答应：最多挂几天
    "promise_shows": 3,  # 最多提几次
    "promise_after_min": 30,  # 答应完多久才提（刚答应完接着聊的那几句里不提）
    "promise_gap_min": 90,  # 提过一次隔多久再提
    "promise_max": 5,  # 同一个人在同一个对话里最多挂几件（多了丢最早的）
}
STATUS_TEXT = {"pending": "等着", "done": "做了", "missed": "没做成", "cancelled": "取消了", "expired": "过期了"}
OFFLINE_WHY = "到点那会儿机器人没开着（关机 / 重启 / 掉线）"


def is_group(conv):
    return ":GroupMessage:" in str(conv or "")


def seen_in(task_conv, here):
    """记在 task_conv 的事，在 here 这个对话里给不给看：
    同一个对话给；群里记的、在他私聊里也给（群里本来大家都看得到）；私聊里记的不进群、A 群的不进 B 群（隐私）"""
    a, b = str(task_conv or ""), str(here or "")
    return a == b or (bool(b) and not is_group(b) and is_group(a))


def _norm(s):
    return re.sub(r"[\s\W_]+", "", str(s or "")).lower()


def same_thing(a, b):
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    return a == b or (min(len(a), len(b)) >= 4 and (a in b or b in a))


def ref_num(x):
    """「#3」「3」「编号3」→ 3；不是 → None"""
    m = re.search(r"\d+", str(x if x is not None else ""))
    return int(m.group(0)) if m else None


class Table:
    def __init__(self, data, tz=None, conf=None, log=None):
        self.d = data if isinstance(data, dict) else {}
        self.d.setdefault("seq", 0)
        self.d.setdefault("tasks", [])
        self.d.setdefault("notes", [])
        if not isinstance(self.d["tasks"], list):
            self.d["tasks"] = []
        if not isinstance(self.d["notes"], list):
            self.d["notes"] = []
        self.tz = tz
        self.c = dict(DEFAULTS)
        self.configure(conf)
        self.log = log or (lambda m: None)
        self.dirty = False

    def configure(self, conf=None):
        for k, v in (conf or {}).items():
            if k in DEFAULTS and v is not None:
                self.c[k] = type(DEFAULTS[k])(v)

    @property
    def tasks(self):
        return self.d["tasks"]

    def _touch(self):
        self.dirty = True

    # ───────── 查 ─────────
    def find(self, ref):
        n = ref_num(ref)
        if n is None:
            return None
        return next((t for t in self.tasks if t.get("n") == n), None)

    def pending(self, kind="task", who=None, conv=None, by=None):
        out = []
        for t in self.tasks:
            if t.get("status") != "pending" or (kind and t.get("kind", "task") != kind):
                continue
            if who is not None and str(t.get("who")) != str(who):
                continue
            if conv is not None and t.get("conv") != conv:
                continue
            if by is not None and str(t.get("by") or t.get("who")) != str(by):
                continue
            out.append(t)
        return out

    def mine(self, uid, conv, admin=False):
        """这个人在这个对话里能改 / 能取消的（本人的；管理员 = 这个对话里所有的）→ 抽取时给模型看编号"""
        uid = str(uid)
        out = [
            t
            for t in self.pending(kind=None, conv=conv)
            if admin or uid in (str(t.get("who")), str(t.get("by") or t.get("who")))
        ]
        return sorted(out, key=lambda t: (t.get("kind") != "task", float(t.get("due") or 0), t.get("n", 0)))

    @staticmethod
    def can_edit(t, uid, admin=False):
        return bool(admin) or str(uid) in (str(t.get("who")), str(t.get("by") or t.get("who")))

    # ───────── 记 ─────────
    def add_task(
        self,
        conv,
        umo,
        scene,
        who,
        who_name,
        what,
        due,
        repeat=None,
        via="at",
        by=None,
        say="",
        ask="",
        now=0.0,
        admin=False,
        src="chat",
        dom=None,
    ):
        """记一件到点要做的事 → (那件事, "") / (同一件已经记过的, "dup") / (None, 为什么没记上)"""
        who, req = str(who or ""), str(by or who or "")
        what = str(what or "").strip()[:120]
        if not who:
            return None, "不知道是给谁的"
        if not what:
            return None, "不知道到点要做什么"
        if not due:
            return None, "时间没看懂"
        due = float(due)
        if due < now - 60:
            return None, "那个时间已经过了"
        if repeat == "weekdays":
            due = first_weekday(due, self.tz)
        for t in self.pending("task", who=who, conv=conv):
            # 同一个人、同一个对话、时间差 10 分钟以内（重不重复也一样）→ 就是同一件：机器人换个说法复述一遍
            # （「记着呢 明早 8 点叫你」）、同一件事说成「提醒他起床」「叫他起床」，都不新增，只更新说法。
            # 先认这个、再看名额 —— 不然第 5 件说第二遍会被当成「满了」
            if abs(float(t.get("due") or 0) - due) < self.c["dedupe_sec"] and (t.get("repeat") or None) == (repeat or None):
                if say:
                    t["say"] = str(say)[:80]
                if ask:
                    t["ask"] = str(ask)[-120:]
                if not same_thing(t.get("what"), what) and len(_norm(what)) > len(_norm(t.get("what"))):
                    t["what"] = what  # 新说法更具体就换上
                self._touch()
                return t, "dup"
        if not (admin and self.c["admin_unlimited"]) and src != "panel":
            pend = self.pending("task", by=req)
            if len(pend) >= self.c["max_pending"]:
                return None, f"他已经挂着 {len(pend)} 件到点的事（每人最多 {self.c['max_pending']} 件）"
            today = day(now, self.tz)
            made = [
                t
                for t in self.tasks
                if t.get("kind", "task") == "task"
                and str(t.get("by") or t.get("who")) == req
                and t.get("src") != "panel"
                and day(float(t.get("created") or 0), self.tz) == today
            ]
            if len(made) >= self.c["max_daily"]:
                return None, f"今天已经答应他 {len(made)} 件了（每人每天最多 {self.c['max_daily']} 件）"
        t = self._new("task", conv, umo, scene, who, who_name, what, say, ask, req, now, src)
        t.update({"due": due, "repeat": repeat or None, "via": via if via in ("at", "private") else "at"})
        if repeat in ("monthly", "yearly"):
            t["dom"] = int(dom or 0) or int(fmt(due, self.tz, "%d"))
        self.tasks.append(t)
        self._touch()
        self.log(
            f"记下 #{t['n']}：{when_text(due, now, self.tz)} {what[:40]}"
            + (f"（{REPEAT_TEXT[repeat]}）" if repeat in REPEAT_TEXT else "")
            + f" → {'私聊发给' if t['via'] == 'private' else '在这里 @'}「{who_name or who}」"
        )
        return t, ""

    def add_promise(self, conv, umo, scene, who, who_name, what, say="", ask="", now=0.0):
        """记一件没说时间的答应 → (那件, "" / "dup") / (None, 为什么)"""
        who = str(who or "")
        what = str(what or "").strip()[:120]
        if not who or not what:
            return None, "不知道答应了谁什么"
        mine = self.pending("promise", who=who, conv=conv)
        for p in mine:
            if same_thing(p.get("what"), what):
                return p, "dup"
        for p in sorted(mine, key=lambda x: float(x.get("created") or 0))[: max(0, len(mine) - self.c["promise_max"] + 1)]:
            p["status"], p["ended"] = "expired", now  # 挂太多了：丢最早的（不然每次说话都提一长串）
        p = self._new("promise", conv, umo, scene, who, who_name, what, say, ask, who, now, "chat")
        p.update({"due": None, "shows": 0, "shown_at": 0.0})
        self.tasks.append(p)
        self._touch()
        self.log(f"记下 #{p['n']}（没说时间）：答应「{who_name or who}」{what[:40]}")
        return p, ""

    def _new(self, kind, conv, umo, scene, who, who_name, what, say, ask, by, now, src):
        self.d["seq"] = int(self.d.get("seq") or 0) + 1
        return {
            "n": self.d["seq"],
            "kind": kind,
            "conv": str(conv or ""),
            "umo": str(umo or conv or ""),
            "scene": "group" if scene == "group" else "private",
            "who": str(who),
            "who_name": str(who_name or "")[:20],
            "by": str(by or who),
            "what": what,
            "say": str(say or "")[:80],
            "ask": str(ask or "")[-120:],
            "status": "pending",
            "created": float(now),
            "src": src,
            "tries": 0,
            "last_try": 0.0,
            "why": "",
            "hist": [],
            "apology": "",
        }

    # ───────── 改 ─────────
    def cancel(self, t, by="", now=0.0):
        if not t or t.get("status") != "pending":
            return False
        t["status"], t["ended"], t["cancel_by"] = "cancelled", float(now), str(by or "")[:20]
        self._touch()
        self.log(f"#{t['n']}「{str(t.get('what'))[:30]}」取消了（{by or '?'}）")
        return True

    def edit(self, t, due=None, what=None, now=0.0, by=""):
        """改时间 / 改内容 → (改好的, "") / (None, 为什么)"""
        if not t or t.get("status") != "pending":
            return None, "那件已经做完 / 取消了，或者没找到"
        if due is not None:
            if t.get("kind") != "task":
                return None, "没说时间的答应不能改时间"
            if float(due) < now - 60:
                return None, "新的时间已经过了"
            t["due"] = float(due)
            if t.get("repeat") == "weekdays":
                t["due"] = first_weekday(t["due"], self.tz)
            if t.get("repeat") in ("monthly", "yearly"):
                t["dom"] = int(fmt(t["due"], self.tz, "%d"))
            t["tries"], t["last_try"], t["why"], t["next_try"] = 0, 0.0, "", 0.0
        if what:
            t["what"] = str(what).strip()[:120]
        t.pop("draft", None)  # 改过了：上次写好没发出去的那句不能再用
        self._touch()
        self.log(
            f"#{t['n']} 改了（{by or '?'}）："
            + (when_text(t["due"], now, self.tz) + " " if t.get("due") else "")
            + str(t.get("what"))[:30]
        )
        return t, ""

    # ───────── 到点 ─────────
    def due_now(self, now):
        """到点了、该去做的（上次没做成的，等到排好的下一次再试）"""
        return sorted(
            (t for t in self.pending("task") if float(t.get("due") or 0) <= now and now >= float(t.get("next_try") or 0)),
            key=lambda t: float(t["due"]),
        )

    # ───────── 写好的那句（重试只重发，不再叫模型）─────────
    @staticmethod
    def draft(t):
        """这一次（同一个 due）上次写好、没发出去的那句 → (话, 谁写的) / None"""
        d = t.get("draft")
        if isinstance(d, dict) and d.get("for") == t.get("due") and d.get("text"):
            return d["text"], d.get("by") or ""
        return None

    def save_draft(self, t, text, by=""):
        t["draft"] = {"for": t.get("due"), "text": str(text)[:2000], "by": str(by or "")}
        self._touch()

    def overdue(self, t, now):
        return now - float(t.get("due") or now) > float(self.c["grace_min"]) * 60

    def done(self, t, text="", now=0.0, by=""):
        """做成了：记一笔；重复的排到下一次。发的时候他刚取消了 → 不改回「做了」"""
        late = max(0.0, now - float(t.get("due") or now))
        t["hist"] = (t.get("hist") or [])[-19:] + [
            {"due": t.get("due"), "at": float(now), "ok": True, "text": str(text or "")[:200], "late": round(late), "by": by}
        ]
        t["tries"], t["last_try"], t["why"], t["late_why"], t["next_try"] = 0, 0.0, "", "", 0.0
        t.pop("draft", None)
        if t.get("status") == "pending":
            if t.get("repeat"):
                t["due"] = next_after(float(t["due"]), t["repeat"], now, self.tz, t.get("dom"))
            else:
                t["status"], t["ended"] = "done", float(now)
        self._touch()
        self.log(
            f"#{t['n']} 做了：{str(t.get('what'))[:30]} →「{t.get('who_name') or t.get('who')}」"
            + (f"（晚了 {span(late)}）" if late >= 120 else "")
            + (f" 下一次 {when_text(t['due'], now, self.tz)}" if t.get("repeat") and t.get("status") == "pending" else "")
        )
        return t

    def failed(self, t, why, now=0.0, final=False, offline=False, retry_at=None):
        """这次没做成 → "retry"（宽限内接着试）/ "missed"（晚过宽限 / 明确发不了：记成没做成，欠一个道歉）。
        重试越隔越久（failure.retry_after）；offline = QQ 没连上（先密后疏）；retry_at = 指定几点再试（禁言到点）。
        final = 明确发不了（不是好友 / 被禁言 / 不在群里）：不再试"""
        before = t.get("why")
        t["tries"] = int(t.get("tries") or 0) + 1
        t["last_try"], t["why"] = float(now), str(why or "")[:60]
        t["late_why"] = t.get("late_why") or t["why"]  # 晚了的原因记第一个（开机前就过点了，就是「机器人没开着」）
        nxt = float(retry_at) if retry_at else float(now) + retry_after(t["tries"], offline)
        if not final and not self.overdue(t, nxt):
            t["next_try"] = nxt
            self._touch()
            if t["tries"] == 1 or t["why"] != before:  # 同一个原因只记第一次（不然一小时几十上百行）
                self.log(f"#{t['n']} 到点了但这次没做成（{why}）{span(nxt - now)}后再试")
            return "retry"
        # 没做成的原因：明确发不了的写这次的（不是好友 / 被禁言）；拖过宽限的写最早那个（机器人没开着 / QQ 没连上）
        why_missed = t["why"] if final else t["late_why"]
        t["hist"] = (t.get("hist") or [])[-19:] + [{"due": t.get("due"), "at": float(now), "ok": False, "why": why_missed}]
        t["apology"], t["apo_for"], t["apo_why"] = "owed", t.get("due"), why_missed
        t.pop("draft", None)
        if t.get("repeat"):
            t["due"] = next_after(float(t["due"]), t["repeat"], now, self.tz, t.get("dom"))
            t["tries"], t["last_try"], t["late_why"], t["next_try"] = 0, 0.0, "", 0.0
        else:
            t["status"], t["ended"] = "missed", float(now)
        self._touch()
        self.log(f"#{t['n']}「{str(t.get('what'))[:30]}」没做成（{why}）→ 记下了，他下次来找机器人时告诉它欠着一个道歉")
        return "missed"

    def sweep(self, now):
        """开机：已经过点很久（超过宽限）的不补，直接记成没做成 → 返回这几件"""
        out = []
        for t in list(self.pending("task")):
            if float(t.get("due") or now) > now:
                continue
            if self.overdue(t, now):
                self.failed(t, OFFLINE_WHY, now, final=True)
                out.append(t)
            elif not t.get("late_why") and float(t.get("due") or now) < now - 60:
                t["late_why"] = OFFLINE_WHY  # 开机前就过点了（宽限内）：照常去补，补的时候告诉模型晚了是因为机器人没开着
                self._touch()
        return out

    # ───────── 每轮给模型看的 ─────────
    def state_for(self, uid, conv, now, admin=False):
        """答应过这个人、在这个对话里看得到的：还没做的 / 别处还有几件 / 刚做过的 / 欠着的道歉 / 没说时间的 / 没记上的 / 满没满"""
        uid = str(uid or "")
        out = {"here": [], "elsewhere": 0, "done": [], "apology": [], "promises": [], "notes": [], "full": 0}
        if not uid:
            return out
        hrs = float(self.c["done_note_hours"]) * 3600
        for t in self.tasks:
            if str(t.get("who")) != uid:
                continue
            here = seen_in(t.get("conv"), conv)
            kind = t.get("kind", "task")
            if t.get("status") == "pending" and kind == "task":
                if here:
                    out["here"].append(t)
                else:
                    out["elsewhere"] += 1  # 别的对话里答应的：只说有几件，不带内容（防重复答应，也不把私事带进群）
            if not here:
                continue
            last = (t.get("hist") or [{}])[-1]
            if kind == "task" and last.get("ok") and now - float(last.get("at") or 0) < hrs and last.get("by") != "panel":
                out["done"].append(t)
            if t.get("apology") == "owed":
                out["apology"].append(t)
            if kind == "promise" and t.get("status") == "pending" and self._prom_now(t, now):
                out["promises"].append(t)
        out["here"].sort(key=lambda t: float(t.get("due") or 0))
        out["here"] = out["here"][:6]
        out["notes"] = [x for x in self.d["notes"] if str(x.get("uid")) == uid and seen_in(x.get("conv"), conv)]
        pend = self.pending("task", by=uid)
        if not (admin and self.c["admin_unlimited"]) and len(pend) >= self.c["max_pending"]:
            out["full"] = len(pend)
        return out

    def _prom_now(self, p, now):
        if now - float(p.get("created") or 0) < float(self.c["promise_after_min"]) * 60:
            return False
        return now - float(p.get("shown_at") or 0) >= float(self.c["promise_gap_min"]) * 60

    def consume(self, uid, shown, now):
        """这一轮模型看过、话也发出去了：道歉算说过了、没说时间的答应提醒次数 +1、没记上的那几条说过了。
        只算这一轮真给它看过的（别的对话里的不动）"""
        shown = shown or {}
        ch = False
        for t in self.tasks:
            if str(t.get("who")) != str(uid):
                continue
            if t.get("n") in (shown.get("apo") or ()) and t.get("apology") == "owed":
                t["apology"], t["apo_told"] = "told", float(now)
                ch = True
            if t.get("n") in (shown.get("prom") or ()) and t.get("status") == "pending":
                t["shows"], t["shown_at"] = int(t.get("shows") or 0) + 1, float(now)
                ch = True
        ids = set(shown.get("notes") or ())
        if ids:
            keep = [x for x in self.d["notes"] if x.get("id") not in ids]
            if len(keep) != len(self.d["notes"]):
                self.d["notes"][:] = keep
                ch = True
        if ch:
            self._touch()
        return ch

    def note(self, uid, conv, text, now):
        """没记上 / 没改成：下次他来找机器人时让它知道（它可能已经跟人说了「记下了」）"""
        if not uid:
            return None
        self.d["seq_note"] = int(self.d.get("seq_note") or 0) + 1
        x = {"id": self.d["seq_note"], "uid": str(uid), "conv": str(conv or ""), "text": str(text)[:120], "t": float(now)}
        mine = [n for n in self.d["notes"] if n.get("uid") == str(uid)]
        if len(mine) >= 4:
            self.d["notes"].remove(mine[0])
        self.d["notes"].append(x)
        self._touch()
        return x

    # ───────── 清理 / 别人家的 AI ─────────
    def prune(self, now):
        keep_s = float(self.c["keep_days"]) * 86400
        pd, ps = float(self.c["promise_days"]) * 86400, int(self.c["promise_shows"])
        ch = False
        for p in self.pending("promise"):
            if now - float(p.get("created") or now) > pd or int(p.get("shows") or 0) >= ps:
                p["status"], p["ended"] = "expired", float(now)
                ch = True
        kept = [
            t
            for t in self.tasks
            if t.get("status") == "pending"
            or t.get("apology") == "owed"
            or now - float(t.get("ended") or t.get("created") or now) < keep_s
        ]
        if len(kept) != len(self.tasks):
            self.d["tasks"][:] = kept
            ch = True
        notes = [x for x in self.d["notes"] if now - float(x.get("t") or 0) < 3 * 86400]
        if len(notes) != len(self.d["notes"]):
            self.d["notes"][:] = notes
            ch = True
        if ch:
            self._touch()
        return ch

    def drop_person(self, uid, why, now):
        """这个号后来被认出是别人家的 AI：答应他的、他让定的，没做的都划掉"""
        out = []
        for t in self.pending(kind=None):
            if str(uid) in (str(t.get("who")), str(t.get("by"))):
                self.cancel(t, why, now)
                out.append(t)
        return out

    # ───────── 面板 ─────────
    def counts(self, now):
        today = day(now, self.tz)
        c = {"pending": 0, "promises": 0, "done_today": 0, "missed": 0, "apology": 0}
        for t in self.tasks:
            k = t.get("kind", "task")
            if t.get("status") == "pending":
                c["pending" if k == "task" else "promises"] += 1
            if t.get("status") == "missed":
                c["missed"] += 1
            if t.get("apology") == "owed":
                c["apology"] += 1
            c["done_today"] += sum(1 for h in t.get("hist") or [] if h.get("ok") and day(float(h.get("at") or 0), self.tz) == today)
        return c

    def view(self, t, now):
        x = {
            k: t.get(k)
            for k in (
                "n",
                "kind",
                "conv",
                "scene",
                "who",
                "who_name",
                "by",
                "what",
                "say",
                "ask",
                "due",
                "repeat",
                "via",
                "status",
                "created",
                "ended",
                "tries",
                "why",
                "apology",
                "apo_why",
                "shows",
                "src",
                "cancel_by",
            )
        }
        x["status_text"] = STATUS_TEXT.get(t.get("status"), t.get("status"))
        x["repeat_text"] = REPEAT_TEXT.get(t.get("repeat") or "", "")
        x["when"] = when_text(t["due"], now, self.tz) if t.get("due") else "没说时间"
        x["hist"] = (t.get("hist") or [])[-5:]
        return x

    def snapshot(self, now, limit=60):
        pend = sorted(self.pending("task"), key=lambda t: float(t.get("due") or 0))
        proms = sorted(self.pending("promise"), key=lambda t: -float(t.get("created") or 0))
        past = sorted(
            (t for t in self.tasks if t.get("status") != "pending"),
            key=lambda t: -float(t.get("ended") or t.get("created") or 0),
        )
        return {
            "pending": [self.view(t, now) for t in pend[:limit]],
            "promises": [self.view(t, now) for t in proms[:limit]],
            "past": [self.view(t, now) for t in past[:limit]],
            "counts": self.counts(now),
            "notes": list(self.d["notes"])[-20:],
        }


class Gap:
    """同一个地方（群 / 私聊）两条主动发的消息至少隔 gap 秒：一件一件发，不刷屏，也不容易被 QQ 风控"""

    def __init__(self, gap=20.0):
        self.gap = float(gap)
        self.last = {}

    def ok(self, dest, now):
        return now - self.last.get(dest, -1e18) >= self.gap

    def mark(self, dest, now):
        self.last[dest] = float(now)
