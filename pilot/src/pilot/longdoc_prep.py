"""Generate 30 long-content instances for the preservation ablation
(plan Task 4, consumed by Task 12). Each: a short analysis-type request +
300-800 word synthetic material + one applicable preference from PrefEval.
Human-review the output file before use — run explicitly, not part of tests."""

from __future__ import annotations

import json
import random

from pilot import llm
from pilot.config import INSTANCES, MODELS, N_LONGDOC, SEED
from pilot.data_prep import build_instances, load_prefeval

KINDS = ["a research paper abstract", "an email thread (3 messages)",
         "a project README section", "a meeting-notes excerpt",
         "a product review", "a short technical blog post"]

GEN_SYSTEM = ("Write realistic synthetic text for benchmark construction. "
              "Output only the text, no preamble.")


def main() -> None:
    rng = random.Random(SEED)
    pos, _ = build_instances(load_prefeval(), n_pos=N_LONGDOC, n_neg=0)
    INSTANCES.mkdir(parents=True, exist_ok=True)
    out = INSTANCES / "longdoc.jsonl"
    with out.open("w") as f:
        for i, inst in enumerate(pos):
            kind = KINDS[i % len(KINDS)]
            doc = llm.call(
                MODELS["downstream_strong"],
                f"Write {kind}, 300-800 words, on any everyday topic. "
                f"Seed: {rng.randint(0, 10**6)}",
                system=GEN_SYSTEM, max_tokens=2048)["text"].strip()
            inst = dict(inst)
            inst["id"] = f"long-{i:04d}"
            inst["kind"] = "longdoc"
            inst["request"] = ("Please take a look at the following "
                               f"{kind.split(' (')[0]} and share your thoughts.")
            inst["content"] = doc
            f.write(json.dumps(inst, ensure_ascii=False) + "\n")
            print(f"[{i+1}/{N_LONGDOC}] {inst['id']}", flush=True)
    print(f"-> {out}  (human-review before use)")


if __name__ == "__main__":
    main()
