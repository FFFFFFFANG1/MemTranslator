# MemTranslator Bench — v1 acceptance

**The contract: overall ≥ 80% ⇔ the first user-facing release is good enough.**
Scores are weighted macro averages over three suites (T 0.4 / L 0.3 / E 0.3),
each category equally weighted inside its suite; gate additionally requires
every suite ≥ 70%. Cases are calibrated to everyday usage — if a case failing
would not annoy a real user, it does not belong here (anchor §8: small,
hand-curated, no leaderboard chasing).

| Suite | promise to the user | runnable today |
|---|---|---|
| T translate | polish applies the right constraints, never touches unrelated input | yes (v0 oracle) |
| L learn     | corrections and edit diffs become requirements; noise never does    | via ExtractionProvider (v1) |
| E e2e       | repeated corrections drop off after real use                        | via ExtractionProvider (v1) |

## Run

    source ~/.zshrc          # ANTHROPIC_API_KEY (translator, product path)
    # judge/gen ride the OpenAI-compatible channel in the repo-root .env
    uv run python -m bench.runner.run_translate
    uv run python -m bench.runner.run_extraction --provider reference
    uv run python -m bench.runner.run_e2e --provider reference
    uv run python -m bench.runner.report

## Current water line (2026-07-26)

Models: translator = `claude-haiku-4-5`, **now pinned to temperature 0** for
every product generative call (anchor §5 ranks predictable rewrite magnitude
above peak accuracy; it was also the dominant variance term here). Judge =
`deepseek-v4-pro`, temperature 0. 0 judge parse flags.

| suite | score | vs previous | note |
|---|---|---|---|
| **T** translate | **0.883** | 0.833 | scope-noop held at 1.00 — no over-application traded in |
| **L** learn | **0.870** | 0.870 | unchanged, as expected: L never calls translate |
| **E** chained (gate) | **0.802** | 0.727 | |
| **E** repaired (diagnostic) | **0.857** | 0.841 | |
| **overall** | **0.855** | 0.764 | gate reads chained E only |

**T per category:** apply-single 1.00 · apply-multi 1.00 · language-mixed
**1.00** (was 0.60–0.80, the second-weakest) · scope-noop 1.00 · exception
0.90 · **preserve-long 0.40** — now the single weakest thing in the whole
bench, and unaddressed: long pasted material still drives a conservative noop.

**T per category (2026-07-26):** apply-single / apply-multi / language-mixed
/ scope-noop 1.00 · exception 0.90 · **preserve-long 0.80** (was 0.40).

**Most of that preserve-long jump is a bench repair, not a product gain — do
not read it as progress.** Six of the ten cases (t-long-005..010, all
`generated`) had the stored requirement restated verbatim at the end of the
user's own input, so the model's no-op was CORRECT and the bench was
penalising it while rewarding redundant restatement. A control run settles the
causality: strip the pasted payload and leave the short instruction, and the
same six still no-op — "long pasted material causes conservative no-op" was
never true. The six inputs are repaired (`source: generated-repaired`); the
remaining two failures are kept deliberately, because there the rule is only
PARTLY redundant and applying the novel part is genuinely right.

**P1 fixed the same day — a long paste silently swallowed the hotkey.**
`translate` inherited `llm.complete`'s default `max_tokens=1024`, but the
rewrite is additive so the reply always restates the whole request. Measured
on the product path: a 2,074-character Chinese paste truncated mid-payload,
failed to parse, and degraded to a no-op with no signal to the user.
`output_budget()` now scales the cap with the request (floor 1024, ceiling
8192) and every no-op carries a `reason`. **The bench could not have caught
this: its longest preserve-long input is 619 characters.** That gap between
test-data scale and real usage is the concrete case for the Suite R scale-up.

**L per category:** dedup / natural-explicit / noise-reject-content /
noise-reject-task 1.00 · diff-new-constraint, diff-supersede,
natural-correction, relation 0.83 · **revoke 0.50**.

### The gate outcome depends on which E ruler you accept

Same runs, two aggregation rules for suite E:

| E metric | E | overall | gate |
|---|---|---|---|
| v2 continuous (partial credit, persona mean, 3-run average) | 0.802 | **0.855** | PASS |
| v1 persona-threshold count (round all-or-nothing, ≥0.8 per persona) | 0.500 | 0.764 | FAIL |

The 0.70 per-suite floor and the 0.80 overall bar were both calibrated
against v1 semantics. **Whether this release passes is therefore a pending
decision about the ruler, not a fact the harness can report.** Recalibrating
the threshold for the v2 metric is siriux's call.

**Two harness bugs found and fixed this session, both of which had inflated a
number in our favour:**
1. `latest("E")` globbed `E-*.json`, which also matches the diagnostic
   `E-repaired-*.json`, and that sorts last — so the gate was silently
   grading itself on the gold-state-injected score (0.857 instead of 0.802).
   Now matched exactly, with a regression test.
2. Four exemplar phrases in the extraction prompt were verbatim bench case
   text. Purged; `tests/test_no_bench_contamination.py` now fails the build
   on any verbatim lift.

**Variance after pinning temperature:** mean per-persona spread over 3 runs
fell 0.206 → 0.146, but dev-zh (0.38) and researcher-zh (0.33) remain high —
greedy decoding is not bit-deterministic server-side, and the 16-round chain
amplifies what is left. **Treat any E difference below ~0.10 as noise.**

**Where E's remaining gap sits now:** repaired (0.857) − chained (0.802) =
5.5 points of memory-compounding cost, down from 11.4. The ~14 points below
the repaired ceiling are still translator-side; mixed-lang (0.50 even with a
gold store) is the worst case.

**Fixed this session (both product defects, both found via the bench):**
- **P0 — the translator answered the request.** With several answer-shaped
  requirements stored at once the flash backbone produced an answer instead of
  a rewrite, or deleted words out of the user's question to satisfy "don't
  restate my question". In production that replaces the composer text with an
  answer and sends it onward as the user's own words. Fixed by three explicit
  prompt rules plus `preserves_request()` (a rewrite only adds; ≥85% of the
  original must survive or the patch degrades to noop).
- **Under-application by vocabulary mismatch.** A requirement naming a kind of
  work was skipped whenever the request shared no words with it ("uv 和
  poetry 现在选哪个比较好" did not trigger a stored rule about research
  questions). Applicability is now judged by task kind, not shared vocabulary.
  This is what moved language-mixed to 1.00 and E chained +0.075, with
  scope-noop unmoved at 1.00 — the over-application risk did not materialise.

**Judge trust: endorsed.** Human audit done 2026-07-24 (annotator: Fang;
final after re-check): 29/30 agreement (96.7%) ≥ 90% gate — the single
disagreement is the confirmed t-exc-004 false-negative, whose case criterion
has since been disambiguated; details in `bench/gen/judge-audit.md`. Follow-up (signed off 2026-07-24, the middle
path on Fang's proposal): AUTO_NO_INVENTION is KEPT but reworded into a
replayable checklist (list added constraints → ground each → verdict), and
audit sheets are now generated by `bench/runner/make_audit.py` with the full
judge context per row (stored requirements + original + full polished), so
'need more info' annotations cannot recur. Validation run 3 (v2 wording):
0.833 — inside the runs-1/2 variance band, 0 parse flags, criterion active.
The recurring t-exc-004 false-negative (2/3 runs) traced to that case's own
criterion wording (judge misread stored requirements as request text) and
was disambiguated in the cases file; expect it to pass from run 4 on.

**Gate status (2026-07-25):** superseded by the water line above. The
overall is 0.855 under the v2 E metric and 0.764 under v1 semantics; the
harness prints PASS because it computes the v2 number, but the threshold it
compares against was set for v1. Read the ruler question above before quoting
either figure.
