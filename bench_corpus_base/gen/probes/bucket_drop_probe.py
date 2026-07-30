"""Does extraction silently drop rules when the model mislabels the bucket?

`parse_ops` validates "bucket" against the six-item BUCKETS tuple and
`continue`s on a miss — the whole op is discarded, rule text and all, over a
metadata typo. (A bad "polarity", by contrast, is merely dropped as
metadata and the rule survives.) A flash-tier model picking a near-miss label
would therefore lose the rule outright, which is the shape of the writer-zh
failure: the first flush sometimes yields three clean rules and sometimes
yields nothing the translator can use.

Runs writer-zh's real first-flush payload through the real V1 path N times,
capturing the parse flags V1Provider normally discards.
"""
import collections
import json
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, ".")
sys.path.insert(0, "src")

from memtranslator.extraction import run_extraction              # noqa: E402
from memtranslator.schema import BUCKETS                         # noqa: E402
from memtranslator.signals import attribute_diff, screen_message  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 20


def first_flush_signals(persona):
    """Rounds 1-2 both miss on an empty store, so the pending list is their
    edited diffs plus any natural corrections — exactly what run_persona
    hands the provider at the first flush."""
    a_spans, b_triples = [], []
    for rd in persona["rounds"][:2]:
        attr = attribute_diff(rd["task"], rd["task"], rd["final"])
        b_triples.append({"raw": rd["task"], "polished": rd["task"],
                          "final": rd["final"], "applied": [],
                          "survival": attr["injection_survival"]})
        if rd.get("natural_correction"):
            a_spans += screen_message(rd["natural_correction"],
                                      existing_keys=[])
    return a_spans, b_triples


def main():
    persona = json.loads(open("bench/cases/personas/writer-zh.json").read())
    a_spans, b_triples = first_flush_signals(persona)
    print(f"SIGNALS-A spans: {a_spans}")
    print(f"SIGNALS-B records: {len(b_triples)}")
    print(f"legal buckets: {BUCKETS}\n")

    with ThreadPoolExecutor(max_workers=4) as ex:
        runs = list(ex.map(lambda _: run_extraction(a_spans, b_triples, []),
                           range(N)))

    kept_hist = collections.Counter()
    flag_freq = collections.Counter()
    trials_with_drop = 0
    for r in runs:
        kept_hist[len(r["ops"])] += 1
        dropped = False
        for f in r["flags"]:
            flag_freq[f] += 1
            if "unknown bucket" in f:
                dropped = True
        trials_with_drop += dropped

    print(f"trials: {N}")
    print("\nops surviving parse_ops, per trial:")
    for k in sorted(kept_hist):
        bar = "#" * kept_hist[k]
        print(f"   {k} ops  x{kept_hist[k]:<3} {bar}")
    print(f"\ntrials losing >=1 op to an unknown bucket: {trials_with_drop}/{N}")
    if flag_freq:
        print("\nparse flags raised:")
        for f, c in flag_freq.most_common():
            print(f"   {c:3d}x  {f}")
    else:
        print("\nno parse flags raised in any trial")

    print("\nbuckets on surviving ops:")
    bf = collections.Counter(o.get("bucket", "") for r in runs for o in r["ops"])
    for b, c in bf.most_common():
        print(f"   {c:3d}x  {b!r}")

    print("\nrule texts, by how many trials produced them:")
    tf = collections.Counter(o.get("text", "")[:52] for r in runs
                             for o in r["ops"])
    for t, c in tf.most_common(15):
        print(f"   {c:3d}/{N}  {t}")


if __name__ == "__main__":
    main()
