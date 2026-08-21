# E1 OASST1 noise pool

`oasst1-root-prompts.jsonl` is a deterministic subset of initial prompter
messages from `OpenAssistant/oasst1`, revision
`fdf72ae0827c1cda404aff25b6603abec9e3399b`.

Source: https://huggingface.co/datasets/OpenAssistant/oasst1

License: Apache-2.0. OASST1 is human-generated and human-annotated by the
OpenAssistant contributors. The benchmark treats these prompts as ordinary
one-off requests with no durable user-memory requirement; that assumption is
part of the E1 noise protocol and is intentionally not LLM-validated.

Only root `prompter` messages with positive review, non-deleted,
non-synthetic records are eligible. Rows with positive official spam, PII,
not-appropriate, hate-speech, or sexual-content labels are excluded. Text is
whitespace-normalized and capped at 500 characters. Selection is by a stable
hash of the OASST1 message id, not by model scoring.

Regenerate after downloading the pinned supplemental prompts export:

```bash
PYTHONPATH=src .venv/bin/python -m bench.suites.build_noise_pool \
  /path/to/2023-04-12_oasst_prompts.messages.jsonl.gz \
  --output bench/cases/noise/oasst1-root-prompts.jsonl

PYTHONPATH=src .venv/bin/python -m bench.suites.expand_episode_noise \
  --episodes-dir bench/cases/episodes \
  --noise-pool bench/cases/noise/oasst1-root-prompts.jsonl \
  --output-dir bench/cases/episodes-noisy
```
