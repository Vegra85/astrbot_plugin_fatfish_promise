# -*- coding: utf-8 -*-
"""存档：plugin_data/astrbot_plugin_fatfish_promise/promise.json，重启不丢。

    {"schema": 1, "table": {承诺表}, "holds": {约束}, "events": [最近发生的事], "stats": {今天的数}}

写的时候先写 .tmp 再换过去：写到一半断电也不会把整张表写坏。读坏了的文件不覆盖，先改名留着。
"""

import json
import time
from pathlib import Path

SCHEMA = 1


class Store:
    def __init__(self, path, warn=None, clock=time.time):
        self.path = Path(path)
        self.warn = warn or (lambda m: None)
        self.clock = clock
        self.data = self._read()
        self.data.setdefault("schema", SCHEMA)
        for k in ("table", "holds", "stats"):
            if not isinstance(self.data.get(k), dict):
                self.data[k] = {}
        if not isinstance(self.data.get("events"), list):
            self.data["events"] = []
        self._saved_at = 0.0
        self.dirty = False

    def _read(self):
        if not self.path.exists():
            return {}
        try:
            d = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if isinstance(d, dict):
                return d
        except Exception as e:  # 坏了：改名留着，别拿空表覆盖掉（里面可能还有没做的事）
            self.warn(f"存档读不了（{e!r}），改名留着、从空表开始")
        try:
            self.path.replace(self.path.with_suffix(f".broken-{int(time.time())}.json"))
        except Exception:
            pass
        return {}

    def event(self, kind, text, now=None):
        self.data["events"] = self.data["events"][-99:] + [
            {"t": int(now if now is not None else self.clock()), "kind": kind, "text": str(text)[:200]}
        ]
        self.dirty = True

    def save(self, force=False):
        """有变化就尽快存（AstrBot 被直接关掉时不会调 terminate）：最多 2 秒存一次，剩下的后台补"""
        now = time.time()
        if not force and now - self._saved_at < 2:
            self.dirty = True
            return False
        self._saved_at = now
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)
            self.dirty = False
            return True
        except Exception as e:
            self.warn(f"存档失败：{e!r}")
            self.dirty = True
            return False
