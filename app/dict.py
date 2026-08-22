# -*- coding: utf-8 -*-
"""本地英汉词典（ECDICT 数据裁剪版）：查询词的词典义项列表。

数据文件：assets/dict.csv，格式：word<TAB>义项1|义项2|...（义项来自 ECDICT translation 字段）
义项列表用于约束 AI：中文义项必须出自词典，AI 只做"句子→义项"归类，不自己编义项。
"""
import csv
from pathlib import Path

from . import config
from .lemmatizer import lemmatize

_DICT: dict[str, list[str]] = {}
_LOADED = False


def dict_path() -> Path:
    return config.resource_path("assets/dict.csv")


def load() -> bool:
    """加载词典（进程内只加载一次）。成功返回 True。"""
    global _LOADED
    if _LOADED:
        return bool(_DICT)
    p = dict_path()
    if p.exists():
        try:
            with p.open(encoding="utf-8") as f:
                for row in csv.reader(f, delimiter="\t"):
                    if len(row) >= 2 and row[0] and row[1]:
                        defs = [d.strip() for d in row[1].split("|") if d.strip()]
                        if defs:
                            _DICT[row[0]] = defs
            _LOADED = True
        except Exception:
            _DICT.clear()
    _LOADED = True
    return bool(_DICT)


def lookup(word: str, max_defs: int = 12) -> list[str] | None:
    """查词典义项。先查原词，再查词形还原后的原形。查不到返回 None。"""
    if not load():
        return None
    w = word.lower().strip()
    for key in (w, lemmatize(w)):
        if key in _DICT:
            return _DICT[key][:max_defs]
    return None


def all_words() -> list[str]:
    """返回词典全部词条（供输入框自动补全）。"""
    if not load():
        return []
    return sorted(_DICT.keys())


def has_word(word: str) -> bool:
    return lookup(word) is not None
