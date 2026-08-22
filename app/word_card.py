# -*- coding: utf-8 -*-
"""词条卡片：open-dictionary 裁剪数据（assets/word_cards.json）的本地查询。

卡片内容（全部离线、零 AI 费用）：
- memory_hook  记忆主线（一句话帮记住主要义项）
- summary      词条摘要
- etymology    词源/词根注记
- usage        用法说明（搭配、语域、易错点）
- meanings     义项列表 [{pos, priority, gloss, explain}]，gloss 与
               dict.csv 的义项文字同源，可按文字匹配取 explain（柯林斯式解释）
"""
import json
import re
import unicodedata
from pathlib import Path

from . import config

_CARDS: dict[str, dict] | None = None
_LOADED = False


def cards_path() -> Path:
    return config.resource_path("assets/word_cards.json")


def load() -> bool:
    """加载词条卡片（进程内只加载一次）。成功返回 True。"""
    global _CARDS, _LOADED
    if _LOADED:
        return _CARDS is not None
    p = cards_path()
    if p.exists():
        try:
            with p.open(encoding="utf-8") as f:
                _CARDS = json.load(f)
        except Exception:
            _CARDS = None
    _LOADED = True
    return _CARDS is not None


def _norm(s: str) -> str:
    """归一化：去词性前缀、空白、标点，只留中文和字母（用于义项文字匹配）。"""
    t = unicodedata.normalize("NFKC", s or "").lower()
    t = re.sub(r"^[a-z]+\.[\s]*", "", t)          # 去词性前缀 adj./n./v.
    t = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", t)  # 只留字母数字中文
    return t


def lookup(word: str) -> dict | None:
    """查词条卡片。返回原始 card dict；查不到返回 None。"""
    if not load():
        return None
    w = word.lower().strip()
    return _CARDS.get(w) or _CARDS.get(_norm(word)) or None


def match_explain(card: dict, meaning_text: str) -> str:
    """按义项文字匹配卡片里该义项的中文解释（柯林斯式一句话解释）。
    匹配失败返回空串（界面不显示解释）。"""
    if not card:
        return ""
    target = _norm(meaning_text)
    if not target:
        return ""
    for m in card.get("meanings", []):
        if _norm(m.get("gloss", "")) == target:
            return str(m.get("explain") or "").strip()
    # 宽匹配：义项文字包含某个 gloss（如「n. 代理人（搜索代理）」→「n. 代理人」）；
    # 限制最小长度，避免单字义项误配
    for m in card.get("meanings", []):
        g = _norm(m.get("gloss", ""))
        if len(g) >= 2 and g and (g in target or target in g):
            return str(m.get("explain") or "").strip()
    return ""
