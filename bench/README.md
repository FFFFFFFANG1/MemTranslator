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

## Current water line

**T = 0.817** (first real run, 2026-07-24; translator=`claude-haiku-4-5`,
judge=`deepseek-v4-pro` via Ark, 0 judge parse flags; snapshot
`T-20260724-005534`)

| category | rate | note |
|---|---|---|
| scope-noop | 1.00 | never touches unrelated input |
| apply-single | 0.90 | 1 fail: zh requirement dragged an en input into zh |
| apply-multi | 0.90 | 1 fail: one of two constraints not woven in |
| exception | 0.80 | 1 real miss + 1 suspected judge false-negative (t-exc-004, → Task 9 audit) |
| language-mixed | 0.80 | same language-drag failure mode as above |
| preserve-long | 0.50 | v0's main weakness: long pasted material → conservative noop |

L / E: pending v1 (NullProvider floor and ReferenceProvider baseline recorded
by Task 9).
