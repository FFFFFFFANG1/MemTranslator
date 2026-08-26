"""Catalogue build: skeletons → mutate → annotate → the atom pool episodes
draw from. Output bench/gen/harvest/catalogue.jsonl (still gitignored — the
episode file is the versioned artifact, and it carries only skeleton-derived
material, never source text).

Each atom gets:
- a mutated skeleton (anti-backbone, field-level)
- coords from 3-vote annotation, with per-field confidence
- a `distinctive` anchor: the mutated number, or the object head word —
  the substring family that grading and store-alignment key on

    uv run python -m bench_corpus_base.gen.build_catalogue
"""
import argparse
import json
import random
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bench_corpus_base.gen.annotate import annotate
from bench_corpus_base.gen.gates import delivery_gate
from bench_corpus_base.gen.mutate import mutate


def _canonical(sk: dict) -> str:
    """Readable rendering of a skeleton. The first version concatenated
    trigger+act+object+"{value} {unit}" blindly and produced strings like
    "when writing shell scripts use shell 14 items" — a number welded onto a
    clause that never asked for one. 5.6% of the first fleet's nodes carried
    that damage into the gold. The threshold now renders as a comparison
    phrase, and only when the object does not already state it."""
    parts = []
    if sk.get("trigger"):
        parts.append(str(sk["trigger"]).strip())
    act = str(sk.get("act") or "").strip()
    obj = str(sk.get("object") or "").strip()
    if act and obj:
        parts.append(f"{act} {obj}")
    elif act or obj:
        parts.append(act or obj)
    th = sk.get("threshold") or {}
    val = th.get("value")
    if val is not None and str(val) not in obj:
        unit = str(th.get("unit") or "").strip()
        cmp_ = "at least" if any(w in act.lower()
                                 for w in ("least", "minimum", "min")) \
            else "no more than"
        parts.append(f"({cmp_} {val} {unit})".replace(" )", ")"))
    order = [str(x) for x in (sk.get("order") or []) if x]
    if len(order) == 2:
        parts.append(f"({order[0]} before {order[1]})")
    if sk.get("polarity") in ("avoid", "prohibit") and act \
            and not any(w in act.lower() for w in ("avoid", "not", "never",
                                                   "omit", "skip")):
        parts.insert(max(0, len(parts) - 1), "avoid:")
    return " ".join(p for p in parts if p).strip()

HARVEST = Path(__file__).resolve().parent / "harvest"
OUT = HARVEST / "catalogue.jsonl"


def _distinctive(sk: dict) -> str:
    th = sk.get("threshold")
    if th and th.get("value") is not None:
        return str(th["value"])
    obj = (sk.get("object") or "").strip()
    # head word of the object: survives rewording better than the full phrase
    words = re.findall(r"[a-zA-Z]+|[一-鿿]+", obj)
    return words[-1] if words else obj


_SRC = Path(__file__).resolve().parents[2] / "src"
_SRC_CORPUS = None


def _src_corpus() -> str:
    global _SRC_CORPUS
    if _SRC_CORPUS is None:
        _SRC_CORPUS = "\n".join(p.read_text()
                                for p in _SRC.rglob("*.py")).lower()
    return _SRC_CORPUS


def anchor_ok(distinctive: str) -> bool:
    """Admission control for the grading anchor. The distinctive doubles as
    the substring the whole mech band keys on; a weak one poisons every
    number downstream — 'case' matches everything (fake CARRY), a single
    digit matches noise (fake SUPPRESS misses), and anything already sitting
    in src/ means the 'memory' under test ships in the product prompt.

    This is the G1 gate's second half: no strong anchor → no mechanical
    criterion → the atom does not enter the catalogue."""
    d = distinctive.strip()
    if not d:
        return False
    if d.isdigit():
        return len(d) >= 2
    cjk = len(re.findall(r"[一-鿿]", d))
    if cjk == 0 and len(d) < 4:
        return False
    if cjk == 1 and len(d) == 1:
        return False
    return d.lower() not in _src_corpus()


def build_one(args) -> dict | None:
    n, item, seed = args
    rng = random.Random(seed * 7919 + n)
    mutated, desc = mutate(item["skeleton"], rng)
    if not anchor_ok(_distinctive(mutated)):
        return None                     # weak grading anchor → not admissible
    ok, _why = delivery_gate(_canonical(mutated))
    if not ok:
        return None                     # content/values/vacuous → distractor pool
    coords = annotate(mutated)
    if not coords["key"]:
        return None                     # no registry key won a vote → unusable
    return {"aid": f"atom-{n:04d}",
            "skeleton": mutated,
            "raw": item.get("raw", ""),      # gitignored; licence gate input
            "mutation": desc,
            "coords": coords,
            "distinctive": _distinctive(mutated),
            "provenance": item["provenance"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=23)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    skels = [json.loads(l) for l in
             (HARVEST / "skeletons.jsonl").read_text().splitlines()
             if l.strip()]
    if args.limit:
        skels = skels[:args.limit]
    print(f"annotating {len(skels)} skeletons (3 votes each)")
    jobs = [(n, s, args.seed) for n, s in enumerate(skels)]
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(build_one, jobs))
    kept = [r for r in results if r]
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                           for r in kept))
    n_low = sum(1 for r in kept if r["coords"]["conf"]["bucket"] < 1.0
                or r["coords"]["conf"]["key"] < 1.0)
    print(f"catalogue: {len(kept)} atoms ({len(skels) - len(kept)} dropped "
          f"keyless), {n_low} with a contested field -> {OUT.name}")


if __name__ == "__main__":
    main()
