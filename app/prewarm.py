# -*- coding: utf-8 -*-
"""批量预热：按真题词频（或自定义词表）把高频词预先查一遍写入缓存，
之后查这些词全部离线零成本。建议在平峰时段（如凌晨/周末）运行。

用法（命令行）：
python -m app.prewarm --top 300        # 预热真题最高频 300 个实词
python -m app.prewarm --file 词表.txt   # 预热自定义词表（每行一个词）
"""
import argparse
import sys
import time

import requests

from . import config
from .db import get_conn
from .lemmatizer import lemmatize
from .query import cache_key, normalize_word, query_word

# 常见功能词：预热时跳过（用户查这些词的概率低，省钱）
STOPWORDS = {
    "the", "be", "is", "are", "was", "were", "been", "being", "am",
    "a", "an", "and", "or", "but", "if", "then", "else", "when", "while",
    "of", "to", "in", "for", "on", "with", "at", "by", "from", "as", "into",
    "about", "against", "between", "through", "during", "before", "after",
    "above", "below", "up", "down", "out", "off", "over", "under", "again",
    "further", "once", "here", "there", "where", "why", "how", "all", "any",
    "both", "each", "few", "more", "most", "other", "some", "such", "no",
    "nor", "not", "only", "own", "same", "so", "than", "too", "very",
    "can", "will", "just", "should", "now", "do", "does", "did", "done",
    "doing", "have", "has", "had", "having", "it", "its", "i", "you", "he",
    "she", "we", "they", "them", "his", "her", "their", "my", "your", "our",
    "me", "him", "us", "who", "whom", "which", "what", "whose", "this",
    "that", "these", "those", "am", "aren", "cannot", "could", "may",
    "might", "must", "shall", "would", "also", "even", "however", "thus",
    "therefore", "hence", "yet", "still", "ever", "never", "often",
    "always", "usually", "sometimes", "perhaps", "maybe", "quite",
    "rather", "almost", "nearly", "indeed", "instead", "namely", "per",
    "via", "etc", "eg", "ie", "one", "two", "three", "four", "five",
    "six", "seven", "eight", "nine", "ten", "hundred", "thousand",
    "million", "billion", "first", "second", "third", "last", "next",
    "new", "old", "many", "much", "little", "few", "great", "large",
    "small", "big", "long", "short", "high", "low", "early", "late",
    "say", "said", "says", "saying", "get", "got", "make", "made",
    "take", "took", "go", "went", "gone", "come", "came", "see", "saw",
    "know", "knew", "think", "thought", "want", "wanted", "look",
    "looked", "like", "liked", "give", "gave", "find", "found", "tell",
    "told", "ask", "asked", "work", "worked", "seem", "seemed", "feel",
    "felt", "try", "tried", "leave", "left", "call", "called", "put",
    "keep", "kept", "let", "begin", "began", "show", "showed", "hear",
    "heard", "play", "played", "run", "ran", "move", "moved", "live",
    "lived", "believe", "believed", "hold", "held", "bring", "brought",
    "happen", "happened", "write", "wrote", "sit", "sat", "stand", "stood",
    "lose", "lost", "pay", "paid", "meet", "met", "set", "learn",
    "learned", "change", "changed", "lead", "led", "understand",
    "understood", "watch", "watched", "follow", "followed", "stop",
    "stopped", "create", "created", "speak", "spoke", "read", "spend",
    "spent", "grow", "grew", "open", "opened", "walk", "walked", "win",
    "won", "offer", "offered", "remember", "remembered", "love", "loved",
    "consider", "considered", "appear", "appeared", "buy", "bought",
    "wait", "waited", "serve", "served", "die", "died", "send", "sent",
    "expect", "expected", "build", "built", "stay", "stayed", "fall",
    "fell", "cut", "reach", "reached", "kill", "killed", "remain",
    "remained", "suggest", "suggested", "raise", "raised", "pass",
    "passed", "sell", "sold", "require", "required", "report",
    "reported", "decide", "decided", "pull", "pulled", "return",
    "returned", "explain", "explained", "hope", "hoped", "develop",
    "developed", "carry", "carried", "break", "broke", "receive",
    "received", "agree", "agreed", "support", "supported", "hit",
    "produce", "produced", "eat", "ate", "cover", "covered", "catch",
    "caught", "draw", "drew", "choose", "chose", "man", "men", "woman",
    "women", "people", "person", "year", "years", "time", "times", "day",
    "days", "week", "weeks", "month", "months", "world", "life", "lives",
    "hand", "hands", "part", "parts", "place", "places", "case", "cases",
    "point", "points", "thing", "things", "way", "ways", "end", "ends",
    "fact", "facts", "group", "groups", "number", "numbers", "kind",
    "kinds", "example", "examples", "question", "questions", "side",
    "sides", "house", "houses", "home", "homes", "school", "schools",
    "state", "states", "country", "countries", "city", "cities", "child",
    "children", "family", "families", "student", "students", "friend",
    "friends", "father", "mother", "parent", "parents", "brother",
    "sister", "government", "governments", "company", "companies",
    "president", "director", "university", "professor", "researcher",
    "researchers", "author", "authors", "book", "books", "paper",
    "papers", "study", "studies", "studied", "research", "science",
    "scientist", "scientists", "technology", "information", "news",
    "story", "stories", "business", "market", "markets", "money", "price",
    "prices", "job", "jobs", "war", "wars", "law", "laws", "power",
    "powers", "problem", "problems", "idea", "ideas", "effect", "effects",
    "result", "results", "change", "changes", "increase", "decrease",
    "level", "levels", "rate", "rates", "period", "periods", "century",
    "centuries", "history", "language", "english", "american", "america",
    "china", "chinese", "japan", "japanese", "europe", "european",
    "france", "french", "germany", "german", "britain", "british",
    "india", "indian", "human", "humans", "public", "private", "national",
    "international", "local", "federal", "political", "social", "economic",
    "cultural", "scientific", "modern", "natural", "important", "good",
    "bad", "different", "similar", "common", "special", "general",
    "possible", "likely", "certain", "true", "false", "real", "main",
    "major", "minor", "particular", "specific", "clear", "right", "wrong",
    "better", "best", "worse", "worst", "able", "unable", "available",
    "necessary", "present", "past", "future", "current", "recent",
    "early", "later", "former", "latter", "entire", "whole", "full",
    "free", "open", "closed", "easy", "hard", "difficult", "simple",
    "complex", "strong", "weak", "young", "older", "elder", "younger",
    "federal", "republican", "democratic", "obama", "trump", "biden",
    # 题目指令词：真题文本里的高频噪声，预热它们浪费钱
    "sentence", "sentences", "section", "sections", "following", "directions",
    "direction", "passage", "passages", "answer", "answers", "question",
    "questions", "choose", "chose", "chosen", "mark", "marks", "marked",
    "blank", "blanks", "translate", "translation", "translations",
    "exercise", "exercises", "text", "texts", "word", "words", "item",
    "items", "example", "examples", "note", "notes", "notice", "test",
    "tests", "testing", "cloze", "reading", "writing", "listening",
}


def get_freq_words(conn, limit: int):
    """按真题词频从高到低取实词（过滤停用词）。"""
    rows = conn.execute(
        "SELECT lemma, total FROM word_freq ORDER BY total DESC, lemma").fetchall()
    words = []
    for r in rows:
        w = r["lemma"]
        if w in STOPWORDS or len(w) < 3:
            continue
        words.append(w)
        if len(words) >= limit:
            break
    return words


def read_word_file(path: str):
    words = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            w = normalize_word(line)
            if w and lemmatize(w) not in words:
                words.append(w)
    return words


def prewarm(words, cfg=None, progress_cb=None, cancel_cb=None, db_path=None,
            budget: float = 0.0):
    """逐个查询（自动跳过已缓存），返回统计 dict。
    progress_cb(done, total, word, status)；cancel_cb() 返回 True 时中止；
    budget > 0 时，实际花费累计达到预算即停止（预算控费）。"""
    cfg = cfg or config.load_config()
    from .db import get_conn
    conn = get_conn(db_path)
    # 共享 Session：整批预热复用同一 TCP 连接（省握手），并发批次共享亦安全
    session = requests.Session()
    stats = {"total": len(words), "done": 0, "api_calls": 0, "cached_skip": 0,
             "failed": 0, "cost_yuan": 0.0, "aborted": False, "budget_hit": False}
    start = time.time()
    try:
        for i, w in enumerate(words):
            if cancel_cb and cancel_cb():
                stats["aborted"] = True
                break
            if budget > 0 and stats["cost_yuan"] >= budget:
                stats["budget_hit"] = True
                break
            key = cache_key(w)
            hit = conn.execute(
                "SELECT 1 FROM query_cache WHERE word=?", (key,)).fetchone()
            if hit:
                stats["cached_skip"] += 1
                if progress_cb:
                    progress_cb(i + 1, len(words), w, "缓存已存在，跳过")
                continue
            try:
                r = query_word(w, cfg=cfg, conn=conn, session=session)
            except Exception as e:
                stats["failed"] += 1
                if progress_cb:
                    progress_cb(i + 1, len(words), w, f"失败：{e}")
                continue
            if r.get("error") or r.get("total_found", 1) == 0:
                # error（AI 失败）或查无此词：都不写缓存，如实统计为跳过
                reason = r.get("error") or "真题中未找到该词"
                stats["failed"] += 1
                if progress_cb:
                    progress_cb(i + 1, len(words), w, "跳过：" + str(reason)[:60])
            else:
                stats["api_calls"] += 1
                stats["cost_yuan"] += r.get("cost_yuan", 0)
                if progress_cb:
                    progress_cb(i + 1, len(words), w,
                                f"已缓存（本次 {r.get('cost_yuan', 0):.4f} 元）")
            stats["done"] += 1
            time.sleep(0.1)  # 轻度限速，避免触发限流
    finally:
        session.close()
    stats["seconds"] = round(time.time() - start, 1)
    conn.close()
    return stats


def estimate_words(words, cfg=None, samples: int = 3):
    """预热前成本预估：用官方 tokenizer 离线数样本词的输入 token，
    按配置单价估算预计花费（输出按每句约 55 token 粗估，仅作参考）。
    返回 dict：{words, input_tokens_per_word, est_input_cost, est_total_cost}
    或 None（tokenizer 不可用时降级）。"""
    cfg = cfg or config.load_config()
    from . import tokenizer
    if not words:
        return None
    tok_ok = tokenizer.tokenizer_dir() is not None
    if not tok_ok:
        return None
    from .llm import SYSTEM_PROMPT, build_user_prompt
    from . import dict as dict_mod
    from .db import get_conn
    from .query import find_sentences, sample_sentences
    conn = get_conn()
    max_n = int(cfg.get("max_sentences", 36))
    sys_tok = tokenizer.count_tokens(SYSTEM_PROMPT) or 500
    total_in = 0
    n = 0
    for w in words[:samples]:
        rows, total, _ = find_sentences(conn, w)
        if not rows:
            continue
        texts, _, _ = sample_sentences(rows, max_n, w)
        prompt = build_user_prompt(w, texts, dict_mod.lookup(w))
        t = tokenizer.count_tokens(prompt)
        if t:
            total_in += t
            n += 1
    conn.close()
    if n == 0:
        return None
    avg_in = (total_in / n) + sys_tok  # 每词平均输入 token（含系统提示）
    est_out = max_n * 55.0             # 输出按每句翻译+归类约 55 token 粗估
    zone, mult = config.billing_zone(cfg=cfg)
    p_in = float(cfg.get("price_input", 1.5))
    p_out = float(cfg.get("price_output", 4.5))
    per_word = (avg_in * p_in + est_out * p_out) / 1e6 * mult
    return {
        "words": len(words),
        "per_word_input_tokens": round(avg_in),
        "per_word_est": per_word,
        "est_total": per_word * len(words),
        "zone": zone,
        "mult": mult,
    }


def main():
    parser = argparse.ArgumentParser(description="预热真题高频词到本地缓存")
    parser.add_argument("--top", type=int, default=0, help="按真题词频预热前 N 个实词")
    parser.add_argument("--file", type=str, default="", help="自定义词表文件（每行一个词）")
    parser.add_argument("--budget", type=float, default=0.0,
                        help="预算上限（元）：实际花费累计达到即停止，0=不限制")
    args = parser.parse_args()

    cfg = config.load_config()
    if not cfg.get("api_key"):
        print("未配置 API Key，无法预热。请先运行程序在设置中填写。")
        sys.exit(1)
    zone, mult = config.billing_zone(cfg=cfg)
    print(f"当前计费时段：{zone}（价格 ×{mult:g}）")

    # 与 GUI 启动一致：语料版本变化时重建索引、提示词升级时清空旧缓存。
    from .corpus_builder import corpus_version, build
    from .db import get_conn, get_meta, set_meta
    from .llm import PROMPT_VERSION
    conn = get_conn()
    try:
        try:
            stored = get_meta(conn, "corpus_version")
        except Exception:
            stored = None
        if stored != corpus_version():
            print("语料版本已变化，正在重建索引（请稍候）…")
            build()  # 重建后自动作废 corpus_version 不匹配的旧缓存
            conn = get_conn()  # build 内部重新打开了连接
        if get_meta(conn, "prompt_version") != PROMPT_VERSION:
            conn.execute("DELETE FROM query_cache")
            set_meta(conn, "prompt_version", PROMPT_VERSION)
            print("提示词已升级，旧查询缓存已清空。")
    except FileNotFoundError:
        print("语料文件缺失：corpus\\kaoyan_sentences.jsonl")
        sys.exit(1)
    finally:
        conn.close()

    conn = get_conn()
    if args.file:
        words = read_word_file(args.file)
    elif args.top > 0:
        words = get_freq_words(conn, args.top)
    else:
        print("请用 --top N 或 --file 词表.txt 指定预热范围。")
        sys.exit(1)
    conn.close()
    print(f"共 {len(words)} 个词待预热，开始…")

    # 预热前成本预估（官方 tokenizer 离线估算，仅参考）
    est = estimate_words(words, cfg)
    if est:
        print(f"预计：每词输入约 {est['per_word_input_tokens']} token，"
              f"每词约 {est['per_word_est']:.4f} 元，"
              f"{est['words']} 词合计约 {est['est_total']:.2f} 元（{est['zone']}）")
        if args.budget > 0:
            print(f"预算上限：{args.budget:.2f} 元（达到即停止）")
    else:
        print("（未找到官方 tokenizer，跳过成本预估；可把 deepseek_tokenizer.zip "
              "解压到 corpus/_raw/deepseek_tokenizer/ 启用）")

    def cb(done, total, word, status):
        print(f"[{done}/{total}] {word}: {status}")

    stats = prewarm(words, cfg, progress_cb=cb, budget=args.budget)
    msg = (f"\n完成：处理 {stats['done']} 个，新增缓存 {stats['api_calls']} 个，"
           f"跳过已有缓存 {stats['cached_skip']} 个，失败 {stats['failed']} 个，"
           f"实际花费约 {stats['cost_yuan']:.2f} 元，耗时 {stats['seconds']} 秒。")
    if stats.get("budget_hit"):
        msg += "（达到预算上限，提前停止）"
    print(msg)


if __name__ == "__main__":
    main()
