# -*- coding: utf-8 -*-
"""生成 assets/dict.csv（查词时约束 AI 义项的本地词典）。

义项来源（按优先级）：
1. 考研红宝书 2025 词库（corpus/_raw/kaoyan_hongbaoshu_2025.json，6705 词）：
   义项现代、按词性分组，覆盖约 98% 考研大纲词——每个分号组拆成一个独立义项；
2. ECDICT 完整 csv（corpus/_raw/ecdict.csv）兜底：
   真题词形原形 + 大纲词中红宝书没收录的、以及 COCA 前 3 万高频词。

输出格式：word<TAB>义项1|义项2|…（义项间用 | 分隔）。

用法：python scripts/build_dict.py
"""
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_CSV = ROOT / "corpus" / "_raw" / "ecdict.csv"
HB_JSON = ROOT / "corpus" / "_raw" / "kaoyan_hongbaoshu_2025.json"
OUT_CSV = ROOT / "assets" / "dict.csv"
MAX_DEFS = 8
TOP_FREQ = 50_000


def load_hongbaoshu() -> dict[str, list[str]]:
    """解析红宝书词库：trans 每条按「；」拆成独立义项组（组内「，」为近义并列，
    保留词性前缀，如「n. 代理人，经纪人」「n. 代理商，经销商」）。
    拆分后的组补上本条 trans 的词性前缀，保证每个义项都带词性。"""
    out: dict[str, list[str]] = {}
    if not HB_JSON.exists():
        return out
    pos_re = re.compile(r"^([a-z]+\.)\s*")
    data = json.loads(HB_JSON.read_text(encoding="utf-8"))
    for item in data:
        word = str(item.get("name", "")).strip().lower()
        if not word:
            continue
        defs: list[str] = []
        for t in item.get("trans", []):
            t = str(t).strip()
            pos = pos_re.match(t).group(1) if pos_re.match(t) else ""
            for group in re.split(r"[；;]", t):
                g = group.strip().strip("。. \t")
                if not g:
                    continue
                g = pos_re.sub("", g).strip()
                if pos and g:
                    g = f"{pos} {g}"
                if g and g not in defs:
                    defs.append(g)
        if defs:
            out[word] = defs
    return out


def load_corpus_lemmas() -> set[str]:
    sys.path.insert(0, str(ROOT))
    from app.db import get_conn
    conn = get_conn()
    rows = conn.execute("SELECT lemma FROM word_freq").fetchall()
    conn.close()
    return {r["lemma"] for r in rows}


def load_dagang_words() -> set[str]:
    p = ROOT / "corpus" / "_raw" / "words-statistics" / "data" / "5495大纲词汇.txt"
    words = set()
    if p.exists():
        text = p.read_bytes().decode("gbk", errors="ignore")
        for line in text.splitlines():
            w = line.strip().split()[0].lower() if line.strip() else ""
            if w and w.isascii() and w.isalpha():
                words.add(w)
    return words


def clean_defs(defs: list[str]) -> list[str]:
    """过滤领域标签义项（[计]/[医]/[经]/[法] 等，考研不考），保留通用义项。"""
    general = [d for d in defs if not re.match(r"^\[", d)]
    return general[:MAX_DEFS] if general else defs[:MAX_DEFS]


def main():
    if not RAW_CSV.exists():
        print(f"缺少 {RAW_CSV}，请先下载 ECDICT 数据。")
        sys.exit(1)
    hb = load_hongbaoshu()
    print(f"红宝书词条：{len(hb)} 个（义项已按分号拆开）")
    want = load_corpus_lemmas() | load_dagang_words()
    print(f"真题词形原形 + 大纲词：{len(want)} 个")

    out: dict[str, list[str]] = dict(hb)  # 红宝书义项优先，全部收录
    freq_cands: list[tuple[float, str, list[str]]] = []
    with RAW_CSV.open(encoding="utf-8", errors="ignore") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) < 4:
                continue
            word = row[0].strip()
            if not word or word in out:  # 红宝书已收录的不再用 ECDICT 义项
                continue
            defs = clean_defs([d.strip() for d in row[3].split("\\n") if d.strip()])
            if not defs:
                continue
            frq_s = row[10].strip() if len(row) > 10 else ""
            is_freq = frq_s.replace(".", "").isdigit()
            frq = float(frq_s) if is_freq else float("inf")
            if word in want:
                out[word] = defs
            elif is_freq and frq < 30000:
                freq_cands.append((frq, word, defs))
    freq_cands.sort(key=lambda x: x[0])
    for frq, word, defs in freq_cands:
        if word in out:
            continue
        out[word] = defs
        if len(out) >= len(want) + len(hb) + TOP_FREQ:
            break

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        for w in sorted(out):
            writer.writerow([w, "|".join(out[w])])
    size_mb = OUT_CSV.stat().st_size / 1048576
    print(f"dict.csv 已生成：{len(out)} 词条（红宝书 {len(hb)} + ECDICT 兜底 "
          f"{len(out) - len(hb)}），{size_mb:.1f} MB")


if __name__ == "__main__":
    main()
