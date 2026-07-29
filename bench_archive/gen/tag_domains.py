"""Tag every catalogue atom with the work domain it belongs to, once.

The fleet partitions the catalogue across 12 personas by stride, which is
domain-blind: an SRE's memory ended up holding "每种岩石描述控制在71个词以内".
Filtering that per-persona after the fact throws away 80% of the corpus,
because most atoms are fine for SOME persona and wrong for this one. Tagging
once and ASSIGNING by fit keeps the supply and removes the non-sequiturs.

`other-specialist` is the drop bucket: rules bound to a trade nobody in the
fleet practises (geology, law, cooking). They are perfectly good rules and
perfectly useless here.

    uv run python -m bench_archive.gen.tag_domains
"""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bench_archive.gen.build_catalogue import _canonical
from bench_archive.gen.flash import flash_json

HARVEST = Path(__file__).resolve().parent / "harvest"
CATALOGUE = HARVEST / "catalogue.jsonl"

DOMAINS = ("code", "docs", "email-comms", "data-analysis",
           "general-writing", "other-specialist")

SYSTEM = f"""You tag a delivery rule with the ONE work domain it belongs to.
{DOMAINS[0]}            — writing or reviewing source code, commits, scripts
{DOMAINS[1]}            — technical documentation, guides, references, reports
{DOMAINS[2]}     — email, chat, announcements, anything addressed to people
{DOMAINS[3]}   — numbers, tables, charts, experiment results
{DOMAINS[4]} — prose style that applies to any written output (tone, length, structure, punctuation)
{DOMAINS[5]} — bound to a trade the rule names explicitly (geology, law, medicine, cooking, education...)

Choose general-writing when the rule is about writing in general rather than one of the specific domains.
Choose other-specialist ONLY when the rule names subject matter outside ordinary knowledge work.
Output exactly: {{"domain": "<one of the six>"}}"""


def tag(atom: dict) -> str:
    got = flash_json(SYSTEM, f"Rule:\n{_canonical(atom['skeleton'])}\n\nJSON:",
                     max_tokens=60)
    d = (got or {}).get("domain")
    return d if d in DOMAINS else "general-writing"


def main():
    atoms = [json.loads(l) for l in CATALOGUE.read_text().splitlines()
             if l.strip()]
    print(f"tagging {len(atoms)} atoms")
    with ThreadPoolExecutor(max_workers=8) as ex:
        tags = list(ex.map(tag, atoms))
    for a, t in zip(atoms, tags):
        a["domain"] = t
    CATALOGUE.write_text("".join(json.dumps(a, ensure_ascii=False) + "\n"
                                 for a in atoms))
    from collections import Counter
    for k, v in Counter(tags).most_common():
        print(f"  {k:18s} {v:5d}")
    keep = sum(1 for t in tags if t != "other-specialist")
    print(f"usable for the fleet: {keep}/{len(atoms)}")


if __name__ == "__main__":
    main()
