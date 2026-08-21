# Candidate-first memory write path

Status: implemented on 2026-08-11. This document supersedes the route-A
direct-CRUD portion of the v1/v1.1 write-path documents. Route B remains an
independent attributed-edit path.

## Module homes

- `extraction.py`: candidate Extractor prompt + parse (`CANDIDATE_EXTRACTION_SYSTEM`)
- `retrieval.py`: BM25 + local-embedding RRF helpers
- `consolidate.py`: multi-CASE Consolidator prompt + parse
- `memory_write.py`: thin orchestrator (inventory → extract → retrieve → consolidate)
- `consolidate_tidy_backup.py`: archived GROUPS tidy pass (not on the server path)

## Pipeline

```text
    ordered route-A batch
  -> CandidateExtractor (LLM call 1; batch + work-kinds inventory only)
  -> one independent BM25 + local-embedding RRF search per candidate
  -> fixed top-3 memories per candidate
  -> one multi-CASE Consolidator call (LLM call 2)
  -> mechanical contract validation
  -> append-only Store operations
```

The Extractor does not see memory texts or Store IDs. It does receive the
current work-kinds inventory (seed ∪ kinds on active requirements) so it can
reuse existing genre tags and invent a new slug only when none fit.

The Consolidator receives every candidate's own top-3 in a separate `CASE`.
There is no global candidate union and no `GROUPS` layer. A model decision can
only name memory numbers inside its own CASE, and one Store entry may be
mutated at most once in a batch. If otherwise-valid actions from multiple
CASES claim the same Store entry, all actions involved in that collision are
dropped; CASE order never selects a winner.

## Extractor contract

The Extractor first emits an explicit decision for each plausible atomic
clause. `discard` decisions (`temporary|unclear|not_requirement`) are retained
for audit but never become candidates or reach retrieval. `candidate`
decisions normalize durable items, perform batch-local duplicate removal, and
apply the latest explicit correction in the ordered batch. The Extractor never
sees Store IDs. It may consult the store's work-kinds inventory only.

Candidate kinds:

- `potential_new`: a self-contained desired rule; RRF queries `item.text`.
- `potential_change`: wording that presumes an old rule. `change_mode` is
  explicit: `replace` requires a successor item; `withdraw` requires a null
  item. RRF queries the extractor-produced `target_query`, a facet-level search
  description that need not reconstruct the old rule's exact value.

A successor `item` may be absent only when `change_mode=withdraw`. Such a
candidate must still carry bucket, scope, work kinds, and key so the
Consolidator can compare its intended applicability with retrieved memories.
A bare deictic phrase is resolvable only when its antecedent occurs earlier in
the same batch; a deictic plus a named facet may use that facet as the
`target_query`.

Temporal admission precedes lifecycle and item normalization. An explicitly
current exception, or an override followed by restoration of the old/default
behavior, emits `discard: temporary` even when the message names a reusable
work class or stable facet. If one message also contains a separate durable
future clause, only that durable clause may become a candidate.

`work_kinds` is a non-empty open-slug admission field (seed:
`email|report|postmortem|code|any`). Prefer inventory values; invent a new
English slug only when none fit. Missing or empty values reject the candidate.

`scope` is a free key:value narrowness dict (`audience`, `app`, `language`,
…). Genre / work class belongs in `work_kinds`, not in `scope.task`.

Memory worthiness is defined by the six controlled buckets, in decision order:
`task_goal`, `reasoning_policy`, `deliverables`, `output_contract`,
`communication_style`, and `execution_policy`. One candidate represents one
independently enforceable requirement.

## Retrieval contract

Each candidate is searched independently and receives exactly the first three
fused results. BM25 supplies an inspectable lexical rank; a local lightweight
embedding model supplies a semantic/cross-language rank; standard reciprocal
rank fusion combines rank positions.

The supported default adapter is a local multilingual-e5 ONNX export running
through ONNX Runtime's CPU provider. The model is never downloaded during a
memory flush. If its files or optional dependencies are absent, retrieval
degrades to BM25. Any alternative embedding backend must run on CPU or an
integrated GPU; a discrete GPU, external embedding API, or remote vector store
cannot be required for correctness.

## Consolidator contract

Every candidate and retrieved memory includes text, bucket, scope, work kinds,
and key. The action vocabulary is deliberately small:

- `add`: create the candidate item.
- `reaffirm`: reinforce one semantically equivalent memory (keep its text).
- `merge`: near-synonym unify; optional enriched `text`; one target →
  store `contradict`, two+ → store `merge`.
- `replace`: candidate item supersedes one or more same-facet memories; a
  `potential_change` must carry `change_mode=replace`.
- `retire`: `change_mode=withdraw`, a null successor item, and a matching
  retrieved target. A withdraw CASE may only retire or ignore.
- `ignore`: insufficient evidence or no safe state change.

`add` and `replace` must use the Extractor's item text verbatim. Consolidation
does not synthesize a missing successor. Multiple-target `replace` maps to the
Store's append-only merge/supersede operation; `retire` writes a withdrawal
tombstone and never physically deletes a record.

The validator rejects `reaffirm`, `replace`, and `retire` when candidate and
target have explicitly incompatible scope or work kinds. A uniquely matching
exact-text duplicate is mechanically normalized to `reaffirm`, even if the
model answered `add`, `ignore`, or `replace`.

## Call and failure budget

An admitted route-A batch uses at most two generative calls. Work-kind tagging
is part of the Extractor schema, so no third tagging call follows a normal
flush. If extraction returns only discards or no candidates, the second call is
skipped. Parse errors, inconsistent `change_mode`/item combinations, invalid
CASE targets, duplicate mutations, and local embedding failure all fail closed
without granting the model access to arbitrary Store IDs.

## Bench alignment (2026-08-12)

See `docs/2026-08-12-bench-alignment-candidate-first.md` for Suite L dedup →
CASE consolidator retargeting, E1 product projection (bucket/kinds/scope;
polarity/binding graph-only), and E2E tidy archival notes.
