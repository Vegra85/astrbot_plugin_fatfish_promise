#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端测试：真的 AstrBot（测过 4.29.4）+ 这个插件 + 假 QQ 端（假 NapCat 反向 WebSocket）+ 假模型（OpenAI 兼容）
  A 起来了、插件加载了
  B 阿木 @ 机器人「明天早上8点提醒我交作业」，机器人（假模型）回「好 明天早上 8 点提醒你交作业」→ 后台抽一次 → 表里有一条
    （明天 08:00、给阿木、在这个群 @ 他）；随便聊一句没筛中 → 不调抽取；下一轮给模型的请求里带着「你答应他的、还没做的 #1」（临时的，不进聊天记录）
  C 把插件的「现在几点」拨到 8 点 → 主动在群里发了一条、前面 @ 阿木；给模型写那句的状态里有谁、原话、现在几点
  D 「10分钟后提醒我喝水」记上 →「不用提醒了」→ 取消；指令 /说到做到 看自己的、别人取消不了、本人能取消、管理员看全部
  E 机器人说「我去睡了」（开了 AstrBot 主动回复的群）→ 没 @ 的不回；有人 @ 它一次就醒来回了（v0.1.1 的默认：有人找就醒），
    这一轮的状态里写着「你刚回来…谁叫醒的」；醒了以后没 @ 的又照常接
    （E、F 这两节 11-10 跟着 v0.1.1 的新默认改过，已在真 AstrBot 4.29.4 上跑过；硬睡档和它的系统提示在 tests/test_hold.py、test_hooks.py 里测）
  F 跟认 AI 插件一起装：标成 AI 的号约的事不进表（也不花钱去抽）；睡着时 AI @ 叫不醒，真人一 @ 就醒
  G 面板接口：读状态、取消、结束约束；没登录读不到；面板页认得出来
  I 私聊里答应的：群里只说「别处还有 1 件」（内容不进群）；到点私聊发给他、不 @
  J 没说时间的答应（「等会帮你查一下」）：记下但不会到点去做；刚答应完接着聊不提，过了半小时他再来时状态里写着还欠着
  K 到点那会儿模型叫不通：发一句系统口吻的「（系统提示）到点了：……」，照样 @ 他
  L 明确发不了（机器人在群里被禁言了、宽限内解不了）：直接记成没做成，不叫模型、不往群里硬发
  M 发不出去（QQ 拒收）：重试只重发第一次写好的那句、越隔越久（1、2、5 分钟），日志不刷屏；QQ 好了补发、照样 @ 他
  I 里另外查：管理员在群里发 /说到做到 全部 只列本群的（别人私聊里的不贴进群），私聊里发才看得到全部
  H 重启：表还在；开机时过点很久的（晚了快 2 小时）直接记成没做成，他再来时状态里写着欠一个道歉；
    晚了 20 分钟的（宽限内）补上，状态里写着晚了多久
用法：python tests/e2e_astrbot.py [插件目录 默认上一层] [--keep] [--alone]
  需要装了 astrbot（测过 4.29.4）的 Python；astrbot 命令在 PATH 里或者跟这个 python 在同一个目录；另外要 aiohttp、pyjwt、websockets
  旁边有认 AI 插件（../astrbot_plugin_fatfish_aiguard 或 /home/claude/dev 下）就一起装（--alone 不装，F 跳过）
  只在临时文件夹里跑：模型是假的、QQ 端是假的，不连外网；端口用空闲的，几个测试同时跑互不打架
"""

import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import aiohttp
from aiohttp import web
import jwt
import websockets

PLUGIN_SRC = Path(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else Path(__file__).resolve().parent.parent).resolve()
KEEP = "--keep" in sys.argv
ALONE = "--alone" in sys.argv
PNAME = PLUGIN_SRC.name
AIGUARD_SRC = next(
    (p for p in (PLUGIN_SRC.parent / "astrbot_plugin_fatfish_aiguard", Path("/home/claude/dev/astrbot_plugin_fatfish_aiguard")) if (p / "main.py").exists()),
    None,
)
AIGUARD_SRC = None if ALONE else AIGUARD_SRC
ASTRBOT = shutil.which("astrbot") or str(Path(sys.executable).parent / "astrbot")
SELF, ADMIN, AMU, XC, LW, AZ, BOTX = 99999, 10001, 20002, 30003, 40004, 50005, 60006  # 号都是编的
G1, G2, G3, G4, G5 = 7001, 7002, 7003, 7004, 7005
RES = []
SECRET = "e2e-secret-0123456789abcdef0123456789"


def check(cond, msg, why=""):
    RES.append((bool(cond), msg))
    print(("  [过]   " if cond else "  [没过] ") + msg + ("" if cond or not why else f"\n           {str(why)[:900]}"), flush=True)
    return bool(cond)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def real_tracebacks(text):
    """日志里的 Traceback；AstrBot 自带「主动回复」被插件拦下时它自己打的那段 GeneratorExit 不算（认 AI 的 e2e 里一样）"""
    out = []
    for chunk in text.split("Traceback (most recent call last):")[1:]:
        head = chunk[:1500]
        if "GeneratorExit" in head and "主动回复失败" in head:
            continue
        out.append(chunk[:1200])
    return out


LLM_PORT, WS_PORT, DASH_PORT = free_port(), free_port(), free_port()
ROOT = Path(tempfile.mkdtemp(prefix="astrbot-e2e-promise-"))
chat_calls, extract_calls, speak_calls, judge_calls = [], [], [], []


# ───────────── 假模型 ─────────────
def _texts(content):
    if isinstance(content, str):
        return [content]
    out = []
    for p in content or []:
        if isinstance(p, dict) and p.get("type") == "text":
            out.append(str(p.get("text") or ""))
    return out


def extract_reply(prompt):
    """假的抽取模型：照机器人回的那句给 JSON"""
    m = re.search(r"机器人回：「(.*?)」\n对方挂着的事", prompt, re.S)
    bot = m.group(1) if m else ""
    mine = re.findall(r"#(\d+) ", prompt.split("对方挂着的事：", 1)[-1])
    if "明天早上 8 点提醒你交作业" in bot:
        items = [{"type": "task", "what": "提醒他交作业", "when": "明天早上8点", "repeat": "", "via": "", "quote": "明天早上 8 点提醒你交作业"}]
    elif "10 分钟后提醒你喝水" in bot:
        items = [{"type": "task", "what": "提醒他喝水", "when": "10分钟后", "repeat": "", "via": "", "quote": "10 分钟后提醒你喝水"}]
    elif "10 分钟后提醒你吃药" in bot:
        items = [{"type": "task", "what": "提醒他吃药", "when": "10分钟后", "repeat": "", "via": "", "quote": "10 分钟后提醒你吃药"}]
    elif "10 分钟后提醒你取快递" in bot:
        items = [{"type": "task", "what": "提醒他取快递", "when": "10分钟后", "repeat": "", "via": "", "quote": "10 分钟后提醒你取快递"}]
    elif "10 分钟后提醒你开会" in bot:
        items = [{"type": "task", "what": "提醒他开会", "when": "10分钟后", "repeat": "", "via": "", "quote": "10 分钟后提醒你开会"}]
    elif "10 分钟后提醒你浇花" in bot:
        items = [{"type": "task", "what": "提醒他浇花", "when": "10分钟后", "repeat": "", "via": "", "quote": "10 分钟后提醒你浇花"}]
    elif "100 分钟后提醒你收衣服" in bot:
        items = [{"type": "task", "what": "提醒他收衣服", "when": "100分钟后", "repeat": "", "via": "", "quote": "100 分钟后提醒你收衣服"}]
    elif "那就不提醒了" in bot and mine:
        items = [{"type": "cancel", "id": int(mine[-1]), "quote": "那就不提醒了"}]
    elif "我去睡了" in bot:
        items = [{"type": "hold", "kind": "sleep", "minutes": None, "quote": "我去睡了"}]
    elif "等会帮你查一下" in bot:
        items = [{"type": "promise", "what": "帮他查明天的天气", "quote": "等会帮你查一下"}]
    else:
        items = []
    return json.dumps({"items": items}, ensure_ascii=False)


def chat_reply(user):
    for key, out in (
        ("提醒我交作业", "好 明天早上 8 点提醒你交作业"),
        ("提醒我喝水", "行 10 分钟后提醒你喝水"),
        ("提醒我收衣服", "行 100 分钟后提醒你收衣服"),
        ("提醒我浇花", "行 10 分钟后提醒你浇花"),
        ("提醒我吃药", "行 10 分钟后提醒你吃药"),
        ("提醒我取快递", "行 10 分钟后提醒你取快递"),
        ("提醒我开会", "行 10 分钟后提醒你开会"),
        ("不用提醒了", "好的 那就不提醒了"),
        ("晚安", "我去睡了 晚安"),
        ("帮我查一下明天的天气", "等会帮你查一下"),
    ):
        if key in user:
            return out
    return f"收到第{len(chat_calls)}句"


async def chat_completions(request):
    body = await request.json()
    msgs = body.get("messages") or []
    sysmsg = " ".join(" ".join(_texts(m.get("content"))) for m in msgs if m.get("role") == "system")
    last = msgs[-1] if msgs else {}
    parts = _texts(last.get("content"))
    last_all = "\n".join(parts)
    if "你是记录员" in sysmsg:
        extract_calls.append(last_all)
        text = extract_reply(last_all)
    elif "分辨：群里某个账号是不是" in sysmsg:
        judge_calls.append(last_all)
        text = json.dumps({"bot": False, "mixed": False, "confidence": 85, "why": "真人"}, ensure_ascii=False)
    elif "现在到点了" in last_all:
        speak_calls.append(last_all)
        if "浇花" in last_all:  # K：到点那会儿模型出错
            return web.Response(status=500, text="fake model down")
        n_same = sum(1 for x in speak_calls if ("开会" in x) == ("开会" in last_all))
        text = ("交作业的时间到啦" if "交作业" in last_all else "该喝水啦" if "喝水" in last_all
                else f"该去开会啦（第{n_same}次写的）" if "开会" in last_all else "到点啦，该去收衣服了")
    else:
        user = parts[0] if parts else ""
        chat_calls.append({"user": user, "last": last_all, "history": json.dumps(msgs[:-1], ensure_ascii=False)})
        text = chat_reply(user)
    return web.json_response(
        {
            "id": "x",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model", "fake"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
    )


async def models(request):
    return web.json_response({"object": "list", "data": [{"id": "fake-model", "object": "model"}]})


# ───────────── 假 QQ 端（NapCat 反向 WebSocket） ─────────────
class FakeQQ:
    def __init__(self):
        self.ws = None
        self.mid = 1000
        self.sent = []  # {"gid", "uid", "text", "at", "t"}
        self.store = {}
        self.names = {SELF: "大肥鱼", ADMIN: "管理员", AMU: "阿木", XC: "小橙", LW: "老王", AZ: "阿珍", BOTX: "隔壁的机器人"}
        self.new_sent = asyncio.Event()
        self.muted = {}  # 群 → 机器人被禁言到几点
        self.fail_groups = set()  # 往这些群发消息：QQ 拒收（不是明确发不了的那种）
        self.send_tries = []  # (群, 时间)：机器人试着往群里发的每一次（发成没发成都记）

    async def connect(self):
        for _ in range(120):
            try:
                self.ws = await websockets.connect(
                    f"ws://127.0.0.1:{WS_PORT}/ws/", additional_headers={"X-Self-ID": str(SELF), "X-Client-Role": "Universal"}
                )
                break
            except Exception:
                await asyncio.sleep(0.5)
        if not self.ws:
            raise RuntimeError("连不上 AstrBot 的反向 WebSocket")
        asyncio.create_task(self.loop())
        await self.ws.send(json.dumps({"post_type": "meta_event", "meta_event_type": "lifecycle", "sub_type": "connect", "self_id": SELF, "time": int(time.time())}))

    async def loop(self):
        try:
            async for raw in self.ws:
                try:
                    d = json.loads(raw)
                except Exception:
                    continue
                if "action" not in d:
                    continue
                act, p, echo = d["action"], d.get("params") or {}, d.get("echo")
                data = {}
                gid_ = int(p.get("group_id") or 0)
                if act in ("send_group_msg", "send_msg") and gid_:
                    self.send_tries.append((gid_, time.time()))
                if act in ("send_group_msg", "send_msg") and (gid_ in self.fail_groups or self.muted.get(gid_, 0) > time.time()):
                    msg_ = "机器人被禁言了" if gid_ in self.muted else "服务器繁忙"
                    await self.ws.send(json.dumps({"status": "failed", "retcode": 1400, "data": None, "msg": msg_, "wording": msg_, "echo": echo}))
                    continue
                if act in ("send_group_msg", "send_private_msg", "send_msg"):
                    self.mid += 1
                    msg = p.get("message")
                    segs = msg if isinstance(msg, list) else [{"type": "text", "data": {"text": str(msg)}}]
                    text = "".join((s.get("data") or {}).get("text", "") for s in segs if isinstance(s, dict) and s.get("type") == "text")
                    ats = [str((s.get("data") or {}).get("qq")) for s in segs if isinstance(s, dict) and s.get("type") == "at"]
                    self.sent.append({"gid": int(p.get("group_id") or 0), "uid": int(p.get("user_id") or 0), "text": text, "at": ats, "t": time.time()})
                    self.store[self.mid] = {"message_id": self.mid, "message_type": "group", "group_id": p.get("group_id"),
                                            "sender": {"user_id": SELF, "nickname": "大肥鱼"}, "user_id": SELF, "self_id": SELF,
                                            "time": int(time.time()), "message": segs}
                    data = {"message_id": self.mid}
                    self.new_sent.set()
                elif act == "get_group_member_info":
                    uid = int(p.get("user_id") or 0)
                    data = {"user_id": uid, "nickname": self.names.get(uid, str(uid)), "card": self.names.get(uid, ""), "role": "member"}
                    if uid == SELF and gid_ in self.muted:
                        data["shut_up_timestamp"] = int(self.muted[gid_])
                elif act == "get_friend_list":
                    data = [{"user_id": u, "nickname": self.names[u]} for u in (AMU, ADMIN)]
                elif act == "get_stranger_info":
                    uid = int(p.get("user_id") or 0)
                    data = {"user_id": uid, "nickname": self.names.get(uid, str(uid))}
                elif act == "get_msg":
                    data = self.store.get(int(p.get("message_id") or 0)) or {}
                elif act == "get_login_info":
                    data = {"user_id": SELF, "nickname": "大肥鱼"}
                await self.ws.send(json.dumps({"status": "ok", "retcode": 0, "data": data, "echo": echo}))
        except Exception:
            pass

    async def say(self, gid, uid, text, at_bot=False):
        self.mid += 1
        segs = []
        if at_bot:
            segs.append({"type": "at", "data": {"qq": str(SELF)}})
            segs.append({"type": "text", "data": {"text": " " + text}})
        else:
            segs.append({"type": "text", "data": {"text": text}})
        ev = {
            "post_type": "message", "message_type": "group", "sub_type": "normal", "message_id": self.mid, "group_id": gid,
            "user_id": uid, "self_id": SELF, "time": int(time.time()), "message": segs, "raw_message": text, "font": 0,
            "sender": {"user_id": uid, "nickname": self.names.get(uid, str(uid)), "card": self.names.get(uid, ""), "role": "member"},
        }
        self.store[self.mid] = dict(ev)
        await self.ws.send(json.dumps(ev, ensure_ascii=False))
        return self.mid

    async def say_private(self, uid, text):
        self.mid += 1
        ev = {
            "post_type": "message", "message_type": "private", "sub_type": "friend", "message_id": self.mid, "user_id": uid,
            "self_id": SELF, "time": int(time.time()), "message": [{"type": "text", "data": {"text": text}}], "raw_message": text,
            "font": 0, "sender": {"user_id": uid, "nickname": self.names.get(uid, str(uid))},
        }
        await self.ws.send(json.dumps(ev, ensure_ascii=False))

    async def ask_private(self, uid, text, timeout=8.0):
        t0 = time.time()
        await self.say_private(uid, text)
        return await self.wait(lambda s: s["gid"] == 0 and s["uid"] == uid, t0, timeout)

    async def wait(self, pred, since, timeout=8.0):
        end = time.time() + timeout
        while time.time() < end:
            got = [s for s in self.sent if s["t"] >= since and pred(s)]
            if got:
                return got
            self.new_sent.clear()
            try:
                await asyncio.wait_for(self.new_sent.wait(), max(0.05, end - time.time()))
            except asyncio.TimeoutError:
                pass
        return []

    async def ask(self, gid, uid, text, at_bot=True, timeout=8.0):
        t0 = time.time()
        await self.say(gid, uid, text, at_bot)
        return await self.wait(lambda s: s["gid"] == gid, t0, timeout)


def setup_root():
    env = dict(os.environ, ASTRBOT_ROOT=str(ROOT))
    subprocess.run([ASTRBOT, "init", "-y"], cwd=ROOT, env=env, check=True, capture_output=True)
    ign = shutil.ignore_patterns("__pycache__", "*.pyc", ".git", "tests")
    shutil.copytree(PLUGIN_SRC, ROOT / "data" / "plugins" / PNAME, ignore=ign)
    if AIGUARD_SRC:
        shutil.copytree(AIGUARD_SRC, ROOT / "data" / "plugins" / AIGUARD_SRC.name, ignore=ign)
    code = f"from astrbot.core.config.astrbot_config import AstrBotConfig;AstrBotConfig(config_path=r'{ROOT / 'data' / 'cmd_config.json'}')"
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, check=True, capture_output=True)
    p = ROOT / "data" / "cmd_config.json"
    cfg = json.loads(p.read_text(encoding="utf-8-sig"))
    cfg["platform"] = [{"id": "napcat", "type": "aiocqhttp", "enable": True, "ws_reverse_host": "127.0.0.1", "ws_reverse_port": WS_PORT, "ws_reverse_token": ""}]
    cfg["provider"] = [{"id": "fake", "type": "openai_chat_completion", "provider_type": "chat_completion", "enable": True,
                        "key": ["sk-fake"], "api_base": f"http://127.0.0.1:{LLM_PORT}/v1", "model": "fake-model", "timeout": 30}]
    cfg["admins_id"] = [str(ADMIN)]
    # E：只有 G2 开 AstrBot 自带的主动回复（概率 1 = 每句没 @ 的都接）—— 看「睡着了没 @ 的不回」是不是真的挡住了
    cfg["provider_ltm_settings"]["active_reply"] = {"enable": True, "method": "possibility_reply", "possibility_reply": 1.0, "whitelist": [str(G2)]}
    cfg["platform_settings"]["rate_limit"]["count"] = 1000
    cfg.setdefault("dashboard", {})["port"] = DASH_PORT
    cfg["dashboard"]["host"] = "127.0.0.1"
    cfg["dashboard"]["jwt_secret"] = SECRET
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def log_text():
    return (ROOT / "astrbot_stdout.log").read_text(encoding="utf-8", errors="replace")


async def main():
    setup_root()
    app = web.Application()
    app.router.add_post("/v1/chat/completions", chat_completions)
    app.router.add_get("/v1/models", models)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", LLM_PORT).start()
    base_env = dict(os.environ, ASTRBOT_ROOT=str(ROOT), DASHBOARD_PORT=str(DASH_PORT), PYTHONUNBUFFERED="1",
                    FATFISH_PROMISE_TEST="1", FATFISH_PROMISE_TEST_TICK="1",
                    PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""))
    log = open(ROOT / "astrbot_stdout.log", "w", encoding="utf-8")
    proc = subprocess.Popen([ASTRBOT, "run"], cwd=ROOT, env=base_env, stdout=log, stderr=subprocess.STDOUT)
    token = jwt.encode({"username": "astrbot", "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")
    hdr = {"Authorization": f"Bearer {token}"}
    api = f"http://127.0.0.1:{DASH_PORT}/api/v1/plugins/extensions/{PNAME}"
    http = aiohttp.ClientSession()

    async def state():
        for _ in range(3):
            try:
                async with http.get(f"{api}/state", headers=hdr) as r:
                    d = await r.json(content_type=None)
                return (d or {}).get("data") or {}
            except Exception:
                await asyncio.sleep(1)
        return {}

    async def action(**body):
        async with http.post(f"{api}/action", headers=hdr, json=body) as r:
            return r.status, await r.json(content_type=None)

    async def until(fn, timeout=12.0):
        end = time.time() + timeout
        st = {}
        while time.time() < end:
            st = await state()
            try:
                if fn(st):
                    return st
            except Exception:
                pass
            await asyncio.sleep(0.5)
        return st

    def task_of(st, what, who=AMU):
        return next((t for t in (st.get("pending") or []) + (st.get("past") or []) if t.get("what") == what and t.get("who") == str(who)), None)

    qq = FakeQQ()
    try:
        await qq.connect()
        await asyncio.sleep(5)
        text = log_text()
        check(PNAME in text and re.search(r"\[说到做到\] v\d+\.\d+\.\d+ 已启用", text) and "测试模式" in text and not real_tracebacks(text),
              "A AstrBot 起来了、插件加载了（测试模式能拨钟）、没有报错", text[-1500:])

        # ═════════ B 记进表 ═════════
        print("\n[B 机器人答应「明天早上 8 点提醒你」→ 表里有一条]")
        got = await qq.ask(G1, AMU, "明天早上8点提醒我交作业")
        check(got and "明天早上 8 点提醒你交作业" in got[-1]["text"], "机器人回了「好 明天早上 8 点提醒你交作业」", got)
        st = await until(lambda s: task_of(s, "提醒他交作业"))
        t1 = task_of(st, "提醒他交作业")
        check(t1 and t1["status"] == "pending" and t1["conv"] == f"napcat:GroupMessage:{G1}" and t1["via"] == "at", "表里有一条：给阿木、在这个群 @ 他、等着", t1)
        bj = time.gmtime(float(t1["due"]) + 8 * 3600) if t1 else None
        check(t1 and bj.tm_hour == 8 and bj.tm_min == 0 and 0 < float(t1["due"]) - st["now"] <= 30 * 3600 and "08:00" in t1["when"],
              f"时间是北京时间的明早 08:00（{t1 and t1['when']}）", t1)
        check(t1 and t1["say"] and t1["ask"] == "明天早上8点提醒我交作业", "原话出处记着（它说的、他说的）", t1)
        check(len(extract_calls) == 1 and "明天早上8点提醒我交作业" in extract_calls[0] and "好 明天早上 8 点提醒你交作业" in extract_calls[0],
              "抽取调了一次（给它看了他说的和机器人回的）", extract_calls)
        n_ex = len(extract_calls)
        await qq.ask(G1, AMU, "今天天气不错")
        await asyncio.sleep(1.5)
        check(len(extract_calls) == n_ex, "随便聊一句（没筛中）：不调抽取、不花钱")
        await qq.ask(G1, AMU, "在吗")
        last = chat_calls[-1]
        check("# 说到做到（插件记的状态，不是谁说的话）" in last["last"] and f"#{t1['n']}：{t1['when']}（北京时间）提醒他交作业" in last["last"]
              and "在这里 @ 他" in last["last"], "下一轮给模型的请求里带着「你答应他的、还没做的 #1」（编号、时间、怎么发）", last["last"][-700:])
        await qq.ask(G1, AMU, "还在吗")
        check("# 说到做到" not in chat_calls[-1]["history"], "那段状态是临时的：没进聊天记录（下一轮的历史里没有）", chat_calls[-1]["history"][-600:])

        # ═════════ C 到点 ═════════
        print("\n[C 拨钟到 8 点 → 主动发了一条、@ 了阿木]")
        t0 = time.time()
        code, d = await action(op="test_clock", offset=float(t1["due"]) - time.time() + 5)
        check(code == 200 and (d.get("data") or {}).get("offset"), "测试钩子：把插件的「现在几点」拨到 8 点", d)
        got = await qq.wait(lambda s: s["gid"] == G1 and str(AMU) in s["at"], t0, timeout=15)
        check(got and got[0]["text"].strip() == "交作业的时间到啦", "到点了：在群里主动发了「交作业的时间到啦」，前面 @ 了阿木", got)
        sp = speak_calls[-1] if speak_calls else ""
        check("答应了「阿木」：提醒他交作业" in sp and "他当时说：「明天早上8点提醒我交作业」" in sp and "你当时回的：" in sp
              and "现在是 " in sp and "前面自动 @ 他" in sp, "给模型写那句的状态：谁、答应了什么、原话、现在几点、插件会 @ 他", sp)
        check("你可以说" not in sp and "语气" not in sp, "E1：只给状态，不给台词")
        st = await until(lambda s: (task_of(s, "提醒他交作业") or {}).get("status") == "done")
        check((task_of(st, "提醒他交作业") or {}).get("status") == "done" and st["counts"]["done_today"] >= 1, "表里记成做了")
        n_sent = len([s for s in qq.sent if str(AMU) in s["at"]])
        await asyncio.sleep(3)
        check(len([s for s in qq.sent if str(AMU) in s["at"]]) == n_sent, "做完不会再发一遍")

        # ═════════ D 取消 / 指令 ═════════
        print("\n[D 「不用提醒了」→ 取消；指令]")
        await qq.ask(G1, AMU, "10分钟后提醒我喝水")
        st = await until(lambda s: task_of(s, "提醒他喝水"))
        t2 = task_of(st, "提醒他喝水")
        check(t2 and t2["status"] == "pending" and 590 <= float(t2["due"]) - st["now"] <= 620, "「10 分钟后提醒你喝水」记上了（插件时间 10 分钟后）", t2)
        n_ex = len(extract_calls)
        await qq.ask(G1, AMU, "算了 不用提醒了")
        st = await until(lambda s: (task_of(s, "提醒他喝水") or {}).get("status") == "cancelled")
        check((task_of(st, "提醒他喝水") or {}).get("status") == "cancelled", "他说不用了、机器人答应了 → 取消了", task_of(st, "提醒他喝水"))
        check(len(extract_calls) == n_ex + 1 and f"#{t2['n']} " in extract_calls[-1], "抽取时给模型看了他挂着的编号", extract_calls[-1][-300:])
        n_ex = len(extract_calls)
        await qq.ask(G1, XC, "不用提醒了")
        await asyncio.sleep(1.5)
        check(len(extract_calls) == n_ex, "小橙没挂着事：说「不用了」不调抽取（也改不了别人的）")
        await qq.ask(G1, AMU, "10分钟后提醒我喝水")
        st = await until(lambda s: any(t["what"] == "提醒他喝水" and t["status"] == "pending" for t in s.get("pending") or []))
        t3 = next((t for t in st.get("pending") or [] if t["what"] == "提醒他喝水"), None)
        got = await qq.ask(G1, AMU, "/说到做到", at_bot=False)
        check(got and f"#{t3['n']}" in got[-1]["text"] and "提醒他喝水" in got[-1]["text"], "/说到做到：看自己的（编号、时间、做什么）", got)
        got = await qq.ask(G1, XC, f"/说到做到 取消 {t3['n']}", at_bot=False)
        check(got and "不是你的" in got[-1]["text"], "别人取消不了", got)
        got = await qq.ask(G1, XC, "/说到做到 全部", at_bot=False)
        check(got and "只有管理员" in got[-1]["text"], "不是管理员看不了全部", got)
        got = await qq.ask(G1, ADMIN, "/说到做到 全部", at_bot=False)
        check(got and "提醒他喝水" in got[-1]["text"] and "阿木" in got[-1]["text"], "管理员看全部", got)
        got = await qq.ask(G1, AMU, f"/说到做到 取消 {t3['n']}", at_bot=False)
        check(got and "取消了" in got[-1]["text"], "本人能取消", got)
        st = await state()
        check(not any(t["what"] == "提醒他喝水" for t in st.get("pending") or []), "取消以后表里没有要做的了")

        # ═════════ E 我去睡了 ═════════
        print("\n[E 机器人说「我去睡了」→ 没叫它的不接；有人 @ 它就醒（v0.1.1 的默认）]")
        got = await qq.ask(G2, AMU, "大家好")
        check(bool(got), "（准备）有人 @ 机器人：回了（这个群有了对话，主动回复才接得上）", got)
        await asyncio.sleep(1.5)
        got = await qq.ask(G2, LW, "今天吃什么", at_bot=False)
        check(bool(got), "（对照）这个群开了主动回复：没 @ 的话平时会接", got)
        await asyncio.sleep(1.5)
        got = await qq.ask(G2, AMU, "我困了 晚安")
        check(got and "我去睡了" in got[-1]["text"], "机器人回「我去睡了 晚安」", got)
        st = await until(lambda s: any(h["kind"] == "sleep" and h["conv"].endswith(f":{G2}") for h in (s.get("holds") or {}).get("live") or []))
        hs = [h for h in (st.get("holds") or {}).get("live") or [] if h["conv"].endswith(f":{G2}")]
        check(hs and hs[0]["kind"] == "sleep" and hs[0]["left_min"] > 0, "约束记上了：这个群里在睡觉", hs)
        n_chat = len(chat_calls)
        check(not await qq.ask(G2, LW, "有人吗", at_bot=False, timeout=4), "没 @ 的话：不回（主动回复也被挡下）")
        check(len(chat_calls) == n_chat, "没叫它的这条连模型都没叫（不花钱）")
        got = await qq.ask(G2, XC, "你真睡了啊")
        check(bool(got), "一个人 @ 它一次 → 醒了，回了（默认：有人找就醒）", got)
        back = chat_calls[-1]["last"] if chat_calls else ""
        check("你刚回来" in back and "说了「我去睡了」" in back and "然后真的去睡了" in back and "是「小橙」叫回来的" in back,
              "醒来这一轮的状态：N 分钟前你说了「…」然后真的去睡了、谁叫醒的", back[-600:])
        check("这期间这里有 1 条要回的消息你没回" in back, "还写着这期间没回几条", back[-400:])
        await asyncio.sleep(1.5)
        got = await qq.ask(G2, LW, "现在呢", at_bot=False)
        check(bool(got), "醒了以后：没 @ 的又照常接", got)
        await asyncio.sleep(1.5)
        await qq.ask(G2, LW, "那再聊聊", at_bot=False)
        check("你刚回来" not in (chat_calls[-1]["last"] if chat_calls else ""), "「你刚回来」只说一次")

        # ═════════ F 别人家的 AI ═════════
        if AIGUARD_SRC:
            print("\n[F 跟认 AI 一起装：AI 约的事不进表、AI 叫不醒]")
            got = await qq.ask(G1, ADMIN, f"/认ai 标记 {BOTX}", at_bot=False)
            check(got and "标成别人家的 AI" in got[-1]["text"], "（准备）管理员把「隔壁的机器人」标成 AI", got)
            n_ex = len(extract_calls)
            got = await qq.ask(G1, BOTX, "明天早上8点提醒我交作业")
            check(got and "明天早上 8 点提醒你交作业" in got[-1]["text"], "它 @ 机器人约提醒：机器人照样回了", got)
            await asyncio.sleep(2.5)
            st = await state()
            check(not task_of(st, "提醒他交作业", BOTX), "跟 AI 约的事不进表")
            check(len(extract_calls) == n_ex, "也不为它花钱去抽")
            await asyncio.sleep(1.5)
            got = await qq.ask(G3, AMU, "晚安啦")
            check(got and "我去睡了" in got[-1]["text"], "（准备）另一个群里机器人说「我去睡了」")
            st = await until(lambda s: any(h["conv"].endswith(f":{G3}") for h in (s.get("holds") or {}).get("live") or []))
            await action(op="test_clock", offset=float(st.get("offset") or 0) + 150)  # 过了刚说完的那 2 分钟
            await asyncio.sleep(1.5)
            check(not await qq.ask(G3, BOTX, "醒醒", timeout=3.5), "别人家的 AI @：不算人，叫不醒")
            await asyncio.sleep(1.2)
            got = await qq.ask(G3, AZ, "醒醒")
            check(bool(got), "真人一 @ → 醒了", got)
            st = await state()
            hist = [b for b in (st.get("holds") or {}).get("hist") or [] if str(b.get("conv", "")).endswith(f":{G3}")]
            check(hist and hist[-1]["how"] == "woke" and hist[-1]["by"] == "阿珍", "记着是阿珍叫醒的（不是 AI）", hist)
        else:
            print("\n[F 跳过：旁边没有认 AI 插件]")

        # ═════════ G 面板 ═════════
        print("\n[G 面板接口]")
        await qq.ask(G1, AMU, "10分钟后提醒我喝水")
        st = await until(lambda s: any(t["what"] == "提醒他喝水" and t["status"] == "pending" for t in s.get("pending") or []))
        t4 = next((t for t in st.get("pending") or [] if t["what"] == "提醒他喝水"), None)
        check(t4 and "counts" in st and "holds" in st and "events" in st and st["tz"] == "北京时间", "GET state：表、约束、最近发生的事都在")
        code, d = await action(op="cancel", n=t4["n"])
        check(code == 200 and not any(t["n"] == t4["n"] for t in (d.get("data") or {}).get("pending") or []), "POST action：面板里取消", d.get("message"))
        await qq.ask(G2, AMU, "我也困了 晚安")
        st = await until(lambda s: any(h["conv"].endswith(f":{G2}") for h in (s.get("holds") or {}).get("live") or []))
        hid = next(h["id"] for h in st["holds"]["live"] if h["conv"].endswith(f":{G2}"))
        code, d = await action(op="end_hold", id=hid)
        check(code == 200 and not any(h["id"] == hid for h in (d.get("data") or {}).get("holds", {}).get("live", [])), "POST action：面板里让它回来")
        await asyncio.sleep(1.5)
        check(bool(await qq.ask(G2, LW, "回来了吗", at_bot=False)), "面板结束以后照常接")
        async with http.get(f"{api}/state") as r:
            check(r.status in (401, 403), f"没登录读不到（{r.status}）")
        async with http.get(f"http://127.0.0.1:{DASH_PORT}/api/v1/plugins/{PNAME}/views/panel", headers=hdr) as r:
            raw = json.dumps(await r.json(content_type=None), ensure_ascii=False)
        m = re.search(r'"([^"]*/_t/[^"]*)"', raw)
        check(r.status == 200 and m, "面板页 panel 认出来了", raw[:300])
        if m:
            u = m.group(1)
            async with http.get(u if u.startswith("http") else f"http://127.0.0.1:{DASH_PORT}{u}", headers=hdr) as r2:
                html = await r2.text()
            check(r2.status == 200 and "鱼力max · 说到做到" in html and "bridge-sdk.js" in html, "面板页 HTML 拿得到、AstrBot 插上了桥接脚本")

        # ═════════ I 私聊 ═════════
        print("\n[I 私聊里答应的：到点私聊发给他（不 @）]")
        got = await qq.ask_private(AMU, "10分钟后提醒我喝水")
        check(got and "10 分钟后提醒你喝水" in got[-1]["text"], "私聊里机器人回了「行 10 分钟后提醒你喝水」", got)
        st = await until(lambda s: any(t["what"] == "提醒他喝水" and t["conv"].endswith(f"FriendMessage:{AMU}") for t in s.get("pending") or []))
        pv = next((t for t in st.get("pending") or [] if t["what"] == "提醒他喝水" and t["conv"].endswith(f"FriendMessage:{AMU}")), None)
        check(pv and pv["scene"] == "private", "表里记着是私聊里答应的", pv)
        got = await qq.ask(G1, AMU, "在吗")
        check(f"#{pv['n']}：" not in (chat_calls[-1]["last"] if chat_calls else "") and "别的地方还答应过他 1 件" in chat_calls[-1]["last"],
              "群里说话时：私聊里答应的只说「别处还有 1 件」，内容不进群", chat_calls[-1]["last"][-500:])
        got = await qq.ask(G1, ADMIN, "/说到做到 全部", at_bot=False)
        check(got and "请私聊我" in got[-1]["text"] and "喝水" not in got[-1]["text"] and str(AMU) not in got[-1]["text"],
              "管理员在群里发 /说到做到 全部：只列本群的，别人私聊里的提醒和 QQ 号不贴进群", got)
        got = await qq.ask_private(ADMIN, "/说到做到 全部")
        check(got and "提醒他喝水" in got[-1]["text"] and f"私聊 {AMU}" in got[-1]["text"], "私聊里发：管理员看得到全部（带在哪、QQ 号）", got)
        t0 = time.time()
        await action(op="test_clock", offset=float(st.get("offset") or 0) + 11 * 60)
        got = await qq.wait(lambda s: s["gid"] == 0 and s["uid"] == AMU, t0, timeout=15)
        check(got and got[0]["text"] == "该喝水啦" and not got[0]["at"], "到点了：私聊发给他（不 @）", got)
        check(speak_calls and "私聊发给他" in speak_calls[-1], "给模型的状态写着插件会私聊发给他")

        # ═════════ J 没说时间的答应 ═════════
        print("\n[J 没说时间的答应：他下次来时让模型知道还欠着]")
        got = await qq.ask(G1, AMU, "帮我查一下明天的天气")
        check(got and "等会帮你查一下" in got[-1]["text"], "机器人回「等会帮你查一下」（没说时间）")
        st = await until(lambda s: any(p["what"] == "帮他查明天的天气" for p in s.get("promises") or []))
        pr = next((p for p in st.get("promises") or [] if p["what"] == "帮他查明天的天气"), None)
        check(pr and pr["kind"] == "promise" and pr["due"] is None, "记成没说时间的答应（不会到点去做）", pr)
        await asyncio.sleep(1.5)
        await qq.ask(G1, AMU, "那个呢")
        check("帮他查明天的天气" not in (chat_calls[-1]["last"] if chat_calls else ""), "刚答应完接着聊：不提（不然一句话里反复提醒）")
        await action(op="test_clock", offset=float(st.get("offset") or 0) + 35 * 60)
        await asyncio.sleep(1.5)
        await qq.ask(G1, AMU, "我回来了")
        last = chat_calls[-1]["last"] if chat_calls else ""
        check("前答应过他「帮他查明天的天气」（没说时间，插件不会到点去做）" in last and "他当时说「帮我查一下明天的天气」" in last,
              "过了半小时他再来：状态里写着还欠着这件（他当时说了什么）", last[-500:])
        st = await until(lambda s: any(p["what"] == "帮他查明天的天气" and p.get("shows") == 1 for p in s.get("promises") or []))
        check(any(p["what"] == "帮他查明天的天气" and p.get("shows") == 1 for p in st.get("promises") or []), "提过一次记一笔（最多提 3 次）")

        # ═════════ K 模型叫不通 ═════════
        print("\n[K 到点那会儿模型叫不通：发一句系统提示，照样 @ 他]")
        await qq.ask(G1, AMU, "10分钟后提醒我浇花")
        st = await until(lambda s: any(t["what"] == "提醒他浇花" and t["status"] == "pending" for t in s.get("pending") or []))
        check(any(t["what"] == "提醒他浇花" for t in st.get("pending") or []), "（准备）记上了「10 分钟后提醒他浇花」")
        t0 = time.time()
        await action(op="test_clock", offset=float(st.get("offset") or 0) + 11 * 60)
        got = await qq.wait(lambda s: s["gid"] == G1 and str(AMU) in s["at"], t0, timeout=40)
        check(got and got[0]["text"].strip().startswith("（系统提示）到点了：提醒他浇花（") and got[0]["text"].strip().endswith("答应的）"),
              "模型出错：插件发一句系统口吻的「（系统提示）到点了：……」，前面 @ 他", got)
        st = await until(lambda s: any(t["what"] == "提醒他浇花" and t["status"] == "done" for t in s.get("past") or []))
        check(any(t["what"] == "提醒他浇花" and t["status"] == "done" for t in st.get("past") or []), "算做了（不会再发一遍）")

        # ═════════ L 明确发不了 ═════════
        print("\n[L 明确发不了（机器人在群里被禁言了）：直接记成没做成，不叫模型、不发]")
        await qq.ask(G4, AMU, "10分钟后提醒我取快递")
        st = await until(lambda s: any(t["what"] == "提醒他取快递" and t["status"] == "pending" for t in s.get("pending") or []))
        check(any(t["what"] == "提醒他取快递" for t in st.get("pending") or []), "（准备）记上了「10 分钟后提醒他取快递」")
        qq.muted[G4] = time.time() + 6 * 3600
        n_speak, n_try = len(speak_calls), len([x for x in qq.send_tries if x[0] == G4])
        await action(op="test_clock", offset=float(st.get("offset") or 0) + 11 * 60)
        st = await until(lambda s: any(t["what"] == "提醒他取快递" and t["status"] == "missed" for t in s.get("past") or []), 15)
        miss = next((t for t in st.get("past") or [] if t["what"] == "提醒他取快递"), None)
        check(miss and miss["status"] == "missed" and miss["apology"] == "owed" and "禁言" in (miss.get("apo_why") or ""),
              "到点一看被禁言了（6 小时后才解）→ 直接记成没做成、欠一个道歉", miss)
        check(len(speak_calls) == n_speak and len([x for x in qq.send_tries if x[0] == G4]) == n_try, "回退检查：没叫模型写、也没往群里硬发")
        qq.muted.pop(G4, None)

        # ═════════ M 发不出去：重试只重发 ═════════
        print("\n[M 发不出去（QQ 拒收）：重试只重发写好的那句，越隔越久，补上了照样 @ 他]")
        await qq.ask(G5, AMU, "10分钟后提醒我开会")
        st = await until(lambda s: any(t["what"] == "提醒他开会" and t["status"] == "pending" for t in s.get("pending") or []))
        check(any(t["what"] == "提醒他开会" for t in st.get("pending") or []), "（准备）记上了「10 分钟后提醒他开会」")
        qq.fail_groups.add(G5)
        n_try0 = len([x for x in qq.send_tries if x[0] == G5])  # 机器人刚才回他那句不算
        off = float(st.get("offset") or 0) + 11 * 60
        n_speak = len([x for x in speak_calls if "开会" in x])
        await action(op="test_clock", offset=off)
        for step in (70, 130, 310):  # 插件的钟往前拨：1 分钟、2 分钟、5 分钟后各该试一次
            await asyncio.sleep(2.5)
            off += step
            await action(op="test_clock", offset=off)
        await asyncio.sleep(2.5)
        tries = len([x for x in qq.send_tries if x[0] == G5]) - n_try0
        check(tries == 4, f"拒收期间：到点试 1 次 + 1、2、5 分钟后各 1 次 = {tries} 次（不是每分钟一次）", qq.send_tries[-6:])
        check(len([x for x in speak_calls if "开会" in x]) == n_speak + 1, "回退检查：那句只叫模型写了 1 次（重试只重发）")
        qq.fail_groups.discard(G5)
        t0 = time.time()
        off += 610
        await action(op="test_clock", offset=off)
        got = await qq.wait(lambda s: s["gid"] == G5 and str(AMU) in s["at"], t0, timeout=15)
        check(got and got[0]["text"].strip() == "该去开会啦（第1次写的）", "QQ 好了：补发的是第一次写好的那句，照样 @ 他", got)
        lines = [x for x in log_text().splitlines() if "群里没发出去（QQ 拒收了）" in x]
        check(len(lines) == 1, f"回退检查：同一件事同一个原因的日志 10 分钟最多一行（拒收 4 次，日志 {len(lines)} 行）", lines[-4:])

        # ═════════ H 重启 ═════════
        print("\n[H 重启：表还在；过点很久的记成没做成、欠道歉；宽限内的补上并写明晚了多久]")
        await qq.ask(G1, AMU, "10分钟后提醒我喝水")
        await asyncio.sleep(1.2)
        await qq.ask(G1, AMU, "100分钟后提醒我收衣服")
        st = await until(lambda s: any(t["what"] == "提醒他收衣服" for t in s.get("pending") or [])
                         and any(t["what"] == "提醒他喝水" and t["status"] == "pending" for t in s.get("pending") or []))
        water = next((t for t in st.get("pending") or [] if t["what"] == "提醒他喝水"), None)
        clothes = next((t for t in st.get("pending") or [] if t["what"] == "提醒他收衣服"), None)
        check(water and clothes, "（准备）两件：10 分钟后喝水、100 分钟后收衣服", (water, clothes))
        offset = float(st.get("offset") or 0) + 120 * 60  # 重启以后插件的钟再快 2 小时：喝水晚了 110 分钟、收衣服晚了 20 分钟
        proc.terminate()
        proc.wait(20)
        await qq.ws.close()
        n_speak = len(speak_calls)
        env2 = dict(base_env, FATFISH_PROMISE_TEST_OFFSET=str(offset))
        proc = subprocess.Popen([ASTRBOT, "run"], cwd=ROOT, env=env2, stdout=log, stderr=subprocess.STDOUT)
        qq2 = FakeQQ()
        t0 = time.time()
        await qq2.connect()
        st = await until(lambda s: any(t["what"] == "提醒他喝水" and t["status"] == "missed" for t in s.get("past") or []), 20)
        miss = next((t for t in st.get("past") or [] if t["what"] == "提醒他喝水" and t["status"] == "missed"), None)
        check(miss and miss["apology"] == "owed" and "没开着" in (miss.get("apo_why") or ""), "开机时晚了快 2 小时的：不补，直接记成没做成、欠一个道歉", miss)
        check(any(t["what"] == "提醒他交作业" and t["status"] == "done" for t in st.get("past") or []), "重启以后表还在（之前做过的那件还记着）")
        got = await qq2.wait(lambda s: s["gid"] == G1 and str(AMU) in s["at"], t0, timeout=40)
        check(got and "收衣服" in got[0]["text"], "晚了 20 分钟的（宽限内）：开机后补上了，照样 @ 他（QQ 一连上就发）", got)
        late = speak_calls[n_speak:]
        check(late and re.search(r"已经晚了 2\d 分钟（到点那会儿机器人没开着", late[-1]) and "收衣服" in late[-1],
              "补的时候状态里写着晚了多久、为什么晚（机器人没开着，不是报错原文）", late[-1:])
        check(not any("喝水" in x for x in late), "晚过宽限的那件没去补")
        await asyncio.sleep(1.5)
        got = await qq2.ask(G1, AMU, "在吗")
        last = chat_calls[-1]["last"] if chat_calls else ""
        check(f"#{miss['n']}「提醒他喝水」" in last and "没做成（到点那会儿机器人没开着" in last and "还欠他一个道歉" in last,
              "他再来找机器人：状态里写着欠一个道歉（原因照实写）", last[-600:])
        st = await until(lambda s: any(t["what"] == "提醒他喝水" and t.get("apology") == "told" for t in s.get("past") or []))
        check(any(t["what"] == "提醒他喝水" and t.get("apology") == "told" for t in st.get("past") or []), "说过一次就算道过了")
        await asyncio.sleep(1.5)
        await qq2.ask(G1, AMU, "还在吗")
        check("还欠他一个道歉" not in (chat_calls[-1]["last"] if chat_calls else ""), "下一轮不再提道歉")
        check((ROOT / "data" / "plugin_data" / PNAME / "promise.json").exists(), "存档在 data/plugin_data/<插件>/promise.json")
        text = log_text()
        check("[说到做到] 记下 #" in text and "做了" in text, "日志里有「记下」「做了」")
        bad_tb = real_tracebacks(text)
        check(not bad_tb, "整个过程 AstrBot 日志里没有 Traceback", bad_tb[:1])
        await qq2.ws.close()
    finally:
        await http.close()
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:
            proc.kill()
        await runner.cleanup()
        log.close()

    ok = sum(1 for c, _ in RES if c)
    bad = [m for c, m in RES if not c]
    print("\n" + "=" * 60)
    print(f"  结果：{ok} 项过了" + (f"，{len(bad)} 项没过" if bad else "，全过"))
    for m in bad:
        print("    -", m)
    print("=" * 60)
    if KEEP or bad:
        print("AstrBot 目录留着：", ROOT)
    else:
        shutil.rmtree(ROOT, ignore_errors=True)
    sys.exit(1 if bad else 0)


asyncio.run(main())
