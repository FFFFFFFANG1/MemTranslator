# Bench alignment with candidate-first write path (2026-08-12)

Status: incremental update after the Layout-B cleanup
(`extraction.py` owns A extract; `consolidate.py` owns CASE reconcile;
GROUPS tidy lives only in `consolidate_tidy_backup.py`).

This note records how the bench was retargeted. Older design docs are left
intact; they describe the history that produced the suites.

## Suite L — `dedup` now feeds the CASE consolidator

Previously `l-ddp-*` had `events: []` and expected `merge` from
`provider.consolidate` (GROUPS tidy). That path is archived.

Now each dedup case carries a structured `candidate` fixture. The harness
calls `provider.reconcile(candidate, existing)`:

1. Build a `MemoryCandidate` from the fixture (kind/item/work_kinds/…).
2. Run product hybrid retrieval (fixed top-3).
3. Call the live CASE consolidator prompt + `parse_consolidation_output`.
4. Grade store ops. Near-duplicate restatements expect `reinforce` against
   **any** of the listed near-duplicate indices (`targets: [i, j, …]`).

Route-A extract cases and Route-B diff cases are unchanged.

## Suite E1 — product projection vs catalogue overhang

Scoring bands (CARRY / SUPPRESS / STATE) are unchanged.

**Product Requirements** built for oracle/gold stores now project:

| Catalogue | Product field |
|---|---|
| clause/text | text |
| coords.key | key |
| coords.bucket | bucket |
| coords.scope (4-dim) | free scope via `to_product_scope` (app/lang; task → kinds) |
| scope.task + annotate_kinds + optional coords.kinds | `Requirement.kinds` |

**Not projected (intentionally):** `coords.polarity`, `coords.binding`.

They remain in episode JSON because `bench.graph.relate` still uses polarity
sign for DUPLICATES vs CONTRADICTS when rebuilding edges. E1 scoring never
read them; the live product schema no longer stores them. Deleting them from
the corpus would require rewriting the relation algebra — deferred.

## Suite E2E — seed-then-score + B-side alignment (2026-08-12)

Product rule: Route B judges attributed edits only (`update`/`retire` on
entries the patch wove in) and never creates memory. Route A is the create
path.

E2E harness protocol:

1. **Absorb.** First `E2E_SEED_ROUNDS` (5) `final`s plus any
   `natural_correction`s are one Route-A batch with `skip_screen=True`
   (rewritten requests fail `screen_message`; seed naturals are standing
   restatements we still force through). Flush before any scored translate.
2. **Score.** Translate + carry judge only for rounds
   `E2E_SECOND_HALF_FROM` (6) … 16.
3. **Continue learning.** On a scored miss: queue `natural_correction` when
   present; always queue `final` (`skip_screen`) so later paraphrases still
   hit CASE consolidate; queue `edited_diff` only if `applied_ids` and a
   real `patch_diff`; flush splits `channel=a|b` onto `apply_ops` /
   `apply_feedback_ops`.

`METRIC_VERSION` bumped to 4 for the seed-window change.


## Still partial / follow-ups

- L `relation` fixtures are still plain texts (no kinds/scope metadata).
- E1 catalogue still authors closed 4-dim scope + polarity/binding for the
  graph; product sees the projection only.
- No bench yet grades intermediate candidate-first contracts
  (`change_candidate`, CASE collision drop) directly outside L dedup.
