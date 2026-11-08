# -*- coding: utf-8 -*-
"""到点发不出去时怎么办（不依赖 AstrBot）：报错换成人话、分清「过会儿还能发」和「明确发不了」、重试越隔越久、日志限流。

为什么：发不出去以前每分钟重来一遍（QQ 没连上时 10 秒一次），一件提醒在 1 小时宽限里能叫上百次模型、打几百行日志；
被禁言、不是好友这种再试也没用。现在：
  - 写好的那句存在这件事上，重试只重发，不再叫模型（见 table.py 的 draft）；
  - 重试越隔越久：1、2、5、10 分钟，之后每 10 分钟；QQ 没连上时先密后疏（15 秒、30 秒、1、2、5、10 分钟）——
    开机时 NapCat 一般几秒就连上，别让到点的事白等一分钟；
  - 不是好友、机器人被禁言、机器人不在群里 → 明确发不了，直接记成没做成（禁言知道几点解、而且在宽限内的，到点再发一次）；
  - 同一件事、同一个原因的日志 10 分钟最多一行。
"""

import re

OFFLINE = "QQ 没连上"
NOT_FRIEND = "他不是机器人的 QQ 好友（私聊发不过去）"
MUTED = "机器人在这个群被禁言了"
NOT_IN_GROUP = "机器人不在这个群了"
REFUSED = "QQ 拒收了"
NO_REPLY = "QQ 那边没回应"
SEND_ERROR = "发送出错"
RETRY = (60, 120, 300, 600)
RETRY_OFFLINE = (15, 30, 60, 120, 300, 600)


def classify(err):
    """发送报错（异常或它的 repr）→ (人话原因, 是不是明确发不了)"""
    s = err if isinstance(err, str) else repr(err)
    low = s.lower()
    if "apinotavailable" in low or "notconnected" in low:
        return OFFLINE, False
    if "actionfailed" in low or "retcode" in low:
        if re.search(r"好友|friend", low):
            return NOT_FRIEND, True
        if re.search(r"禁言|mute|shut.?up|banned", low):
            return MUTED, True
        if re.search(r"不在.{0,4}群|不是.{0,4}群成员|群不存在|not.{0,12}(member|in.{0,4}group)|group.{0,12}not.{0,6}(found|exist)", low):
            return NOT_IN_GROUP, True
        return REFUSED, False
    if "timeout" in low or "networkerror" in low:
        return NO_REPLY, False
    return SEND_ERROR, False


def retry_after(tries, offline=False):
    """已经失败了 tries 次 → 隔几秒再试（越隔越久，最多 10 分钟）"""
    seq = RETRY_OFFLINE if offline else RETRY
    return float(seq[min(max(int(tries), 1), len(seq)) - 1])


class Throttle:
    """同一件事、同一个原因：gap 秒里只放行一次（日志限流）"""

    def __init__(self, gap=600.0):
        self.gap = float(gap)
        self.last = {}

    def ok(self, key, why, now):
        k = (key, why)
        if now - self.last.get(k, -1e18) < self.gap:
            return False
        self.last[k] = float(now)
        if len(self.last) > 500:  # 别越攒越多
            for x in sorted(self.last, key=self.last.get)[:250]:
                self.last.pop(x, None)
        return True
