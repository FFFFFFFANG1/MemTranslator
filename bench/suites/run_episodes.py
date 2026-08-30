"""Suite E (lifecycle): drive one episode's scripted user history through the
real product, probe at checkpoints under the arm panel, score three bands.

Protocol v2 — the user is SCRIPTED. What the user says never depends on what
the SUT did (gold-by-fold requires the log to be authored), with one
deliberate exception: diff moves edit the SUT's actual `polished` string,
because that is what an edit IS. The judge is out of the store loop entirely.

E1 protocol v3 has only two payloads: ``user_turns`` and ``ground_truth``.
Of every turn, only ``user_input`` may cross into the product. Probe
expectations and lifecycle/checkpoint data are evaluator-only and may never
affect translation, extraction, batching, or Store state.

Bands (reported separately — owner ruling 2026-07-28: no weighted composite):
- CARRY    should_apply constraints carried into the rewrite, judge-graded
           (E-judge); carry_mech_numeric is the zero-judge cross-check on
           numeric anchors only.
- SUPPRESS must_not_apply (dead, applies-to-filtered, I11-reachable)
           distinctive anchors absent from the rewrite. Zero judge.
- STATE    the SUT store's own account: every dead gold cid has no ACTIVE
           store entry carrying its distinctive; every live one has at least
           one. Alignment is by distinctive substring, never by key — the
           SUT invents its own keys.

Update 2026-08-19 (oracle attributes): the real chain still receives user
input only. The oracle evaluator uses ``should_apply`` to select perfect
memory and passes each selected golden item's authored Extractor attributes
to Translator. Those attributes never cross into the real chained SUT path.

Arms: real / no_retire / oracle / full_context / null-generic — the M6
panel. null-generic is a corpus instrument (prior floor), separated in the
report. Cost note: one episode ≈ 62 chained + |probes|×|arms| translate calls.

    uv run python -m bench.suites.run_episodes e-01
    # Fused E1+perf (one chain → owner metrics + canary/scale instruments):
    uv run python -m bench.perf --episodes e-01,e-03,e-05,e-09
"""
import argparse
import json
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from memtranslator import llm, translate as tr_mod
import memtranslator.recall as recall_mod
from memtranslator.bm25 import BM25
from memtranslator.config import (GEN_TEMPERATURE,
                                  GLOBAL_RECALL_MAX_TOKENS, MODELS,
                                  PATCH_OUTPUT_TOKENS)
from memtranslator.recall import (requirement_block_tokens,
                                  select_within_token_budget)
from memtranslator.schema import Requirement
from memtranslator.store import Store

from bench.graph.derive import Effect, fold
from bench.suites.config import (CASES, RUN_DIR, STATE_JUDGE_MAX_TOKENS,
                                 STATE_JUDGE_MODEL)
from bench.suites.instruments import (pick_canary, sample_instrument,
                                      size_bucket)
from bench.suites.judge import judge
from bench.suites.providers import V1Provider
from bench.suites.report import write_snapshot
from bench.suites.retry import with_retry

# Owner ruling 2026-07-28: no weighted composite; bands report separately.
EXTRACT_BATCH_SIZE = 10
ORACLE_PROTOCOL_VERSION = 4

GENERIC_POLISH_SYSTEM = """You are a request polisher sitting between a user and their AI agent.
Rewrite the user's request so the agent knows exactly what is expected: make the implicit delivery expectations explicit (format, length, structure, style, language).

Rules:
1. Never change the core task the user is asking for.
2. The rewrite only ADDS. Every word of the user's original request survives in it.
3. Keep the rewritten request natural, in the language the user wrote in.
4. Your output is ALWAYS the user's REQUEST — never your answer to it.

Output strictly one JSON object, nothing else:
{"decision": "noop"} or {"decision": "apply", "hunks": [{"old": "<verbatim snippet>", "new": "<replacement>"}]}"""

FULL_CONTEXT_PREAMBLE = (
    "Below is this user's conversation history with you, oldest first. "
    "Later turns override earlier ones when they conflict — a preference "
    "the user has since changed or withdrawn must NOT be applied.")


def _effects(ep: dict) -> list[Effect]:
    return [Effect(seq=e["seq"], kind=e["op"], cid=e.get("id") or "",
                   target=e.get("target") or "",
                   targets=tuple(e.get("targets") or ()),
                   delta=e.get("delta") or 0)
            for e in ep["ground_truth"]["lifecycle"]]


def _requirements(ep: dict) -> list[dict]:
    return ep["ground_truth"]["requirements"]


def _turns(ep: dict) -> list[dict]:
    return ep["user_turns"]


def _checkpoints(ep: dict) -> list[int]:
    return ep["ground_truth"]["state_checkpoints"]


# ---------------------------------------------------------------------------
# arms
# ---------------------------------------------------------------------------

def _complete_with_block(text: str, system: str, block: str,
                         header: str) -> dict:
    user = f"{header}:\n{block}\n\nUser request:\n{text}\n\nJSON:"
    t0 = time.time()
    raw = llm.complete(MODELS["translator"], system, user,
                       max_tokens=PATCH_OUTPUT_TOKENS,
                       temperature=GEN_TEMPERATURE)
    latency_ms = int((time.time() - t0) * 1000)
    patch, parse_error = tr_mod.parse_patch(raw)
    polished = None
    if patch["decision"] == "apply":
        polished = tr_mod.apply_hunks(text, patch["hunks"])
        if polished is None:
            parse_error = True
        elif not tr_mod.preserves_request(text, polished):
            polished = None
            patch = {"decision": "noop"}
    return {"decision": patch["decision"], "polished": polished,
            "parse_error": parse_error,
            "latency_ms": latency_ms, "block_chars": len(block)}


def arm_real(store_items: list, ep, r, transcript, raw_messages=None):
    """Run the product from message text and product-owned state only."""
    del ep, transcript, raw_messages
    active = [x for x in store_items if x.status == "active"]
    out = with_retry(lambda: tr_mod.translate(r["user_input"], active),
                     "arm/real")
    return {**out, "block_chars": sum(len(x.text) for x in active)}


def arm_no_retire(store_items: list, ep, r, transcript, raw_messages=None):
    pool = [x for x in store_items if x.kind == "requirement"]
    pool.sort(key=lambda x: x.created_at)
    if requirement_block_tokens(pool) > GLOBAL_RECALL_MAX_TOKENS:
        scores = BM25([f"{x.text} {x.key or ''}" for x in pool]) \
            .scores(r["user_input"])
        order = sorted(range(len(pool)),
                       key=lambda i: (-scores[i], -pool[i].created_at))
        pool = select_within_token_budget(
            [pool[index] for index in order], GLOBAL_RECALL_MAX_TOKENS)
        pool.sort(key=lambda x: x.created_at)
    block = tr_mod._requirement_block(pool)
    # This counterfactual arm intentionally bypasses the product Translator
    # and retains its single-object parser; keep the matching private prompt.
    return _complete_with_block(
        r["user_input"], tr_mod.LEGACY_TRANSLATOR_SYSTEM, block,
        "Stored requirements")


def arm_oracle(store_items: list, ep, r, transcript, raw_messages=None):
    """Gold-memory application ceiling for one probe.

    Oracle has exactly one protocol: give Translator only this probe's gold
    ``should_apply`` requirements with their authored Extractor attributes.
    It never receives the full gold store, pending raw messages, or query-side
    labels. Selection, retrieval, write-path state, and history are therefore
    fixed as correct; the measured question is only whether Translator can
    carry perfect memory into the current request.
    """
    del store_items, transcript, raw_messages
    by_cid = {n["id"]: n for n in _requirements(ep)}
    expected = r["probe"]
    should_ids = list(expected["should_apply"])
    unknown = [cid for cid in should_ids if cid not in by_cid]
    if unknown:
        raise ValueError(
            f"oracle should_apply references unknown ids: {unknown}")
    if len(should_ids) != len(set(should_ids)):
        raise ValueError("oracle should_apply contains duplicate ids")
    should = [by_cid[cid] for cid in should_ids]
    if not should:
        return {"polished": None, "latency_ms": 0, "block_chars": 0,
                "decision": "noop"}
    required_attributes = {
        "bucket", "scope_mode", "applies_when", "work_kinds", "key",
        "confidence"}
    incomplete = [n["id"] for n in should
                  if not required_attributes <= set(n)]
    if incomplete:
        raise ValueError(
            f"oracle golden items lack Extractor attributes: {incomplete}")
    # Golden files preserve the public Extractor spelling ``all``; Requirement
    # stores the normalised internal spelling ``any``.
    reqs = [Requirement(
        text=n["text"], bucket=n["bucket"], key=n["key"],
        scope_mode=n["scope_mode"], applies_when=n["applies_when"] or "",
        kinds=["any" if kind == "all" else kind
               for kind in n["work_kinds"]],
        confidence=n["confidence"])
        for n in should]
    if requirement_block_tokens(reqs) > GLOBAL_RECALL_MAX_TOKENS:
        raise ValueError(
            "oracle should_apply text exceeds the Translator global-memory "
            f"budget of {GLOBAL_RECALL_MAX_TOKENS} tokens")
    out = with_retry(
        lambda: tr_mod.translate(r["user_input"], reqs), "arm/oracle")
    return {**out, "block_chars": sum(len(x.text) for x in reqs)}


def arm_full_context(store_items: list, ep, r, transcript,
                     raw_messages=None):
    turns = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(transcript))
    block = f"{FULL_CONTEXT_PREAMBLE}\n\n{turns}"
    return _complete_with_block(
        r["user_input"], tr_mod.LEGACY_TRANSLATOR_SYSTEM, block,
        "Conversation history")


def arm_null_generic(store_items: list, ep, r, transcript,
                     raw_messages=None):
    return _complete_with_block(r["user_input"], GENERIC_POLISH_SYSTEM, "(none)",
                                "Stored requirements")


ARMS = {"real": arm_real, "no_retire": arm_no_retire,
        "oracle": arm_oracle,
        "full_context": arm_full_context, "null-generic": arm_null_generic}

# arms whose CARRY is judged (the judge band costs a call per should_apply)
JUDGED_ARMS = ("real", "oracle")


# ---------------------------------------------------------------------------
# chained pass
# ---------------------------------------------------------------------------

def run_chained(ep: dict, batch_size: int = EXTRACT_BATCH_SIZE,
                sizes: list[int] | None = None,
                canary: dict | None = None,
                save_trace: bool = False) -> dict:
    """One write-path chain with probe-triggered extraction.

    Raw turns accumulate until ten messages are buffered or the next authored
    probe needs Translator.  A probe-triggered flush contains only earlier
    turns; the current probe is appended after translation, so evaluator
    expectations and current-turn text cannot leak into its own Store view.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    d = RUN_DIR / "episode-stores"
    d.mkdir(parents=True, exist_ok=True)
    store = Store(d / f"{ep['id']}-{uuid.uuid4().hex[:8]}.jsonl")
    if canary:
        store.add(canary["text"], source="manual")
    provider = V1Provider()
    pending, transcript = [], []
    probe_rows, consolidations = [], []
    write_traces: list[dict] = []
    instrument_rows: list[dict] = []
    snapshots: dict[int, list[dict]] = {}
    peak_active = 0
    taken: set[int] = set()
    probes = [r["user_input"] for r in _turns(ep) if r.get("probe")][:4]
    size_targets = list(sizes or [])

    def flush_pending(flush_seq: int, reason: str, *, final: bool = False):
        nonlocal pending, peak_active
        if not pending:
            return
        batch_events = [dict(event) for event in pending]
        label = f"{ep['id']}/extract{'-final' if final else ''}"
        ops = with_retry(lambda: provider.extract(pending, store.active()),
                         label)
        store_apply = store.apply_ops(ops)
        if save_trace:
            trace = {
                "flush_seq": flush_seq,
                "flush_reason": reason,
                "events": batch_events,
                "provider": getattr(provider, "last_trace", None),
                "ops": list(ops),
                "store_apply": store_apply,
                "store_after": [item.to_dict() for item in store.list()],
            }
            if final:
                trace["final_flush"] = True
            write_traces.append(trace)
        pending = []
        peak_active = max(peak_active, len(store.active()))
        if size_targets:
            n = len(store.active())
            due = [s for s in size_targets if s <= n and s not in taken]
            if due:
                taken.update(due)
                instrument_rows.append(
                    sample_instrument(store, canary, probes, ep["id"]))

    for r in _turns(ep):
        is_probe = bool(r.get("probe"))
        # Only authored probes invoke Translator. Flush the accumulated prior
        # messages first; the current raw request is appended below.
        if is_probe:
            flush_pending(r["seq"], "before_probe_translate")
        user_input = r["user_input"]
        transcript.append(user_input)
        if is_probe:
            out = with_retry(lambda: tr_mod.translate(
                user_input, store.active()), f"{ep['id']}/r{r['seq']}")
            # snapshot the store AS OF this probe: arms scored later must see
            # the store the probe-time system saw, not the end-of-episode one
            probe_rows.append({"round": r, "transcript": list(transcript),
                               "pending_raw": [],
                               "chained_polished": out["polished"],
                               "chained_out": dict(out),
                               "latency_ms": out.get("latency_ms", 0),
                               "store_state": [x.to_dict()
                                               for x in store.list()]})
        pending.append({"type": "natural", "text": user_input})
        if len(pending) >= batch_size:
            flush_pending(r["seq"], "batch_full")
        peak_active = max(peak_active, len(store.active()))
        if r["seq"] in _checkpoints(ep):
            snapshots[r["seq"]] = [x.to_dict() for x in store.list()]

    # The episode is a complete history, not a live daemon waiting for the
    # idle timer. Force the trailing partial batch through A before final
    # checkpoints / STATE are evaluated.
    if pending:
        final_seq = _turns(ep)[-1]["seq"]
        flush_pending(final_seq, "episode_end", final=True)
        if final_seq in _checkpoints(ep):
            snapshots[final_seq] = [x.to_dict() for x in store.list()]

    # Always finish the episode so E1 gold probes/checkpoints stay complete;
    # instruments only sample along the way (and once at the end).
    if size_targets and (not instrument_rows
                         or instrument_rows[-1]["size"] != len(store.active())):
        instrument_rows.append(
            sample_instrument(store, canary, probes, ep["id"]))

    return {"store": store, "probe_rows": probe_rows,
            "snapshots": snapshots, "consolidations": consolidations,
            "peak_active": peak_active,
            "extract_batch_size": batch_size,
            "write_traces": write_traces,
            "instrument_rows": instrument_rows,
            "canary": canary["text"] if canary else None}


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def _mech(polished: str | None, node) -> bool:
    return bool(polished) and node["anchor"] in polished


def _normalised_clause(text: str) -> str:
    """Punctuation-insensitive exact-clause fast path before the LLM judge."""
    return "".join(re.findall(r"[a-z0-9]+|[一-鿿]", text.lower()))


def _explicit_clause_present(text: str, node: dict) -> bool:
    haystack = _normalised_clause(text)
    return any(
        bool(needle) and _normalised_clause(needle) in haystack
        for needle in (node.get("text"), node.get("paraphrase")))


def score_probe(ep, row, arm_name, by_cid) -> dict:
    r = row["round"]
    store_items = [Requirement.from_dict(d) for d in row["store_state"]]
    if arm_name == "real" and isinstance(row.get("chained_out"), dict):
        out = {**row["chained_out"], "block_chars": sum(
            len(x.text) for x in store_items if x.status == "active")}
    elif arm_name == "real" and row.get("chained_polished") is not None:
        out = {"decision": "apply", "polished": row["chained_polished"],
               "latency_ms": 0, "block_chars": 0}
    else:
        out = ARMS[arm_name](
            store_items, ep, r, row["transcript"], row.get("pending_raw", []))
    polished = out.get("polished") or ""
    # A noop sends the original request downstream. Grade that effective text
    # so already-satisfied constraints can pass, while absent constraints stay
    # in the denominator and fail instead of disappearing from the task.
    effective_text = polished or r["user_input"]
    # Three pilots taught the split: SUPPRESS is mechanical (a dead rule's
    # anchor reappearing IS a leak), but mechanical CARRY is only
    # well-defined for OPERATIVE anchors — a number must appear for the rule
    # to be honoured ("≤185词" carried means 185 is in the text), while a
    # qualitative rule ("先给结论") is honoured without reproducing any
    # particular token. The harvest is ~92% qualitative, so CARRY runs on
    # the judge band (E-judge, like E0's criterion) with numeric-mech kept
    # as a zero-judge cross-check column. This is the spec's own E-mech
    # boundary — its mechanical claims were always the SUPPRESS half.
    expected = r["probe"]
    should = list(expected["should_apply"])
    numeric = [cid for cid in should if by_cid[cid]["anchor"].isdigit()]
    carry_judged = []
    if arm_name in JUDGED_ARMS:
        for cid in should:
            n = by_cid[cid]
            if _explicit_clause_present(effective_text, n):
                ok, flag, method = True, False, "explicit_clause"
            else:
                ok, flag = judge(
                    f"The effective request explicitly instructs the "
                    f"downstream agent to follow this constraint: "
                    f"{n['text']}. An authored equivalent phrasing is: "
                    f"{n['paraphrase']}. Count either that phrasing, another "
                    f"equivalent behavioral "
                    f"instruction or directly transforming an applicable "
                    f"occurrence in the original request to obey the rule "
                    f"(for example, changing 3.2% to 3.2 per cent or fixing "
                    f"the case of a named team). Equivalent wording need not "
                    f"repeat the rule verbatim; mere compliance, compatibility, "
                    f"or absence "
                    f"of prohibited content is not enough when the original "
                    f"request contained no applicable occurrence and the "
                    f"effective request states no instruction. A general rule "
                    f"may be instantiated for this task without repeating its "
                    f"future/global quantifier.",
                    {"original_request": r["user_input"],
                     "effective_request": effective_text,
                     "rewritten_request": effective_text,
                     "authored_equivalent": n["paraphrase"]})
                method = "judge"
            carry_judged.append({"cid": cid, "hit": ok,
                                 "judge_parse_flag": flag,
                                 "method": method})
    carry_mech = [(cid, _mech(effective_text, by_cid[cid]))
                  for cid in numeric]
    supp = [(cid, not _mech(effective_text, by_cid[cid]))
            for cid in expected["must_not_apply"]]
    return {"arm": arm_name, "seq": r["seq"],
            "noop": not polished,
            "carry_hits": sum(1 for value in carry_judged
                              if value["hit"]),
            "carry_n": len(carry_judged),
            "carry_mech_hits": sum(1 for _c, h in carry_mech if h),
            "carry_mech_n": len(carry_mech),
            "suppress_hits": sum(1 for _c, h in supp if h),
            "suppress_n": len(supp),
            "block_chars": out.get("block_chars", 0),
            "latency_ms": out.get("latency_ms", 0),
            "effective_text": effective_text,
            "carry_detail": carry_judged,
            "suppress_detail": [{"cid": cid, "hit": hit}
                                for cid, hit in supp],
            "translator": out}


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
    by_cid = {n["id"]: n for n in _requirements(ep)}
    active_entries = [Requirement.from_dict(s) for s in snapshot
                      if s["status"] == "active"
                      and s["kind"] == "requirement"]
    active_texts = [entry.text for entry in active_entries]

    def candidates(node: dict, cap: int = 5) -> list[Requirement]:
        """Shortlist likely equivalents without asking the judge to scan a
        long store. Original sources are ranking evidence only; the judge
        still decides from the stored canonical entry text."""
        target = node["text"]
        distinctive = node.get("anchor") or ""
        documents = ["\n".join((entry.text, *entry.sources))
                     for entry in active_entries]
        sparse = [index for index, _score in BM25(documents).rank(target)]
        source_hits = [
            index for index, entry in enumerate(active_entries)
            if distinctive and any(distinctive in source
                                   for source in entry.sources)
        ]
        order = list(dict.fromkeys(source_hits + sparse))
        return [active_entries[index] for index in order[:cap]]

    def aligned(node) -> bool:
        if any(node["anchor"] in t for t in active_texts):
            return True
        if not active_entries:
            return False
        shortlist = candidates(node)
        ok, _flag = judge(
            "At least one candidate entry expresses the same enforceable "
            "durable rule as the target rule. Count translations, "
            "paraphrases, and canonical normalization as matches, but "
            "require the same direction, value, and scope; related topic or "
            "facet overlap alone is not enough.",
            {"candidate_entries": [
                {"text": entry.text, "key": entry.key,
                 "bucket": entry.bucket, "work_kinds": entry.kinds,
                 "scope": entry.scope}
                for entry in shortlist],
             "target_rule": node["text"]},
            model=STATE_JUDGE_MODEL,
            max_tokens=STATE_JUDGE_MAX_TOKENS)
        return ok

    ok = n = 0
    detail = []
    for cid, g in st.items():
        node = by_cid.get(cid)
        if node is None or not node["anchor"]:
            continue
        # a dead entry whose live SUCCESSOR shares the distinctive (object
        # anchors survive supersession) cannot be told apart — skip those
        successor_ids = [
            effect.get("id")
            for effect in ep["ground_truth"]["lifecycle"]
            if effect["op"] == "contradict" and effect.get("target") == cid]
        succ = [by_cid[successor_id] for successor_id in successor_ids
                if successor_id in by_cid
                and by_cid[successor_id]["anchor"] == node["anchor"]]
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


def _owner_metrics(rows: list[dict], arm: str) -> dict:
    """Owner ruling 2026-07-30: per-task perfect + per-memory hit first."""
    sub = [r for r in rows if r["arm"] == arm
           and (r["carry_n"] + r["suppress_n"]) > 0]
    perfect = sum(1 for r in sub
                  if r["carry_hits"] == r["carry_n"]
                  and r["suppress_hits"] == r["suppress_n"])
    mem_n = sum(r["carry_n"] for r in sub)
    mem_hit = sum(r["carry_hits"] for r in sub)
    return {"tasks_perfect": perfect, "tasks_n": len(sub),
            "memory_hit": mem_hit, "memory_n": mem_n}


def run_one(ep: dict, arms: list[str], sizes: list[int] | None,
            use_canary: bool, save_trace: bool = False,
            cases_dir: Path | None = None) -> dict:
    """One episode: chained write + E1 scoring + optional perf instruments."""
    by_cid = {n["id"]: n for n in _requirements(ep)}
    canary = pick_canary(ep) if use_canary else None
    if use_canary and canary is None:
        print(f"{ep['id']}: no collision-free canary — instruments without "
              f"canary carry/kill")

    print(f"{ep['id']}: chained pass ({len(_turns(ep))} rounds)"
          f"{', canary planted' if canary else ''}...")
    chained = run_chained(ep, sizes=sizes, canary=canary,
                          save_trace=save_trace)
    print(f"  peak SUT active {chained['peak_active']}, "
          f"consolidations {len(chained['consolidations'])}")

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
        if not sub:
            continue
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

    state = sum(r["ok"] for r in state_rows) / max(
        1, sum(r["n"] for r in state_rows))
    real = per_arm.get("real", {})
    om = _owner_metrics(rows, "real")

    if om["tasks_n"]:
        print(f"\nper-task  (全部要求完美选出): {om['tasks_perfect']}"
              f"/{om['tasks_n']} = "
              f"{om['tasks_perfect'] / om['tasks_n']:.2f}")
    if om["memory_n"]:
        print(f"per-memory (该提到的记忆命中): {om['memory_hit']}"
              f"/{om['memory_n']} = "
              f"{om['memory_hit'] / om['memory_n']:.2f}")

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
    if len(arms) > 1:
        print("note: null-generic is a corpus instrument, not a product "
              "baseline — do not plot it against the other arms")

    bands = [x for x in (real.get("carry"), real.get("suppress"), state)
             if x is not None]
    band_mean = sum(bands) / len(bands) if bands else 0.0
    result = {"id": ep["id"], "category": "episode",
              "episode": ep["id"], "pass": bool(bands),
              "score": band_mean, "score_is": "unweighted band mean",
              "owner_metrics": om,
              "carry": real.get("carry"), "suppress": real.get("suppress"),
              "state": state,
              "instrument_rows": chained["instrument_rows"],
              "canary": chained["canary"],
              "peak_sut_active": chained["peak_active"],
              "state_judge_model": STATE_JUDGE_MODEL,
              "extract_batch_size": chained["extract_batch_size"],
              "final_active": len(chained["store"].active()),
              "final_retired": sum(1 for x in chained["store"].list()
                                   if x.status == "retired")}
    if save_trace:
        result["probe_trace"] = {
            "chained": chained["probe_rows"],
            "scores": rows,
        }
        result["write_trace"] = chained["write_traces"]
    cases_dir = cases_dir or CASES / "episodes"
    write_snapshot(f"E1-{ep['id']}", str(cases_dir), [result],
                   expected=1,
                   extra={"protocol_version": ep.get("protocol_version"),
                          "arms": per_arm,
                          "state_band": state, "state_rows": state_rows,
                          "consolidations": chained["consolidations"],
                          "extract_batch_size": (
                              chained["extract_batch_size"]),
                          "peak_sut_active": chained["peak_active"],
                          "probe_rows_n": len(chained["probe_rows"]),
                          "instrument_rows": chained["instrument_rows"],
                          "canary": chained["canary"],
                          "scoped_recall_cap": recall_mod.SCOPED_RECALL_CAP,
                          "scoped_attribute_pool_cap": (
                              recall_mod.SCOPED_ATTRIBUTE_POOL_CAP),
                          "oracle_protocol_version": (
                              ORACLE_PROTOCOL_VERSION
                              if "oracle" in arms else None)})
    return result


def _print_instrument_table(results: list[dict]) -> None:
    print(f"\n{'bucket':>7} {'carry@alive':>12} {'kills':>6} {'noop%':>6} "
          f"{'ms':>6} {'chars':>7}")
    by_b: dict[str, list] = {}
    for r in results:
        for row in r.get("instrument_rows") or []:
            by_b.setdefault(size_bucket(row["size"]), []).append(row)
    if not by_b:
        print("  (no instrument samples — pass --sizes to enable)")
        return
    for b in sorted(by_b, key=lambda x: int(x.split("-")[0])):
        rows = by_b[b]
        alive = [x for x in rows if x["canary"].get("alive")]
        carried = sum(1 for x in alive if x.get("canary_carried"))
        kills = sum(1 for x in rows if not x["canary"].get("alive"))
        print(f"{b:>7} {carried}/{len(alive):>2}@alive {kills:>6} "
              f"{100 * sum(x['noop_rate'] for x in rows) / len(rows):>5.0f} "
              f"{sum(x['mean_ms'] for x in rows) // len(rows):>6} "
              f"{sum(x['block_chars'] for x in rows) // len(rows):>7}")
    for r in results:
        for row in r.get("instrument_rows") or []:
            if not row["canary"].get("alive"):
                print(f"  KILL in {r['episode']} at size {row['size']}: "
                      f"canary superseded by: "
                      f"{row['canary'].get('successor')}")


def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(
        description="E1 lifecycle (+ optional perf instruments on one chain)")
    ap.add_argument("episode", nargs="?", default=None,
                    help="single episode id (default e-01); "
                         "ignored when --episodes is set")
    ap.add_argument("--episodes", default="",
                    help="comma-separated episode ids; enables fused "
                         "E1+perf output (default arms=real, canary on)")
    ap.add_argument(
        "--episodes-dir", type=Path, default=CASES / "episodes",
        help="episode corpus directory (default: bench/cases/episodes; use "
             "bench/cases/episodes-noisy for the OASST1-expanded corpus)")
    ap.add_argument("--arms", default="",
                    help="default: full arm panel for one episode; "
                         "real only when --episodes is set")
    ap.add_argument("--sizes", default=None,
                    help="active-store thresholds for instrument samples "
                         "(default: 4,8,16,24,32 with --episodes; off for "
                         "single-episode classic E1). Pass '' to disable.")
    ap.add_argument("--canary", action=argparse.BooleanOptionalAction,
                    default=None,
                    help="plant collision-free canary on the chained store "
                         "(default: on with --episodes, off for single)")
    ap.add_argument("--workers", type=int, default=4,
                    help="episode-level parallelism (default 4)")
    ap.add_argument(
        "--scoped-cap", type=int, default=None,
        help="bench ablation: override the product scoped recall cap for "
             "this process")
    ap.add_argument(
        "--attribute-pool", type=int, default=None,
        help="bench ablation: preselect this many scoped rules from "
             "work_kinds + applies_when before body retrieval; 0 disables")
    ap.add_argument(
        "--save-trace", action=argparse.BooleanOptionalAction, default=False,
        help="persist full per-probe inputs, store snapshots, translator "
             "outputs and per-cid scores (default: scores only)")
    args = ap.parse_args(argv)
    if args.scoped_cap is not None:
        if args.scoped_cap < 1:
            ap.error("--scoped-cap must be positive")
        recall_mod.SCOPED_RECALL_CAP = args.scoped_cap
    if args.attribute_pool is not None:
        if args.attribute_pool < 0:
            ap.error("--attribute-pool cannot be negative")
        recall_mod.SCOPED_ATTRIBUTE_POOL_CAP = args.attribute_pool
    if (recall_mod.SCOPED_ATTRIBUTE_POOL_CAP
            and recall_mod.SCOPED_ATTRIBUTE_POOL_CAP
            < recall_mod.SCOPED_RECALL_CAP):
        ap.error("--attribute-pool must be at least --scoped-cap")
    print(f"scoped recall cap: {recall_mod.SCOPED_RECALL_CAP}", flush=True)
    print("scoped attribute pool: "
          f"{recall_mod.SCOPED_ATTRIBUTE_POOL_CAP or 'disabled'}", flush=True)

    multi = bool(args.episodes.strip())
    ep_ids = ([e.strip() for e in args.episodes.split(",") if e.strip()]
              if multi else [args.episode or "e-01"])
    arms = ([a.strip() for a in args.arms.split(",") if a.strip()]
            if args.arms.strip()
            else (["real"] if multi else [
                "real", "no_retire", "oracle",
                "full_context", "null-generic"]))
    if args.sizes is None:
        sizes = [4, 8, 16, 24, 32] if multi else None
    elif not str(args.sizes).strip():
        sizes = None
    else:
        sizes = [int(s) for s in str(args.sizes).split(",") if s.strip()]
    use_canary = (bool(multi) if args.canary is None else args.canary)
    episodes_dir = args.episodes_dir.resolve()
    if not episodes_dir.is_dir():
        ap.error(f"--episodes-dir is not a directory: {episodes_dir}")

    def _load_and_run(epid: str) -> dict:
        episode_path = episodes_dir / f"{epid}.json"
        if not episode_path.is_file():
            raise FileNotFoundError(f"episode not found: {episode_path}")
        ep = json.loads(episode_path.read_text())
        return run_one(ep, arms, sizes, use_canary,
                       save_trace=args.save_trace, cases_dir=episodes_dir)

    results = []
    workers = max(1, args.workers)
    if workers == 1 or len(ep_ids) == 1:
        for epid in ep_ids:
            results.append(_load_and_run(epid))
    else:
        by_id = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_load_and_run, epid): epid for epid in ep_ids}
            for fut in as_completed(futs):
                epid = futs[fut]
                by_id[epid] = fut.result()
        results = [by_id[epid] for epid in ep_ids]

    if len(results) > 1:
        tasks_n = sum(r["owner_metrics"]["tasks_n"] for r in results)
        tasks_p = sum(r["owner_metrics"]["tasks_perfect"] for r in results)
        mem_n = sum(r["owner_metrics"]["memory_n"] for r in results)
        mem_h = sum(r["owner_metrics"]["memory_hit"] for r in results)
        print("\n=== pooled owner metrics ===")
        if tasks_n:
            print(f"per-task  {tasks_p}/{tasks_n} = {tasks_p / tasks_n:.3f}")
        if mem_n:
            print(f"per-memory {mem_h}/{mem_n} = {mem_h / mem_n:.3f}")

    if sizes is not None:
        _print_instrument_table(results)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        payload = {"suite": "E1+P", "at": stamp,
                   "episodes": ",".join(ep_ids), "arms": arms,
                   "episodes_dir": str(episodes_dir),
                   "sizes": sizes, "canary": use_canary,
                   "scoped_recall_cap": recall_mod.SCOPED_RECALL_CAP,
                   "scoped_attribute_pool_cap": (
                       recall_mod.SCOPED_ATTRIBUTE_POOL_CAP),
                   "save_trace": args.save_trace,
                   "results": results}
        out = Path(__file__).resolve().parents[1] / "results" / f"lifecycle-{stamp}.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
        latest = Path(__file__).resolve().parents[1] / "perf_results.json"
        latest.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
        print(f"-> {out} (+ latest pointer {latest.name})")


if __name__ == "__main__":
    main()
