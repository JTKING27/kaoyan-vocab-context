# -*- coding: utf-8 -*-
"""本地词根词缀表：随查词逐渐积累（AI 拆解结果回填），
之后新词优先用本地表保守拆解——拆得出就不再让 AI 输出（省钱），
拆不出的才问 AI 并继续回填，表随时间越用越全。

词素表：data/affix_table.json（运行时生成，不入 git，像缓存一样随机器走）
结构：{morpheme: {"type": "prefix|suffix|root", "gloss": "中文含义",
                 "words": [出现过的例词...]}}
"""
import json
import re

from . import config

_TABLE = None
_PATH = config.DATA_DIR / "affix_table.json"
_GLOSS_MAX = 24  # 回填时 gloss 最长保留长度


def load() -> dict:
    global _TABLE
    if _TABLE is None:
        if _PATH.exists():
            try:
                _TABLE = json.loads(_PATH.read_text(encoding="utf-8"))
            except Exception:
                _TABLE = {}
        else:
            _TABLE = {}
    return _TABLE


def save():
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(_TABLE, ensure_ascii=False, indent=1),
                     encoding="utf-8")


def count() -> int:
    return len(load())


def fmt(parts) -> str:
    """本地拆解 parts -> 展示字符串："ex- 向外 + cept 拿取 + -ion 名词后缀"。"""
    out = []
    for p in parts:
        text = p["morpheme"]
        if p.get("gloss"):
            text += " " + p["gloss"]
        out.append(text.strip())
    return " + ".join(out)


def _norm(m: str) -> str:
    """词素去掉连字符后的小写形式（ex- -> ex，-tion -> tion）。"""
    return m.replace("-", "").lower().strip()


def classify(m: str) -> str:
    if m.endswith("-"):
        return "prefix"
    if m.startswith("-"):
        return "suffix"
    return "root"


def learn(word: str, affix_str: str) -> int:
    """把 AI 返回的词根词缀串解析并回填词素表。返回本次新增词素数。
    affix_str 格式（提示词约束）："ex- 向外 + cept 拿取 + -ion 名词后缀"。"""
    table = load()
    added = 0
    for part in re.split(r"[+＋]", affix_str or ""):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^((?:[A-Za-z]+-)|(?:-[A-Za-z]+)|(?:[A-Za-z]+))\s*(.*)$", part)
        if not m:
            continue
        morpheme = m.group(1).strip()
        gloss = m.group(2).strip()
        key = _norm(morpheme)
        if len(key) < 2:
            continue
        if key not in table:
            table[key] = {"type": classify(morpheme), "gloss": gloss,
                          "words": [word.lower()], "raw": morpheme}
            added += 1
        else:
            # 已存在：补充 gloss（若为空）与例词
            if not table[key].get("gloss") and gloss:
                table[key]["gloss"] = gloss[: _GLOSS_MAX]
            if word.lower() not in table[key]["words"]:
                table[key]["words"].append(word.lower())
    if added:
        save()
    return added


def decompose(word: str):
    """用积累的词素表保守拆解。返回 [{morpheme, type, gloss}]；
    拆不出或拆不完整返回 None（调用方此时才让 AI 输出 affix）。"""
    table = load()
    if not table:
        return None
    w = word.lower()
    n = len(w)

    # 1) 前缀：词首最长匹配
    pre = None
    for m, info in table.items():
        if info.get("type") == "prefix" and w.startswith(_norm(m)):
            nm = _norm(m)
            if pre is None or len(nm) > len(_norm(pre[0])):
                pre = (m, info, nm)
    # 2) 后缀：词尾最长匹配
    suf = None
    for m, info in table.items():
        if info.get("type") == "suffix" and w.endswith(_norm(m)):
            nm = _norm(m)
            if suf is None or len(nm) > len(_norm(suf[0])):
                suf = (m, info, nm)

    p_len = len(pre[2]) if pre else 0
    s_len = len(suf[2]) if suf else 0
    middle = w[p_len: n - s_len if s_len else n]

    # 3) 词根：中间剩余部分最长匹配（含变体词根直接匹配）
    root = None
    for m, info in table.items():
        if info.get("type") == "root":
            nm = _norm(m)
            if nm and (middle.startswith(nm) or middle == nm):
                if root is None or len(nm) > len(_norm(root[0])):
                    root = (m, info, nm)
    r_len = len(root[2]) if root else 0

    parts = []
    if pre:
        parts.append({"morpheme": pre[1].get("raw", pre[0]), "type": "prefix",
                      "gloss": pre[1].get("gloss", "")})
    if root:
        parts.append({"morpheme": root[1].get("raw", root[0]), "type": "root",
                      "gloss": root[1].get("gloss", "")})
    if suf:
        parts.append({"morpheme": suf[1].get("raw", suf[0]), "type": "suffix",
                      "gloss": suf[1].get("gloss", "")})

    # 保守判定：至少 2 个词素，且拆出部分覆盖单词主体（允许少量未覆盖）
    covered = p_len + r_len + s_len
    if len(parts) >= 2 and covered >= max(n - 2, 0):
        return parts
    if len(parts) >= 2 and covered >= n * 0.6:
        return parts
    return None
