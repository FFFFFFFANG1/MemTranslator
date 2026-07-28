"""Episode assembly: catalogue atoms → one lifecycle episode file.

Direction of construction (the load-bearing decision inherited from the
design): the GRAPH is built first — which constraints exist, which supersede
which, when each dies — and the text is generated FROM the edges. Nobody
labels "was that edit a retire or a contradict" after the fact, because the
move was chosen by the effect it must produce.

Shape of e-XX (pilot numbers, spec §M5 amendments applied):
- 40 catalogue nodes = 33 primary + 7 successors (successors are mutations of
  their predecessors, consuming no corpus)
- 20 invalidated by the final checkpoint (7 superseded + 11 withdrawn + 2
  merged via consolidation) = 50%
- gold-active peaks at 33 > RECALL_CAP=32, so the cap genuinely bites
- 62 rounds: intro phase (1-40) → lifecycle phase (41-58) → closing probes;
  a ≥8-round all-quiet window tests whole-batch-silent → zero extraction ops
- 8 checkpoints; R-rounds near each checkpoint are the probes, with narrow
  and wide contexts mixed (scope filtering steals density otherwise)
- surface quotas across signal rounds: complaint 40 / aside 35 /
  standing_order ≤25 — the product's _RULE_PAT literally contains
  以后|一律|always, and a pure-standing-order corpus measures that regex

The episode file stores diff_plan, never `final` — `polished` is the SUT's
output at runtime, and E0 persona files storing `final` (an SUT output frozen
as a constant) is a recorded correctness bug this format exists to fix.

    uv run python -m bench.gen.build_episode e-01 --seed 41
"""
import argparse
import json
import random
from pathlib import Path

from bench.gen.flash import flash_json
from bench.gen.gates import run_gates
from bench.gen.mutate import mutate
from bench.gen.utter import utter
from bench.graph.derive import Effect, fold
from bench.graph.invariants import lint_episode
from bench.graph.schema import ANY, Constraint, Coords, Value, validate

HARVEST = Path(__file__).resolve().parent / "harvest"
EPISODES = Path(__file__).resolve().parents[1] / "cases" / "episodes"

PERSONAS = {
    "e-01": {"id": "infra-writer-zh",
             "who": "偏基础设施的后端工程师，常给组里写文档和邮件",
             "lang": "zh", "register": "口语，直接，偶尔中英混杂",
             "domain": "后端/运维",
             "quirks": "语音输入偶有错字，不爱打句号"},
}

CONTEXT_POOL = {
    "apps": ("editor", "slack", "email-client"),
    "tasks": ("email", "report", "code-write", "postmortem"),
}

HOOK_SYSTEM = """You write ONE short work request a user types to their AI assistant.
PERSONA and TASK KIND are given. The request must be a plain, concrete piece of
work — no rules, no preferences, no meta-instructions. In the persona's language.
Output exactly: {"request": "<the message>"}"""


def _value_from_dict(d: dict) -> Value:
    return Value(type=d["type"], num=d.get("num"), unit=d.get("unit", ""),
                 cmp=d.get("cmp", ""), domain=d.get("domain", ""),
                 val=d.get("val", ""), tag=d.get("tag", ""),
                 bool_val=d.get("bool_val"), op=d.get("op", ""),
                 items=tuple(d.get("items", ())),
                 before=d.get("before", ""), after=d.get("after", ""))


def _constraint(cid: str, atom: dict, scope: dict, text: str) -> Constraint:
    co = atom["coords"]
    c = Constraint(
        cid=cid, text=text,
        coords=Coords(bucket=co["bucket"], key=co["key"],
                      polarity=co["polarity"], binding=co["binding"],
                      value=_value_from_dict(co["value"]), scope=scope),
        atom={"provenance": atom["provenance"],
              "mutation": atom.get("mutation", "")},
        distinctive=atom["distinctive"])
    validate(c)
    return c


def _gen_hooks(persona: dict, n: int, rng) -> list[dict]:
    hooks = []
    for i in range(n):
        task = CONTEXT_POOL["tasks"][i % len(CONTEXT_POOL["tasks"])]
        got = flash_json(HOOK_SYSTEM,
                         f"PERSONA:\n{json.dumps(persona, ensure_ascii=False)}"
                         f"\n\nTASK KIND: {task}\nvariation: {i}\n\nJSON:",
                         max_tokens=200, temperature=0.9)
        if got and got.get("request"):
            hooks.append({"task": task, "text": got["request"].strip(),
                          "app": rng.choice(CONTEXT_POOL["apps"])})
    return hooks


DISTRACTORS = [
    {"kind": "content-preference", "text": "推荐工具的时候优先开源的啊，闭源的我们过不了审"},
    {"kind": "one-off", "text": "这次这份写详细一点，季度 review 要用"},
    {"kind": "task-step", "text": "先把日志按天切开再统计，别一把梭"},
    {"kind": "pasted-material", "text": "帮我看下这段规范写得对不对：「All test names must start with test_ and use snake_case. Do not abbreviate.」"},
    {"kind": "third-party-obligation", "text": "我老板要求他们组的周报全用 bullet，真够呛"},
    {"kind": "rule-pattern-no-rule", "text": "又来了，这 API 每次都超时，烦死"},
    {"kind": "quoted-agent", "text": "你上次自己说的「建议拆成两个 PR」，我照做了，结果还是冲突"},
    {"kind": "one-off-restate", "text": "就这一次，代码给我带上详细注释，我要拿去讲"},
]


def plan(catalogue: list[dict], seed: int) -> dict:
    """Deterministic episode plan: node selection, effect schedule, round
    skeleton. No LLM here — text comes later."""
    rng = random.Random(seed)

    # --- select 33 primaries with distinct keys + 2 same-key near-dup pairs
    by_key: dict[str, list] = {}
    for a in catalogue:
        by_key.setdefault(a["coords"]["key"], []).append(a)
    dup_keys = [k for k, v in by_key.items()
                if len(v) >= 2 and a_same_value(v)]
    keys_order = sorted(by_key, key=lambda k: -len(by_key[k]))
    primaries, dup_pairs = [], []
    for k in dup_keys[:2]:
        a, b = by_key[k][0], by_key[k][1]
        dup_pairs.append((a, b))
        primaries += [a, b]
    for k in keys_order:
        if len(primaries) >= 33:
            break
        if any(k == p["coords"]["key"] for p in primaries):
            continue
        primaries.append(by_key[k][0])
    if len(primaries) < 33:
        raise SystemExit(f"catalogue too thin: {len(primaries)}/33 primaries")

    # --- scope assignment: 55% global, 30% single-dim, 15% two-dim
    scopes = []
    for i, p in enumerate(primaries):
        base = {"app": ANY, "task": ANY, "code_lang": ANY, "nat_lang": ANY}
        r = i / len(primaries)
        if r >= 0.55:
            base["task"] = rng.choice(CONTEXT_POOL["tasks"])
        if r >= 0.85:
            base["app"] = rng.choice(CONTEXT_POOL["apps"])
        scopes.append(base)

    # --- effect schedule
    # intro: 33 asserts on signal rounds in 2..40 (some rounds carry 2)
    # quiet window: rounds 24-31 carry NO signals
    intro_rounds = [s for s in range(2, 41)
                    if not (24 <= s <= 31) and s % 5 != 0]  # %5: probe slots
    rng.shuffle(intro_rounds)
    effects, node_meta = [], {}
    ri = 0
    for i, p in enumerate(primaries):
        seq = sorted(intro_rounds)[ri % len(intro_rounds)]
        # every third assignment doubles up a round (ATOMISE material)
        if i % 3 != 2:
            ri += 1
        cid = f"e01-c{i:02d}"
        effects.append(Effect(seq=seq, kind="assert", cid=cid))
        node_meta[cid] = {"atom": primaries[i], "scope": scopes[i],
                          "intro_seq": seq}

    # lifecycle: 7 contradicts (successors), 11 retires, 3 reinforces
    late = [s for s in range(41, 59) if s % 4 != 0]         # %4: probe slots
    rng.shuffle(late)
    cids = sorted(node_meta)
    dying = rng.sample(cids, 18)
    superseded, withdrawn = dying[:7], dying[7:18]
    late_sorted = sorted(late)
    for j, target in enumerate(superseded):
        cid = f"e01-s{j:02d}"
        seq = late_sorted[j % len(late_sorted)]
        effects.append(Effect(seq=seq, kind="contradict", cid=cid,
                              target=target))
        node_meta[cid] = {"successor_of": target, "intro_seq": seq}
    for j, target in enumerate(withdrawn):
        # two withdrawals may share a round — a compound message is exactly
        # the ATOMISE material extraction rule 4a exists for
        seq = late_sorted[(7 + j) % len(late_sorted)]
        effects.append(Effect(seq=seq, kind="retire", target=target))
    alive_pool = [c for c in cids if c not in dying]
    for j, target in enumerate(rng.sample(alive_pool, 3)):
        # a reinforce must land strictly after its target's introduction
        floor = node_meta[target]["intro_seq"]
        candidates = [s for s in (15, 22, 33, 38, 39) if s > floor]
        seq = candidates[j % len(candidates)] if candidates else floor + 1
        effects.append(Effect(seq=seq, kind="reinforce", target=target))

    checkpoints = [8, 16, 24, 32, 40, 46, 53, 62]
    return {"primaries": primaries, "dup_pairs": dup_pairs,
            "node_meta": node_meta, "effects": effects,
            "checkpoints": checkpoints, "superseded": superseded,
            "withdrawn": withdrawn, "rng": rng}


def a_same_value(atoms: list) -> bool:
    """Two atoms with the same key AND equivalent value → usable dup pair."""
    v0 = atoms[0]["coords"]["value"]
    v1 = atoms[1]["coords"]["value"]
    return v0 == v1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("episode", nargs="?", default="e-01")
    ap.add_argument("--seed", type=int, default=41)
    args = ap.parse_args()
    persona = PERSONAS[args.episode]

    catalogue = [json.loads(l) for l in
                 (HARVEST / "catalogue.jsonl").read_text().splitlines()
                 if l.strip()]
    p = plan(catalogue, args.seed)
    rng = p["rng"]

    # --- build Constraint objects (successors = re-mutated predecessors)
    constraints, cat_out = [], []
    for cid in sorted(p["node_meta"]):
        meta = p["node_meta"][cid]
        if "successor_of" in meta:
            pred_meta = p["node_meta"][meta["successor_of"]]
            sk2, desc = mutate(pred_meta["atom"]["skeleton"], rng)
            atom = {**pred_meta["atom"], "skeleton": sk2,
                    "mutation": desc,
                    "distinctive": _re_distinctive(sk2)}
            scope = pred_meta["scope"]
        else:
            atom, scope = meta["atom"], meta["scope"]
        text = _canonical_text(atom["skeleton"])
        c = _constraint(cid, atom, scope, text)
        meta["constraint"] = c
        meta["atom"] = atom              # gates need skeleton + raw later
        constraints.append(c)

    # --- rounds: hooks, utterances, diffs, distractors, probes
    print("generating hooks...")
    hooks = _gen_hooks(persona, 30, rng)
    if len(hooks) < 20:
        raise SystemExit(f"hook generation too lossy: {len(hooks)}")

    surfaces = (["complaint"] * 16 + ["aside"] * 14 + ["standing_order"] * 10)
    rng.shuffle(surfaces)

    by_seq: dict[int, list] = {}
    for e in p["effects"]:
        by_seq.setdefault(e.seq, []).append(e)

    rounds, probes, gate_drops = [], [], 0
    distractor_iter = iter(DISTRACTORS)
    hook_i = 0
    print("uttering signal rounds...")
    for seq in range(1, 63):
        evs = by_seq.get(seq, [])
        signal_evs = [e for e in evs if e.kind in ("assert", "contradict",
                                                   "retire", "reinforce")]
        if signal_evs:
            texts = []
            hook = hooks[hook_i % len(hooks)]
            hook_i += 1
            for e in signal_evs:
                node = p["node_meta"].get(e.cid or e.target, {})
                c = node.get("constraint")
                if e.kind in ("assert", "contradict"):
                    surface = surfaces.pop() if surfaces else "aside"
                    u = _uttered_with_gates(c, node.get("atom") or {},
                                            persona, hook["text"], surface,
                                            e.kind)
                    if u is None:
                        gate_drops += 1
                        u = {"utterance": c.text, "clause": c.text,
                             "alt_clause": c.text, "surface": "fallback"}
                    c.clause, c.alt_clause = u["clause"], u["alt_clause"]
                    texts.append(u["utterance"])
                elif e.kind == "retire":
                    texts.append(_withdrawal_text(c, persona))
                elif e.kind == "reinforce":
                    texts.append(f"对了，{c.clause or c.text}这条继续保持啊")
            rtype = "C" if any(e.kind == "assert" for e in signal_evs) \
                and rng.random() < 0.6 else "S"
            text = "，".join(texts) if rtype == "S" else \
                f"{hook['text']}。{'。'.join(texts)}"
            rounds.append({"seq": seq, "type": rtype, "text": text,
                           "context": {"app": hook["app"],
                                       "task": hook["task"]},
                           "effects": [_effect_dict(e) for e in signal_evs]})
        elif seq % 5 == 0 or seq % 4 == 0 or seq >= 59:
            hook = hooks[hook_i % len(hooks)]
            hook_i += 1
            wide = rng.random() < 0.4
            ctx = {} if wide else {"app": hook["app"], "task": hook["task"]}
            rounds.append({"seq": seq, "type": "R", "text": hook["text"],
                           "context": ctx, "probe": True})
        else:
            try:
                d = next(distractor_iter)
                rounds.append({"seq": seq, "type": "N", "text": d["text"],
                               "context": {}, "distractor_kind": d["kind"],
                               "effects": []})
            except StopIteration:
                hook = hooks[hook_i % len(hooks)]
                hook_i += 1
                rounds.append({"seq": seq, "type": "R", "text": hook["text"],
                               "context": {"task": hook["task"]},
                               "probe": True})

    # --- derive probe gold from the fold
    by_cid = {c.cid: c for c in constraints}
    for r in rounds:
        if not r.get("probe"):
            continue
        st = fold(p["effects"], r["seq"])
        ctx = r["context"]
        from bench.graph.derive import scope_compatible
        bctx = {"app": ctx.get("app"), "task": ctx.get("task"),
                "code_lang": None, "nat_lang": None}
        alive = [cid for cid, g in st.items() if g.status == "active"
                 and scope_compatible(by_cid[cid].coords.scope, bctx)]
        dead = [cid for cid, g in st.items() if g.status != "active"
                and scope_compatible(by_cid[cid].coords.scope, bctx)]
        probes.append({"seq": r["seq"], "query": r["text"], "context": bctx,
                       "may_fire": alive, "must_not_fire": dead})
        r["may_fire"], r["must_not_fire"] = alive, dead

    # --- I11 pruning: traps a no-retire arm would not inject are FREE POINTS;
    # prune them from the assertion set and count what was pruned
    from bench.graph.invariants import simulate_no_retire_injection
    pruned = 0
    for pr, r in zip(probes, [x for x in rounds if x.get("probe")]):
        injected = simulate_no_retire_injection(constraints, p["effects"], pr)
        keep = [t for t in pr["must_not_fire"] if t in injected]
        pruned += len(pr["must_not_fire"]) - len(keep)
        pr["must_not_fire"] = keep
        r["must_not_fire"] = keep

    errs = lint_episode(constraints, p["effects"], probes,
                        p["checkpoints"])
    final = fold(p["effects"])
    n_dead = sum(1 for g in final.values() if g.status != "active")
    peak = max(len([1 for _c, g in fold(p["effects"], s).items()
                    if g.status == "active"]) for s in range(1, 63))

    EPISODES.mkdir(parents=True, exist_ok=True)
    out = {
        "id": args.episode, "schema_version": "E1", "seed": args.seed,
        "protocol_version": 2,           # scripted user, judge out of the loop
        "persona": persona,
        "catalogue": [_node_dict(c, p["node_meta"]) for c in constraints],
        "effects": [_effect_dict(e) for e in p["effects"]],
        "rounds": rounds,
        "checkpoints": p["checkpoints"],
        "dup_pairs": [[a["aid"], b["aid"]] for a, b in p["dup_pairs"]],
        "stats": {"nodes": len(constraints), "dead_final": n_dead,
                  "peak_gold_active": peak, "gate_drops": gate_drops,
                  "i11_pruned_traps": pruned,
                  "lint_errors": errs},
    }
    path = EPISODES / f"{args.episode}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"\n{args.episode}: {len(constraints)} nodes, {n_dead} dead at "
          f"final, peak gold-active {peak}, {len(probes)} probes, "
          f"{gate_drops} gate fallbacks, {pruned} traps I11-pruned")
    print(f"lint: {'GREEN' if not errs else errs}")
    print(f"-> {path}")


def _re_distinctive(sk: dict) -> str:
    from bench.gen.build_catalogue import _distinctive
    return _distinctive(sk)


def _canonical_text(sk: dict) -> str:
    th = sk.get("threshold")
    parts = [sk.get("trigger") or "", sk.get("act") or "",
             sk.get("object") or ""]
    if th:
        parts.append(f"{th.get('value')} {th.get('unit') or ''}")
    if sk.get("order"):
        parts.append(" before ".join(sk["order"]))
    return " ".join(x for x in parts if x).strip()


def _uttered_with_gates(c, atom, persona, hook, surface, kind):
    """utter → gates, one regeneration, then None (caller falls back and
    counts it — silent fallbacks would let the corpus quietly go formal).

    The REAL skeleton and the REAL source sentence go to the gates: an
    earlier version fed a mangled skeleton (registry key as object) and the
    provenance URL as the source text, which made readback fail spuriously
    and the licence gate vacuously pass — the exact quiet corruption gates
    exist to prevent."""
    sk = atom["skeleton"]
    if kind == "contradict":
        surface = "complaint"            # supersessions read as corrections
    for _attempt in range(2):
        u = utter(sk, persona, hook, surface)
        if u is None:
            continue
        ok, _fails = run_gates(u["utterance"], sk, atom.get("raw", ""),
                               c.distinctive)
        if ok:
            return u
    return None


def _th_of(c):
    v = c.coords.value
    if v.type == "numeric":
        return {"kind": "count", "value": v.num, "unit": v.unit}
    return None


def _ord_of(c):
    v = c.coords.value
    if v.type == "ordering":
        return [v.before, v.after]
    return None


def _effect_dict(e: Effect) -> dict:
    return {"seq": e.seq, "kind": e.kind, "cid": e.cid, "target": e.target,
            "targets": list(e.targets), "delta": e.delta}


def _node_dict(c: Constraint, node_meta: dict) -> dict:
    co = c.coords
    return {"cid": c.cid, "text": c.text, "clause": c.clause,
            "alt_clause": c.alt_clause, "distinctive": c.distinctive,
            "coords": {"bucket": co.bucket, "key": co.key,
                       "polarity": co.polarity, "binding": co.binding,
                       "value": co.value.__dict__, "scope": co.scope},
            "atom": c.atom,
            "successor_of": node_meta.get(c.cid, {}).get("successor_of")}


def _withdrawal_text(c, persona) -> str:
    anchor = c.clause or c.text
    return f"之前说的「{anchor}」那条不用了，按你默认的来吧"


if __name__ == "__main__":
    main()
