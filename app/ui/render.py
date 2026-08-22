# -*- coding: utf-8 -*-
"""查询结果 -> HTML 渲染：义项总览（一句话解释 + 按文章篇数排序）+ 分组真题句子
（目标词/搭配高亮，整句翻译内对应中文高亮，同一篇文章的句子折叠）。

没网/没配 Key 等 AI 失败时也照常渲染全部匹配句子（未翻译状态）。
"""
import html
import re

_STYLE = """
<style>
body { font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif; color:#1f2937;
  font-size: 17px; }
.head-note { font-size: 17px; color:#374151; margin: 12px 0 4px 0; }
.m-title { font-size: 20px; font-weight: bold; color: #1e40af; margin: 20px 0 8px 0;
  border-left: 5px solid #3b82f6; padding-left: 10px; }
.m-title .stat { font-size: 16px; color: #6b7280; font-weight: normal; }
.m-list { margin: 10px 0; }
.m-item { font-size: 18px; line-height: 1.9; padding: 8px 12px; margin: 6px 0;
  border:1px solid #e5e7eb; border-radius:8px; }
.m-item .num { color:#1d4ed8; font-weight:bold; }
.m-item .explain { font-size: 19px; font-weight: bold; color:#1f2937; }
.m-item .mraw { font-size: 15px; color:#6b7280; margin-left:4px; }
.m-item .stat { font-size: 16px; color:#6b7280; }
.m-item .warn { color:#b91c1c; font-size:15px; }
.mrow { color:#1f2937; text-decoration:none; display:block; }
.mrow:hover { text-decoration:none; }
.mrow .meaning { font-size:18px; color:#1f2937; }
.mrow .num { color:#1d4ed8; font-weight:bold; }
.mrow .stat { font-size:16px; color:#6b7280; }
.mrow .arrow { color:#6b7280; margin-left:4px; }
.mrow .explain-inline { color:#15803d; font-size:17px; margin-left:6px; }
.sents-box { margin:2px 0 10px 26px; padding-left:10px;
  border-left:3px solid #bfdbfe; }
.g-title { font-size: 20px; font-weight: bold; color: #374151; margin: 24px 0 8px 0;
  border-left: 5px solid #9ca3af; padding-left: 10px; }
.sub-title { font-size: 18px; font-weight: bold; color: #dc2626; margin: 14px 0 4px 0; }
.sub-title .stat { font-size: 15px; color: #6b7280; font-weight: normal; }
.art-title { font-size: 16px; color: #475569; font-weight: bold; margin: 10px 0 2px 0; }
.tmark { background:#fde68a; padding:0 2px; border-radius:3px; }
.sent { border:none; padding:9px 2px; margin:0; }
.sep-line { background:#aeb3b8; font-size:2px; line-height:2px;
  margin:4px 0; }
.sent .en { font-size: 19px; line-height: 1.7; }
.sent .meta { font-size: 16px; color:#475569; margin-top:5px; }
.sent .src { font-size: 14px; color:#9ca3af; margin-top:2px; }
mark { background:#fde68a; padding:0 2px; border-radius:3px; }
.untranslated { color:#9ca3af; font-size:15px; }
.warn { color:#b91c1c; border:1px solid #e5e7eb;
  border-radius:8px; padding:12px 16px; margin:12px 0; font-size:17px; }
.hint { color:#475569; font-size:17px; margin:10px 0; }
.fold-link { margin:12px 0; }
.fold-link a { cursor:pointer; color:#1e40af; font-size:17px;
  text-decoration:none; border-bottom:1px dashed #93c5fd; }
.extra-sent { font-size:17px; color:#374151; border-bottom:1px dashed #d1d5db;
  padding:5px 0; line-height:1.6; }
.extra-sent .src { font-size:14px; color:#9ca3af; }
.card-box { border:1px solid #e5e7eb; border-radius:8px;
  padding:10px 14px; margin:10px 0; }
.card-title { font-size:19px; font-weight:bold; color:#374151; margin-bottom:6px; }
.card-title a { color:#374151; text-decoration:none; }
.card-row { font-size:18px; color:#1f2937; line-height:1.8; margin:4px 0; }
.quote { font-weight: bold; }
.notes-item { font-size:18px; color:#1f2937; line-height:1.8; margin:2px 0;
  padding-left: 1.2em; text-indent: -1.2em; }
</style>
"""


def _mark_spans(text: str, spans: list, phrase: str = ""):
    """按字符区间高亮（转义安全）：spans 是建索引时算好的目标词位置，
    phrase 是 AI 返回的搭配词组（在原文中正则定位、整体高亮，覆盖其中单词）。
    无区间时原样转义返回。"""
    spans = [list(s) for s in (spans or [])]
    if phrase and phrase.strip():
        p = phrase.strip()
        for m in re.finditer(rf"\b{re.escape(p)}\b", text, re.I):
            spans.append([m.start(), m.end()])
    if not spans:
        return html.escape(text)
    spans.sort()
    merged = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    out, pos = [], 0
    for s, e in merged:
        out.append(html.escape(text[pos:s]))
        out.append(f"<mark>{html.escape(text[s:e])}</mark>")
        pos = e
    out.append(html.escape(text[pos:]))
    return "".join(out)


def _quote_underline(text: str) -> str:
    """把文本里的中文双引号「“…”」内容包成下划线增强显示（转义安全）。"""
    esc = html.escape(text or "")
    return re.sub(r"“([^”]+)”", r'<span class="quote">“\1”</span>', esc)


def _card_box_html(card: dict) -> str:
    """词条卡片 HTML：全面解释 → 记忆主线 → 学习要点 → 词源 → 用法
    （本地数据，字体已加大，双引号内容加粗增强显示）。"""
    out = ['<div class="card-box"><div class="card-title">📖 词条卡片</div>']
    if card.get("summary"):
        out.append(f'<div class="card-row"><b>全面解释</b>：'
                   f'{_quote_underline(str(card["summary"]))}</div>')
    if card.get("memory_hook"):
        out.append(f'<div class="card-row"><b>记忆主线</b>：'
                   f'{_quote_underline(str(card["memory_hook"]))}</div>')
    notes = card.get("study_notes") or []
    if notes:
        out.append('<div class="card-row"><b>学习要点</b></div>')
        for n in notes:
            out.append(f'<div class="notes-item">· {_quote_underline(str(n))}</div>')
    if card.get("etymology"):
        out.append(f'<div class="card-row"><b>词源</b>：'
                   f'{_quote_underline(str(card["etymology"]))}</div>')
    if card.get("usage"):
        out.append(f'<div class="card-row"><b>用法</b>：'
                   f'{_quote_underline(str(card["usage"]))}</div>')
    out.append('</div>')
    return "".join(out)


def _affix_box_html(affix: str) -> str:
    """词根词缀独立区块（AI 结果返回后显示在词条卡片下方）。"""
    return ('<div class="card-box"><div class="card-title">🔤 词根词缀</div>'
            f'<div class="card-row">{html.escape(affix)}</div></div>')


def _translation_html(translation: str) -> str:
    """整句中文翻译渲染：【对应含义】→ 高亮；兼容半角 []。"""
    esc = html.escape(translation or "")
    esc = re.sub(r"【([^】]+)】", r'<span class="tmark">\1</span>', esc)
    esc = re.sub(r"\[([^\[\]]{1,20})\]",
                 r'<span class="tmark">\1</span>', esc)
    return esc


def _exam_name(exam_type: str) -> str:
    return {"kaoyan": "统考", "kaoyan1": "英语一", "kaoyan2": "英语二"}.get(
        exam_type, exam_type or "")


def _gloss_text(pos_meaning: str) -> str:
    """从 pos_meaning 取句内词义标注：优先取括注（如「n. 媒介，动因（搜索代理）」
    → 搜索代理），无括注则取义项第一部分（如「n. 代理人」→ 代理人）。"""
    s = (pos_meaning or "").strip()
    m = re.search(r"[（(]([^）)]+)[）)]", s)
    if m and m.group(1).strip():
        return m.group(1).strip()
    s = re.sub(r"^[a-z]+\.[\s]*", "", s)
    return re.split(r"[；;，,]", s)[0].strip()


def _sent_html(s, forms, with_translation=True):
    """句子渲染：目标词按索引位置高亮（搭配整体高亮）；下方显示句内词义
    与整句翻译（翻译中该词对应的中文用高亮标出）。"""
    esc = _mark_spans(s["text"], s.get("spans", []), s.get("phrase", ""))
    meta_parts = [s.get("pos_meaning", ""), _translation_html(s.get("translation", ""))]
    meta = " · ".join(p for p in meta_parts if p)
    src = f'{s.get("year", "")}年 {_exam_name(s.get("exam_type", ""))}'
    out = f'<div class="sent"><div class="en">{esc}</div>'
    if meta:
        out += f'<div class="meta">{meta}</div>'
    else:
        out += '<div class="untranslated">（未翻译）</div>'
    out += f'<div class="src">{html.escape(src)}</div></div>'
    return out


def _fold_link(group_id: str, expanded: bool, text: str) -> str:
    """折叠组的点击链接：点击后由主窗口捕获信号、切换该组展开状态。

    用纯锚点（#fold-N）承载组号：QTextBrowser 点击锚点会发 anchorClicked
    信号，主窗口据此重新渲染（<details> 标签在 QTextBrowser 里不生效，
    这是替代交互）。"""
    label = "▲ 收起本组句子" if expanded else text
    return f'<p class="fold-link"><a href="#{group_id}">{html.escape(label)}</a></p>'


def _sent_group_html(sents, forms, group_id, expanded, max_open: int = 3):
    """一组句子渲染：同篇文章超过 max_open 句时，默认只展示前 max_open 句，
    其余通过点击链接展开（该组在 expanded 中时全部展示 + 收起链接）。"""
    out = []
    if group_id in expanded:
        for i, s in enumerate(sents):
            out.append(_sent_html(s, forms))
            if i < len(sents) - 1:
                out.append('<div class="sep-line">&nbsp;</div>')
        out.append(_fold_link(group_id, True, ""))
        return out
    open_sents = sents[:max_open]
    rest = sents[max_open:]
    for i, s in enumerate(open_sents):
        out.append(_sent_html(s, forms))
        if i < len(open_sents) - 1:
            out.append('<div class="sep-line">&nbsp;</div>')
    if rest:
        first = sents[0]
        label = (f'展开同一篇文章的其余 {len(rest)} 句'
                 f'（{first.get("year", "")}年 {_exam_name(first.get("exam_type", ""))}'
                 f' · {first.get("article", "") or "同篇"}）')
        out.append(_fold_link(group_id, False, label))
    return out


def _render_sent_groups(out: list, sents: list, forms: list[str],
                        expanded, counter: list, fold_prefix: str = "fold"):
    """把一组句子按「文章」聚合：同篇文章连续句子放一起，
    超过 3 句折叠其余（同一篇文章不刷屏）。counter 为折叠组编号器，
    fold_prefix 用于保证折叠组号在义项内部稳定（展开/收起重渲染不变号）。
    任意两条相邻句子之间（无论是否同一篇文章）都插分隔线；
    折叠组自带的 art-title / 收起链接是结构性分隔，不算句子相邻。"""
    by_art: dict[tuple, list] = {}
    for s in sents:
        key = (s.get("year"), s.get("exam_type"), s.get("article", ""))
        by_art.setdefault(key, []).append(s)
    prev_is_sent = False  # 上一个输出块是否为纯句子（决定要不要插分隔线）
    for key in sorted(by_art.keys()):
        arr = by_art[key]
        if len(arr) > 3:
            first = arr[0]
            label = (f'{first.get("year", "")}年 '
                     f'{_exam_name(first.get("exam_type", ""))}'
                     f' · {first.get("article", "") or "同篇"}')
            out.append(
                f'<div class="art-title">{html.escape(label)}'
                f' <span class="stat">（共 {len(arr)} 句）</span></div>')
            counter[0] += 1
            gid = f"{fold_prefix}-{counter[0]}"
            out.extend(_sent_group_html(arr, forms, gid, expanded))
            prev_is_sent = False  # 组尾有收起链接，形成结构性分隔
        else:
            for s in arr:
                if prev_is_sent:
                    out.append('<div class="sep-line">&nbsp;</div>')
                out.append(_sent_html(s, forms))
                prev_is_sent = True


def _render_meaning_sents(out: list, i: int, ids: list, by_id: dict,
                          meaning: str, forms: list[str], expanded, counter: list):
    """渲染某义项下的真题句子：按句内词义（pos_meaning 括注）分小组，
    小组内按文章聚合、超 3 句折叠。折叠组号 fold-{义项号}-{n}，
    用义项号做前缀 + 义项内独立编号，展开/收起重渲染时组号稳定。"""
    sub: dict[str, list] = {}
    for sid in ids:
        pm = by_id[sid].get("pos_meaning", "") or meaning
        sub.setdefault(pm, []).append(sid)
    fold_prefix = f"fold-{i}"
    if len(sub) == 1:
        _render_sent_groups(out, [by_id[sid] for sid in ids], forms,
                            expanded, counter, fold_prefix)
    else:
        for pm, sids in sorted(sub.items(), key=lambda kv: -len(kv[1])):
            label = _gloss_text(pm) or pm
            out.append(
                f'<div class="sub-title">{html.escape(label)}'
                f' <span class="stat">（{len(sids)} 句）</span></div>')
            _render_sent_groups(out, [by_id[sid] for sid in sids],
                                forms, expanded, counter, fold_prefix)


def render_result_html(r: dict, expanded: frozenset = frozenset()):
    """渲染查询结果。expanded 为已展开的折叠组号集合：sents-N（点义项展开的
    真题句）、fold-*（文章内句折叠）点击后由主窗口传入，实现「展开/收起」交互。
    柯林斯式解释直接显示在义项行下方，不再折叠。"""
    # ---------- AI 失败：提示 + 全部匹配句子（未翻译） ----------
    if r.get("error"):
        out = [f'<div class="warn">⚠ {html.escape(r["error"])}</div>']
        all_sents = r.get("all_sentences", [])
        total = r.get("total_found", 0)
        forms = r.get("highlight_forms", [r.get("word", "")])
        if total and all_sents:
            note = f'<div class="hint">匹配到的真题句（共 <b>{total}</b> 句'
            if len(all_sents) < total:
                note += f'，列出前 {len(all_sents)} 句'
            note += '）</div>'
            out.append(note)
            for i, s in enumerate(all_sents):
                en = _mark_spans(s["text"], s.get("spans", []))
                src = f'{s.get("year", "")}年 {_exam_name(s.get("exam_type", ""))}'
                out.append(f'<div class="sent"><div class="en">{en}</div>'
                           f'<div class="src">{html.escape(src)}</div></div>')
                if i < len(all_sents) - 1:
                    out.append('<div class="sep-line">&nbsp;</div>')
        if r.get("suggestions"):
            s = "、".join(f'<b>{html.escape(x)}</b>' for x in r["suggestions"])
            out.append(f'<div class="hint">你要找的是不是：{s}</div>')
        return _STYLE + "".join(out)

    # ---------- 本地预览（查新词 AI 分析中）：词条卡片 + 真题句子原文 ----------
    if r.get("preview"):
        out = []
        card = r.get("word_card") or {}
        if card.get("memory_hook") or card.get("etymology") or card.get("usage"):
            out.append(_card_box_html(card))
        total = r.get("total_found", 0)
        sents = r.get("preview_sentences", [])
        out.append(f'<div class="head-note">📊 {html.escape(r["word"])} · '
                   f'真题共 <b>{total}</b> 句 · <b>AI 分析中…</b></div>')
        out.append(f'<div class="hint">以下为真题句子原文（目标词已高亮），'
                   f'正在分析各句词义与整句翻译，完成后本页自动更新。</div>')
        for i, s in enumerate(sents):
            en = _mark_spans(s["text"], s.get("spans", []))
            src = f'{s.get("year", "")}年 {_exam_name(s.get("exam_type", ""))}'
            out.append(f'<div class="sent"><div class="en">{en}</div>'
                       f'<div class="src">{html.escape(src)}</div></div>')
            if i < len(sents) - 1:
                out.append('<div class="sep-line">&nbsp;</div>')
        if len(sents) < total:
            out.append(f'<div class="hint">…共 {total} 句，其余待 AI 分析完成后显示。</div>')
        return _STYLE + "".join(out)

    # ---------- 查无此词 ----------
    if r.get("total_found", 0) == 0:
        out = ['<div class="hint">📭 真题中未找到该词。</div>']
        if r.get("suggestions"):
            s = "、".join(f'<b>{html.escape(x)}</b>' for x in r["suggestions"])
            out.append(f'<div class="hint">你要找的是不是：{s}</div>')
        return _STYLE + "".join(out)

    forms = r.get("highlight_forms", [r["word"]])
    analyzed = r.get("analyzed_sentences", [])
    total = r.get("total_found", 0)
    n = r.get("analyzed_count", len(analyzed))
    cached = r.get("cached", False)

    out = []
    # ---- 顶部统计（极简一行）----
    out.append(f'<div class="head-note">📊 {html.escape(r["word"])} · '
               f'真题共 <b>{total}</b> 句 · 逐句分析 <b>{n}</b> 句</div>')
    if r.get("dict_missing"):
        out.append('<div class="hint">⚠ 词典未收录该词，义项由 AI 给出，仅供参考。</div>')

    # ---- 词条卡片（本地数据零费用：全面解释/记忆主线/学习要点/词源/用法）----
    card = r.get("word_card") or {}
    if card.get("memory_hook") or card.get("etymology") or card.get("usage"):
        out.append(_card_box_html(card))
    # ---- 词根词缀（AI 结果返回后显示在卡片下方）----
    if r.get("affix"):
        out.append(_affix_box_html(r["affix"]))

    # ---- 义项列表（点义项行展开/收起该义项的真题句子）----
    meanings = [m for m in (r.get("meanings") or []) if m.get("sentence_ids")]
    by_id = {s["id"]: s for s in analyzed}
    used_ids = set()
    group_ids: list[list] = []  # 每个义项实际对应的句子编号
    for m in meanings:
        ids = [sid for sid in m.get("sentence_ids", []) if sid in by_id]
        group_ids.append(ids)
        used_ids.update(ids)
    if meanings:
        out.append('<div class="m-list">')
        for i, m in enumerate(meanings):
            ac = m.get("article_count", 0)
            sc = m.get("sentence_count", len(group_ids[i]))
            warn = ' <span class="warn">⚠ 词典外义项</span>' \
                if m.get("unverified") else ""
            explain = html.escape(str(m.get("explain", "") or ""))
            meaning = html.escape(str(m.get("meaning", "") or ""))
            sents_id = f"sents-{i}"
            sents_open = sents_id in expanded
            arrow = "▾" if sents_open else "▸"
            out.append('<div class="m-item">')
            out.append(
                f'<a class="mrow" href="#{sents_id}">'
                f'<span class="num">义项 {i + 1}</span> · '
                f'<span class="meaning">{meaning}</span> '
                f'<span class="stat">（{ac} 篇 · {sc} 句）</span>'
                f'{warn}')
            if explain:
                out.append(f'<span class="explain-inline">{explain}</span>')
            out.append(f'<span class="arrow">{arrow}</span></a>')
            out.append('</div>')
            if sents_open and group_ids[i]:
                out.append('<div class="sents-box">')
                _render_meaning_sents(out, i, group_ids[i], by_id, meaning,
                                      forms, expanded, [0])
                out.append('</div>')
        out.append('</div>')

    # ---- 其余句子（未归入任何义项的逐句翻译句，极少见）----
    ungrouped = [s for s in analyzed if s["id"] not in used_ids]
    if ungrouped:
        out.append(f'<div class="m-title">其余句子（{len(ungrouped)} 句）</div>')
        for i, s in enumerate(ungrouped):
            out.append(_sent_html(s, forms))
            if i < len(ungrouped) - 1:
                out.append('<div class="sep-line">&nbsp;</div>')

    # ---- 未逐句翻译的句子（默认折叠，点击展开/收起）----
    extra = r.get("extra_sentences", [])
    if extra:
        gid = "fold-extra"
        # 未逐句翻译的真实总数 = 全部句数 - 已分析句数；展示量受
        # max_shown_extra 限制时如实标注（不悄悄少给句子）
        n_shown = len(extra)
        n_all = max(int(r.get("total_found", 0)) - int(r.get("analyzed_count", 0)),
                    n_shown)
        if gid in expanded:
            for s in extra:
                en = _mark_spans(s["text"], s.get("spans", []))
                src = f'{s.get("year", "")}年 {_exam_name(s.get("exam_type", ""))}'
                out.append(f'<div class="extra-sent">{en} '
                           f'<span class="src">{html.escape(src)}</span></div>')
            if n_all > n_shown:
                out.append(f'<div class="hint">共 {n_all} 句未逐句翻译，'
                           f'仅展示前 {n_shown} 句（可在设置中调高'
                           f'「额外展示句数上限」）。</div>')
            out.append(_fold_link(gid, True, ""))
        else:
            label = f"其余 {n_shown} 句 · 点击展开"
            if n_all > n_shown:
                label = f"共 {n_all} 句未逐句翻译 · 列出前 {n_shown} 句 · 点击展开"
            out.append(_fold_link(gid, False, label))

    return _STYLE + "".join(out)
