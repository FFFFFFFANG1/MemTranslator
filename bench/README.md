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

(filled by Task 5 / Task 9 runs)
