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

## Current water line (2026-07-24)

Models: translator=`claude-haiku-4-5` (product path, temperature unpinned),
judge=`deepseek-v4-pro` via the .env Ark channel (temperature 0, thinking
disabled). Judge parse flags: 0 across all runs.

| suite | score | provider | note |
|---|---|---|---|
| **T** | **0.817 / 0.800** (two runs) | v0 oracle | real v0 water line |
| **L** | 0.333 floor / **0.806 baseline** | null / reference | baseline to beat for v1 |
| **E** | **0.000 floor / 0.500 baseline** | null / reference | 4/8 personas pass on the naive baseline |

**T per-category (run 1 / run 2):** scope-noop 1.00/1.00 ·
apply-single 0.90/0.90 · apply-multi 0.90/1.00 · exception 0.80/0.70 ·
language-mixed 0.80/0.60 · preserve-long 0.50/0.60.
v0's weak spots: long pasted material → conservative noop (preserve-long),
and zh requirements dragging en inputs into zh (language-mixed).

**Stability (T, two runs):** case-level flips 5/60 (8.3%). Attribution: all
5 flips trace to the translator producing different output between runs
(decision or polished changed); zero flips with identical translator output —
i.e. the grading layer (mech + judge) showed no instability, and the flip
rate measures v0's own run-to-run variance (product path keeps its default
temperature; the bench does not modify src). Suite score moved 0.817 → 0.800.

**L reference detail:** diff-new-constraint 0.17 (the naive one-call baseline
cannot learn from edit diffs — exactly the v1 value proposition),
noise-reject-content 0.67, all other categories 1.00.

**E reference detail:** researcher-zh/writer-zh 1.00, pm-en/student-en 0.88,
mixed-lang 0.50, dev-zh 0.38, datasci-zh 0.75, minimalist-zh 0.00. The
baseline learns personas whose corrections restate rules explicitly, and
loses the ones where a correction appears once and the rest must come from
edit diffs — the same b3 gap Suite L isolates.

**Judge trust: endorsed.** Human audit done 2026-07-24 (annotator: Fang):
28/30 agreement (93.3%) ≥ 90% gate — 1 confirmed judge false-negative
(t-exc-004), 1 row pending annotator re-check; details and v2 improvements in
`bench/gen/judge-audit.md`. Open item for siriux: Fang proposes dropping the
AUTO_NO_INVENTION criterion (hard to audit as phrased); it is also the only
line of defense against invented constraints (it caught the two
exception-category real misses), so this is a scoring-protocol decision, not
applied yet.

**Gate status:** with L/E on stand-in providers the overall is far below
0.80 — expected and by design (sign-off ③: the gate is the v1 acceptance
bar; today's FAIL is a statement of fact, not a bug).
