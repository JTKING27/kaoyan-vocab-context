# -*- coding: utf-8 -*-
"""词形还原：simplemma + 不规则词表兜底，以及查询词形集合生成。

思路：索引与查询都用 simplemma 还原；查询时再生成"该词可能出现的变形集合"，
匹配时 lemma 或 form 命中集合任一成员即可，保证输入原形能命中句中变形。
"""
import re

import simplemma

# 不规则动词/名词/形容词对照：原形 -> 变形集合（双向都会生成）
IRREGULAR = {
    "be": {"am", "is", "are", "was", "were", "been", "being"},
    "have": {"has", "had", "having"},
    "do": {"does", "did", "done", "doing"},
    "go": {"goes", "went", "gone", "going"},
    "make": {"makes", "made", "making"},
    "take": {"takes", "took", "taken", "taking"},
    "come": {"comes", "came", "coming"},
    "see": {"sees", "saw", "seen", "seeing"},
    "know": {"knows", "knew", "known", "knowing"},
    "get": {"gets", "got", "gotten", "getting"},
    "give": {"gives", "gave", "given", "giving"},
    "find": {"finds", "found", "finding"},
    "think": {"thinks", "thought", "thinking"},
    "tell": {"tells", "told", "telling"},
    "become": {"becomes", "became", "becoming"},
    "show": {"shows", "showed", "shown", "showing"},
    "leave": {"leaves", "left", "leaving"},
    "feel": {"feels", "felt", "feeling"},
    "put": {"puts", "putting"},
    "bring": {"brings", "brought", "bringing"},
    "begin": {"begins", "began", "begun", "beginning"},
    "keep": {"keeps", "kept", "keeping"},
    "hold": {"holds", "held", "holding"},
    "write": {"writes", "wrote", "written", "writing"},
    "stand": {"stands", "stood", "standing"},
    "hear": {"hears", "heard", "hearing"},
    "let": {"lets", "letting"},
    "mean": {"means", "meant", "meaning"},
    "set": {"sets", "setting"},
    "meet": {"meets", "met", "meeting"},
    "run": {"runs", "ran", "running"},
    "pay": {"pays", "paid", "paying"},
    "sit": {"sits", "sat", "sitting"},
    "speak": {"speaks", "spoke", "spoken", "speaking"},
    "lie": {"lies", "lay", "lain", "lying"},
    "lead": {"leads", "led", "leading"},
    "read": {"reads", "reading"},
    "grow": {"grows", "grew", "grown", "growing"},
    "lose": {"loses", "lost", "losing"},
    "fall": {"falls", "fell", "fallen", "falling"},
    "send": {"sends", "sent", "sending"},
    "build": {"builds", "built", "building"},
    "understand": {"understands", "understood", "understanding"},
    "draw": {"draws", "drew", "drawn", "drawing"},
    "break": {"breaks", "broke", "broken", "breaking"},
    "spend": {"spends", "spent", "spending"},
    "cut": {"cuts", "cutting"},
    "rise": {"rises", "rose", "risen", "rising"},
    "drive": {"drives", "drove", "driven", "driving"},
    "buy": {"buys", "bought", "buying"},
    "wear": {"wears", "wore", "worn", "wearing"},
    "choose": {"chooses", "chose", "chosen", "choosing"},
    "seek": {"seeks", "sought", "seeking"},
    "teach": {"teaches", "taught", "teaching"},
    "catch": {"catches", "caught", "catching"},
    "fight": {"fights", "fought", "fighting"},
    "win": {"wins", "won", "winning"},
    "sell": {"sells", "sold", "selling"},
    "throw": {"throws", "threw", "thrown", "throwing"},
    "fly": {"flies", "flew", "flown", "flying"},
    "forget": {"forgets", "forgot", "forgotten", "forgetting"},
    "steal": {"steals", "stole", "stolen", "stealing"},
    "swim": {"swims", "swam", "swum", "swimming"},
    "bear": {"bears", "bore", "borne", "born", "bearing"},
    "arise": {"arises", "arose", "arisen", "arising"},
    "awake": {"awakes", "awoke", "awoken", "awaking"},
    "bend": {"bends", "bent", "bending"},
    "bet": {"bets", "betting"},
    "bid": {"bids", "bade", "bidden", "bidding"},
    "bind": {"binds", "bound", "binding"},
    "bite": {"bites", "bit", "bitten", "biting"},
    "bleed": {"bleeds", "bled", "bleeding"},
    "blow": {"blows", "blew", "blown", "blowing"},
    "breed": {"breeds", "bred", "breeding"},
    "burn": {"burns", "burnt", "burning"},
    "burst": {"bursts", "bursting"},
    "cast": {"casts", "casting"},
    "cling": {"clings", "clung", "clinging"},
    "cost": {"costs", "costing"},
    "creep": {"creeps", "crept", "creeping"},
    "deal": {"deals", "dealt", "dealing"},
    "dig": {"digs", "dug", "digging"},
    "dive": {"dives", "dove", "diving"},
    "dream": {"dreams", "dreamt", "dreaming"},
    "drink": {"drinks", "drank", "drunk", "drinking"},
    "eat": {"eats", "ate", "eaten", "eating"},
    "feed": {"feeds", "fed", "feeding"},
    "fit": {"fits", "fitting"},
    "flee": {"flees", "fled", "fleeing"},
    "forbid": {"forbids", "forbade", "forbidden", "forbidding"},
    "forgive": {"forgives", "forgave", "forgiven", "forgiving"},
    "freeze": {"freezes", "froze", "frozen", "freezing"},
    "grind": {"grinds", "ground", "grinding"},
    "hang": {"hangs", "hung", "hanging"},
    "hide": {"hides", "hid", "hidden", "hiding"},
    "hit": {"hits", "hitting"},
    "hurt": {"hurts", "hurting"},
    "kneel": {"kneels", "knelt", "kneeling"},
    "knit": {"knits", "knitting"},
    "lay": {"lays", "laid", "laying"},
    "lend": {"lends", "lent", "lending"},
    "light": {"lights", "lit", "lighting"},
    "mistake": {"mistakes", "mistook", "mistaken", "mistaking"},
    "overcome": {"overcomes", "overcame", "overcoming"},
    "prove": {"proves", "proved", "proven", "proving"},
    "ride": {"rides", "rode", "ridden", "riding"},
    "ring": {"rings", "rang", "rung", "ringing"},
    "saw": {"saws", "sawed", "sawn", "sawing"},
    "shake": {"shakes", "shook", "shaken", "shaking"},
    "shine": {"shines", "shone", "shining"},
    "shoot": {"shoots", "shot", "shooting"},
    "shrink": {"shrinks", "shrank", "shrunk", "shrinking"},
    "shut": {"shuts", "shutting"},
    "sing": {"sings", "sang", "sung", "singing"},
    "sink": {"sinks", "sank", "sunk", "sinking"},
    "sleep": {"sleeps", "slept", "sleeping"},
    "slide": {"slides", "slid", "sliding"},
    "smell": {"smells", "smelt", "smelling"},
    "sow": {"sows", "sowed", "sown", "sowing"},
    "spin": {"spins", "spun", "spinning"},
    "spit": {"spits", "spat", "spitting"},
    "split": {"splits", "splitting"},
    "spread": {"spreads", "spreading"},
    "spring": {"springs", "sprang", "sprung", "springing"},
    "stick": {"sticks", "stuck", "sticking"},
    "sting": {"stings", "stung", "stinging"},
    "strike": {"strikes", "struck", "stricken", "striking"},
    "strive": {"strives", "strove", "striven", "striving"},
    "swear": {"swears", "swore", "sworn", "swearing"},
    "sweep": {"sweeps", "swept", "sweeping"},
    "swell": {"swells", "swelled", "swollen", "swelling"},
    "swing": {"swings", "swung", "swinging"},
    "tear": {"tears", "tore", "torn", "tearing"},
    "thrive": {"thrives", "throve", "thriven", "thriving"},
    "undertake": {"undertakes", "undertook", "undertaken", "undertaking"},
    "wake": {"wakes", "woke", "woken", "waking"},
    "weave": {"weaves", "wove", "woven", "weaving"},
    "weep": {"weeps", "wept", "weeping"},
    "wind": {"winds", "wound", "winding"},
    "withdraw": {"withdraws", "withdrew", "withdrawn", "withdrawing"},
    "withstand": {"withstands", "withstood", "withstanding"},
    "child": {"children"},
    "man": {"men"},
    "woman": {"women"},
    "foot": {"feet"},
    "tooth": {"teeth"},
    "mouse": {"mice"},
    "person": {"people", "persons"},
    "life": {"lives"},
    "wife": {"wives"},
    "knife": {"knives"},
    "leaf": {"leaves"},
    "half": {"halves"},
    "self": {"selves"},
    "crisis": {"crises"},
    "analysis": {"analyses"},
    "basis": {"bases"},
    "datum": {"data"},
    "medium": {"media"},
    "phenomenon": {"phenomena"},
    "criterion": {"criteria"},
    "thesis": {"theses"},
    "index": {"indexes", "indices"},
    "good": {"better", "best"},
    "bad": {"worse", "worst"},
    "little": {"less", "least"},
    "many": {"more", "most"},
    "much": {"more", "most"},
    "far": {"farther", "further", "farthest", "furthest"},
    "old": {"older", "elder", "oldest", "eldest"},
    "well": {"better", "best"},
}

# 反向映射：变形 -> {原形}
FORM_TO_BASE: dict[str, set] = {}
for _base, _forms in IRREGULAR.items():
    _forms.add(_base)
    for _f in _forms:
        FORM_TO_BASE.setdefault(_f, set()).add(_base)


def lemmatize(word: str) -> str:
    """还原词形：先查不规则表，再用 simplemma。"""
    w = word.lower().strip("'\".,;:!?()[]- ")
    if not w:
        return word
    if w in FORM_TO_BASE:
        return next(iter(FORM_TO_BASE[w]))
    return simplemma.lemmatize(w, lang="en")


_VOWELS = "aeiou"


def _rule_forms(base: str) -> set:
    """为原形生成常见规则变形（s/es/ies、ed/d/ied、ing）。假词无害：只会多出几个匹配参数。"""
    forms = set()
    if len(base) < 3:
        return forms
    forms.add(base + "s")
    if base.endswith("y") and len(base) > 3 and base[-2] not in _VOWELS:
        forms.add(base[:-1] + "ies")
    elif base.endswith(("s", "x", "z", "ch", "sh", "o")):
        forms.add(base + "es")
    forms.add(base + "ed")
    if base.endswith("e"):
        forms.add(base + "d")
    elif base.endswith("y") and len(base) > 3 and base[-2] not in _VOWELS:
        forms.add(base[:-1] + "ied")
    forms.add(base + "ing")
    if base.endswith("e"):
        forms.add(base[:-1] + "ing")
    # 双写末字母（run->running, stop->stopping）
    if (len(base) >= 3 and base[-1] not in _VOWELS
            and base[-2] in _VOWELS and base[-3] not in _VOWELS):
        forms.add(base + base[-1] + "ing")
        forms.add(base + base[-1] + "ed")
    return forms


def query_forms(word: str) -> set:
    """查询词可能出现的全部词形（含原形、还原形、不规则变形、规则变形）。"""
    w = word.lower().strip()
    forms = {w}
    base = lemmatize(w)
    forms.add(base)
    forms |= IRREGULAR.get(w, set())
    forms |= IRREGULAR.get(base, set())
    if w in FORM_TO_BASE:
        for b in FORM_TO_BASE[w]:
            forms |= IRREGULAR.get(b, set())
    forms |= _rule_forms(w)
    forms |= _rule_forms(base)
    return {f for f in forms if re.fullmatch(r"[a-z][a-z'-]{0,30}", f)}


def tokenize(text: str):
    """语料分词：只保留英文单词形式（连字符、撇号允许）。"""
    return re.findall(r"[A-Za-z][A-Za-z'-]*", text)


def tokenize_spans(text: str):
    """带字符区间的分词：返回 [(word, start, end)]，start/end 为
    word 在 text 中的起止下标（供结果页按位置高亮，不用正则碰运气）。"""
    return [(m.group(0), m.start(), m.end())
            for m in re.finditer(r"[A-Za-z][A-Za-z'-]*", text)]
