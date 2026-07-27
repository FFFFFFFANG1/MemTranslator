"""Did the six-bucket extraction prompt make rules over-narrow?

The writer-zh probe showed extraction writing the rule scoped to the instance
it saw — "给房东的邮件不超过120词" instead of "邮件不超过120词", "实验室入组
指南开头带个目录" instead of "长文档开头带目录". An instance-scoped rule
never fires again once the user writes to a different recipient, so the
persona never learns and the translator correctly no-ops forever.

This A/Bs the extraction prompt at da52a7d^ (pre-六桶) against HEAD on
identical first-flush signals, N trials each, and measures how often the
emitted rule names an entity that appeared only in the evidence.
Everything except extraction.py is held fixed.
"""
import collections
import importlib.util
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, "src")

from memtranslator.signals import attribute_diff, screen_message  # noqa: E402

HERE = Path(__file__).parent
N = int(sys.argv[1]) if len(sys.argv) > 1 else 20

# Entities that appear only in rounds 1-2 of writer-zh. A durable rule that
# names one of these has been scoped to the instance rather than the class.
INSTANCE_MARKERS = ["房东", "洗衣机", "实验室入组指南", "入组指南", "新同学"]


PRE_BUCKETS = "da52a7d^"     # the commit that routed extraction through the buckets


def load_old():
    """The pre-六桶 extraction module, checked out on demand so this probe
    still runs on a fresh clone."""
    old = HERE / "extraction_old.py"
    if not old.exists():
        old.write_text(subprocess.run(
            ["git", "show", f"{PRE_BUCKETS}:src/memtranslator/extraction.py"],
            capture_output=True, text=True, check=True).stdout)
    spec = importlib.util.spec_from_file_location("extraction_old", old)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def first_flush_signals(persona):
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


def narrow(text):
    return any(m in text for m in INSTANCE_MARKERS)


def arm(name, run_extraction, a_spans, b_triples):
    with ThreadPoolExecutor(max_workers=4) as ex:
        runs = list(ex.map(lambda _: run_extraction(a_spans, b_triples, []),
                           range(N)))
    n_ops = [len(r["ops"]) for r in runs]
    texts = [o.get("text", "") for r in runs for o in r["ops"]]
    narrow_ops = [t for t in texts if narrow(t)]
    # a trial is "poisoned" if ANY emitted rule is instance-scoped: that rule
    # will sit in the store failing to fire for the rest of the persona
    poisoned = sum(1 for r in runs
                   if any(narrow(o.get("text", "")) for o in r["ops"]))
    scoped_field = sum(1 for r in runs for o in r["ops"] if o.get("scope"))
    print(f"\n{'='*70}\n{name}\n{'='*70}")
    print(f"  ops per trial: mean {sum(n_ops)/len(n_ops):.2f}  "
          f"dist {dict(sorted(collections.Counter(n_ops).items()))}")
    print(f"  instance-scoped rule texts: {len(narrow_ops)}/{len(texts)} ops "
          f"({len(narrow_ops)/len(texts):.0%})")
    print(f"  trials emitting >=1 instance-scoped rule: {poisoned}/{N} "
          f"({poisoned/N:.0%})")
    print(f"  ops carrying a non-empty \"scope\" field: {scoped_field}")
    print("  rule texts:")
    for t, c in collections.Counter(texts).most_common(12):
        print(f"    {'NARROW' if narrow(t) else '  ok  '} {c:3d}/{N}  {t[:60]}")
    return {"poisoned": poisoned, "narrow_ops": len(narrow_ops),
            "total_ops": len(texts)}


def main():
    persona = json.loads(open("bench/cases/personas/writer-zh.json").read())
    a_spans, b_triples = first_flush_signals(persona)

    from memtranslator.extraction import run_extraction as new_run
    old_run = load_old().run_extraction

    old = arm(f"PRE-六桶  (da52a7d^)  N={N}", old_run, a_spans, b_triples)
    new = arm(f"POST-六桶 (HEAD)      N={N}", new_run, a_spans, b_triples)

    print(f"\n{'='*70}\nDELTA\n{'='*70}")
    print(f"  trials with >=1 instance-scoped rule: "
          f"{old['poisoned']}/{N} -> {new['poisoned']}/{N}")
    print(f"  instance-scoped op rate: "
          f"{old['narrow_ops']}/{old['total_ops']} -> "
          f"{new['narrow_ops']}/{new['total_ops']}")


if __name__ == "__main__":
    main()
