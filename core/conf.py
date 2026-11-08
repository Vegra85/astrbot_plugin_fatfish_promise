# -*- coding: utf-8 -*-
"""配置分组：_conf_schema.json 分了几组（basic / extract / tasks / hold / wake），这里包一层当扁平字典读。
总配置是 AstrBotConfig（dict）或者普通 dict；缺了分组、缺了项、填了乱七八糟的值都退回默认值，不报错。"""


class Sub:
    def __init__(self, root, name):
        self._root = root if root is not None else {}
        self._name = name

    def _d(self):
        try:
            v = self._root.get(self._name)
        except Exception:
            v = None
        return v if isinstance(v, dict) else {}

    def get(self, key, default=None):
        return self._d().get(key, default)


def truthy(v, default=True):
    """开关：True/False，也认「开 / on / 1 / true」这些字符串；没填用默认"""
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on", "开")


def num(v, default, lo=None, hi=None):
    """数字配置：填错了退回默认值；超出范围夹回去"""
    try:
        x = type(default)(v)
    except (TypeError, ValueError):
        x = default
    if lo is not None and x < lo:
        x = type(default)(lo)
    if hi is not None and x > hi:
        x = type(default)(hi)
    return x


def id_list(v):
    """群号 / QQ 号列表：list 或者「7001，7002 7003」这种字符串都认"""
    if isinstance(v, str):
        v = v.replace("，", ",").replace(" ", ",").split(",")
    return {str(x).strip() for x in (v or []) if str(x).strip()}
