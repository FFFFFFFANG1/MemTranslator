"""Join submit events (from agent hooks) with translate events.

No markers are ever embedded in text — the daemon holds both sides of the
join, so a time window plus text similarity is enough. Classification feeds
two consumers: acceptance metrics for the rewrite loop, and the v1
extraction corpus.
"""
import re
from difflib import SequenceMatcher

from memtranslator.config import (B_DIFF_CHANGE_TOKENS, B_DIFF_CONTEXT_TOKENS,
                                  B_DIFF_MERGE_GAP_TOKENS,
                                  B_DIFF_SENTENCE_TOKENS)

JOIN_WINDOW_S = 15 * 60
EDIT_SIM_THRESHOLD = 0.55
REVERT_SIM_THRESHOLD = 0.85


def _norm(s: str) -> str:
    return " ".join(s.split())


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def classify_submit(text: str, at: float, translate_events: list[dict]) -> dict:
    """Returns {classification, matched_translate_id, similarity}.

    classification ∈ accepted_verbatim | edited_after_polish | reverted | natural
    """
    candidates = [e for e in translate_events
                  if e.get("kind") == "translate"
                  and e.get("decision") == "apply"
                  and e.get("polished")
                  and 0 <= at - e["at"] <= JOIN_WINDOW_S]
    best = None
    for e in reversed(candidates):  # newest first
        sim_polished = _sim(text, e["polished"])
        sim_original = _sim(text, e.get("original", ""))
        score = max(sim_polished, sim_original)
        if best is None or score > best[0] + 1e-9:
            best = (score, sim_polished, sim_original, e)
    if best is None:
        return {"classification": "natural",
                "matched_translate_id": None, "similarity": None}
    score, sim_polished, sim_original, event = best
    tid = event["translate_id"]
    if _norm(text) == _norm(event["polished"]):
        return {"classification": "accepted_verbatim",
                "matched_translate_id": tid, "similarity": 1.0}
    if sim_original >= REVERT_SIM_THRESHOLD and sim_original >= sim_polished:
        return {"classification": "reverted",
                "matched_translate_id": tid, "similarity": sim_original}
    if sim_polished >= EDIT_SIM_THRESHOLD:
        return {"classification": "edited_after_polish",
                "matched_translate_id": tid, "similarity": sim_polished}
    return {"classification": "natural",
            "matched_translate_id": None, "similarity": None}


# ---------------------------------------------------------------------------
# M1 / B1 — mechanical span attribution over the (raw, polished, final) triple
# (design 2026-07-24 §4; 0 tokens). Verdict drives the mechanical strength
# rule; ambiguous cases carry the triple into the extraction batch instead.
# ---------------------------------------------------------------------------

# Length-weighted survival thresholds for injected spans: below KILL the
# injection is effectively gone, above KEEP it survived; in between the
# signal is ambiguous and the LLM attribution call decides. Engineering
# constants over span arithmetic, not tuned against any eval data.
_SURVIVE_KEEP = 0.7
_SURVIVE_KILL = 0.3


def _spans(a: str, b: str, tags: tuple, side: str) -> list[tuple[int, int]]:
    """Opcode ranges on one side of a SequenceMatcher diff."""
    out = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b).get_opcodes():
        if tag in tags:
            out.append((i1, i2) if side == "a" else (j1, j2))
    return [(s, e) for s, e in out if e > s]


def attribute_diff(raw: str, polished: str, final: str) -> dict:
    """Classify what the user's final edit did to the injected constraints.

    Returns {verdict, injection_survival, strength_delta, user_added}:
    verdict accepted|reverted|partial; survival kept|removed|mixed|none;
    user_added = text the user added on top of polished (route-B b3 feed).
    """
    if _norm(final) == _norm(polished):
        return {"verdict": "accepted", "injection_survival": "kept",
                "strength_delta": +1, "user_added": []}
    if _norm(final) == _norm(raw):
        return {"verdict": "reverted", "injection_survival": "removed",
                "strength_delta": -1, "user_added": []}

    inject = _spans(raw, polished, ("insert", "replace"), side="b")
    edits = _spans(polished, final, ("delete", "replace"), side="a")
    user_added = [final[j1:j2] for j1, j2 in
                  _spans(polished, final, ("insert", "replace"), side="b")]

    total = sum(e - s for s, e in inject)
    if total == 0:
        return {"verdict": "partial", "injection_survival": "none",
                "strength_delta": 0, "user_added": user_added}

    removed = 0
    for s, e in inject:
        for es, ee in edits:
            lo, hi = max(s, es), min(e, ee)
            if hi > lo:
                removed += hi - lo
    survival = 1 - removed / total
    if survival >= _SURVIVE_KEEP:
        label, delta = "kept", +1
    elif survival <= _SURVIVE_KILL:
        label, delta = "removed", -1
    else:
        label, delta = "mixed", 0
    return {"verdict": "partial", "injection_survival": label,
            "strength_delta": delta, "user_added": user_added}


# ---------------------------------------------------------------------------
# Route B — what the user actually changed in our patch, as sentences the
# feedback extractor can attribute. Character-level shards made a semantic
# replacement look like an unrelated add plus an unrelated delete, which is
# the failure this layer exists to prevent.
# ---------------------------------------------------------------------------

_LEXICAL_TOKEN = re.compile(
    r"[\u3400-\u9fff]|[A-Za-z0-9_]+|[^\w\s]", re.UNICODE)
_SENTENCE_END = re.compile(r"[.!?。！？；;\n]")
_TRUNCATED = "[truncated]"


def _token_spans(text: str) -> list[tuple[str, int, int]]:
    """Cheap deterministic lexical tokens with source offsets.

    CJK characters are individual tokens; Latin words, numbers and
    punctuation are tokens. This is intentionally tokenizer-independent so
    write capture stays available whatever the model channel is doing.
    """
    return [(m.group(0), m.start(), m.end())
            for m in _LEXICAL_TOKEN.finditer(text)]


def _token_char_span(tokens: list[tuple[str, int, int]], start: int,
                     end: int, text_len: int) -> tuple[int, int]:
    left = tokens[start][1] if start < len(tokens) else text_len
    right = tokens[end - 1][2] if end > start else left
    return left, right


def _sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    left = 0
    for match in _SENTENCE_END.finditer(text, 0, start):
        left = match.end()
    right_match = _SENTENCE_END.search(text, max(start, end))
    right = right_match.end() if right_match else len(text)
    while left < right and text[left].isspace():
        left += 1
    return left, right


def _marked_sentence(text: str, change_start: int, change_end: int) -> str:
    """Full sentence through B_DIFF_SENTENCE_TOKENS tokens, otherwise a
    symmetric context window around the change."""
    sent_start, sent_end = _sentence_bounds(text, change_start, change_end)
    tokens = [t for t in _token_spans(text)
              if t[1] >= sent_start and t[2] <= sent_end]
    clip_start, clip_end = sent_start, sent_end
    prefix = suffix = ""
    if len(tokens) > B_DIFF_SENTENCE_TOKENS:
        before = [i for i, t in enumerate(tokens) if t[2] <= change_start]
        after = [i for i, t in enumerate(tokens) if t[1] >= change_end]
        first = max(0, (before[-1] + 1 if before else 0)
                    - B_DIFF_CONTEXT_TOKENS)
        last_change = after[0] if after else len(tokens)
        last = min(len(tokens), last_change + B_DIFF_CONTEXT_TOKENS)
        clip_start = tokens[first][1]
        clip_end = tokens[last - 1][2]
        if clip_start > sent_start:
            prefix = _TRUNCATED + " "
        if clip_end < sent_end:
            suffix = " " + _TRUNCATED

    # A huge pasted replacement can itself exceed the sentence budget. Keep
    # its edges while preserving the explicit changed-region marker.
    changed = _token_spans(text[change_start:change_end])
    if len(changed) > B_DIFF_CHANGE_TOKENS:
        half = B_DIFF_CHANGE_TOKENS // 2
        head_end = changed[half - 1][2]
        tail_start = changed[-half][1]
        raw_change = (text[change_start:change_start + head_end]
                      + " " + _TRUNCATED + " "
                      + text[change_start + tail_start:change_end])
    else:
        raw_change = text[change_start:change_end]
    return (prefix + text[clip_start:change_start]
            + "<changed>" + raw_change + "</changed>"
            + text[change_end:clip_end] + suffix)


def _coalesced_changes(a_tokens: list[tuple[str, int, int]],
                       b_tokens: list[tuple[str, int, int]]) -> list[tuple]:
    """Opcodes with near-neighbours merged: an edit that swaps a couple of
    words reads as one change, not a burst of them."""
    matcher = SequenceMatcher(
        None, [t[0].lower() for t in a_tokens],
        [t[0].lower() for t in b_tokens], autojunk=False)
    changes = [op for op in matcher.get_opcodes() if op[0] != "equal"]
    if not changes:
        return []
    out = [list(changes[0])]
    for tag, i1, i2, j1, j2 in changes[1:]:
        prev = out[-1]
        if (i1 - prev[2] <= B_DIFF_MERGE_GAP_TOKENS
                and j1 - prev[4] <= B_DIFF_MERGE_GAP_TOKENS):
            prev[2], prev[4] = i2, j2
            prev[0] = "replace" if prev[1] != i2 and prev[3] != j2 \
                else ("delete" if prev[1] != i2 else "insert")
        else:
            out.append([tag, i1, i2, j1, j2])
    return [tuple(x) for x in out]


def patch_diff(polished: str, final: str) -> list[dict]:
    """Sentence-level, token-aligned human edits for route B.

    Normal edits carry the complete sentence before and after, with the
    changed span explicitly marked. An unedited patch yields no hunks at
    all, which is what lets the queue skip it without spending a call.
    """
    if _norm(polished) == _norm(final):
        return []
    before_tokens, after_tokens = _token_spans(polished), _token_spans(final)
    hunks: list[dict] = []
    labels = {"insert": "add", "delete": "delete", "replace": "replace"}
    for tag, i1, i2, j1, j2 in _coalesced_changes(
            before_tokens, after_tokens):
        a1, a2 = _token_char_span(before_tokens, i1, i2, len(polished))
        b1, b2 = _token_char_span(after_tokens, j1, j2, len(final))
        if i1 == i2 and i1:
            a1 = a2 = before_tokens[i1 - 1][2]
        if j1 == j2 and j1:
            b1 = b2 = after_tokens[j1 - 1][2]
        hunks.append({
            "op": labels[tag],
            "before_sentence": _marked_sentence(polished, a1, a2),
            "after_sentence": _marked_sentence(final, b1, b2),
        })
    return hunks


# ---------------------------------------------------------------------------
# M1 / Route A — sentence-level screening of natural messages (design §4;
# 0 tokens). Splits a message into material vs discourse zones, scores
# discourse sentences on rule-setting features, submits top spans only.
#
# Lexicon provenance (design §8 discipline), corrected 2026-07-25 after an
# audit found the previous note overstated it. Two batches:
#   (a) initial — the signal proposal's own examples ("不是/别再/以后都/记住/
#       要求/太长/太短/重新"), v0 translator vocabulary, generic phrasing;
#   (b) added while iterating against suite failures ("写短/短一点/复述/重复",
#       "repeat/rephrase"). Bench case text was never read to pick these, but
#       the iteration loop that prompted them was bench-driven, so each was
#       re-justified afterwards as everyday delivery vocabulary any user would
#       use about response length and redundancy — not corpus-specific
#       phrasing. tests/test_no_bench_contamination.py enforces mechanically
#       that no lexicon or prompt string is a verbatim lift from a case file.
# ---------------------------------------------------------------------------

# Rule-setting / restating / correcting phrasings. The 太长/太短 entries from
# the proposal generalize to 太X / "too X" (same correction pattern, any
# adjective); restatement generalizes 说过 → 再说一遍/说了多少次/又来了;
# "i said" is the English restatement counterpart; 继续保持 is the everyday
# idiom for re-affirming a standing rule ("keep doing X"). Generic phrasing
# classes, not case-derived vocabulary.
_RULE_PAT = re.compile(
    r"以后|一律|从现在起|从现在开始|从今往后|从今以后|每次都|别再|不要再|"
    r"不是让你|说过|再说一遍|说了?多少次|又来了|记住|必须|一概|太[一-鿿]|"
    r"重新|继续保持|from now on|always|never|only ever|stop\s|i told you|"
    r"i said|remember to|make sure|"
    # "too X" over meta adjectives is the English twin of 太X — a correction
    # of HOW something was delivered, not of content
    r"too\s+(technical|formal|casual|long|short|brief|verbose|detailed|"
    r"complex|simple|many|few)", re.IGNORECASE)
# Withdrawal phrasings score lower than rule-setting: they need a
# meta-discourse hit alongside ("邮件不用卡120词了" yes, "不用谢" no).
# 默认/"back to default" is the everyday way to withdraw a customisation —
# "restore the default" presupposes a standing rule to withdraw.
_WITHDRAW_PAT = re.compile(
    r"不用|不必|取消|算了|去掉|删掉|移除|默认|forget (that|the)|no longer|"
    r"no need to|remove|drop (that|the)|scratch that|never ?mind|"
    r"back to default", re.IGNORECASE)
# Meta-discourse vocabulary: nouns any user reaches for when talking about
# HOW output is rendered (never about its subject matter). The additions
# past the first batch are rendering-level everyday words — emoji, italics,
# brackets, punctuation, decimals — plus numeric length bounds ("152 words",
# "699个词"): a number glued to a length unit is about delivery, not content.
_META_PAT = re.compile(
    r"格式|语气|长度|语言|风格|单位|段落|字数|词数|\d+\s*个?[词字]|简短|简洁|"
    r"[写说]短|短一?点|详细|正式|口语|注释|大纲|引用|来源|出处|结论|总结|"
    r"解释|复述|重复|表情|引号|括号|标点|缩写|脚注|标题|百分比|小数|"
    r"bullet|markdown|latex|format|tone|length|style|concise|"
    r"formal|comment|cite|source|outline|summar|jargon|repeat|rephrase|"
    r"type hints?|emoji|italic|quotation|bracket|punctuat|footnote|heading|"
    r"paragraph|abbreviat|capitali[sz]|percentage|decimal|"
    r"\d+\s*(?:words?|sentences?|lines?|pages?)", re.IGNORECASE)
_IMPERATIVE_PAT = re.compile(
    r"帮我别|给我直接|你要|你别|i need|i want|don't|do not|please\s",
    re.IGNORECASE)
_MD_STRUCT = re.compile(r"^\s*(#{1,6}\s|[-*>]\s|\d+\.\s)")

# Retrospective complaint about OUR output = a preference signal (loop-5,
# 2026-07-31). Measured miss: an emoji-usage rule stated only as a
# complaint about the previous output — no durability marker, no
# imperative, no rendering noun, so every scorer above stays silent. A
# referent pointing back at prior output plus an excess/deficit evaluator
# is feedback extraction should get to judge; its precision rules still
# decide whether a durable rule comes out (screening recalls, extraction
# vets).
_CORRECTION_PAT = re.compile(
    r"(?:that\s+last|the\s+last\s+\w+\s+you|last\s+time|上次|刚才|上一(?:条|封|个|次))"
    r".{0,60}?"
    r"(?:way\s+too|too\s+(?:much|many|long|short|formal|casual)|太(?:多|长|短|正式|随意)|"
    r"别这么|不要这么|过于)",
    re.IGNORECASE | re.DOTALL)

# Controlled facet lexicon: maps facet-key vocabulary to surface forms in
# both product languages, so a stored key can boost a borderline sentence.
_KEY_LEXICON = {
    "email": ["email", "mail", "邮件"], "code": ["code", "代码"],
    "report": ["report", "周报", "报告"], "doc": ["doc", "文档"],
    "meeting": ["meeting", "会议"], "research": ["research", "调研", "论文"],
    "tone": ["tone", "语气"], "length": ["length", "长度", "字数", "词数"],
    "format": ["format", "格式"], "language": ["language", "语言"],
    "style": ["style", "风格"], "explanation": ["explanation", "解释"],
    "comment": ["comment", "注释"], "citation": ["cite", "引用", "出处"],
}

# Latin full stops end a sentence only before whitespace, so decimals
# (0.85), filenames (perf.py) and URLs survive. CJK enders need no such
# guard — they are unambiguous.
_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;\n])|(?<=\.)(?=\s)")
_MATERIAL_MIN_LEN = 80        # a run of ≥3 sentences this HEAVY reads as pasted material
_SPAN_BUDGET = 600            # chars submitted per message, ~600 tokens for zh

_CJK_CHAR = re.compile(r"[一-鿿]")


def _weight(s: str) -> float:
    """Language-normalised sentence length. CJK packs roughly twice the
    meaning per character (same 2:1 the contamination guard uses for
    distinctiveness thresholds), so latin characters count half. Without
    this, _MATERIAL_MIN_LEN — calibrated on Chinese — labels ordinary
    three-sentence English turns as pasted material and masks rule
    statements that scored 5 (measured on the archive replays: en assert
    screening recall 0.57 vs zh 0.97, almost entirely this mask)."""
    s = s.strip()
    cjk = len(_CJK_CHAR.findall(s))
    return cjk + (len(s) - cjk) / 2


def _clip(s: str, max_weight: float) -> str:
    """Prefix of `s` up to a language-normalised weight — the span-assembly
    twin of _weight(); a flat [:80] silently amputated the operative tail
    of English rule sentences (the trailing "…N words max" is the rule)."""
    w = 0.0
    for i, ch in enumerate(s):
        w += 1 if _CJK_CHAR.match(ch) else 0.5
        if w > max_weight:
            return s[:i]
    return s


def _strip_code_fences(text: str) -> str:
    parts = text.split("```")
    return "\n".join(p for i, p in enumerate(parts) if i % 2 == 0)


def _material_mask(sents: list[str]) -> list[bool]:
    mask = [False] * len(sents)
    for i, s in enumerate(sents):
        if _MD_STRUCT.match(s) or "http://" in s or "https://" in s:
            mask[i] = True
    run = []
    for i, s in enumerate(sents):
        if _weight(s) >= _MATERIAL_MIN_LEN:
            run.append(i)
        else:
            if len(run) >= 3:
                for j in run:
                    mask[j] = True
            run = []
    if len(run) >= 3:
        for j in run:
            mask[j] = True
    return mask


def _key_terms(existing_keys: list[str]) -> list[str]:
    terms = []
    for k in existing_keys:
        for part in k.split("."):
            terms += _KEY_LEXICON.get(part, [part] if len(part) > 2 else [])
    return terms


# Tokens that appear in half of all rules AND half of all rule-referencing
# sentences (rule scaffolding, function words, deictics) carry zero facet
# information — overlap on them is not evidence the sentence is ABOUT a
# stored rule. One set serves all three overlap consumers (screening boost,
# extraction referent hints, grounding guard): the perf canary once died
# over a single scaffold token bridging unrelated rules, so the guard and
# the boost must agree on what counts as content. CJK entries are
# bm25-style bigrams.
_OVERLAP_SCAFFOLD = {
    "一律", "以后", "每次", "必须", "不要", "不用", "别再", "别用", "记住",
    "记得", "都要", "使用", "时候", "直接", "之前", "说的", "那条", "这条",
    "现在", "开始", "默认",
    "a", "an", "the", "in", "on", "at", "to", "of", "for", "and", "or",
    "but", "is", "are", "be", "it", "that", "this", "with", "you", "your",
    "i", "my", "me", "we", "our", "please", "don", "dont", "do", "not",
    "no", "never", "always", "must", "keep", "make", "when", "any", "all",
    "under", "over", "than", "from", "now", "so", "just", "can", "use",
    "using", "write", "writing", "up",
}


def content_tokens(text: str) -> set:
    """Facet vocabulary of a rule or a sentence, for overlap matching:
    bm25 tokens minus scaffold, with one trailing latin plural 's'
    stripped so "notifications" (stored rule) meets "notification
    restriction" (withdrawal). Shared by the screening boost, extraction's
    referent hints, the grounding guard and consolidation's overlap
    clustering — BM25 ranking keeps raw tokens.

    Lexicon roots ride along as pseudo-tokens ("root:email"): with English
    as the store's canonical language (owner ruling 2026-07-29) a Chinese
    quotation of a rule shares no surface token with its stored English
    text — digits and format terms bridge naturally, the lexicon bridges
    the rest ("邮件" and "emails" both contribute root:email)."""
    from memtranslator.bm25 import tokenize
    out = set()
    for t in tokenize(text):
        if len(t) <= 1 or t in _OVERLAP_SCAFFOLD:
            continue
        if len(t) >= 4 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        out.add(t)
    low = text.lower()
    for root, surfaces in _KEY_LEXICON.items():
        if any(s.lower() in low for s in surfaces):
            out.add(f"root:{root}")
    return out


def _entry_token_sets(existing_texts: list[str]) -> list[set]:
    return [content_tokens(x) for x in existing_texts]


def overlap_is_reference(sent_tokens: set, entry_tokens: set) -> bool:
    """Does this sentence visibly reference this stored rule? Two shared
    content tokens, or one that is distinctive alone — numeric (a quoted
    cap like "78") or a long latin word ("notification"). This is what
    catches withdrawal/reaffirmation by quotation ("that rule about X —
    drop it"): such a sentence scores WITHDRAW(+2) only, one short of the
    threshold, because the quoted rule text X has no reason to contain
    rule-SETTING phrasing; its vocabulary points at the store instead
    (measured: retire screening recall 0.59-0.64 in both languages before
    this boost)."""
    shared = sent_tokens & entry_tokens
    return (len(shared) >= 2
            or any(any(c.isdigit() for c in t) or len(t) >= 8
                   for t in shared))


def _overlaps_store(sent_tokens: set, entries: list[set]) -> bool:
    return any(overlap_is_reference(sent_tokens, ent) for ent in entries)


def screen_message(text: str,
                   existing_keys: list[str] | None = None,
                   existing_texts: list[str] | None = None) -> list[str]:
    """Return the spans of a natural message worth showing to extraction,
    or [] (most messages — the whole-batch-silent → 0-call property)."""
    sents = [s for s in _SENT_SPLIT.split(_strip_code_fences(text)) if s.strip()]
    if not sents:
        return []
    material = _material_mask(sents)
    key_terms = _key_terms(existing_keys or [])
    entries = _entry_token_sets(existing_texts or [])

    scored = []
    for i, s in enumerate(sents):
        if material[i] or len(s.strip()) < 6:
            continue
        score = 0
        if _RULE_PAT.search(s):
            score += 3
        if _WITHDRAW_PAT.search(s):
            score += 2
        if _META_PAT.search(s):
            score += 2
        if _CORRECTION_PAT.search(s):
            score += 3
        if _IMPERATIVE_PAT.search(s):
            score += 1
        if len(sents) >= 3 and i in (0, len(sents) - 1):
            score += 1
        low = s.lower()
        if any(t.lower() in low for t in key_terms):
            score += 2
        if entries and _overlaps_store(content_tokens(s), entries):
            score += 2
        if score >= 3:
            scored.append((score, i))

    scored.sort(key=lambda x: (-x[0], x[1]))
    spans, budget, taken = [], _SPAN_BUDGET, set()
    for _, i in scored[:3]:
        lo, hi = max(0, i - 1), min(len(sents), i + 2)
        # A SHORT durability anchor is usually deictic ("just don't do it
        # from now on") — the rule's content sits further back, and the ±1
        # window handed extraction a bare pronoun (measured: content
        # sentence two back from the anchor). One extra sentence of
        # lookback, only for short rule-marked anchors.
        if _RULE_PAT.search(sents[i]) and len(sents[i].strip()) < 50:
            lo = max(0, i - 2)
        piece = "".join(_clip(sents[j], _MATERIAL_MIN_LEN)
                        for j in range(lo, hi)
                        if not material[j] and j not in taken)
        taken.update(range(lo, hi))
        if piece and len(piece) <= budget:
            spans.append(piece)
            budget -= len(piece)
    return spans
