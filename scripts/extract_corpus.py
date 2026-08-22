# -*- coding: utf-8 -*-
"""把 corpus/_raw 下的多个真题源提取成统一的 JSONL 语料：corpus/kaoyan_sentences.jsonl

每行一个句子：
{"year": 2005, "exam_type": "kaoyan1", "text": "...", "source": "pfoocc"}
exam_type: kaoyan1(英语一，含 2010 年前统考) / kaoyan2(英语二)

来源：
1. words-statistics/data/N.txt (GBK)      -> 1980+N 年统考真题全题型
2. language-learner-texts 考研英语一阅读文本/*/Text*.md, Trans.md  -> 1998-2022 英语一
3. pfoocc 201_204_kaoyan  201/*/read|cloze/articles*.tex, 204/...  -> 英语一2005-2023 / 英语二2010-2023
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "corpus" / "_raw"
OUT = ROOT / "corpus" / "kaoyan_sentences.jsonl"


def dedup_key(year, text: str):
    """去重键：同一年内实质相同的句子（忽略标点/空白/大小写/排版符号差异）
    视为重复。只保留字母数字。与 app/corpus_builder.py 保持一致。"""
    t = unicodedata.normalize("NFKC", text).lower()
    t = re.sub(r"[^a-z0-9]", "", t)
    return (year, t)

_ABBREV = {"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc",
           "e.g", "i.e", "fig", "no", "vol", "pp", "dept", "univ", "u.s",
           "u.k", "al", "approx", "inc", "ltd", "co", "ph.d"}


def split_sentences(text: str):
    """按句号/问号/感叹号切句，保护常见缩写。返回句子列表。"""
    def _protect(m):
        word = m.group(1).lower()
        if word in _ABBREV:
            return m.group(0).replace(".", "\u0001")
        return m.group(0)

    text = re.sub(r"\b([A-Za-z](?:[A-Za-z]\.)+)", _protect, text)
    parts = re.split(r"(?<=[.!?])(?:\s+|$)", text)
    out = []
    for p in parts:
        p = p.replace("\u0001", ".").strip()
        p = re.sub(r"\s+", " ", p)
        if p:
            out.append(p)
    return out


def is_english_sentence(s: str, min_letters=8):
    if len(s) < min_letters:
        return False
    letters = sum(c.isascii() and c.isalpha() for c in s)
    cjk = sum(not c.isascii() and not c.isspace() for c in s)
    if letters < min_letters:
        return False
    if cjk > letters * 0.2:  # 中文混排超过 20% 视为解析内容
        return False
    return True


def clean_text(s: str):
    """去掉编号、选项字母前缀、多余符号，但保留单词间标点。"""
    s = re.sub(r"^\s*[\d]+[\.\、\)]?\s*", "", s)
    s = re.sub(r"^\s*[A-H][\.\)]\s*", "", s)
    s = re.sub(r"_{3,}", " ___ ", s)  # 挖空
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip(" -\t")


sentences = []  # list of dict


def add(year, exam_type, text, source, article=""):
    # 统考(kaoyan)并入英语一(kaoyan1)：2010 年前统考与英语一实为同一套卷
    if exam_type == "kaoyan":
        exam_type = "kaoyan1"
    for sent in split_sentences(text):
        sent = clean_text(sent)
        if is_english_sentence(sent):
            sentences.append({"year": year, "exam_type": exam_type,
                              "text": sent, "source": source,
                              "article": article})


# ---------- 1. words-statistics (1980-2012, GBK) ----------
# 文章边界：Section ... / Text N / Passage N 标题行；标题行本身不入语料。
_SECTION_RE = re.compile(r"^(Section\s+[IVX]+\b.*|Text\s+\d+\b.*|Passage\s+\d+\b.*)$",
                         re.I)


def extract_words_statistics():
    data_dir = RAW / "words-statistics" / "data"
    files = sorted(data_dir.glob("[0-9]*.txt"))
    n = 0
    for f in files:
        try:
            year = int(f.stem) + 1980
        except ValueError:
            continue
        try:
            raw = f.read_bytes().decode("gbk", errors="ignore")
        except Exception:
            continue
        cur_article = f"{year}卷"  # 无标记时的兜底
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            if _SECTION_RE.match(line) and len(line) < 80:
                cur_article = line
                continue  # 大题/文章标题行：作为边界，不入语料
            letters = sum(c.isascii() and c.isalpha() for c in line)
            cjk = sum(not c.isascii() and not c.isspace() for c in line)
            if letters < 8 or cjk > letters * 0.5:
                continue  # 中文说明行或太短的行
            # 去掉行内中文解析片段（若少量中文混在英文行）
            line = re.sub(r"[\u4e00-\u9fff]+[，。：；、]*", " ", line)
            if sum(c.isascii() and c.isalpha() for c in line) < 8:
                continue
            add(year, "kaoyan", line, "words-statistics", cur_article)
            n += 1
    print(f"[words-statistics] 处理完成，年份 1980-2012，新增行 {n}")


# ---------- 2. language-learner-texts (英语一阅读 1998-2022, UTF-8 md) ----------
def extract_llt():
    base = RAW / "language-learner-texts" / "考研英语一阅读文本"
    n = 0
    for md in sorted(base.rglob("*.md")):
        m = re.search(r"(\d{4})-英语一-(\w+)", md.name + md.read_text(encoding="utf-8", errors="ignore")[:200])
        if not m:
            continue
        year = int(m.group(1))
        article = md.stem  # 每个 md 一篇阅读文章
        text = md.read_text(encoding="utf-8", errors="ignore")
        text = re.sub(r"^---.*?---", "", text, flags=re.S | re.M)  # frontmatter
        text = re.sub(r"^\^{3}.*$", "", text, flags=re.M)
        text = re.sub(r"^#{1,6}\s*.*$", "", text, flags=re.M)
        text = re.sub(r"[*_`~]", "", text)
        text = re.sub(r"[\u4e00-\u9fff]+[，。：；、\s]*", " ", text)  # 去掉残留中文
        for para in text.split("\n\n"):
            para = para.strip()
            if para and sum(c.isascii() and c.isalpha() for c in para) > 40:
                add(year, "kaoyan1", para, "language-learner-texts", article)
                n += 1
    print(f"[language-learner-texts] 处理完成，新增段落 {n}")


# ---------- 3. 考生回忆版真题原文 md（英语一2010-2026 / 英语二2010-2025） ----------
def extract_user_md():
    base = RAW / "user_md"
    n = 0
    for md in sorted(base.glob("*.md")):
        if "英语二" in md.name:
            exam_type = "kaoyan2"
        elif "英语一" in md.name:
            exam_type = "kaoyan1"
        else:
            continue
        current_year = None
        current_article = ""
        para_lines = []
        for line in md.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            m = re.match(r"^#\s*(\d{4})\s*年", line)
            if m:
                if current_year and para_lines:
                    add(current_year, exam_type, " ".join(para_lines),
                        "kaoyan-papers-recall", current_article)
                    n += 1
                current_year = int(m.group(1))
                current_article = ""
                para_lines = []
                continue
            if line.startswith("##"):
                current_article = line.lstrip("#").strip()  # 完型填空 / 阅读 Text 1
                continue
            if line.startswith("#"):
                continue
            if not line:
                if para_lines:
                    add(current_year, exam_type, " ".join(para_lines),
                        "kaoyan-papers-recall", current_article)
                    n += 1
                    para_lines = []
                continue
            letters = sum(c.isascii() and c.isalpha() for c in line)
            cjk = sum(not c.isascii() and not c.isspace() for c in line)
            if letters >= 8 and cjk <= letters * 0.5 and not line.startswith("📖"):
                para_lines.append(line)
        if current_year and para_lines:
            add(current_year, exam_type, " ".join(para_lines),
                "kaoyan-papers-recall", current_article)
            n += 1
    print(f"[user-md] 处理完成，新增段落 {n}")


# ---------- 4. pfoocc 201_204_kaoyan (LaTeX, 英语一2005-2023 / 英语二2010-2023) ----------
_LATEX_RE = re.compile(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^{}]*\})*")


def extract_pfoocc():
    base = RAW / "201_204_kaoyan"
    n = 0
    for exam_dir, exam_type in (("201", "kaoyan1"), ("204", "kaoyan2")):
        for year_dir in sorted((base / exam_dir).iterdir()):
            if not year_dir.is_dir() or not year_dir.name.isdigit():
                continue
            year = int(year_dir.name)
            for tex in sorted(year_dir.rglob("articles*.tex")):
                article = tex.stem  # articles1/2/3/4 = 阅读文章，articles = 完形
                text = tex.read_text(encoding="utf-8", errors="ignore")
                text = re.sub(r"%.*$", "", text, flags=re.M)  # 注释
                text = _LATEX_RE.sub(" ", text)  # LaTeX 命令
                text = text.replace("{", " ").replace("}", " ").replace("\\", " ")
                text = text.replace("``", '"').replace("''", '"')
                text = re.sub(r"[ \t]+", " ", text)
                for para in text.split("\n"):
                    para = para.strip()
                    if para and sum(c.isascii() and c.isalpha() for c in para) > 40:
                        add(year, exam_type, para, "pfoocc", article)
                        n += 1
    print(f"[pfoocc] 处理完成，新增段落 {n}")


def main():
    extract_words_statistics()
    extract_llt()
    extract_user_md()
    extract_pfoocc()
    # 去重：同一年内实质相同的句子（忽略标点差异）只保留第一条（来源顺序即优先级）
    seen = set()
    uniq = []
    for s in sentences:
        key = dedup_key(s["year"], s["text"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(s)
    uniq.sort(key=lambda s: (s["year"], s["exam_type"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for s in uniq:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    by_year = {}
    for s in uniq:
        by_year.setdefault(s["year"], 0)
        by_year[s["year"]] += 1
    print(f"\n共 {len(uniq)} 个句子写入 {OUT.name}")
    years = sorted(by_year)
    print(f"覆盖年份 {years[0]}-{years[-1]}（{len(years)} 年）")
    for y in years:
        print(f"  {y}: {by_year[y]}")


if __name__ == "__main__":
    main()
