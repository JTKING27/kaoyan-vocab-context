# -*- coding: utf-8 -*-
"""查词流水线：归一化 -> 缓存命中 -> 捞真题句 -> AI 逐句译义+汇总 -> 存缓存。

省钱设计：
1. 缓存键 = 词形还原后的原形（study/studying/STUDY 共享一条缓存），重复查零成本；
2. 缓存绑定语料版本，语料更新后自动失效，不会返回过期结果；
3. 每个词只调一次 AI；超过 max_sentences 时按年份均匀抽样（保证义项代表性），
   其余句子照常全部展示，只是不做逐句翻译，成本封顶；
4. AI 输出原始 JSON 原样入库，出错不吞：解析失败单独返回 error 不写缓存。
"""
import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests

from . import config
from . import dict as dict_mod
from . import word_card
from . import affix as affix_mod
from .db import get_conn, get_meta
from .lemmatizer import lemmatize, query_forms
from .llm import (LLMBadRequest, LLMError, PROMPT_VERSION, SYSTEM_PROMPT,
                  build_user_prompt, call_llm)

_MAX_AI_SENTENCES_HARD = 80  # 无论设置如何，最多送 AI 的句数（防误设天价账单）


def normalize_word(word: str):
    """清洗输入：只接受单个英文单词（可含连字符/撇号），返回小写或 None。
    注意：正则不含空格——输入"make up"这类短语会整体被拒（查询是
    按单词匹配的，带空格进来只会得到"未找到"的误导结果）。"""
    w = word.strip().lower()
    w = w.strip("'\".,;:!?()[]")
    if not re.fullmatch(r"[a-z][a-z'-]{1,40}", w):
        return None
    return w


def cache_key(word: str) -> str:
    return lemmatize(word)


def find_sentences(conn: sqlite3.Connection, word: str, limit: int = 2000):
    """捞取包含该词（含变形）的全部句子。返回 (rows, total_count, spans_by_sid)。
    语料层已去重（同一年内实质相同的句子只保留一条）；rows 带 article；
    spans_by_sid: {sentence_id: [(start, end), ...]} 是该句中目标词（含变形）
    的字符区间列表（建索引时算好，供结果页按位置高亮）。

    limit 是捞取上限（防极端高频词内存爆表）：500 会截断 make(549 句)/
    people(659 句) 这类词，2000 覆盖语料里所有实词（只有 the/a/of 等
    停用级虚词超过 2000 句，展示本就受 max_shown_extra 限制）。"""
    forms = sorted(query_forms(word))
    placeholders = ",".join("?" for _ in forms)
    sql = (
        "SELECT DISTINCT s.id, s.year, s.exam_type, s.text, s.source, s.article "
        "FROM words w JOIN sentences s ON w.sentence_id = s.id "
        f"WHERE w.lemma IN ({placeholders}) OR w.form IN ({placeholders}) "
        "ORDER BY s.year, s.id"
    )
    params = forms + forms
    rows = conn.execute(sql, params).fetchall()
    total = len(rows)
    spans_by_sid: dict[int, list[tuple[int, int]]] = {}
    if rows:
        ids = [r["id"] for r in rows]
        id_ph = ",".join("?" for _ in ids)
        span_rows = conn.execute(
            f"SELECT sentence_id, start, end FROM words w "
            f"WHERE (w.lemma IN ({placeholders}) OR w.form IN ({placeholders})) "
            f"AND w.sentence_id IN ({id_ph})",
            params + ids).fetchall()
        for sr in span_rows:
            spans_by_sid.setdefault(sr["sentence_id"], []).append(
                (sr["start"], sr["end"]))
    if limit and len(rows) > limit:
        rows = rows[:limit]
    return rows, total, spans_by_sid


def sample_sentences(rows, max_n: int, word: str):
    """抽样：优先含查询原词本身的句子；每篇文章最多 8 句（同一篇文章
    刷屏时不把整篇都送 AI，省钱且义项归类样本跨篇更均匀）；
    文章间轮转，总数不超过 max_n。"""
    PER_ARTICLE = 8
    if len(rows) <= max_n:
        return [r["text"] for r in rows], [r["id"] for r in rows], len(rows)
    by_art: dict[tuple, list] = {}
    for r in rows:
        key = (r["year"], r["exam_type"], r["article"])
        by_art.setdefault(key, []).append(r)
    for arr in by_art.values():
        arr.sort(key=lambda r: (
            not re.search(rf"\b{re.escape(word)}\b", r["text"], re.I),
            r["year"], r["id"]))
    picked = []
    taken = {k: 0 for k in by_art}
    active = list(by_art.keys())
    i = 0
    while len(picked) < max_n and active:
        key = active[i % len(active)]
        arr = by_art[key]
        if taken[key] >= PER_ARTICLE or not arr:
            active.remove(key)
            continue
        picked.append(arr.pop(0))
        taken[key] += 1
        i += 1
    picked.sort(key=lambda r: r["id"])
    return [r["text"] for r in picked], [r["id"] for r in picked], len(rows)


def parse_ai_json(content: str):
    """解析 AI 输出 JSON，兼容 ```json 围栏。失败抛 ValueError。"""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict) or "sentences" not in data:
        raise ValueError("输出缺少 sentences 字段")
    return data


def _coverage(data) -> set:
    """AI 输出中已给出翻译的句子编号集合（提示词编号 1..N）。"""
    return {item.get("id") for item in data.get("sentences", [])
            if isinstance(item, dict) and item.get("id") is not None}


def _merge_usage(u1, u2):
    out = dict(u1)
    for k in ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens"):
        out[k] = int(u1.get(k) or 0) + int(u2.get(k) or 0)
    return out


def _ai_batch(word: str, texts: list, dict_defs, cfg: dict,
              affix_required: bool = True, etymology: str = "",
              session: requests.Session | None = None):
    """单批调用 AI：texts 用批内编号 1..len(texts)。返回 (data, usage)。
    逐句翻译没给齐时自动重试一次（多花一次钱）。失败抛 LLM 相关异常。
    session 复用连接（并发批次/预热共享同一 Session）。"""
    prompt = build_user_prompt(word, texts, dict_defs, affix_required,
                               etymology)
    content, usage = call_llm(SYSTEM_PROMPT, prompt, cfg, session=session)
    data = parse_ai_json(content)
    prompt_ids = list(range(1, len(texts) + 1))
    if any(pid not in _coverage(data) for pid in prompt_ids):
        content2, usage2 = call_llm(SYSTEM_PROMPT, prompt, cfg, session=session)
        data = parse_ai_json(content2)
        usage = _merge_usage(usage, usage2)
    return data, usage


def _merge_batches(datas: list, batch_sizes: list) -> dict:
    """合并多批 AI 输出（新 schema：句子用 meaning_id 回指义项）。
    datas: 各批 data；batch_sizes: 各批句数（sentences 编号做全局偏移）。
    返回 {"sentences": [...], "meanings": [...]}：
    - meanings 按义项文字精确合并（义项受词典约束，文字一致即同一义项），
      id 全局重新编号；
    - sentences 的 meaning_id 重映射到全局 id（无效 id 置 None，下游归「未分组」）；
    - 各义项的 sentence_ids/count 由代码端从 sentences[].meaning_id 聚合，
      不信任 AI 输出（新提示词也不再要求输出这些字段）。"""
    all_sent = []
    merged: dict[str, dict] = {}   # meaning 文字 -> 全局义项
    id_map: dict[tuple, int] = {}  # (批号, 批内 meaning_id) -> 全局 id
    offset = 0
    for bi, d in enumerate(datas):
        for m in d.get("meanings", []) or []:
            mkey = str(m.get("meaning", "") or "").strip()
            if mkey not in merged:
                merged[mkey] = {"meaning": m.get("meaning", ""),
                                "explain": m.get("explain", ""),
                                "id": len(merged) + 1}
            mid = m.get("id")
            if isinstance(mid, int):
                id_map[(bi, mid)] = merged[mkey]["id"]
        for item in d.get("sentences", []) or []:
            if isinstance(item, dict) and isinstance(item.get("id"), int):
                it = dict(item)
                it["id"] = item["id"] + offset
                mid = item.get("meaning_id")
                if isinstance(mid, int):
                    it["meaning_id"] = id_map.get((bi, mid))
                else:
                    it["meaning_id"] = None
                all_sent.append(it)
        offset += batch_sizes[bi]
    meanings = list(merged.values())
    for m in meanings:
        ids = [s["id"] for s in all_sent if s.get("meaning_id") == m["id"]]
        m["sentence_ids"] = ids
        m["count"] = len(ids)
    return {"sentences": all_sent, "meanings": meanings}


def query_word(word: str, cfg: dict | None = None, conn: sqlite3.Connection | None = None,
               stage: str = "full", session: requests.Session | None = None):
    """查询一个单词。返回结果 dict（含 cached 标志）；AI 不可用时
    allow_api=False 只走缓存。
    stage="preview"：未命中缓存时返回本地预览（词条卡片+真题句子原文，
    不调 AI，秒回）；stage="full"：完整流程（AI 归类翻译）。
    session 复用连接（批量预热传入共享 Session，省 TCP 握手）。"""
    cfg = cfg or config.load_config()
    own_conn = conn is None
    if own_conn:
        conn = get_conn()

    result = {"word": word, "cached": False, "error": None}
    word_n = normalize_word(word)
    if not word_n:
        result["error"] = "请输入单个英文单词（可含连字符，如 well-being）。"
        return result

    key = cache_key(word_n)
    version = get_meta(conn, "corpus_version")
    cached = conn.execute(
        "SELECT result_json, corpus_version, prompt_version, model, usage, "
        "cost_yuan, created_at FROM query_cache WHERE word=?", (key,)).fetchone()
    if cached and cached["corpus_version"] == version \
            and cached["prompt_version"] == PROMPT_VERSION:
        data = json.loads(cached["result_json"])
        data["cached"] = True
        data["cache_created_at"] = cached["created_at"]
        data["cost_yuan"] = cached["cost_yuan"]
        data["cache_key"] = key
        if own_conn:
            conn.close()
        return data

    # ---- 捞句子 ----
    rows, total, spans_by_sid = find_sentences(conn, word_n)
    if total == 0:
        result["total_found"] = 0
        result["suggestions"] = suggest_similar(conn, word_n)
        if own_conn:
            conn.close()
        return result

    # ---- 本地预览阶段（不调 AI，秒回）：词条卡片 + 真题句子原文 ----
    # 查新词时 UI 先显示预览让用户看着，AI 归类翻译完成后再出完整结果
    if stage == "preview":
        card = word_card.lookup(word_n)
        if card:
            result["word_card"] = {
                "memory_hook": card.get("memory_hook", ""),
                "summary": card.get("summary", ""),
                "etymology": card.get("etymology", ""),
                "usage": card.get("usage", ""),
                "study_notes": card.get("study_notes", []),
            }
        # 预览阶段不显示词根词缀（等 AI 拆解结果，避免本地匹配误导）
        result["preview"] = True
        result["cache_key"] = key
        result["total_found"] = total
        result["highlight_forms"] = sorted(query_forms(word_n))
        result["dict_missing"] = dict_mod.lookup(word_n) is None
        shown = int(cfg.get("max_shown_extra", 200))
        result["preview_sentences"] = [
            {"year": r["year"], "exam_type": r["exam_type"],
             "text": r["text"], "source": r["source"],
             "spans": spans_by_sid.get(r["id"], [])}
            for r in rows[:shown]
        ]
        if own_conn:
            conn.close()
        return result

    max_n = min(int(cfg.get("max_sentences", 40)), _MAX_AI_SENTENCES_HARD)
    texts, sent_ids, all_count = sample_sentences(rows, max_n, word_n)
    if not texts:
        result["error"] = "匹配到的句子无法提取。"
        return result

    result.update({
        "cache_key": key,
        "total_found": total,
        "analyzed_count": len(texts),
        "highlight_forms": sorted(query_forms(word_n)),
        "extra_sentences": [
            {"year": r["year"], "exam_type": r["exam_type"],
             "text": r["text"], "source": r["source"],
             "spans": spans_by_sid.get(r["id"], [])}
            for r in rows if r["id"] not in sent_ids
        ][: int(cfg.get("max_shown_extra", 200))],
    })

    # ---- AI ----
    zone, mult = config.billing_zone(cfg=cfg)
    dict_defs = dict_mod.lookup(word_n)
    card = word_card.lookup(word_n)  # 词条卡片（记忆主线/用法/词源/义项解释）
    # 词根词缀：每次都让 AI 拆解（语义判断更可靠，不做本地字符串匹配——
    # 简单匹配会把形似词错拆、误导记忆），结果回填本地词素表随查词积累。
    etymology = card.get("etymology", "") if card else ""
    datas = []  # 多批并发结果（affix 处理用，单批时为空）

    def _plain_rows():
        """AI 失败时：把全部匹配句子（未翻译）放进结果，让用户至少能看到真题句。"""
        return [{"year": r["year"], "exam_type": r["exam_type"],
                 "text": r["text"], "source": r["source"],
                 "spans": spans_by_sid.get(r["id"], [])}
                for r in rows][: int(cfg.get("max_shown_extra", 200))]

    prompt_ids = list(range(1, len(texts) + 1))  # AI 看到的编号是 1..N
    try:
        # 句数多时拆成多批并发（每批 ≤9 句、最多 4 批，防限流）。
        # 义项受词典约束，多批结果可按义项文字精确合并。
        MAX_WORKERS = 4
        MIN_BATCH = 4
        if len(texts) > MIN_BATCH:
            n = len(texts)
            batch_size = max(MIN_BATCH, (n + MAX_WORKERS - 1) // MAX_WORKERS)
            batches = [texts[i:i + batch_size] for i in range(0, n, batch_size)]
            with ThreadPoolExecutor(max_workers=len(batches)) as ex:
                futures = [ex.submit(_ai_batch, word_n, b, dict_defs, cfg,
                                     True, etymology, session)
                           for b in batches]
                results = [f.result() for f in futures]
            datas = [r[0] for r in results]
            usages = [r[1] for r in results]
            # 合并（新 schema）：sentences 编号做全局偏移；meanings 按义项文字
            # 精确合并、id 全局重编号；句子 meaning_id 重映射；
            # 各义项 sentence_ids/count 由代码端从 sentences[].meaning_id 聚合
            merged_data = _merge_batches(datas, [len(b) for b in batches])
            data = {"sentences": merged_data["sentences"],
                    "meanings": merged_data["meanings"],
                    "recommended": datas[0].get("recommended", [])}
            usage = usages[0]
            for u in usages[1:]:
                usage = _merge_usage(usage, u)
        else:
            data, usage = _ai_batch(word_n, texts, dict_defs, cfg,
                                    True, etymology, session)
        # ---- 词根词缀：AI 拆解回填词素表（积累），结果带进展示 ----
        ai_affix = ""
        if datas:  # 多批并发：affix 从第一批 AI 输出取
            ai_affix = str(datas[0].get("affix") or "").strip()
        elif isinstance(data, dict):  # 单批：AI 原始输出
            ai_affix = str(data.get("affix") or "").strip()
        if ai_affix:
            affix_mod.learn(word_n, ai_affix)
        result["affix"] = ai_affix
        missing = [pid for pid in prompt_ids if pid not in _coverage(data)]
        result["untranslated_ids"] = missing  # 提示词编号
    except LLMBadRequest as e:
        result["error"] = str(e)
        result["ai_skipped"] = True
        result["all_sentences"] = _plain_rows()
        if own_conn:
            conn.close()
        return result
    except LLMError as e:
        result["error"] = f"AI 调用失败：{e}"
        result["ai_skipped"] = True
        result["all_sentences"] = _plain_rows()
        if own_conn:
            conn.close()
        return result
    except ValueError as e:
        result["error"] = f"AI 输出解析失败（不扣费重试，请换词或稍后再试）：{e}"
        result["ai_skipped"] = True
        result["all_sentences"] = _plain_rows()
        if own_conn:
            conn.close()
        return result

    # ---- 组装展示数据（AI 输出用提示词编号 1..N 对齐到真实句子）----
    # 新 schema：句子只回指 meaning_id，展示文本由代码端拼
    # 「义项原文（note）」——不再依赖 AI 逐字照抄 pos_meaning，杜绝抄错。
    meaning_by_id = {}
    for m in data.get("meanings", []) or []:
        if isinstance(m.get("id"), int):
            meaning_by_id[m["id"]] = str(m.get("meaning", "") or "").strip()
    sent_map = {}
    for i, (sid, text) in enumerate(zip(sent_ids, texts)):
        sent_map[i + 1] = {"sid": sid, "text": text,
                           "pos_meaning": "", "translation": "", "phrase": "",
                           "meaning_id": None}
    for item in data.get("sentences", []):
        pid = item.get("id")
        if isinstance(pid, int) and pid in sent_map:
            mid = item.get("meaning_id")
            # 无效 meaning_id（不在 meanings 中）归一为 None，
            # 与多批合并行为一致：该句归「未分组」
            valid_mid = mid if (isinstance(mid, int) and mid in meaning_by_id) else None
            note = str(item.get("note", "") or "").strip()
            mtext = meaning_by_id.get(valid_mid, "") if valid_mid else ""
            pm = (mtext + (f"（{note}）" if note else "")).strip()
            sent_map[pid]["pos_meaning"] = pm
            sent_map[pid]["meaning_id"] = valid_mid
            sent_map[pid]["translation"] = str(item.get("translation", "") or "")
            sent_map[pid]["phrase"] = str(item.get("phrase", "") or "")
    analyzed = []
    for i, (sid, text) in enumerate(zip(sent_ids, texts)):
        row = next((r for r in rows if r["id"] == sid), None)
        analyzed.append({
            "id": i + 1,  # 提示词编号，与 meanings[].sentence_ids 一致
            "text": text,
            "year": row["year"] if row else None,
            "exam_type": row["exam_type"] if row else None,
            "source": row["source"] if row else None,
            "article": row["article"] if row else "",
            "spans": spans_by_sid.get(sid, []),
            "pos_meaning": sent_map[i + 1]["pos_meaning"],
            "translation": sent_map[i + 1]["translation"],
            "phrase": sent_map[i + 1]["phrase"],
            "meaning_id": sent_map[i + 1]["meaning_id"],
        })
    meanings = data.get("meanings", [])
    # 新 schema：sentence_ids/count 由代码端从 sentences[].meaning_id 聚合
    # （不信任 AI 输出，新提示词也不再要求输出这些字段）
    by_mid: dict[int, list] = {}
    for item in data.get("sentences", []) or []:
        mid = item.get("meaning_id")
        if isinstance(mid, int) and isinstance(item.get("id"), int):
            by_mid.setdefault(mid, []).append(item["id"])
    for m in meanings:
        mid = m.get("id")
        m.setdefault("meaning", "")
        ids = by_mid.get(mid, []) if isinstance(mid, int) else []
        m["sentence_ids"] = ids
        m["count"] = len(ids)
        # 一句话中文解释：优先本地词条卡片（离线零费用），AI 返回的兜底
        m["explain"] = (word_card.match_explain(card, m.get("meaning", ""))
                        or str(m.get("explain", "") or ""))
    # 空义项（没有任何句子匹配）不展示：程序端硬保证，不依赖 AI 自觉
    meanings = [m for m in meanings if m.get("sentence_ids")]
    # 词典校验：AI 义项若不在词典义项列表内（措辞可比对），标记存疑
    if dict_defs:
        dict_cn = set()
        for d in dict_defs:
            dm = re.sub(r"^[a-z]+\.\s*", "", d.strip())
            for part in re.split(r"[；;，,]", dm):
                if part.strip():
                    dict_cn.add(part.strip())
        for m in meanings:
            m_cn = re.sub(r"^[a-z]+\.\s*", "", str(m.get("meaning", "")).strip())
            m_cn_parts = [p.strip() for p in re.split(r"[；;，,]", m_cn) if p.strip()]
            ok = any(any(p and (p in d or d in p) for d in dict_cn)
                     for p in m_cn_parts)
            if not ok:
                m["unverified"] = True
    # 按「文章篇数」重排义项：一篇刷屏文章不虚高；同篇数比句数
    art_of = {}
    for s in analyzed:
        art_of[s["id"]] = (s.get("year"), s.get("exam_type"),
                           s.get("article", ""))
    for m in meanings:
        ids = [sid for sid in m.get("sentence_ids", []) if sid in art_of]
        m["article_count"] = len({art_of[sid] for sid in ids if art_of[sid]})
        m["sentence_count"] = len(ids)
    meanings.sort(key=lambda m: (-m["article_count"], -m["sentence_count"]))
    recommended = data.get("recommended", [])

    cost = config.estimate_cost(
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
        usage.get("prompt_cache_hit_tokens", 0),
        mult, cfg)
    result.update({
        "meanings": meanings,
        "recommended": recommended,
        "analyzed_sentences": analyzed,
        "dict_missing": dict_defs is None,
        "usage": usage,
        "cost_yuan": round(cost, 5),
        "zone": zone,
        "zone_mult": mult,
        "model": cfg.get("model"),
    })
    # 词条卡片（本地数据，零 AI 费用）：只带展示字段，避免缓存 JSON 膨胀
    if card:
        result["word_card"] = {
            "memory_hook": card.get("memory_hook", ""),
            "summary": card.get("summary", ""),
            "etymology": card.get("etymology", ""),
            "usage": card.get("usage", ""),
            "study_notes": card.get("study_notes", []),
        }

    # ---- 写缓存（含 AI 原始输出，失败不写）----
    conn.execute(
        "INSERT INTO query_cache(word, result_json, corpus_version, "
        "prompt_version, model, usage, cost_yuan, created_at) "
        "VALUES(?,?,?,?,?,?,?,?) "
        "ON CONFLICT(word) DO UPDATE SET result_json=excluded.result_json, "
        "corpus_version=excluded.corpus_version, "
        "prompt_version=excluded.prompt_version, model=excluded.model, "
        "usage=excluded.usage, cost_yuan=excluded.cost_yuan, "
        "created_at=excluded.created_at",
        (key, json.dumps(result, ensure_ascii=False), version,
         PROMPT_VERSION, cfg.get("model"), json.dumps(usage),
         result["cost_yuan"], datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    if own_conn:
        conn.close()
    return result


def suggest_similar(conn, word: str, top: int = 5):
    """查无此词时给出拼写相近的候选（按词频排序）。"""
    letters = sorted(set(word))
    if not letters:
        return []
    rows = conn.execute(
        "SELECT lemma, total FROM word_freq WHERE length(lemma) BETWEEN ? AND ? "
        "ORDER BY total DESC LIMIT 4000",
        (max(1, len(word) - 2), len(word) + 2)).fetchall()

    def dist(a, b):
        if abs(len(a) - len(b)) > 2:
            return 99
        d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
        for i in range(len(a) + 1):
            d[i][0] = i
        for j in range(len(b) + 1):
            d[0][j] = j
        for i in range(1, len(a) + 1):
            for j in range(1, len(b) + 1):
                d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1,
                              d[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
        return d[len(a)][len(b)]

    cands = [(dist(word, r["lemma"]), r["lemma"], r["total"]) for r in rows]
    cands = [c for c in cands if c[0] <= 1 and c[1] != word]
    cands.sort(key=lambda c: (c[0], -c[2]))
    return [c[1] for c in cands[:top]]
