# Codex vs MemTranslator E1 comparison

Status: complete. The 12-episode Codex fleet and offline aggregate completed on
2026-08-26.

## Claim and arms

The main experiment compares complete memory systems on the same authored E1
noisy fleet. It does not force MemTranslator through a GPT-5.5 readout.

- MemTranslator reference: native extraction, Store, BGE-M3 retrieval, and
  DeepSeek V4 Flash Translator. The user-provided 2026-08-21 aggregate reports
  CARRY `0.713`, SUPPRESS `0.894`, STATE `0.707`, per-memory `74/107`, and
  task-perfect `68/103`. The original machine-readable snapshot is not present
  locally, so these values are explicitly marked as screenshot-reported.
- Codex baseline: online `AGENTS.md + MEMORY.md` maintenance and GPT-5.5
  medium readout.

The earlier clean-`e-02` common-readout diagnostic is a separate ablation and
is not a MemTranslator system score.

## Codex causal protocol

For each of the 12 `bench/cases/episodes-noisy` episodes:

1. Start with empty `AGENTS.md` and `MEMORY.md`.
2. Immediately before every authored probe, give a fresh Codex maintenance
   call only the previous files and user messages since the previous probe.
3. Exclude the current probe from that update, then freeze the files.
4. On probes with at least one CARRY or SUPPRESS target, give a second fresh
   Codex call the frozen files and current request. It rewrites the request but
   does not execute it.
5. Treat unscored probes as maintenance checkpoints: update memory, append the
   user message to future history, and skip the unnecessary readout call.
6. Reuse the E1 CARRY judge and mechanical SUPPRESS scorer. Ground truth never
   enters either Codex call.

This requires 209 memory-maintenance calls and 103 scored readout calls rather
than 418 calls. Every checkpoint and prompt hash is persisted for resume.

## Reporting

Report CARRY and SUPPRESS separately as macro episode means with episode-
cluster bootstrap 95% confidence intervals, plus micro counts and task-perfect
rate. Codex has no native structured Store equivalent, so STATE is reported
only for MemTranslator and is not silently treated as comparable.

The primary comparison uses all 12 episodes. Per-episode results are needed
for a paired test; the screenshot aggregate alone supports only aggregate
delta and interval comparison.

## Live pilot

Noisy `e-01`, GPT-5.5 medium:

- CARRY: `5/6` (`0.833`)
- SUPPRESS: `6/6` (`1.000`)
- Task-perfect: `6/7` (`0.857`)
- Maintenance checkpoints: `18`
- Scored readouts: `7`
- Codex-reported tokens under the scored-only accounting: `232,021`

This single episode is a transport and protocol validation, not a comparison
against the 12-episode MemTranslator mean.

Pilot snapshot:
`bench/results/codex-memory-fleet-20260825-110612.json`.

## Full fleet result

The complete Codex run used Codex CLI `0.146.0`, GPT-5.5, medium reasoning,
209 incremental memory-maintenance checkpoints, and 103 scored readouts. The
final aggregate was reconstructed entirely from persisted checkpoints in
under one second, confirming that all 12 episodes were present and no model
call was needed during aggregation.

| Metric | MemTranslator native | Codex file memory | Codex minus MemTranslator |
| --- | ---: | ---: | ---: |
| CARRY macro | `0.713` `[0.637, 0.794]` | `0.672` `[0.585, 0.767]` | `-0.041` |
| SUPPRESS macro | `0.894` `[0.788, 0.970]` | `0.987` `[0.961, 1.000]` | `+0.093` |
| Per-memory / CARRY micro | `74/107` (`69.2%`) | `69/107` (`64.5%`) | `-5/107` |
| Task-perfect | `68/103` (`66.0%`) | `67/103` (`65.0%`) | `-1/103` |
| STATE | `0.707` `[0.671, 0.738]` | not comparable | — |

Codex SUPPRESS micro is `34/35` (`97.1%`). Its total reported usage is
`2,082,725` tokens; summed call latency is `15,179,459 ms`. Mean frozen
`AGENTS.md + MEMORY.md` size over scored readouts is `4,470.6` characters.

Per-episode Codex scores:

| Episode | CARRY | SUPPRESS | Task-perfect |
| --- | ---: | ---: | ---: |
| e-01 | `0.833` | `1.000` | `6/7` |
| e-02 | `0.600` | `1.000` | `6/8` |
| e-03 | `0.750` | no targets | `5/7` |
| e-04 | `0.684` | `1.000` | `7/12` |
| e-05 | `0.667` | `1.000` | `6/9` |
| e-06 | `0.500` | `1.000` | `3/9` |
| e-07 | `1.000` | `1.000` | `4/4` |
| e-08 | `0.667` | `1.000` | `4/5` |
| e-09 | `0.545` | `1.000` | `6/11` |
| e-10 | `0.875` | `0.857` | `10/12` |
| e-11 | `0.545` | `1.000` | `7/10` |
| e-12 | `0.400` | `1.000` | `3/9` |

## Conclusion and limits

On this run, MemTranslator retains more applicable memory: it leads Codex by
five of 107 CARRY anchors and one of 103 fully correct tasks. Codex suppresses
retired or inapplicable memory more reliably: it leads by `0.093` on the
SUPPRESS macro score and leaks one of 35 mechanically checked anchors.

The task-perfect headline is effectively a tie at the observed resolution:
`68/103` versus `67/103`. The aggregate confidence intervals overlap for both
CARRY and SUPPRESS. Because the local repository has only MemTranslator's
screenshot aggregate, not its per-episode vectors or traces, a paired
bootstrap or paired significance test cannot be reconstructed. This result
therefore does not establish overall statistical superiority for either
system. It supports the narrower descriptive finding that MemTranslator has
the better observed CARRY score while Codex has the better observed SUPPRESS
score under their respective native end-to-end pipelines.

This is a system-level comparison, not an isolated memory-writer comparison:
the arms differ in memory representation, retrieval, translator/readout model,
and maintenance protocol. The clean-`e-02` common-readout diagnostic remains
the attribution experiment for holding GPT-5.5 readout constant.

Formal Codex snapshot:
`bench/results/codex-memory-fleet-20260826-020017.json`.
