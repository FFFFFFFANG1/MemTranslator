"""Did trimming 4c keep the writer-zh fix and drop the minimalist-zh damage?

writer-zh has a class to name (emails vs long documents) and 4c helped it.
minimalist-zh's three rules are global answering-style rules with no class at
all — the long 4c ("strip the particulars: who it was addressed to, what the
file was called") had nothing to strip there, and that persona fell 0.708 ->
0.194. This measures the first flush of both personas under the prompt with
and without 4c, so the trim's effect is visible before spending a full E run.

Narrow = the rule text names an entity that appeared only in the evidence
rounds, so it can never fire on a later round.
"""
import collections
import json
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, ".")
sys.path.insert(0, "src")

from memtranslator import llm                                     # noqa: E402
from memtranslator.config import GEN_TEMPERATURE, MODELS          # noqa: E402
from memtranslator import extraction as ex_mod                    # noqa: E402
from memtranslator.signals import attribute_diff, screen_message  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 20

PERSONAS = {
    "writer-zh": ["房东", "洗衣机", "实验室入组指南", "入组指南", "新同学"],
    "minimalist-zh": ["conda", "uv", "git", "rebase", "merge", "端口", "进程"],
}


def strip_4c(system):
    a = system.find("4c. STATE THE CLASS")
    b = system.find("\n5. Rate each op")
    assert a > 0 and b > a, "anchors moved; re-check the prompt"
    return system[:a] + system[b + 1:]


def first_flush_signals(persona):
    a_spans, b_triples = [], []
    for rd in persona["rounds"][:2]:
        attr = attribute_diff(rd["task"], rd["task"], rd["final"])
        b_triples.append({"raw": rd["task"], "polished": rd["task"],
                          "final": rd["final"], "applied": [],
                          "survival": attr["injection_survival"]})
        if rd.get("natural_correction"):
            a_spans += screen_message(rd["natural_correction"], existing_keys=[])
    return a_spans, b_triples


def runner(system):
    def run(a, b, existing):
        user = ex_mod.build_user_prompt(a, b, existing)
        raw = llm.complete(MODELS["translator"], system, user,
                           max_tokens=1500, temperature=GEN_TEMPERATURE)
        ops, flags = ex_mod.parse_ops(raw, existing)
        return {"ops": ops, "flags": flags}
    return run


def main():
    head = ex_mod.EXTRACTION_SYSTEM
    no4c = strip_4c(head)
    print(f"prompt chars: with 4c {len(head)}, without {len(no4c)} "
          f"(4c costs {len(head)-len(no4c)})\n")

    for pid, markers in PERSONAS.items():
        persona = json.loads(open(f"bench/cases/personas/{pid}.json").read())
        a, b = first_flush_signals(persona)
        print("=" * 72)
        print(f"{pid}   gold: {persona['requirements']}")
        for arm, system in (("no 4c", no4c), ("trimmed 4c", head)):
            with ThreadPoolExecutor(max_workers=4) as ex:
                runs = list(ex.map(lambda _: runner(system)(a, b, []), range(N)))
            texts = [o.get("text", "") for r in runs for o in r["ops"]]
            nar = [t for t in texts
                   if any(m.lower() in t.lower() for m in markers)]
            poisoned = sum(1 for r in runs if any(
                any(m.lower() in o.get("text", "").lower() for m in markers)
                for o in r["ops"]))
            print(f"\n  [{arm}]  ops/trial {len(texts)/N:.2f}   "
                  f"narrow ops {len(nar)}/{len(texts)}   "
                  f"poisoned trials {poisoned}/{N}")
            for t, c in collections.Counter(texts).most_common(7):
                bad = any(m.lower() in t.lower() for m in markers)
                print(f"    {'NARROW' if bad else '  ok  '} {c:3d}/{N}  {t[:60]}")
        print()


if __name__ == "__main__":
    main()
