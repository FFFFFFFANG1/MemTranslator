"""Minimal repro: the write path kills an unrelated rule when the user's
withdrawal contains a DEICTIC reference with no matching store entry.

Found by the perf suite's collision-free canary (2026-07-29): e-03's user
says 「以后都别用原来那条指令里的免责声明和结构了，直接给结论」 — "stop using
the disclaimer and structure from THAT earlier instruction". The referent
(an instruction from before memory existed) is not in the store. The store
holds exactly one entry: a meeting-notes ordering rule this user never
mentioned. Extraction resolves the dangling reference to the only numbered
entry it can see and emits contradict against it — 3/3 deterministic at
temperature 0 — even welding the two unrelated rules into one franken-text
("会议纪要按时间倒序排列，但删除免责声明和原有结构…"), which shows the model
knows the fit is bad and the op schema forces a target anyway.

Root cause: EXTRACTION_SYSTEM rule 2 offers contradict-with-number and
retire-with-number but NO escape for "the rule being overridden is not in
the store". Fix directions (product, not applied yet):
  a) prompt escape — a referenced-but-absent rule yields `new` (the
     corrected form), never contradict/retire against a dissimilar entry;
  b) zero-LLM guard in parse_ops — a contradict whose text shares no facet
     vocabulary with its target's text is dropped and flagged.

    uv run python -m bench.repro_deixis_kill
"""
from memtranslator.extraction import run_extraction
from memtranslator.schema import Requirement

STORE_RULE = "会议纪要一律按时间倒序排列"
SIGNAL = "以后都别用原来那条指令里的免责声明和结构了，直接给结论。"


def main():
    store = [Requirement(text=STORE_RULE, key="meeting.format")]
    kills = 0
    for trial in range(3):
        out = run_extraction([SIGNAL], [], store)
        hit = [o for o in out["ops"]
               if o["kind"] in ("contradict", "retire")
               and o.get("target_id") == store[0].id]
        kills += bool(hit)
        print(f"trial {trial}: "
              f"{[(o['kind'], (o.get('text') or '')[:46]) for o in out['ops']]}")
    print(f"\nmistargeted kill in {kills}/3 trials "
          f"({'BUG REPRODUCES' if kills else 'not reproducing'})")


if __name__ == "__main__":
    main()
