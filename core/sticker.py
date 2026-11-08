# -*- coding: utf-8 -*-
"""「不发表情包」：发出去之前把表情包那种图拿掉（不依赖 AstrBot，组件用 duck typing 看）。

只拿表情包：截图、画的图、别的插件发的普通图片都不动。怎么认：
  - 表情包插件（meme_manager）在这一轮登记过的图（它把要发的表情图记在事件上）；
  - 图片的路径里有 meme / sticker / emoji / 表情 这类字样（表情包插件都放在这种文件夹里）；
  - QQ 自己标成表情包的图（sub_type = 1）。
表情包插件有时不放在这一条消息里、而是这一轮发完以后另外发：它在事件上留的「待会儿要发的表情」也一起清掉。
"""

import copy
import re

STICKER_PATH = re.compile(r"meme|sticker|emoji|emoticon|表情", re.I)
# meme_manager 在事件上留的「这一轮要配的表情」：清掉就不会在发完以后另外补发
MEME_EXTRAS = ("meme_manager_pending_images", "found_emotions", "meme_manager_semantic_selected_ids")
MEME_REGISTRY = "meme_manager_delivery_registry"


def is_sticker(comp, registry=None):
    if type(comp).__name__ != "Image":
        return False
    reg = registry if isinstance(registry, dict) else {}
    if reg and (id(comp) in reg or str(getattr(comp, "file", "") or "") in reg):
        return True
    for attr in ("path", "file", "url"):
        v = str(getattr(comp, attr, "") or "")
        if v and not v.startswith("base64://") and STICKER_PATH.search(v):
            return True
    sub = getattr(comp, "subType", None)
    if sub is None:
        sub = getattr(comp, "sub_type", None)
    return str(sub) == "1"


STICKER_TOOL = re.compile(r"meme|sticker|emoji|表情", re.I)


def drop_tools(req):
    """这一轮请求里「找表情 / 发表情」那种工具拿掉（表情包插件让模型自己调工具发图时，发送前那一步拦不到）。
    只改这一轮的请求：工具集先复制一份再删，别动到共享的那份 → 拿掉了几个"""
    ts = getattr(req, "func_tool", None)
    try:
        names = [n for n in (ts.names() if ts is not None else []) if STICKER_TOOL.search(str(n))]
    except Exception:
        return 0
    if not names:
        return 0
    new = copy.copy(ts)
    if hasattr(ts, "tools"):
        new.tools = list(ts.tools)
    for n in names:
        try:
            new.remove_tool(n)
        except Exception:
            pass
    req.func_tool = new
    return len(names)


def strip(chain, registry=None):
    """→ (拿掉表情包以后的组件列表, 拿掉了几个)"""
    keep, n = [], 0
    for c in list(chain or []):
        if is_sticker(c, registry):
            n += 1
        else:
            keep.append(c)
    return keep, n
