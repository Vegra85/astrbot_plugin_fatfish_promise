#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文件和规矩的检查（不用装 AstrBot）：python tests/test_files.py [插件目录 默认上一层]
配置说明和代码里的默认值对得上、每项都有说明和提示；metadata / LICENSE / CHANGELOG / README 的格式；
Python 3.10 能跑；core/ 不 import AstrBot；钩子都兜着异常、停事件 / 清结果之前先替天使之心收口、不改系统提示；
文件里没有像 QQ 号 / 群号那样的长数字、没有外部链接（隐私）。"""

import ast
import json
import re
import sys
from pathlib import Path

d = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(d))
from core import hold as hd  # noqa: E402
from core import table as tb  # noqa: E402

RES = []


def check(c, m, why=""):
    RES.append((bool(c), m))
    print(("  [过]   " if c else "  [没过] ") + m + ("" if c or not why else f"\n           {str(why)[:800]}"))


schema = json.loads((d / "_conf_schema.json").read_text(encoding="utf-8"))
main_src = (d / "main.py").read_text(encoding="utf-8")

print("[1 配置]")
check(list(schema) == ["basic", "extract", "tasks", "hold", "wake"], "五组：总开关 / 抽取 / 到点的事 / 约束 / 叫醒", list(schema))
bad = []
for g, v in schema.items():
    if not v.get("description") or v.get("type") != "object":
        bad.append(g)
    for k, s in (v.get("items") or {}).items():
        if not s.get("description") or not s.get("hint") or s.get("type") not in ("bool", "int", "float", "string", "list", "text"):
            bad.append(f"{g}.{k}")
        dv = s.get("default")
        want = {"bool": bool, "int": int, "float": (int, float), "string": str, "list": list, "text": str}.get(s.get("type"))
        if want and (not isinstance(dv, want) or (s.get("type") == "int" and isinstance(dv, bool))):
            bad.append(f"{g}.{k} 默认值类型")
        if "options" in s and dv not in s["options"]:
            bad.append(f"{g}.{k} 默认值不在选项里")
check(not bad, "每一项都有 description 和 hint、默认值类型对", bad)
T, Hd = schema["tasks"]["items"], schema["hold"]["items"]
check(all(T[k]["default"] == tb.DEFAULTS[k] for k in ("max_pending", "max_daily", "admin_unlimited", "grace_min")), "到点的事：配置默认值 = 代码默认值")
check(all(Hd[k]["default"] == hd.DEFAULTS[k] for k in Hd), "约束：配置默认值 = 代码默认值", {k: (Hd[k]["default"], hd.DEFAULTS.get(k)) for k in Hd})
W = schema["wake"]["items"]
check(all(W[k]["default"] == hd.DEFAULTS["wake_" + k] for k in W), "叫醒：配置默认值 = 代码默认值")
runner_src = (d / "modules" / "runner.py").read_text(encoding="utf-8")
used = set(re.findall(r'(?:self|h)\.c\("(\w+)", "(\w+)"', main_src + runner_src))
used |= {("hold", k) for k in re.findall(r'\bh\("(\w+)"', main_src)} | {("wake", k) for k in re.findall(r'\bw\("(\w+)"', main_src)}
declared = {(g, k) for g, v in schema.items() for k in v["items"]}
check(used == declared, "代码里读的配置项 = 配置说明里写的（不多不少）", (used ^ declared))
lits = re.findall(r'(?:self|h)\.c\("(\w+)", "(\w+)", ("[^"]*"|True|False|\d+|\[\])\)', main_src + runner_src)
mism = [(g, k, lit) for g, k, lit in lits if json.dumps(schema[g]["items"][k]["default"]) != {"True": "true", "False": "false"}.get(lit, lit)]
check(not mism, "代码里写的默认值 = 配置说明的默认值", mism)
check(schema["tasks"]["items"]["fallback"]["default"] is True and schema["tasks"]["items"]["group_via"]["default"] == "at",
      "主动发的消息最克制：群里在原地 @，模型叫不通才发系统提示（能关）")

print("\n[2 metadata / LICENSE / CHANGELOG]")
meta = {}
for line in (d / "metadata.yaml").read_text(encoding="utf-8").splitlines():
    m = re.match(r"^(\w+):\s*(.*)$", line)
    if m:
        meta[m.group(1)] = m.group(2).strip().strip('"')
tags = re.findall(r"^\s+-\s+(.+)$", (d / "metadata.yaml").read_text(encoding="utf-8"), re.M)
check(meta.get("name") == "astrbot_plugin_fatfish_promise" == d.name or meta.get("name") == "astrbot_plugin_fatfish_promise", "name")
check(meta.get("display_name") == "鱼力max · 说到做到", "display_name")
first = meta.get("desc", "").split("。")[0]
check(len(first) <= 40 and meta.get("desc", "").endswith("细节和配置见 README。"), f"desc：第一句 {len(first)} 字（≤ 40）写痛点，最后「细节和配置见 README。」")
check(0 < len(meta.get("short_desc", "")) <= 20, f"short_desc {len(meta.get('short_desc', ''))} 字（≤ 20）")
check(meta.get("version") == "v0.1.0" and meta.get("author") == "Vegra85" and meta.get("license") == "MIT", "版本 / 作者 / 许可")
check(meta.get("repo") == "https://github.com/Vegra85/astrbot_plugin_fatfish_promise" and meta.get("social_link") == "https://github.com/Vegra85", "repo / social_link")
check(meta.get("category") == "生活" and meta.get("astrbot_version") == ">=4.29,<5", "category 生活、AstrBot ≥ 4.29")
check("aiocqhttp" in tags and {"鱼力max", "大肥鱼", "DeepSeek"} <= set(tags), "只支持 aiocqhttp；tags 有鱼力max、大肥鱼、DeepSeek", tags)
check("Copyright (c) 2026 Vegra85" in (d / "LICENSE").read_text(encoding="utf-8"), "LICENSE：MIT，2026 Vegra85")
cl = (d / "CHANGELOG.md").read_text(encoding="utf-8")
check(cl.startswith("# 更新日志") and "## v0.1.0（2026-11-08）" in cl, "CHANGELOG 格式")
check(not (d / "requirements.txt").exists(), "不要第三方库（没有 requirements.txt）")

print("\n[3 README 第一屏]")
rd = (d / "README.md").read_text(encoding="utf-8")
check(rd.startswith("# 鱼力max · 说到做到\n"), "标题")
check("**鱼力max 系列（鱼有分寸）**" in rd and "[说到做到](https://github.com/Vegra85/astrbot_plugin_fatfish_promise)" in rd, "系列那一行带上自己")
order = ["## 30 秒装好", "## 和哪些插件能一起装", "## 常见问题", "## 工作原理", "## 全部配置", "## 已知限制", "## 测试", "## 鱼力max 全家福"]
pos = [rd.find(x) for x in order]
check(all(p > 0 for p in pos) and pos == sorted(pos), "章节照模板的顺序", list(zip(order, pos, strict=False)))
check(rd.rstrip().endswith("觉得有用请点个 Star，市场里点个「喜欢」—— 这两样决定新用户能不能看到它。"), "最后一句")
check("一句话：" in rd[: rd.find("## 30 秒装好")], "第一屏有「一句话」")

print("\n[4 Python 3.10 / core 不依赖 AstrBot]")
pys = sorted(p for p in d.rglob("*.py") if "__pycache__" not in p.parts)
bad = []
for p in pys:
    src = p.read_text(encoding="utf-8")
    try:
        ast.parse(src, feature_version=(3, 10))
    except SyntaxError as e:
        bad.append(f"{p.name}: {e}")
    if p.name == "test_files.py":
        continue  # 这个文件里列着这些写法（要查的名单），不算用了
    for pat in (r"\btomllib\b", r"typing import .*\bSelf\b", r"datetime\.UTC\b", r"from datetime import .*\bUTC\b", r"TaskGroup", r"asyncio\.timeout\(", r"except\s*\*", r"ExceptionGroup"):
        if re.search(pat, src):
            bad.append(f"{p.name}: {pat}")
check(not bad, f"{len(pys)} 个 .py 都是 3.10 能跑的写法", bad)
core_bad = [p.name for p in (d / "core").glob("*.py") if re.search(r"^\s*(from|import)\s+astrbot", p.read_text(encoding="utf-8"), re.M)]
check(not core_bad, "core/ 不 import astrbot（单测不装 AstrBot 也能跑）", core_bad)

print("\n[5 钩子的规矩]")
tree = ast.parse(main_src)
hooks = []
for node in ast.walk(tree):
    if isinstance(node, ast.AsyncFunctionDef):
        decs = [ast.unparse(x) for x in node.decorator_list]
        if any(x.startswith("filter.") and "command" not in x for x in decs):
            body = [b for b in node.body if not (isinstance(b, ast.Expr) and isinstance(getattr(b, "value", None), ast.Constant))]
            hooks.append((node.name, bool(body) and isinstance(body[0], ast.Try)))
check(len(hooks) == 4 and all(ok for _, ok in hooks), "4 个钩子的整个身子都包在 try 里（出错只记日志，不冒到 AstrBot）", hooks)
lines = main_src.splitlines()
stops = [i for i, x in enumerate(lines) if "event.stop_event()" in x or "event.clear_result()" in x]
check(stops and all(any("release_angel(" in lines[j] for j in range(max(0, i - 3), i)) for i in stops),
      f"停事件 / 清结果的 {len(stops)} 处，前面都先替天使之心收口", [lines[i].strip() for i in stops])
check("mark_as_temp()" in main_src and "extra_user_content_parts.append(TextPart(" in main_src, "状态用临时段加（不进聊天记录）")
check("system_prompt" not in main_src.replace("system_prompt=system", ""), "不改系统提示（破坏缓存）")
pr = {k: eval(v, {"sys": sys}) for k, v in re.findall(r"^(\w+_PRIORITY) = (.+)$", main_src, re.M)}
check(1000000 < pr["GATE_PRIORITY"] < sys.maxsize, "挡消息排在认 AI（sys.maxsize）之后、活人感攒一攒（1000000）之前")
check(pr["DECO_PRIORITY"] < 99999 and pr["SENT_PRIORITY"] < 0, "发送前那步排在表情包插件（99999）之后：它加完图再拿掉")
check("import astrbot_plugin" not in main_src and "from astrbot_plugin" not in main_src, "不 import 别的插件（只用 duck typing）")
check("TEST_ENV" in main_src and 'op == "test_clock" and self.test' in main_src, "拨钟只在设了测试环境变量时才让用")

print("\n[6 隐私：没有像真 QQ 号 / 群号的长数字、没有外部链接]")
files = [p for p in d.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix in (".py", ".md", ".json", ".yaml", ".html", ".txt")]
long_nums, links = [], []
for p in files:
    s = p.read_text(encoding="utf-8")
    for m in re.finditer(r"(?<![\d.])\d{6,}(?![\d.])", s):
        if m.group(0) not in ("1000000",) and "0123456789" not in m.group(0).translate(str.maketrans("０１２３４５６７８９", "0123456789")):
            long_nums.append(f"{p.relative_to(d)}: {m.group(0)}")
    for m in re.finditer(r"https?://[^\s)\"'<>]+", s):
        u = m.group(0)
        if not (u.startswith("https://github.com/Vegra85") or u.startswith("http://127.0.0.1") or "example.invalid" in u):
            links.append(f"{p.relative_to(d)}: {u}")
check(not long_nums, "没有 6 位以上的数字（测试里的 QQ 号是 10001 这类、群号是 7001 这类）", long_nums[:10])
check(not links, "链接只有作者自己的仓库（和测试里的本机地址）", links[:10])

ok = sum(1 for c_, _ in RES if c_)
bad = [m for c_, m in RES if not c_]
print("\n" + "=" * 50 + f"\n  结果：{ok} 项过了" + (f"，{len(bad)} 项没过" if bad else "，全过"))
for m in bad:
    print("    -", m)
sys.exit(1 if bad else 0)
