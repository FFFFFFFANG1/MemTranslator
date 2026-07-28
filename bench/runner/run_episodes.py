"""Suite E (lifecycle): drive one episode's scripted user history through the
real product, probe at checkpoints under the arm panel, score three bands.

Protocol v2 — the user is SCRIPTED. What the user says never depends on what
the SUT did (gold-by-fold requires the log to be authored), with one
deliberate exception: diff moves edit the SUT's actual `polished` string,
because that is what an edit IS. The judge is out of the store loop entirely.

Bands (reported separately — owner ruling 2026-07-28: no weighted composite):
- CARRY    should_fire constraints carried into the rewrite, judge-graded
           (E-judge); carry_mech_numeric is the zero-judge cross-check on
           numeric anchors only.
- SUPPRESS must_not_fire (dead, applies_to-filtered, I11-reachable)
           distinctive anchors absent from the rewrite. Zero judge.
- STATE    the SUT store's own account: every dead gold cid has no ACTIVE
           store entry carrying its distinctive; every live one has at least
           one. Alignment is by distinctive substring, never by key — the
           SUT invents its own keys.

Arms: real / no_retire / oracle-arm / full_context / null-generic — the M6
panel. null-generic is a corpus instrument (prior floor), separated in the
report. Cost note: one episode ≈ 62 chained + |probes|×|arms| translate calls.

    uv run python -m bench.runner.run_episodes e-01
"""
import argparse
import json
import time
import uuid
from pathlib import Path

from memtranslator import llm, translate as tr_mod
from memtranslator.bm25 import BM25
from memtranslator.config import (CONSOLIDATE_ACTIVE, GEN_TEMPERATURE,
                                  MODELS, RECALL_CAP)
from memtranslator.consolidate import should_consolidate
from memtranslator.schema import Requirement
from memtranslator.store import Store

from bench.graph.derive import (Effect, fold, project_status,
                                to_product_context, to_product_scope)
from bench.runner.config import CASES, RUN_DIR
from bench.runner.judge import judge
from bench.runner.providers import V1Provider
from bench.runner.report import write_snapshot
from bench.runner.retry import with_retry

# Owner ruling 2026-07-28: no weighted composite; bands report separately.

GENERIC_POLISH_SYSTEM = """You are a request polisher sitting between a user and their AI agent.
Rewrite the user's request so the agent knows exactly what is expected: make the implicit delivery expectations explicit (format, length, structure, style, language).

Rules:
1. Never change the core task the user is asking for.
2. The rewrite only ADDS. Every word of the user's original request survives in it.
3. Keep the rewritten request natural, in the language the user wrote in.
4. Your output is ALWAYS the user's REQUEST — never your answer to it.

Output strictly one JSON object, nothing else:
{"decision": "noop"} or {"decision": "apply", "polished": "..."}"""

FULL_CONTEXT_PREAMBLE = (
    "Below is this user's conversation history with you, oldest first. "
    "Later turns override earlier ones when they conflict — a preference "
    "the user has since changed or withdrawn must NOT be applied.")


def _effects(ep: dict) -> list[Effect]:
    return [Effect(seq=e["seq"], kind=e["kind"], cid=e.get("cid") or "",
                   target=e.get("target") or "",
                   targets=tuple(e.get("targets") or ()),
                   delta=e.get("delta") or 0)
            for e in ep["effects"]]


def _gold_requirements(ep: dict, seq: int) -> list[Requirement]:
    """The store a perfect system would hold at seq: every introduced node,
    with gold-projected status, clause text, and projected product scope."""
    st = fold(_effects(ep), seq)
    by_cid = {n["cid"]: n for n in ep["catalogue"]}
    out = []
    for i, (cid, g) in enumerate(sorted(st.items(),
                                        key=lambda kv: kv[1].since_seq)):
        n = by_cid.get(cid)
        if n is None:
            continue
        r = Requirement(text=n["clause"] or n["text"], key=n["coords"]["key"],
                        scope=to_product_scope(n["coords"]["scope"]))
        r.status = project_status(g)
        r.created_at = 1_000_000 + n_intro_seq(ep, cid) * 60
        r.updated_at = r.created_at
        out.append(r)
    return out


def n_intro_seq(ep: dict, cid: str) -> int:
    for e in ep["effects"]:
        if e.get("cid") == cid:
            return e["seq"]
    return 0


# ---------------------------------------------------------------------------
# arms
# ---------------------------------------------------------------------------

def _complete_with_block(text: str, system: str, block: str,
                         header: str) -> dict:
    user = f"{header}:\n{block}\n\nUser request:\n{text}\n\nJSON:"
    t0 = time.time()
    raw = llm.complete(MODELS["translator"], system, user,
                       max_tokens=tr_mod.output_budget(text),
                       temperature=GEN_TEMPERATURE)
    latency_ms = int((time.time() - t0) * 1000)
    patch, parse_error = tr_mod.parse_patch(raw)
    if patch["decision"] == "apply" and \
            not tr_mod.preserves_request(text, patch["polished"]):
        patch = {"decision": "noop"}
    polished = patch.get("polished") if patch["decision"] == "apply" else None
    return {"polished": polished, "parse_error": parse_error,
            "latency_ms": latency_ms, "block_chars": len(block)}


def arm_real(store_items: list, ep, r, transcript):
    active = [x for x in store_items if x.status == "active"]
    out = with_retry(lambda: tr_mod.translate(
        r["text"], active,
        context=to_product_context(r["context"])), "arm/real")
    return {"polished": out["polished"], "latency_ms": out["latency_ms"],
            "block_chars": sum(len(x.text) for x in active)}


def arm_no_retire(store_items: list, ep, r, transcript):
    pool = [x for x in store_items if x.kind == "requirement"]
    pool.sort(key=lambda x: x.created_at)
    if len(pool) > RECALL_CAP:
        scores = BM25([f"{x.text} {x.key or ''}" for x in pool]) \
            .scores(r["text"])
        order = sorted(range(len(pool)),
                       key=lambda i: (-scores[i], -pool[i].created_at))
        pool = sorted((pool[i] for i in order[:RECALL_CAP]),
                      key=lambda x: x.created_at)
    block = tr_mod._requirement_block(pool)
    return _complete_with_block(r["text"], tr_mod.TRANSLATOR_SYSTEM, block,
                                "Stored requirements")


def arm_oracle(store_items: list, ep, r, transcript):
    gold = [x for x in _gold_requirements(ep, r["seq"])
            if x.status == "active"]
    out = with_retry(lambda: tr_mod.translate(
        r["text"], gold, context=to_product_context(r["context"])),
        "arm/oracle")
    return {"polished": out["polished"], "latency_ms": out["latency_ms"],
            "block_chars": sum(len(x.text) for x in gold)}


def arm_oracle_should(store_items: list, ep, r, transcript):
    """Application ceiling: inject ONLY the rules gold says apply to THIS
    request — nothing to select, nothing to dilute.

    oracle-arm answers "how well does it apply rules given a perfect store"
    and conflates two abilities, because a perfect store still holds 20-30
    rules and the translator must pick. This arm removes the picking: if it
    still cannot carry what it was handed, the remaining loss is application
    (or the applies_to gold is wrong), and neither retrieval nor dilution can
    be blamed for it."""
    by_cid = {n["cid"]: n for n in ep["catalogue"]}
    should = [by_cid[c] for c in r.get("should_fire", []) if c in by_cid]
    if not should:
        return {"polished": None, "latency_ms": 0, "block_chars": 0,
                "decision": "noop"}
    reqs = [Requirement(text=n["clause"] or n["text"], key=n["coords"]["key"],
                        scope=to_product_scope(n["coords"]["scope"]))
            for n in should]
    out = with_retry(lambda: tr_mod.translate(
        r["text"], reqs, context=to_product_context(r["context"])),
        "arm/oracle-should")
    return {"polished": out["polished"], "latency_ms": out["latency_ms"],
            "block_chars": sum(len(x.text) for x in reqs),
            "decision": out["decision"]}


def arm_full_context(store_items: list, ep, r, transcript):
    turns = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(transcript))
    block = f"{FULL_CONTEXT_PREAMBLE}\n\n{turns}"
    return _complete_with_block(r["text"], tr_mod.TRANSLATOR_SYSTEM, block,
                                "Conversation history")


def arm_null_generic(store_items: list, ep, r, transcript):
    return _complete_with_block(r["text"], GENERIC_POLISH_SYSTEM, "(none)",
                                "Stored requirements")


ARMS = {"real": arm_real, "no_retire": arm_no_retire,
        "oracle-arm": arm_oracle, "oracle-should": arm_oracle_should,
        "full_context": arm_full_context, "null-generic": arm_null_generic}

# arms whose CARRY is judged (the judge band costs a call per should_fire)
JUDGED_ARMS = ("real", "oracle-arm", "oracle-should")


# ---------------------------------------------------------------------------
# chained pass
# ---------------------------------------------------------------------------

def run_chained(ep: dict, flush_every: int = 4) -> dict:
    d = RUN_DIR / "episode-stores"
    d.mkdir(parents=True, exist_ok=True)
    store = Store(d / f"{ep['id']}-{uuid.uuid4().hex[:8]}.jsonl")
    provider = V1Provider()
    pending, transcript = [], []
    probe_rows, consolidations = [], []
    snapshots: dict[int, list[dict]] = {}
    adds_since = 0
    peak_active = 0
    rounds_since_flush = 0

    for r in ep["rounds"]:
        transcript.append(r["text"])
        prod_ctx = to_product_context(r["context"])
        out = with_retry(lambda: tr_mod.translate(r["text"], store.active(),
                                                  context=prod_ctx),
                         f"{ep['id']}/r{r['seq']}")
        if r.get("probe"):
            # snapshot the store AS OF this probe: arms scored later must see
            # the store the probe-time system saw, not the end-of-episode one
            probe_rows.append({"round": r, "transcript": list(transcript),
                               "chained_polished": out["polished"],
                               "store_state": [x.to_dict()
                                               for x in store.list()]})
        pending.append({"type": "natural", "text": r["text"]})
        rounds_since_flush += 1
        if rounds_since_flush >= flush_every:
            ops = with_retry(lambda: provider.extract(pending,
                                                      store.active()),
                             f"{ep['id']}/extract")
            store.apply_ops(ops)
            adds_since += sum(1 for o in ops
                              if o.get("kind") in ("new", "contradict"))
            pending, rounds_since_flush = [], 0
            if should_consolidate(store, adds_since):
                trigger = ("active"
                           if len(store.active()) > CONSOLIDATE_ACTIVE
                           else "adds")
                cops = with_retry(
                    lambda: provider.consolidate(store.active()),
                    f"{ep['id']}/consolidate")
                store.apply_ops(cops)
                consolidations.append({"seq": r["seq"], "trigger": trigger,
                                       "n_ops": len(cops)})
                adds_since = 0
        peak_active = max(peak_active, len(store.active()))
        if r["seq"] in ep["checkpoints"]:
            snapshots[r["seq"]] = [x.to_dict() for x in store.list()]

    return {"store": store, "probe_rows": probe_rows,
            "snapshots": snapshots, "consolidations": consolidations,
            "peak_active": peak_active}


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def _mech(polished: str | None, node) -> bool:
    return bool(polished) and node["distinctive"] in polished


def score_probe(ep, row, arm_name, by_cid) -> dict:
    r = row["round"]
    store_items = [Requirement.from_dict(d) for d in row["store_state"]]
    out = ARMS[arm_name](store_items, ep, r, row["transcript"]) \
        if arm_name != "real" or row.get("chained_polished") is None \
        else {"polished": row["chained_polished"], "latency_ms": 0,
              "block_chars": 0}
    polished = out.get("polished") or ""
    # Three pilots taught the split: SUPPRESS is mechanical (a dead rule's
    # anchor reappearing IS a leak), but mechanical CARRY is only
    # well-defined for OPERATIVE anchors — a number must appear for the rule
    # to be honoured ("≤185词" carried means 185 is in the text), while a
    # qualitative rule ("先给结论") is honoured without reproducing any
    # particular token. The harvest is ~92% qualitative, so CARRY runs on
    # the judge band (E-judge, like E0's criterion) with numeric-mech kept
    # as a zero-judge cross-check column. This is the spec's own E-mech
    # boundary — its mechanical claims were always the SUPPRESS half.
    strong = lambda cid: not by_cid[cid].get("anchor_weak")
    should = [cid for cid in r.get("should_fire", r["may_fire"])
              if strong(cid)]
    numeric = [cid for cid in should if by_cid[cid]["distinctive"].isdigit()]
    carry_judged = []
    if polished and arm_name in JUDGED_ARMS:
        for cid in should:
            n = by_cid[cid]
            ok, _flag = judge(
                f"The rewritten request explicitly carries this "
                f"constraint: {n['clause'] or n['text']}",
                {"rewritten_request": polished})
            carry_judged.append((cid, ok))
    carry_mech = [(cid, _mech(polished, by_cid[cid])) for cid in numeric]
    supp = [(cid, not _mech(polished, by_cid[cid]))
            for cid in r["must_not_fire"] if strong(cid)]
    return {"arm": arm_name, "seq": r["seq"],
            "noop": not polished,
            "carry_hits": sum(1 for _c, h in carry_judged if h),
            "carry_n": len(carry_judged),
            "carry_mech_hits": sum(1 for _c, h in carry_mech if h),
            "carry_mech_n": len(carry_mech),
            "suppress_hits": sum(1 for _c, h in supp if h),
            "suppress_n": len(supp),
            "block_chars": out.get("block_chars", 0),
            "latency_ms": out.get("latency_ms", 0)}


def score_state(ep, snapshot: list[dict], seq: int) -> dict:
    """Does the SUT's store hold the right account at this checkpoint?

    Alignment is substring-first, judge-on-miss. Substring alone measured
    0.227 against 0.348 by judge on the same 66 nodes: the SUT routinely
    stores a Chinese rule in English ("函数文档只写接口说明" →
    "In function documentation, include only interface usage..."), so a
    Chinese anchor can never match and the band under-reported real learning
    by roughly a third. A substring HIT is conclusive and costs nothing; only
    misses go to the judge."""
    st = fold(_effects(ep), seq)
    by_cid = {n["cid"]: n for n in ep["catalogue"]}
    active_texts = [s["text"] for s in snapshot
                    if s["status"] == "active" and s["kind"] == "requirement"]
    listing = "\n".join(f"{i + 1}. {t}"
                        for i, t in enumerate(active_texts)) or "(empty)"

    def aligned(node) -> bool:
        if any(node["distinctive"] in t for t in active_texts):
            return True
        if not active_texts:
            return False
        ok, _flag = judge(
            "At least one of the stored entries expresses the same durable "
            "rule as the target rule.",
            {"stored_entries": listing,
             "target_rule": node["clause"] or node["text"]})
        return ok

    ok = n = 0
    detail = []
    for cid, g in st.items():
        node = by_cid.get(cid)
        if node is None or not node["distinctive"] \
                or node.get("anchor_weak"):
            continue
        # a dead entry whose live SUCCESSOR shares the distinctive (object
        # anchors survive supersession) cannot be told apart — skip those
        succ = [m for m in ep["catalogue"]
                if m.get("successor_of") == cid
                and m["distinctive"] == node["distinctive"]]
        if succ:
            continue
        has = aligned(node)
        n += 1
        good = has if g.status == "active" else not has
        ok += good
        if not good:
            detail.append({"cid": cid, "gold": g.status, "aligned": has})
    return {"ok": ok, "n": n, "rate": ok / n if n else 1.0,
            "misses": detail[:20]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("episode", nargs="?", default="e-01")
    ap.add_argument("--arms", default="real,no_retire,oracle-arm,"
                    "oracle-should,full_context,null-generic")
    args = ap.parse_args()
    ep = json.loads((CASES / "episodes" / f"{args.episode}.json").read_text())
    by_cid = {n["cid"]: n for n in ep["catalogue"]}
    arms = args.arms.split(",")

    print(f"{ep['id']}: chained pass ({len(ep['rounds'])} rounds)...")
    chained = run_chained(ep)
    print(f"  peak SUT active {chained['peak_active']}, "
          f"consolidations {chained['consolidations']}")

    rows = []
    for row in chained["probe_rows"]:
        for arm in arms:
            rows.append(score_probe(ep, row, arm, by_cid))
            print(f"  probe seq {row['round']['seq']:2d} {arm:13s} "
                  f"carry {rows[-1]['carry_hits']}/{rows[-1]['carry_n']} "
                  f"suppress {rows[-1]['suppress_hits']}"
                  f"/{rows[-1]['suppress_n']}", flush=True)

    state_rows = [dict(seq=s, **score_state(ep, snap, s))
                  for s, snap in sorted(chained["snapshots"].items())]

    per_arm = {}
    for arm in arms:
        sub = [r for r in rows if r["arm"] == arm]
        cn = sum(r["carry_n"] for r in sub)
        cmn = sum(r["carry_mech_n"] for r in sub)
        sn = sum(r["suppress_n"] for r in sub)
        carry = sum(r["carry_hits"] for r in sub) / cn if cn else None
        cmech = sum(r["carry_mech_hits"] for r in sub) / cmn if cmn else None
        supp = sum(r["suppress_hits"] for r in sub) / sn if sn else None
        per_arm[arm] = {
            "carry": carry, "carry_mech_numeric": cmech,
            "carry_mech_n": cmn, "suppress": supp,
            "noop_rate": sum(1 for r in sub if r.get("noop")) / len(sub),
            "mean_block_chars": sum(r["block_chars"] for r in sub) / len(sub),
            "mean_latency_ms": sum(r["latency_ms"] for r in sub) / len(sub)}

    state = sum(r["ok"] for r in state_rows) / max(1, sum(r["n"]
                                                          for r in state_rows))
    real = per_arm.get("real", {})

    print(f"\n{'arm':<15} {'CARRYj':>7} {'CARRYm#':>8} {'SUPPRESS':>9} "
          f"{'noop':>6} {'chars':>7} {'ms':>6}")
    for arm, s in per_arm.items():
        f = lambda x: "  n/a" if x is None else f"{x:.2f}"
        cm = ("   n/a" if s["carry_mech_numeric"] is None
              else f"{s['carry_mech_numeric']:.2f}/{s['carry_mech_n']}")
        print(f"{arm:<15} {f(s['carry']):>7} {cm:>8} "
              f"{f(s['suppress']):>9} {s['noop_rate']:6.2f} "
              f"{s['mean_block_chars']:7.0f} {s['mean_latency_ms']:6.0f}")
    print(f"STATE (chained store vs gold): {state:.2f}")
    print("note: null-generic is a corpus instrument, not a product "
          "baseline — do not plot it against the other arms")

    # Owner ruling 2026-07-28: no weighted composite. The three bands are
    # the numbers; `score` carries the unweighted band mean purely so
    # waterlines has one scalar to plot, and it is labeled as such.
    bands = [x for x in (real.get("carry"), real.get("suppress"), state)
             if x is not None]
    band_mean = sum(bands) / len(bands) if bands else 0.0
    results = [{"id": ep["id"], "category": "episode",
                "episode": ep["id"], "pass": bool(bands),
                "score": band_mean, "score_is": "unweighted band mean",
                "carry": real.get("carry"), "suppress": real.get("suppress"),
                "state": state}]
    write_snapshot(f"E1-{ep['id']}", str(CASES / "episodes"), results,
                   expected=1,
                   extra={"protocol_version": ep.get("protocol_version"),
                          
                          "arms": per_arm,
                          "state_band": state, "state_rows": state_rows,
                          "consolidations": chained["consolidations"],
                          "peak_sut_active": chained["peak_active"],
                          "probe_rows_n": len(chained["probe_rows"])})


if __name__ == "__main__":
    main()
