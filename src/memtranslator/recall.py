"""Read-path hybrid retrieval for the translator.

Active requirements use two independent lanes. Explicit global rules share a
2048-token prompt budget. By default, all remaining rules enter text retrieval
without a hard scope/work-kind filter. An optional experiment first creates a
wider embedding pool from work_kinds + applies_when and then runs body-text
BM25+dense retrieval inside it. No additional model is involved.

style_rule entries never join this list — they go through style_block only.
"""
from memtranslator.config import (GLOBAL_RECALL_MAX_TOKENS,
                                  SCOPED_ATTRIBUTE_POOL_CAP,
                                  SCOPED_RECALL_CAP, STYLE_RULE_CAP)
from memtranslator.kinds import KIND_ANY, _PROSE
from memtranslator.retrieval import (EmbeddingRanker,
                                     default_embedding_ranker,
                                     flatten_applicability_fields,
                                     quota_interleave_order,
                                     rerank_by_best_rank,
                                     rerank_by_rank_sum, sparse_order)
from memtranslator.schema import Requirement
from memtranslator.scopes import (migrate_genre_from_scope, normalize_kind,
                                  normalize_scope)
from memtranslator.signals import estimate_input_tokens


def format_requirement_line(requirement: Requirement, number: int) -> str:
    """Render one Translator entry; recall budgeting and the actual prompt
    must count the same representation."""
    fields = []
    fields.append(f"scope_mode: {requirement.scope_mode}")
    if requirement.kinds:
        if KIND_ANY in requirement.kinds:
            fields.append("work_kinds: all")
        else:
            shown = set(requirement.kinds)
            if shown & _PROSE:
                shown |= _PROSE
            fields.append("work_kinds: " + ", ".join(sorted(shown)))
    scope = normalize_scope(requirement.scope)
    if requirement.applies_when:
        fields.append(f"applies_when: {requirement.applies_when}")
    if scope:
        fields.append("legacy_scope: " + ", ".join(
            f"{key}={value}" for key, value in sorted(scope.items())))
    if requirement.bucket:
        fields.append(f"bucket: {requirement.bucket}")
    if requirement.key:
        fields.append(f"key: {requirement.key}")
    if requirement.confidence:
        fields.append(f"confidence: {requirement.confidence}/10")
    # Retrieval priority and memory chronology are different axes. Reranking
    # intentionally changes presentation order, so the Translator needs an
    # explicit clock to resolve a still-live legacy conflict deterministically.
    fields.append(f"recency: {int(requirement.updated_at * 1000)}")
    suffix = f"  ({'; '.join(fields)})" if fields else ""
    return f"[{number}] {requirement.text}{suffix}"


def requirement_block_tokens(requirements: list[Requirement]) -> int:
    """Deterministic estimate of the exact numbered requirement block."""
    block = "\n".join(
        format_requirement_line(requirement, number)
        for number, requirement in enumerate(requirements, 1))
    return estimate_input_tokens(block)


def select_within_token_budget(requirements: list[Requirement],
                               max_tokens: int) -> list[Requirement]:
    """Keep an ordered priority list within a prompt-token budget.

    If everything fits, return it unchanged. Otherwise preserve priority and
    skip entries that do not fit, allowing a shorter lower-priority entry to
    use the remaining space. Individual rule text is never truncated.
    """
    if requirement_block_tokens(requirements) <= max_tokens:
        return list(requirements)
    selected = []
    for requirement in requirements:
        candidate = selected + [requirement]
        if requirement_block_tokens(candidate) <= max_tokens:
            selected.append(requirement)
    return selected


def _scope_ok(scope: dict, context: dict) -> bool:
    """Return whether known scope dimensions are compatible.

    Graph validation reuses this structural predicate. The read path no longer
    calls it as a hard candidate filter.
    """
    scope = normalize_scope(scope)
    context = normalize_scope(context)
    for dim, want in scope.items():
        have = context.get(dim)
        if have is not None and have != want:
            return False
    return True


def _is_global(requirement: Requirement) -> bool:
    """Only an explicit all+global declaration enters always-on context."""
    kinds = {normalize_kind(kind) for kind in requirement.kinds
             if str(kind).strip()}
    return (KIND_ANY in kinds and requirement.scope_mode == "global"
            and not requirement.applies_when
            and not normalize_scope(requirement.scope))


def _dense_order(ranker: EmbeddingRanker | None, query: str,
                 documents: list[str]) -> list[int]:
    if ranker is None:
        return []
    prepare = getattr(ranker, "prepare", None)
    if prepare is not None:
        try:
            prepare(documents)
        except Exception:
            pass
    try:
        order = ranker.rank(query, documents)
    except Exception:
        return []
    return [index for index in order
            if isinstance(index, int) and 0 <= index < len(documents)]


def _text_order(pool: list[Requirement], query: str,
                ranker: EmbeddingRanker | None, cap: int
                ) -> tuple[list[int], list[int], list[int]]:
    """Body BM25+dense order and its two component rankings."""
    documents = [requirement.text for requirement in pool]
    sparse = sparse_order(query, documents, positive_only=True)
    dense = _dense_order(ranker, query, documents)
    sparse_quota = cap // 2
    order = quota_interleave_order(
        sparse, dense, cap=cap, sparse_quota=sparse_quota,
        dense_quota=cap - sparse_quota)
    if len(order) < cap:
        fallback = sorted(
            range(len(pool)),
            key=lambda index: (
                -pool[index].strength,
                -pool[index].updated_at,
                -pool[index].created_at))
        for index in fallback:
            if index not in order:
                order.append(index)
            if len(order) == cap:
                break
    return rerank_by_best_rank(order, sparse, dense), sparse, dense


def recall(requirements: list[Requirement], *, query: str = "",
           context: dict | None = None,
           embedding_ranker: EmbeddingRanker | None = None
           ) -> list[Requirement]:
    """Return global rules within 2048 tokens plus retrieved non-global top-16.

    ``context`` remains in the public API for callers, but read retrieval does
    not trust inferred or externally supplied labels as a hard eligibility
    gate. Applicability metadata remains in each candidate document and can
    therefore contribute to ranking when the raw query contains matching
    evidence.
    """
    for req in requirements:
        migrate_genre_from_scope(req)
    pool = [r for r in requirements
            if r.status == "active" and r.kind == "requirement"]
    pool.sort(key=lambda r: r.created_at)
    if not pool:
        return []
    global_pool = [requirement for requirement in pool
                   if _is_global(requirement)]
    # Every global is exposed while the whole block fits. Over budget,
    # strength wins and the most recently updated rule breaks ties;
    # presentation order is restored below.
    global_pool.sort(key=lambda requirement: (
        -requirement.strength, -requirement.updated_at,
        -requirement.created_at))
    selected_global = select_within_token_budget(
        global_pool, GLOBAL_RECALL_MAX_TOKENS)
    selected_global.sort(key=lambda requirement: requirement.created_at)

    scoped_pool = [requirement for requirement in pool
                   if not _is_global(requirement)]
    if len(scoped_pool) <= SCOPED_RECALL_CAP:
        selected_scoped = scoped_pool
    elif not query.strip():
        selected_scoped = scoped_pool[:SCOPED_RECALL_CAP]
    else:
        ranker = (embedding_ranker if embedding_ranker is not None
                  else default_embedding_ranker())
        ranked_pool = scoped_pool
        attribute_first = bool(
            SCOPED_ATTRIBUTE_POOL_CAP > 0 and ranker is not None)
        if attribute_first:
            attribute_documents = [
                flatten_applicability_fields(
                    work_kinds=requirement.kinds,
                    applies_when=requirement.applies_when,
                    scope=requirement.scope)
                for requirement in scoped_pool]
            attribute_order = _dense_order(
                ranker, query, attribute_documents)
            fallback = sorted(
                range(len(scoped_pool)),
                key=lambda index: (
                    -scoped_pool[index].strength,
                    -scoped_pool[index].updated_at,
                    -scoped_pool[index].created_at))
            attribute_order = list(dict.fromkeys(
                attribute_order + fallback))
            pool_cap = max(
                SCOPED_RECALL_CAP, SCOPED_ATTRIBUTE_POOL_CAP)
            ranked_pool = [scoped_pool[index]
                           for index in attribute_order[:pool_cap]]

        order, _sparse, _dense = _text_order(
            ranked_pool, query, ranker, SCOPED_RECALL_CAP)
        # Second-stage precision rerank. The E1 trace ablation compared this
        # against fixed-union RRF, rank-sum-only, and metadata-only orders:
        # equal rank-sum of best text order plus applicability-dense order
        # produced the strongest target coverage near the front of the same
        # 16 candidates. It uses the existing local ranker, not another LLM.
        # In attribute-first mode metadata already controls admission. A
        # second metadata rerank would double-count it and diverge from the
        # frozen-trace ablation protocol.
        if not attribute_first:
            applicability_documents = [
                flatten_applicability_fields(
                    work_kinds=requirement.kinds,
                    applies_when=requirement.applies_when,
                    scope=requirement.scope)
                for requirement in ranked_pool]
            applicability = _dense_order(
                ranker, query, applicability_documents)
            if applicability:
                order = rerank_by_rank_sum(order, order, applicability)
        selected_scoped = [ranked_pool[index]
                           for index in order[:SCOPED_RECALL_CAP]]

    return selected_global + selected_scoped


def style_block(requirements: list[Requirement]) -> str:
    """Learned rewrite-style rules for the translator prompt, ≤ cap entries
    (~250 tokens). Empty string when none exist — v0 prompt stays byte-equal."""
    styles = [r for r in requirements
              if r.status == "active" and r.kind == "style_rule"]
    if not styles:
        return ""
    styles.sort(key=lambda r: (-r.strength, -r.updated_at))
    lines = "\n".join(f"- {r.text}" for r in styles[:STYLE_RULE_CAP])
    return f"\nRewrite style rules learned from this user's edits:\n{lines}"
