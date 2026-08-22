# -*- coding: utf-8 -*-
"""把 open-dictionary v2.0（corpus/_raw/open_dictionary_v2/distribution.jsonl）
裁剪进 assets/，作为查词的本地词典主力：

1. assets/dict.csv —— 义项约束 AI 用（格式不变：word<TAB>义项1|义项2|…）
   义项 = open-dictionary 的 short_gloss，前缀词性缩写，按优先级 core→common→rare 排序；
   open-dictionary 没收录的真题词/大纲词用 ECDICT translation 兜底。
2. assets/word_cards.json —— 词条卡片（本地零 AI 费用展示）：
   {word: {memory_hook, summary, etymology, usage, relations,
           meanings: [{pos, priority, gloss, explain}]}}
   卡片里 meanings[].gloss 与 dict.csv 的义项文本逐字一致（AI 义项照抄，
   展示时按文字匹配取本地解释）。

用法：python scripts/build_odict.py
"""
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ODICT_JSONL = ROOT / "corpus" / "_raw" / "open_dictionary_v2" / "distribution.jsonl"
ECDICT_CSV = ROOT / "corpus" / "_raw" / "ecdict.csv"
OUT_DICT = ROOT / "assets" / "dict.csv"
OUT_CARDS = ROOT / "assets" / "word_cards.json"
MAX_DEFS = 12

# 词性缩写 -> 中文词性名（卡片展示用，词性前缀仍用英文缩写与旧格式一致）
POS_CN = {"noun": "n.", "verb": "v.", "adj": "adj.", "adv": "adv.",
          "pron": "pron.", "prep": "prep.", "conj": "conj.", "interj": "int.",
          "num": "num.", "art": "art.", "name": "n.", "phrase": "phrase",
          "prefix": "前缀", "suffix": "后缀", "determiner": "det."}
PRIORITY_ORDER = {"core": 0, "common": 1, "rare": 2}


def load_wanted_words() -> set[str]:
    """需要覆盖的词：真题词形原形 + 大纲词 + 红宝书词（并集）。"""
    sys.path.insert(0, str(ROOT))
    from app.db import get_conn
    conn = get_conn()
    rows = conn.execute("SELECT lemma FROM word_freq").fetchall()
    conn.close()
    want = {r["lemma"] for r in rows}

    dagang = ROOT / "corpus" / "_raw" / "words-statistics" / "data" / "5495大纲词汇.txt"
    if dagang.exists():
        text = dagang.read_bytes().decode("gbk", errors="ignore")
        for line in text.splitlines():
            w = line.strip().split()[0].lower() if line.strip() else ""
            if w and w.isascii() and w.isalpha():
                want.add(w)

    hb = ROOT / "corpus" / "_raw" / "kaoyan_hongbaoshu_2025.json"
    if hb.exists():
        for item in json.loads(hb.read_text(encoding="utf-8")):
            w = str(item.get("name", "")).strip().lower()
            if w:
                want.add(w)
    return want


def extract_card(obj: dict) -> dict | None:
    """从 open-dictionary 词条提取卡片（仅保留考研可用字段，过滤专名/无义项）。"""
    meanings = []
    for pg in obj.get("pos_groups", []):
        pos = pg.get("pos", "")
        if pos in ("name",) or pg.get("proper_name"):
            continue  # 人名/地名等专名，考研语境不考
        for m in pg.get("meanings", []):
            gloss = str(m.get("short_gloss") or "").strip()
            if not gloss:
                continue
            explain = str(m.get("learner_explanation") or "").strip()
            prio = str(m.get("priority") or "common")
            meanings.append({
                "pos": pos,
                "priority": prio,
                "gloss": gloss,
                "explain": explain,
            })
    if not meanings:
        return None
    meanings.sort(key=lambda x: PRIORITY_ORDER.get(x["priority"], 9))
    # 用法说明：词性组级 usage_note（取第一个非空的）
    usage = ""
    for pg in obj.get("pos_groups", []):
        if pg.get("pos") in ("name",):
            continue
        un = str(pg.get("usage_note") or "").strip()
        if un:
            usage = un
            break
    card = {
        "memory_hook": str(obj.get("memory_hook") or "").strip(),
        "summary": str(obj.get("headword_summary") or "").strip(),
        "etymology": str(obj.get("etymology_note") or "").strip(),
        "usage": usage,
        "study_notes": [str(s).strip() for s in (obj.get("study_notes") or [])
                        if str(s).strip()],
        "relations": [],
        "meanings": meanings,
    }
    # 关系词（同义/反义等）：从各 meaning 的 relations 提取
    seen_rel = set()
    for pg in obj.get("pos_groups", []):
        for m in pg.get("meanings", []):
            for r in m.get("relations", []) or []:
                rel = str(r.get("relation") or "").strip()
                word = str(r.get("word") or "").strip()
                if rel and word:
                    key = f"{rel}|{word}"
                    if key not in seen_rel:
                        seen_rel.add(key)
                        card["relations"].append({"rel": rel, "word": word})
    return card


def gloss_to_meaning_text(pos: str, gloss: str) -> str:
    """义项文本 = 词性缩写. short_gloss（如 adj. 非同寻常的；罕见的）。"""
    pos_prefix = POS_CN.get(pos, pos + ".")
    return f"{pos_prefix} {gloss}".strip()


def ecdict_defs(word: str, reader_rows) -> list[str] | None:
    """ECDICT 兜底：整行解析出中文释义（拆 \n、过滤领域标签、截断）。"""
    return None  # 在 main 里按行处理


def clean_ecdict_defs(defs: list[str]) -> list[str]:
    general = [d for d in defs if not re.match(r"^\[", d)]
    return general[:MAX_DEFS] if general else defs[:MAX_DEFS]


def main():
    if not ODICT_JSONL.exists():
        print(f"缺少 {ODICT_JSONL}\n请先下载 open-dictionary v2.0 的 "
              f"distribution.jsonl.gz 解压后放入。")
        sys.exit(1)
    want = load_wanted_words()
    print(f"待覆盖词数（真题原形∪大纲∪红宝书）：{len(want)}")

    # ---- 第一遍：流式读 open-dictionary，构建主词典与卡片 ----
    cards: dict[str, dict] = {}
    main_defs: dict[str, list[str]] = {}
    n = 0
    with ODICT_JSONL.open(encoding="utf-8") as f:
        for line in f:
            n += 1
            try:
                obj = json.loads(line)
            except Exception:
                continue
            hw = str(obj.get("headword") or "").lower()
            if hw not in want:
                continue
            card = extract_card(obj)
            if not card:
                continue
            cards[hw] = card
            defs = [gloss_to_meaning_text(m["pos"], m["gloss"])
                    for m in card["meanings"]]
            main_defs[hw] = defs[:MAX_DEFS]
    print(f"open-dictionary 命中 {len(main_defs)} 个词（扫描 {n} 行）")

    # ---- 第二遍：ECDICT 兜底 open-dictionary 没覆盖的词 ----
    fallback = 0
    if ECDICT_CSV.exists():
        with ECDICT_CSV.open(encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if len(row) < 4:
                    continue
                w = row[0].strip()
                if not w or w in main_defs:
                    continue
                if w not in want:
                    continue
                defs = clean_ecdict_defs(
                    [d.strip() for d in row[3].split("\\n") if d.strip()])
                if defs:
                    main_defs[w] = defs
                    fallback += 1
    print(f"ECDICT 兜底 {fallback} 个，词典共 {len(main_defs)} 个词")

    # ---- 写出 dict.csv ----
    OUT_DICT.parent.mkdir(parents=True, exist_ok=True)
    with OUT_DICT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        for w in sorted(main_defs):
            writer.writerow([w, "|".join(main_defs[w])])
    print(f"dict.csv 已生成：{len(main_defs)} 词条，"
          f"{OUT_DICT.stat().st_size / 1048576:.1f} MB")

    # ---- 写出 word_cards.json ----
    # 只保留有卡片的词（ECDICT 兜底的没有卡片，界面自然不显示）
    with OUT_CARDS.open("w", encoding="utf-8") as f:
        json.dump(cards, f, ensure_ascii=False)
    print(f"word_cards.json 已生成：{len(cards)} 词条，"
          f"{OUT_CARDS.stat().st_size / 1048576:.1f} MB")


if __name__ == "__main__":
    main()
