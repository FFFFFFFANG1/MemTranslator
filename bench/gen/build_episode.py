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
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bench.gen.flash import flash_json
from bench.gen.gates import plausibility_gate, run_gates
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
    "e-02": {"id": "pm-en", "who": "product manager at a b2b saas company",
             "lang": "en", "register": "brisk, informal, lowercase",
             "domain": "product", "quirks": "types fast, skips punctuation"},
    "e-03": {"id": "datasci-zh", "who": "数据分析师，天天出报表和实验结论",
             "lang": "zh", "register": "简短，爱用行话",
             "domain": "数据分析", "quirks": "数字敏感，讨厌没单位的数"},
    "e-04": {"id": "researcher-mixed", "who": "在读博士，论文和代码来回切",
             "lang": "zh/en 混", "register": "中英混杂，学术腔混口语",
             "domain": "科研", "quirks": "术语用英文，其余用中文"},
    "e-05": {"id": "techwriter-en",
             "who": "technical writer maintaining developer docs",
             "lang": "en", "register": "precise but casual in chat",
             "domain": "docs", "quirks": "quotes style guides from memory"},
    "e-06": {"id": "founder-zh", "who": "小团队创始人，什么都要写一点",
             "lang": "zh", "register": "急性子，句子短",
             "domain": "综合", "quirks": "经常一条消息塞好几件事"},
    "e-07": {"id": "backend-en", "who": "backend engineer on a payments team",
             "lang": "en", "register": "terse, code-adjacent",
             "domain": "backend", "quirks": "hates prose, loves constraints"},
    "e-08": {"id": "ops-zh", "who": "运营，周报月报邮件排期都归他",
             "lang": "zh", "register": "客气但直接",
             "domain": "运营", "quirks": "对格式有执念"},
    "e-09": {"id": "consultant-en", "who": "consultant writing client decks",
             "lang": "en", "register": "polished, audience-aware",
             "domain": "consulting", "quirks": "everything is a deliverable"},
    "e-10": {"id": "sre-zh", "who": "SRE，复盘和 oncall 交接文档常客",
             "lang": "zh", "register": "冷静，条理",
             "domain": "SRE", "quirks": "时间线强迫症"},
    "e-11": {"id": "student-en", "who": "grad student juggling TA and thesis",
             "lang": "en", "register": "chatty, informal",
             "domain": "academia", "quirks": "asks for a lot of rewrites"},
    "e-12": {"id": "editor-zh", "who": "科技媒体编辑，改稿子改到麻木",
             "lang": "zh", "register": "挑剔，词汇量大",
             "domain": "编辑", "quirks": "对标点和用词极敏感"},
}

CONTEXT_POOL = {
    "apps": ("editor", "slack", "email-client"),
    "tasks": ("email", "report", "code-write", "postmortem"),
}

N_EPISODES = 12


# Which work domains each persona plausibly holds rules about. Assignment by
# fit, not filtering after the fact: the stride partition was domain-blind
# and put "每种岩石描述控制在71个词以内" in an SRE's memory, while filtering
# that per-persona threw away 80% of a corpus that was fine for SOMEBODY.
PERSONA_DOMAINS = {
    "e-01": ("code", "docs", "email-comms", "general-writing"),
    "e-02": ("email-comms", "docs", "data-analysis", "general-writing"),
    "e-03": ("data-analysis", "code", "general-writing"),
    "e-04": ("docs", "data-analysis", "code", "general-writing"),
    "e-05": ("docs", "code", "general-writing"),
    "e-06": ("email-comms", "docs", "general-writing"),
    "e-07": ("code", "docs", "general-writing"),
    "e-08": ("email-comms", "docs", "general-writing"),
    "e-09": ("docs", "email-comms", "general-writing"),
    "e-10": ("code", "docs", "email-comms", "general-writing"),
    "e-11": ("docs", "general-writing"),
    "e-12": ("general-writing", "docs", "email-comms"),
}


def episode_slice(catalogue: list[dict], episode: str) -> list[dict]:
    """Per-episode partition, domain-aware. Atoms are dealt round-robin
    WITHIN each domain to the personas that accept it, so episodes never
    share an atom, every episode gets rules its persona would plausibly hold,
    and `other-specialist` atoms are dropped fleet-wide."""
    want = PERSONA_DOMAINS[episode]
    rng = random.Random(7700)
    out = []
    for dom in want:
        pool = sorted((a for a in catalogue if a.get("domain") == dom),
                      key=lambda a: a["aid"])
        rng.shuffle(pool)
        takers = [e for e in sorted(PERSONA_DOMAINS)
                  if dom in PERSONA_DOMAINS[e]]
        out += pool[takers.index(episode)::len(takers)]
    return out

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


def plan(catalogue: list[dict], seed: int, prefix: str = "e01") -> dict:
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
        # Second admission pass: a chunk can run out of distinct keys (the
        # fleet slices carry 29-35). Same-key seconds are admitted with
        # FORCED-DISJOINT task scopes — the algebra reads disjoint boxes as
        # INDEPENDENT, so I1/I3 stay clean by construction. Dup-pair keys are
        # exempt: a dup pair must share its scope or it can never merge.
        n_tasks = len(CONTEXT_POOL["tasks"])
        for k in keys_order:
            if len(primaries) >= 33:
                break
            if k in dup_keys[:2]:
                continue
            for cand in by_key[k][1:]:
                if len(primaries) >= 33:
                    break
                # disjointness is manufactured from distinct concrete tasks,
                # so a key can hold at most len(tasks) primaries
                if sum(1 for p in primaries
                       if p["coords"]["key"] == k) >= n_tasks:
                    break
                if cand not in primaries:
                    primaries.append(cand)
    if len(primaries) < 33:
        raise SystemExit(f"catalogue too thin: {len(primaries)}/33 primaries")

    # --- scope assignment: 55% global, 30% single-dim, 15% two-dim.
    # Keys appearing more than once get DISTINCT concrete tasks (disjoint
    # boxes → INDEPENDENT); dup pairs are pinned to identical global scope
    # (EQUAL → DUPLICATES → merge material).
    dup_aids = {a["aid"] for pair in dup_pairs for a in pair}
    key_counts: dict[str, int] = {}
    for p in primaries:
        key_counts[p["coords"]["key"]] = \
            key_counts.get(p["coords"]["key"], 0) + 1
    task_cycle: dict[str, int] = {}
    scopes = []
    for i, p in enumerate(primaries):
        base = {"app": ANY, "task": ANY, "code_lang": ANY, "nat_lang": ANY}
        k = p["coords"]["key"]
        if p["aid"] in dup_aids:
            pass                                     # pinned global
        elif key_counts[k] > 1:
            n = task_cycle.get(k, 0)
            if n >= len(CONTEXT_POOL["tasks"]):
                raise SystemExit(f"key {k}: more same-key atoms than tasks")
            base["task"] = CONTEXT_POOL["tasks"][n]
            task_cycle[k] = n + 1
        else:
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
        cid = f"{prefix}-c{i:02d}"
        effects.append(Effect(seq=seq, kind="assert", cid=cid))
        node_meta[cid] = {"atom": primaries[i], "scope": scopes[i],
                          "intro_seq": seq}

    # lifecycle: 7 contradicts (successors), 11 retires, 3 reinforces
    late = [s for s in range(41, 59) if s % 4 != 0]         # %4: probe slots
    rng.shuffle(late)
    cids = sorted(node_meta)
    # Deaths PREFER numeric-anchored nodes: a number is the one thing the
    # rewrite reproduces verbatim (measured 0.32 mech-carry vs ~0 for
    # qualitative anchors), so numeric traps are the traps that can actually
    # be caught leaking — and numeric supersede pairs are M1's semantically
    # opposed pairs (185 vs 639) rebuilt at fleet scale.
    numeric = [c for c in cids
               if str(node_meta[c]["atom"]["distinctive"]).isdigit()]
    rest = [c for c in cids if c not in numeric]
    rng.shuffle(numeric)
    rng.shuffle(rest)
    dying = (numeric + rest)[:18]
    rng.shuffle(dying)
    superseded, withdrawn = dying[:7], dying[7:18]
    late_sorted = sorted(late)
    for j, target in enumerate(superseded):
        cid = f"{prefix}-s{j:02d}"
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


def _preflight(candidates: list, persona: dict, hooks: list, seed: int,
               need: int = 40, quiet: bool = False) -> list:
    """Two phases, cheap filter first.

    Plausibility is a property of the ATOM and the persona, not of the
    wording, so it runs on the canonical text for one call before anything
    expensive happens — generating an utterance and running four gates on a
    rule this user would never state is four wasted calls. Only plausible
    atoms go on to utter + gates, and survivors carry their `utt` so the
    round loop never generates and never falls back."""
    from bench.gen.build_catalogue import _canonical

    with ThreadPoolExecutor(max_workers=8) as ex:
        plaus = list(ex.map(
            lambda a: plausibility_gate(_canonical(a["skeleton"]), persona)[0],
            candidates))
    kept = [a for a, ok in zip(candidates, plaus) if ok]
    if not quiet:
        print(f"  plausible for this persona: {len(kept)}/{len(candidates)}")
    kept = kept[:max(need, 1)]

    surfaces = ["complaint"] * 4 + ["aside"] * 4 + ["standing_order"] * 2

    def one(idx_atom):
        i, atom = idx_atom
        surface = surfaces[i % len(surfaces)]
        hook = hooks[i % len(hooks)]["text"]
        for _attempt in range(2):
            u = utter(atom["skeleton"], persona, hook, surface)
            if u is None:
                continue
            ok, _fails = run_gates(u["utterance"], atom["skeleton"],
                                   atom.get("raw", ""), atom["distinctive"])
            if not ok:
                continue
            anchor = _verified_anchor(u, atom["distinctive"])
            if not anchor:
                continue          # no persona-language anchor → ungradeable
            return {**atom, "utt": u, "distinctive": anchor}
        return None

    with ThreadPoolExecutor(max_workers=8) as ex:
        out = list(ex.map(one, enumerate(kept)))
    return [x for x in out if x]


def a_same_value(atoms: list) -> bool:
    """Two atoms with the same key, equivalent value AND the same polarity
    sign → usable dup pair. Value equality alone admitted "prefer snake" +
    "prohibit snake" — a CONTRADICTS pair wearing a dup pair's clothes."""
    a, b = atoms[0]["coords"], atoms[1]["coords"]
    pos = ("require", "prefer")
    return a["value"] == b["value"] and \
        (a["polarity"] in pos) == (b["polarity"] in pos)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("episode", nargs="?", default="e-01")
    ap.add_argument("--seed", type=int, default=41)
    ap.add_argument("--preflight-cap", type=int, default=52,
                    help="plausible atoms sent to utter+gates (need 33 survivors)")
    args = ap.parse_args()
    persona = PERSONAS[args.episode]

    catalogue = [json.loads(l) for l in
                 (HARVEST / "catalogue.jsonl").read_text().splitlines()
                 if l.strip()]
    catalogue = episode_slice(catalogue, args.episode)

    # --- PRE-FLIGHT: generate every candidate's utterance and gate it BEFORE
    # planning, so a gate failure DROPS the atom instead of falling back to
    # canonical text. The first fleet fell back 8-9 times per episode and each
    # fallback wrote machine English into a Chinese persona's gold — 12.1% of
    # nodes fleet-wide. A missing node costs one slot; a fallback node
    # poisons the exam.
    # Pre-flight is the expensive stage (≈4 calls per candidate), so order
    # candidates by key diversity and take only as many as the plan can use
    # plus headroom for the gate loss — the plan needs 33 distinct-key
    # primaries, not the whole slice.
    seen_keys, head, tail = set(), [], []
    for a in catalogue:
        k = a["coords"]["key"]
        (head if k not in seen_keys else tail).append(a)
        seen_keys.add(k)
    catalogue = head + tail

    print(f"pre-flighting {len(catalogue)} candidates...")
    hooks0 = _gen_hooks(PERSONAS[args.episode], 12, random.Random(args.seed))
    if not hooks0:
        raise SystemExit("hook generation failed entirely")
    survivors = _preflight(catalogue, persona, hooks0, args.seed,
                           need=args.preflight_cap)
    print(f"  {len(survivors)}/{len(catalogue)} candidates passed the gates")

    p = plan(survivors, args.seed, prefix=args.episode.replace("-", ""))
    rng = p["rng"]

    # --- build Constraint objects. Primaries reuse their pre-flighted
    # utterance; successors are re-mutated predecessors and must pass the
    # gates now. A successor that cannot be uttered cleanly DEGRADES to a
    # plain withdrawal (its predecessor still dies, just without a
    # replacement) — never to canonical fallback text.
    print("uttering successors...")
    constraints = []
    degraded = []
    for cid in sorted(p["node_meta"]):
        meta = p["node_meta"][cid]
        if "successor_of" in meta:
            pred_meta = p["node_meta"][meta["successor_of"]]
            u = atom = None
            for _try in range(2):
                sk2, desc = mutate(pred_meta["atom"]["skeleton"], rng)
                cand = {**pred_meta["atom"], "skeleton": sk2,
                        "mutation": desc, "distinctive": _re_distinctive(sk2)}
                got = _preflight([cand], persona, hooks0, args.seed + _try,
                                 need=1, quiet=True)
                if got:
                    atom, u = got[0], got[0]["utt"]
                    break
            if atom is None:
                degraded.append(cid)
                continue
            scope = pred_meta["scope"]
        else:
            atom, scope = meta["atom"], meta["scope"]
            u = atom["utt"]
        c = _constraint(cid, atom, scope, _canonical_text(atom["skeleton"]))
        c.clause, c.alt_clause = u["clause"], u["alt_clause"]
        c.distinctive = atom["distinctive"]
        meta["constraint"], meta["atom"], meta["utt"] = c, atom, u
        constraints.append(c)

    if degraded:
        # rewrite the plan: the contradict becomes a retire, the successor
        # node disappears from the catalogue and from every probe's gold
        keep = []
        for e in p["effects"]:
            if e.kind == "contradict" and e.cid in degraded:
                keep.append(Effect(seq=e.seq, kind="retire", target=e.target))
            else:
                keep.append(e)
        p["effects"] = keep
        for cid in degraded:
            p["node_meta"].pop(cid, None)
        print(f"  {len(degraded)} successors degraded to plain withdrawals")

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

    rounds, probes = [], []
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
                    # already generated and gated in pre-flight
                    texts.append(node["utt"]["utterance"])
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
            # TARGETED probe: pick nodes already introduced by this seq (a
            # mix of live candidates and, late in the episode, dead traps on
            # the same facet family) and generate a request squarely in their
            # domain. Pilot #2 measured what untargeted probes buy: gold sets
            # that miss the carried rule and traps that never tempt —
            # SUPPRESS 1.00 as "the exam never asked", not "it held".
            targets = _pick_probe_targets(p, seq, rng)
            req = _targeted_request(persona, targets, hooks, hook_i, rng)
            hook_i += 1
            wide = rng.random() < 0.4
            ctx = {} if wide else {"app": req["app"], "task": req["task"]}
            rounds.append({"seq": seq, "type": "R", "text": req["text"],
                           "context": ctx, "probe": True,
                           "probe_targets": [c.cid for c in targets]})
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

    # --- derive probe gold from the fold + the ONE authored LLM judgment
    # (applies_to). Scope compatibility alone produced denominators of 14-22
    # "carryable" rules per probe in the pilot — a rewrite is not expected to
    # weave in every live rule, only the ones a user would expect applied to
    # THIS request. applies_to is the design's single per-(node, request)
    # judgment; everything else stays a fold.
    by_cid = {c.cid: c for c in constraints}
    print("labeling applies_to per probe...")
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
        applies = _applies_to(r["text"], alive + dead, by_cid)
        should = [cid for cid in alive if cid in applies]
        dead_applying = [cid for cid in dead if cid in applies]
        probes.append({"seq": r["seq"], "query": r["text"], "context": bctx,
                       "may_fire": alive, "should_fire": should,
                       "must_not_fire": dead_applying})
        r["may_fire"], r["should_fire"] = alive, should
        r["must_not_fire"] = dead_applying

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
                  "peak_gold_active": peak, "degraded_successors": len(degraded),
                  "i11_pruned_traps": pruned,
                  "lint_errors": errs},
    }
    path = EPISODES / f"{args.episode}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"\n{args.episode}: {len(constraints)} nodes, {n_dead} dead at "
          f"final, peak gold-active {peak}, {len(probes)} probes, "
          f"{len(degraded)} degraded successors, "
          f"{pruned} traps I11-pruned")
    print(f"lint: {'GREEN' if not errs else errs}")
    print(f"-> {path}")


def _re_distinctive(sk: dict) -> str:
    from bench.gen.build_catalogue import _distinctive
    return _distinctive(sk)


_NUM = re.compile(r"\d{2,}")
_LATIN_TOKEN = re.compile(r"[a-zA-Z][a-zA-Z_-]{3,}")
_CJK_RUN = re.compile(r"[一-鿿]{2,}")


PROBE_SYSTEM = """You write ONE short work request a user types to their AI assistant.
PERSONA and TARGET RULES are given. The request must be a plain, concrete piece
of work squarely in the DOMAIN of the target rules — the kind of work where a
user who stated those rules would expect them honoured. The request itself
must contain NO rules, NO preferences, and must not quote or hint at the
rules' content or numbers. In the persona's language.
Output exactly: {"request": "<the message>", "task": "<one of email|report|code-write|postmortem>"}"""


def _pick_probe_targets(p, seq, rng):
    """2-4 nodes introduced by this seq: prefer live ones; late in the
    episode mix in dead ones so traps are on-topic by construction (a trap
    the probe's domain never touches suppresses for free)."""
    st = fold(p["effects"], seq)
    live = [p["node_meta"][cid]["constraint"] for cid, g in st.items()
            if g.status == "active" and "constraint" in p["node_meta"].get(cid, {})]
    dead = [p["node_meta"][cid]["constraint"] for cid, g in st.items()
            if g.status != "active" and "constraint" in p["node_meta"].get(cid, {})]
    rng.shuffle(live)
    rng.shuffle(dead)
    targets = live[:2]
    if dead:
        targets += dead[:2]
    return [t for t in targets if t is not None][:4]


def _targeted_request(persona, targets, hooks, hook_i, rng) -> dict:
    if targets:
        lines = "\n".join(f"- {t.clause or t.text}" for t in targets)
        got = flash_json(PROBE_SYSTEM,
                         f"PERSONA:\n{json.dumps(persona, ensure_ascii=False)}"
                         f"\n\nTARGET RULES:\n{lines}\n\nJSON:",
                         max_tokens=250, temperature=0.8)
        if got and got.get("request"):
            text = got["request"].strip()
            # a probe containing a target's anchor hands CARRY out for free
            if not any(t.distinctive and t.distinctive in text
                       for t in targets):
                task = got.get("task")
                if task not in CONTEXT_POOL["tasks"]:
                    task = rng.choice(CONTEXT_POOL["tasks"])
                return {"text": text, "task": task,
                        "app": rng.choice(CONTEXT_POOL["apps"])}
    hook = hooks[hook_i % len(hooks)]
    return hook


APPLIES_SYSTEM = """You judge which of a user's stored delivery rules a rewriter MUST add to ONE specific request.

Include a rule only when BOTH hold:
(a) it applies — a reasonable user who stated that rule would expect it honoured in the response to this request, judged by the KIND of work requested, not by shared vocabulary; AND
(b) the request as written does NOT already state or satisfy it — if the user already said it, adding it again is redundant and the rewriter is right to leave it alone.

Exclude a rule when it is about WHAT to say rather than HOW to deliver (topics, opinions, values, safety, persona), when it is vacuous, or when it is garbled and you cannot tell what compliance would look like.
Output exactly: {"applies": [<number>, ...]} (possibly empty). Numbers only from the list."""


def _applies_to(query: str, cids: list, by_cid: dict, votes: int = 3) -> set:
    """Three votes, unanimous intersection — a rule enters the gold only when
    every vote agrees the rewrite MUST add it.

    Two votes at 0.3 was too generous, and an audit of the first fleet's
    misses showed why it matters: the answer key was demanding a word limit
    on a code request, a safety rule on an incident email, and a constraint
    the user had already typed into the request themselves. Every one of
    those is a rewriter correctly declining, scored as a failure. When the
    gold and the product disagree, the gold has to be the thing that earned
    the benefit of the doubt."""
    if not cids:
        return set()
    lines = "\n".join(f"{i + 1}. {by_cid[cid].clause or by_cid[cid].text}"
                      for i, cid in enumerate(cids))
    got_any = False
    out: set = set()
    for k in range(votes):
        got = flash_json(APPLIES_SYSTEM,
                         f"Stored rules:\n{lines}\n\nRequest:\n{query}\n\nJSON:",
                         max_tokens=200, temperature=0.2)
        if not (isinstance(got, dict) and isinstance(got.get("applies"), list)):
            continue
        v = {cids[n - 1] for n in got["applies"]
             if isinstance(n, int) and 1 <= n <= len(cids)}
        out = v if not got_any else (out & v)
        got_any = True
    if not got_any:
        return set()
    return _cap_should_fire(out, by_cid)


SHOULD_FIRE_CAP = 3


def _cap_should_fire(cids: set, by_cid: dict) -> set:
    """Cap the obligation at the most salient few.

    A postmortem request can be scope-compatible with six micro-typographic
    rules at once (no semicolons, no nested clauses, longest sentence not
    mid-paragraph...). Demanding a rewriter weave all six into one request is
    not a memory test — no reasonable rewriter does that, and the audit
    scored it as failure six times over. A perfect system surfaces the ones
    that matter; that is what this measures.

    Ranking: operative anchors first (a number must appear for compliance to
    be visible at all), then hard binding, then the shortest clause — brevity
    correlates with the rule being a single crisp demand rather than a
    typographic aside."""
    def rank(cid):
        c = by_cid[cid]
        text = c.clause or c.text
        binding = getattr(c.coords, "binding", "")
        return (0 if (c.distinctive or "").isdigit() else 1,
                0 if binding == "hard" else 1,
                len(text))
    return set(sorted(cids, key=rank)[:SHOULD_FIRE_CAP])


def _verified_anchor(u: dict, old: str) -> str:
    """Pick the strongest grading anchor that provably lives in the clause,
    strongest first: a ≥2-digit number (survives any paraphrase and any
    language), the generator's own self-nominated anchor, the old
    catalogue anchor if the clause happens to contain it, else any latin
    jargon token or the longest CJK content run. Everything is verified
    mechanically: in-clause, not in src/, minimum length."""
    from bench.gen.build_catalogue import anchor_ok
    clause = u.get("clause") or ""
    m = _NUM.search(clause)
    if m and anchor_ok(m.group()):
        return m.group()
    cands = []
    if u.get("anchor") and u["anchor"] in clause:
        cands.append(u["anchor"])
    if old and old in clause:
        cands.append(old)
    cands += _LATIN_TOKEN.findall(clause)
    runs = sorted(_CJK_RUN.findall(clause), key=len, reverse=True)
    cands += runs[:2]
    for c in cands:
        if anchor_ok(c):
            return c
    return ""


def _canonical_text(sk: dict) -> str:
    from bench.gen.build_catalogue import _canonical
    return _canonical(sk)




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
            "anchor_weak": bool(node_meta.get(c.cid, {}).get("anchor_weak")),
            "successor_of": node_meta.get(c.cid, {}).get("successor_of")}


def _withdrawal_text(c, persona) -> str:
    anchor = c.clause or c.text
    return f"之前说的「{anchor}」那条不用了，按你默认的来吧"


if __name__ == "__main__":
    main()
