"""Mechanical enforcement of the anti-overfit line (design §8 / the 2026-07-25
sign-off): nothing in the product source may be a verbatim lift from a bench
case file.

This exists because the discipline failed as an aspiration. Four exemplar
phrases in the extraction prompt ("这种长文档", "emails I ask you to draft",
"调研类问题", "landlord") were copied out of an instrumented replay of a bench
persona while fixing breadth anchoring; a review caught them, not the author.
A rule the author has to remember is a rule that breaks under deadline, so it
is a test now.

The check: every quoted string literal in the product prompts and lexicons is
sliced into n-grams and looked up in the concatenated case corpus. Short and
generic fragments cannot be evidence of copying, so only spans long enough to
be distinctive are checked — the point is to catch lifted PHRASES, not to ban
the word "email" from a system that is about emails.
"""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "memtranslator"
CASES = Path(__file__).resolve().parents[1] / "bench_archive" / "cases"

# Files whose string literals become prompt or lexicon content.
GUARDED = ["extraction.py", "consolidate.py", "signals.py", "translate.py",
           "recall.py"]

# A lifted phrase is distinctive; a shared word is not. CJK packs far more
# meaning per character, hence the two thresholds.
MIN_CJK_CHARS = 5
MIN_LATIN_WORDS = 4

_CJK = re.compile(r"[\u4e00-\u9fff]")
_STRINGS = re.compile(r'"([^"\\]{4,})"|\'([^\'\\]{4,})\'')

# Narrow escape hatch: fixed set phrases of everyday Chinese that a corpus
# will inevitably also contain. An entry qualifies only if it is dictionary-
# level vocabulary — something written without ever seeing a case file — and
# is short enough to be a set phrase. Anything longer gets deleted from the
# source, never allowlisted; the length cap below is what keeps this from
# becoming a rubber stamp. Each entry carries its justification.
ALLOWED_SET_PHRASES = {
    "从现在开始": "standard Chinese rendering of 'from now on'; the "
                  "rule-setting idiom the signal proposal is built around",
}
ALLOWLIST_MAX_CJK = 6


def _corpus() -> str:
    parts = []
    for p in sorted(CASES.rglob("*")):
        if p.suffix in (".jsonl", ".json") and p.is_file():
            parts.append(p.read_text())
    return "\n".join(parts)


def _literals(path: Path) -> list[str]:
    """String content of a module: quoted literals plus docstring/prompt
    bodies (triple-quoted prompts are the main carrier here)."""
    text = path.read_text()
    out = [m.group(1) or m.group(2) for m in _STRINGS.finditer(text)]
    out += re.findall(r'"""(.*?)"""', text, re.S)
    return [s for s in out if s]


def _cjk_ngrams(s: str, n: int) -> set[str]:
    runs = re.findall(r"[\u4e00-\u9fff]{%d,}" % n, s)
    return {r[i:i + n] for r in runs for i in range(len(r) - n + 1)}


def _latin_ngrams(s: str, n: int) -> set[str]:
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", s)
    return {" ".join(words[i:i + n]).lower()
            for i in range(len(words) - n + 1)}


def test_no_verbatim_bench_phrases_in_product_source():
    corpus = _corpus()
    assert len(corpus) > 10_000, "case corpus not found — guard would be vacuous"
    corpus_lower = corpus.lower()
    cjk_hits, latin_hits = [], []

    for name in GUARDED:
        path = SRC / name
        if not path.exists():
            continue
        for lit in _literals(path):
            for g in _cjk_ngrams(lit, MIN_CJK_CHARS):
                if g in corpus and not any(g in p for p in ALLOWED_SET_PHRASES):
                    cjk_hits.append(f"{name}: {g}")
            for g in _latin_ngrams(lit, MIN_LATIN_WORDS):
                if g in corpus_lower:
                    latin_hits.append(f"{name}: {g}")

    hits = sorted(set(cjk_hits + latin_hits))
    assert not hits, (
        "verbatim bench phrases found in product source — the anti-overfit "
        "line forbids lifting case text into prompts or lexicons:\n  "
        + "\n  ".join(hits))


def test_allowlist_stays_narrow():
    """The escape hatch must stay an escape hatch: set phrases only, each
    justified. A long allowlisted span would mean a lift was waved through."""
    for phrase, why in ALLOWED_SET_PHRASES.items():
        assert len(_CJK.findall(phrase)) <= ALLOWLIST_MAX_CJK, (
            f"{phrase} is too long to be a set phrase — delete it from the "
            f"source instead of allowlisting it")
        assert len(why) > 30, f"{phrase} needs a real justification"


def test_guard_would_catch_a_real_lift():
    """The guard must fail on the exact phrases that slipped through before,
    otherwise it is decoration."""
    corpus = _corpus()
    known_lifts = ["这种长文档", "调研类问题"]
    for phrase in known_lifts:
        grams = _cjk_ngrams(phrase, MIN_CJK_CHARS)
        assert grams, f"{phrase} too short to n-gram"
        assert any(g in corpus for g in grams), (
            f"guard blind to a known lift: {phrase}")
