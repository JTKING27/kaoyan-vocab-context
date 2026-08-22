# -*- coding: utf-8 -*-
"""DeepSeek 官方 tokenizer（离线计算 token 数）。

用途：预热前离线估算每个词的输入 token 与预计花费（事前成本预估/
预算控制），不依赖 API 调用。token 用量仍以 API 返回的 usage 为准。

数据来源：官方 api-docs.deepseek.com/quick_start/token_usage 提供的
deepseek_tokenizer.zip，解压到 corpus/_raw/deepseek_tokenizer/（不入 git）。
找不到时功能自动降级（返回 None，预热预估跳过）。
"""
from pathlib import Path

from . import config

_TOK = None
_LOADED = False


def tokenizer_dir() -> Path | None:
    p = config.ROOT / "corpus" / "_raw" / "deepseek_tokenizer"
    return p if (p / "tokenizer.json").exists() else None


def load():
    """加载官方 tokenizer（进程内一次）。成功返回 tokenizer 对象，否则 None。"""
    global _TOK, _LOADED
    if _LOADED:
        return _TOK
    _LOADED = True
    d = tokenizer_dir()
    if d is None:
        return None
    try:
        from transformers import AutoTokenizer
        _TOK = AutoTokenizer.from_pretrained(str(d), trust_remote_code=True)
    except Exception:
        _TOK = None
    return _TOK


def count_tokens(text: str) -> int | None:
    """离线计算一段文本的 token 数；tokenizer 不可用时返回 None。"""
    tok = load()
    if tok is None:
        return None
    try:
        return len(tok.encode(text or ""))
    except Exception:
        return None
