# -*- coding: utf-8 -*-
"""语料建索引：读 corpus/kaoyan_sentences.jsonl，写 data/kaoyan.db 的
sentences / words(倒排) / word_freq(词频) / meta(语料版本)。

用法：python -m app.corpus_builder
"""
import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime

from . import config
from .db import get_conn, set_meta
from .lemmatizer import lemmatize, tokenize_spans


def dedup_key(year, text: str):
    """去重键：同一年内实质相同的句子（忽略标点/空白/大小写/排版符号差异）
    视为重复。只保留字母数字，连字符、引号、破折号、项目符号等一律忽略。
    与 scripts/extract_corpus.py 保持一致。"""
    t = unicodedata.normalize("NFKC", text).lower()
    t = re.sub(r"[^a-z0-9]", "", t)
    return (year, t)


def norm_exam_type(exam_type: str) -> str:
    """统考(kaoyan)并入英语一(kaoyan1)：2010 年前统考与英语一实为同一套卷，
    避免同一套题出现两个标签。"""
    return "kaoyan1" if exam_type == "kaoyan" else exam_type


def corpus_version() -> str:
    if not config.CORPUS_JSONL.exists():
        raise FileNotFoundError(f"语料文件不存在：{config.CORPUS_JSONL}")
    data = config.CORPUS_JSONL.read_bytes()
    return hashlib.sha256(data).hexdigest()[:12]


def build():
    if not config.CORPUS_JSONL.exists():
        print(f"语料文件不存在：{config.CORPUS_JSONL}")
        sys.exit(1)
    conn = get_conn()
    # 表结构可能变化（如 sentences 增加 article 列）：直接重建索引表
    conn.execute("DROP TABLE IF EXISTS sentences")
    conn.execute("DROP TABLE IF EXISTS words")
    conn.execute("DROP TABLE IF EXISTS word_freq")
    conn.executescript("""
CREATE TABLE sentences(
  id INTEGER PRIMARY KEY,
  year INTEGER NOT NULL,
  exam_type TEXT NOT NULL,
  text TEXT NOT NULL,
  source TEXT,
  article TEXT
);
CREATE TABLE words(
  id INTEGER PRIMARY KEY,
  lemma TEXT NOT NULL,
  form TEXT NOT NULL,
  sentence_id INTEGER NOT NULL,
  start INTEGER NOT NULL DEFAULT 0,
  end INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_words_lemma ON words(lemma);
CREATE INDEX idx_words_form ON words(form);
CREATE INDEX idx_words_sid ON words(sentence_id);
CREATE TABLE word_freq(
  lemma TEXT PRIMARY KEY,
  total INTEGER NOT NULL,
  doc_count INTEGER NOT NULL,
  first_year INTEGER,
  last_year INTEGER
);
""")
    conn.commit()

    sentences = []
    with config.CORPUS_JSONL.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                sentences.append(json.loads(line))

    # 归一化去重：同一年内实质相同的句子（忽略标点差异）只保留第一条；统考并入英语一
    seen = set()
    uniq = []
    for s in sentences:
        s["exam_type"] = norm_exam_type(s.get("exam_type", ""))
        key = dedup_key(s.get("year"), s["text"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(s)
    sentences = uniq

    word_rows = []
    freq = {}      # lemma -> [total, doc_count(临时), first, last]
    doc_seen = {}  # lemma -> {(year, exam_type, article)}：按文章去重计数
    sent_id = 0
    for s in sentences:
        sent_id += 1
        text = s["text"]
        spans = tokenize_spans(text)
        lower_forms = [w.lower() for w, _, _ in spans]
        lemmas = {}
        for wf in lower_forms:
            if wf not in lemmas:
                lemmas[wf] = lemmatize(wf)
        art_key = (s["year"], s["exam_type"], s.get("article", ""))
        for (wf, st, en) in ((w.lower(), st, en) for w, st, en in spans):
            lm = lemmas[wf]
            word_rows.append((lm, wf, sent_id, st, en))
            item = freq.setdefault(lm, [0, 0, s["year"], s["year"]])
            item[0] += 1
            item[2] = min(item[2], s["year"])
            item[3] = max(item[3], s["year"])
            doc_seen.setdefault(lm, set()).add(art_key)
    # doc_count = 该词出现过的「文章」数：同一篇文章里出现多次只算一篇
    # （以前误按出现次数统计，字段名与内容不符）
    for lm, v in freq.items():
        v[1] = len(doc_seen.get(lm, set()))

    conn.executemany(
        "INSERT INTO sentences(id, year, exam_type, text, source, article) "
        "VALUES(?,?,?,?,?,?)",
        [(i + 1, s["year"], s["exam_type"], s["text"], s["source"],
          s.get("article", ""))
         for i, s in enumerate(sentences)])
    conn.executemany(
        "INSERT INTO words(lemma, form, sentence_id, start, end) "
        "VALUES(?,?,?,?,?)", word_rows)
    conn.executemany(
        "INSERT INTO word_freq(lemma, total, doc_count, first_year, last_year) "
        "VALUES(?,?,?,?,?)",
        [(lm, v[0], v[1], v[2], v[3]) for lm, v in freq.items()])
    conn.commit()

    version = corpus_version()
    set_meta(conn, "corpus_version", version)
    set_meta(conn, "built_at", datetime.now().isoformat(timespec="seconds"))
    set_meta(conn, "sentence_count", str(sent_id))
    set_meta(conn, "word_count", str(len(word_rows)))

    # 语料版本变了 -> 旧查询缓存全部作废
    conn.execute("DELETE FROM query_cache WHERE corpus_version != ?",
                 (version,))
    conn.commit()

    print(f"索引完成：{sent_id} 句，{len(word_rows)} 个词条，"
          f"{len(freq)} 个不同词形原形，版本 {version}")
    top = conn.execute(
        "SELECT lemma, total FROM word_freq ORDER BY total DESC LIMIT 10")
    print("词频 top10：" + ", ".join(f"{r['lemma']}({r['total']})" for r in top))
    conn.close()


if __name__ == "__main__":
    build()
