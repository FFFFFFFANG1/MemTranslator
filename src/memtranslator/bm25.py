"""Zero-dependency BM25 for ranking stored requirements against a request.

Why this exists: above a recall lane's budget the read path has to choose, and
until now it chose with `_key_hits_query` — a 14-root lexicon
(email/code/report/doc/…) that only fires when the query happens to use one of
those words. M1 measured what that costs: with a pool of 52, recall()'s output
overlapped "just take the newest 32" on 30 of 32 entries, so the ranking
contributed almost nothing and an old-but-relevant rule was dropped on recency
alone.

BM25 needs no lexicon or model — it is the inspectable lexical half of hybrid
retrieval. Candidate matching may fuse its rank with a local lightweight
embedding rank; if that optional backend is unavailable, BM25 is the complete
fallback. Ranking a 52-entry store costs microseconds.

Tokenisation has to straddle Chinese and English because the users do. Latin
runs become lowercase word tokens; CJK runs become character bigrams, the usual
segmenter-free approach — "邮件结尾" yields 邮件/件结/结尾, so a query saying
"写封邮件" matches on 邮件 without anyone maintaining a word list.
"""
import math
import re
from collections import Counter
from functools import lru_cache

K1 = 1.5          # term-frequency saturation
B = 0.75          # length normalisation
_LATIN = re.compile(r"[a-z0-9_]+")
_CJK = re.compile(r"[一-鿿]+")


def tokenize(text: str) -> list[str]:
    """Latin words plus CJK character bigrams. A one-character CJK run has no
    bigram, so it is kept whole rather than dropped."""
    if not text:
        return []
    low = text.lower()
    tokens = _LATIN.findall(low)
    for run in _CJK.findall(low):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


@lru_cache(maxsize=4096)
def _indexed_document(text: str) -> tuple[tuple[str, ...], Counter]:
    """Content-addressed per-document BM25 work, safe to reuse across calls."""
    tokens = tuple(tokenize(text))
    return tokens, Counter(tokens)


def prepare_bm25_documents(texts: list[str]) -> None:
    """Warm token/TF indexes without constructing a query-specific corpus."""
    for text in texts:
        _indexed_document(text)


def clear_bm25_document_cache() -> None:
    _indexed_document.cache_clear()


def bm25_document_cache_info() -> dict[str, int]:
    info = _indexed_document.cache_info()
    return {"hits": info.hits, "misses": info.misses,
            "size": info.currsize}


class BM25:
    """Immutable corpus snapshot; retrieval caches it by ordered documents."""

    def __init__(self, docs: list[str]):
        indexed = [_indexed_document(d) for d in docs]
        self.docs = [tokens for tokens, _tf in indexed]
        self.n = len(self.docs)
        self.avg_len = (sum(len(d) for d in self.docs) / self.n) if self.n else 0.0
        self.tf = [tf for _tokens, tf in indexed]
        df: Counter[str] = Counter()
        for d in self.docs:
            df.update(set(d))
        # Robertson/Sparck-Jones idf, floored at zero: a term in nearly every
        # document goes negative otherwise and starts penalising the documents
        # that contain it
        self.idf = {
            t: max(0.0, math.log(1 + (self.n - c + 0.5) / (c + 0.5)))
            for t, c in df.items()
        }

    def scores(self, query: str) -> list[float]:
        q = tokenize(query)
        if not q or not self.n:
            return [0.0] * self.n
        out = []
        for tf, doc in zip(self.tf, self.docs):
            dl = len(doc) or 1
            s = 0.0
            for term in q:
                f = tf.get(term)
                if not f:
                    continue
                s += (self.idf.get(term, 0.0) * f * (K1 + 1)
                      / (f + K1 * (1 - B + B * dl / self.avg_len)))
            out.append(s)
        return out

    def rank(self, query: str) -> list[tuple[int, float]]:
        """Document indices by descending score, ties broken by original order
        so the caller's own ordering (recency) survives where BM25 is silent."""
        scored = list(enumerate(self.scores(query)))
        scored.sort(key=lambda p: (-p[1], p[0]))
        return scored
