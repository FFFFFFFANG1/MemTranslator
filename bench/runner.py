"""The single reusable trace runner (auto-memory refine discipline: direct
component calls, no adapter layer; real LLM; scores land in state.json).

A trace file holds one FAMILY of checks. Each check builds a store from
inline specs, runs the product's own translate() on the task, and evaluates
mechanical matchers first, narrow judges second. Special forms:

- equiv_group: checks sharing a group id must agree on BEHAVIOR (same
  decision, same set of satisfied must_contain anchors) — this is how
  paraphrase/order invariance is scored without a taste judge.
- instantiation: contrastive attribution (same task with vs without the
  rule), lexical provenance of the caused addition, then one entailment
  judge. Tier 0/1/2, pass iff tier >= expect.min_tier.

    uv run python -m bench.runner [--trace conflict] [--workers 4]
"""
import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path

from memtranslator.schema import Requirement
from memtranslator.translate import translate

from bench.suites.judge import judge          # shared infra, not corpus
from bench.suites.retry import with_retry

BENCH = Path(__file__).resolve().parent
TRACES = BENCH / "traces"
STATE = BENCH / "state.json"


# ---------------------------------------------------------------------------
# store building
# ---------------------------------------------------------------------------

def build_store(specs: list[dict]) -> list[Requirement]:
    """Inline store specs → Requirement objects. created_at follows list
    order (1 minute apart) unless an explicit `age_rank` reorders it —
    newest = highest created_at."""
    base = 1_700_000_000.0
    reqs = []
    for i, s in enumerate(specs):
        r = Requirement(text=s["text"], kind=s.get("kind", "requirement"),
                        key=s.get("key", ""), scope=s.get("scope") or {})
        r.status = s.get("status", "active")
        r.strength = s.get("strength", 1)
        rank = s.get("age_rank", i)
        r.created_at = base + rank * 60.0
        r.updated_at = r.created_at
        reqs.append(r)
    return reqs


def run_translate(task: str, store: list[Requirement],
                  context: dict | None) -> dict:
    return with_retry(lambda: translate(task, store, context=context),
                      "bench/translate")


# ---------------------------------------------------------------------------
# matchers
# ---------------------------------------------------------------------------

def _match(item, text: str) -> bool:
    if isinstance(item, str):
        return item in text
    kind = item.get("matcher", "substring")
    val = item["value"]
    if kind == "substring":
        return val in text
    if kind == "regex":
        return re.search(val, text) is not None
    if kind == "semantic":
        ok, _ = judge(item.get("criterion") or
                      f"The text explicitly contains or satisfies: {val}",
                      {"text": text})
        return ok
    raise ValueError(f"unknown matcher {kind}")


def _behavior(out: dict) -> str:
    return "noop" if out["decision"] == "noop" else "act"


# ---------------------------------------------------------------------------
# instantiation scoring (contrastive, mech-first)
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[a-zA-Z]{3,}|[一-鿿]{2,}")


def _added_vs(base_text: str, with_text: str) -> str:
    """Text present in `with_text` but not in `base_text` (insert/replace
    spans on the b side)."""
    out = []
    for tag, _i1, _i2, j1, j2 in SequenceMatcher(
            None, base_text, with_text).get_opcodes():
        if tag in ("insert", "replace"):
            out.append(with_text[j1:j2])
    return " ".join(out)


def score_instantiation(check: dict) -> dict:
    """Tier 0/1/2 via contrast: run the task WITHOUT the rule and WITH it;
    the diff of the two rewrites is what the rule caused."""
    task = check["task"]["text"]
    ctx = check["task"].get("context")
    rule = check["store"][0]["text"]           # the abstract rule is store[0]
    with_rule = run_translate(task, build_store(check["store"]), ctx)
    without = run_translate(task, build_store(check["store"][1:]), ctx)

    pol_with = with_rule["polished"] or task
    pol_without = without["polished"] or task
    caused = _added_vs(pol_without, pol_with)

    tier = 0
    detail = {"caused": caused[:200]}
    if caused.strip():
        rule_words = set(_WORD.findall(rule))
        caused_words = set(_WORD.findall(caused))
        novel = caused_words - rule_words - set(_WORD.findall(task))
        overlap = len(caused_words & rule_words) / max(1, len(caused_words))
        detail |= {"novel_words": sorted(novel)[:8],
                   "rule_overlap": round(overlap, 2)}
        if novel:
            ok, _ = judge(
                "Any output complying with the ADDED constraint would also "
                "comply with the STORED RULE — the addition specializes the "
                "rule for this task rather than introducing unrelated "
                "requirements.",
                {"stored_rule": rule, "added_constraint": caused,
                 "task": task})
            tier = 2 if ok else 0
            detail["entailment"] = ok
        elif overlap > 0.3:
            tier = 1
    min_tier = check["expect"].get("min_tier", 2)
    return {"pass": tier >= min_tier, "tier": tier, **detail}


# ---------------------------------------------------------------------------
# one check
# ---------------------------------------------------------------------------

def run_check(check: dict) -> dict:
    if check.get("mode") == "instantiation":
        r = score_instantiation(check)
        return {"id": check["id"], **r}

    store = build_store(check["store"])
    task = check["task"]["text"]
    out = run_translate(task, store, check["task"].get("context"))
    polished = out["polished"] or task
    exp = check["expect"]
    fails = []

    # A defensive noop leaves output == input, and an unchanged input cannot
    # disclose, obey, or leak anything — vacuously safe, mechanically so.
    # Judging the echoed attack text is how two injection checks failed on a
    # product that had defended correctly.
    if exp.get("noop_is_pass") and out["decision"] == "noop":
        return {"id": check["id"], "pass": True, "fails": [],
                "decision": "noop", "polished": polished[:200],
                "behavior": "noop", "anchors_hit": [],
                "equiv_group": check.get("equiv_group")}

    want = exp.get("behavior")
    if want == "noop" and out["decision"] != "noop":
        fails.append(f"expected noop, got apply: {polished[:90]}")
    if want == "act" and out["decision"] == "noop":
        fails.append("expected an injection, product nooped "
                     f"({out.get('reason')})")

    if out["decision"] != "noop" or want != "noop":
        for item in exp.get("must_contain", []):
            if not _match(item, polished):
                fails.append(f"missing: {item}")
        for item in exp.get("must_not_contain", []):
            if _match(item, polished):
                fails.append(f"leaked: {item}")
        for crit in exp.get("judge", []):
            ok, _ = judge(crit, {"original_request": task,
                                 "rewritten_request": polished})
            if not ok:
                fails.append(f"judge: {crit[:80]}")

    return {"id": check["id"], "pass": not fails, "fails": fails,
            "decision": out["decision"], "polished": polished[:200],
            "behavior": _behavior(out),
            "anchors_hit": [str(i) for i in exp.get("must_contain", [])
                            if _match(i, polished)],
            "equiv_group": check.get("equiv_group")}


def check_equiv_groups(results: list[dict]) -> list[dict]:
    """Invariance: same group → same behavior AND same anchor hits."""
    groups: dict[str, list[dict]] = {}
    for r in results:
        if r.get("equiv_group"):
            groups.setdefault(r["equiv_group"], []).append(r)
    out = []
    for gid, rs in groups.items():
        sigs = {(r.get("behavior"), tuple(sorted(r.get("anchors_hit", []))))
                for r in rs}
        ok = len(sigs) == 1
        out.append({"id": f"equiv:{gid}", "pass": ok,
                    "fails": [] if ok else
                    [f"behavior diverged across {len(rs)} variants: {sigs}"]})
        if not ok:
            for r in rs:
                r["pass"] = False
                r["fails"] = r.get("fails", []) + [f"equiv:{gid} diverged"]
    return out


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", default="", help="substring filter on family")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    families = sorted(TRACES.glob("trace_id_read_*.json"))
    if args.trace:
        families = [f for f in families if args.trace in f.name]
    if not families:
        raise SystemExit("no trace files matched")

    # merge into the existing state: a --trace filtered run must not wipe
    # the other families' scores (it did — twice)
    state = {"at": time.strftime("%Y%m%d-%H%M%S"), "paths": {"read": {}}}
    if STATE.exists():
        old = json.loads(STATE.read_text())
        state["paths"]["read"] = old.get("paths", {}).get("read", {})
    total_pass = total_n = 0
    for fam_path in families:
        fam = json.loads(fam_path.read_text())
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            results = list(ex.map(run_check, fam["checks"]))
        results += check_equiv_groups(results)
        n = len(results)
        p = sum(1 for r in results if r["pass"])
        total_pass += p
        total_n += n
        state["paths"]["read"][fam["family"]] = {
            "score": round(p / n, 3), "n": n,
            "fails": [{"id": r["id"], "why": r.get("fails", [])[:2]}
                      for r in results if not r["pass"]]}
        print(f"{fam['family']:24s} {p}/{n}")
        for r in results:
            if not r["pass"]:
                print(f"    ✗ {r['id']}: "
                      f"{'; '.join(map(str, r.get('fails', [])[:2]))[:120]}")

    fam_scores = [v for k, v in state["paths"]["read"].items()
                  if k != "_overall" and isinstance(v, dict)]
    state["paths"]["read"]["_overall"] = round(
        sum(f["score"] * f["n"] for f in fam_scores)
        / max(1, sum(f["n"] for f in fam_scores)), 3)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    print(f"\nread path: {total_pass}/{total_n} = {total_pass / total_n:.3f}")
    print(f"state -> {STATE}")


if __name__ == "__main__":
    main()
