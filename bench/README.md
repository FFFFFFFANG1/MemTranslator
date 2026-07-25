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

## Current water line (2026-07-25, clean code)

"Clean" = after two integrity fixes landed the same day: bench-lifted phrases
purged from the extraction prompt (now enforced by
`tests/test_no_bench_contamination.py`), and the translator P0 below fixed.
Numbers from earlier in the day are NOT comparable and were dropped.

Models: translator = `claude-haiku-4-5` (product path, temperature unpinned —
this is the dominant variance source), judge = `deepseek-v4-pro` over the .env
channel (temperature 0, thinking disabled). 0 judge parse flags.

| suite | score | note |
|---|---|---|
| **T** translate | 0.833 (last measured pre-P0; re-measure pending) | v0 oracle path |
| **L** learn | **0.870** | reference baseline 0.833, gate 0.70 — passes |
| **E** e2e (chained, gate metric) | **0.727** | gate 0.70 under the v2 metric — see the threshold caveat |
| **E** e2e (repaired, diagnostic) | **0.841** | store reset to gold rules after each flush |

**L per category:** dedup 1.00 · natural-explicit 1.00 · noise-reject-content
1.00 · noise-reject-task 1.00 · diff-new-constraint 0.83 · diff-supersede 0.83
· natural-correction 0.83 · relation 0.83 · **revoke 0.50** (the one weak
category: telling a durable revocation apart from a one-off deviation).

**De-contamination cost nothing measurable.** L on the clean prompt is 0.870,
inside the 0.852–0.926 band measured with the contaminated exemplars. The
lifted phrases were a discipline breach, not a score prop — worth stating
plainly in both directions.

**The E metric changed on 2026-07-25 and the gate threshold did not.** v1
scored a round all-or-nothing and a persona pass/fail at 0.8; v2 grades
partial credit per requirement, averages persona rates instead of counting
threshold crossings, and averages `--repeat` runs. On the same clean chained
runs the v1-style persona-pass fraction is 3/8 = 0.375 while the v2 continuous
score is 0.727. The 0.70 gate was calibrated against v1 semantics, so
"0.727 > 0.70" is not a pass — **the threshold needs recalibrating for the new
ruler, and that is siriux's call, not the harness's.**

**Where E's remaining gap actually is.** repaired (0.841) minus chained
(0.727) = 11 points attributable to memory error compounding; the other ~16
points are a ceiling that survives a perfect store, i.e. translator-side
under-application. Diagnosed by probe: "写个小工具监控训练 loss 曲线异常"
with a stored "code comments in English" rule returns noop — the task type is
not recognised as code. The same defect class shows up independently in suite
T's language-mixed category (0.80).

**Variance is still the limiting factor on E.** Per-persona spread over 3 runs
reaches 0.50 (dev-zh), mean 0.21. Any E comparison below ~0.15 is noise. More
repeats, or personas conditioned to be less brittle, are needed before E can
adjudicate a design change.

**P0 fixed this session — the translator was answering the request.** With
several answer-shaped requirements stored at once ("keep answers short" / "no
bullets" / "don't restate my question"), the flash backbone flipped from
rewriting the request to answering it, and in one case satisfied "don't
restate my question" by deleting words out of the question. In production that
replaces the user's composer text with an answer which is then sent onward as
if they had typed it. Fixed by three explicit prompt rules plus a mechanical
`preserves_request()` guard (a rewrite may only add; ≥85% of the original must
survive or the patch degrades to noop). Effect on the worst-hit persona
(minimalist-zh): 0.44 → 0.81 chained, 0.48 → 0.96 repaired.

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

**Gate status:** with L/E on stand-in providers the overall is far below
0.80 — expected and by design (sign-off ③: the gate is the v1 acceptance
bar; today's FAIL is a statement of fact, not a bug).
