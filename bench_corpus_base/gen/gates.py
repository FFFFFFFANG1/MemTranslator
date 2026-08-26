"""Four automatic acceptance gates that replace "a human reads every line".

readback is the load-bearing one: a second, BLIND flash call reconstructs the
skeleton from the generated utterance (it never sees the original skeleton),
and the fields are compared mechanically. It works because skeletons are
structured — the comparison is field equality, not semantic similarity. One
regeneration is allowed; a second mismatch drops the atom.

licence gate is zero-token: content-word 5-gram intersection with the source
must be empty and the longest common substring bounded — the generated
sentence must not be the source sentence wearing a wig.

style gate: self-instruct-anchored "does this sound like a person typing" —
1-5, <4 regenerates, two failures drop.

contamination gate rides tests/test_no_bench_contamination.py's approach:
distinctive tokens must not appear in src/.
"""
import json
import re
from pathlib import Path

from bench_corpus_base.gen.flash import flash_json

SRC = Path(__file__).resolve().parents[2] / "src"

READBACK_SYSTEM = """You read ONE user message to their AI assistant and extract the durable delivery rule it establishes, if any.
Output exactly one JSON object:
{"skeleton": {
   "object": "<the named thing demanded/banned, short noun phrase>",
   "threshold": {"value": <number>, "unit": "<unit>"} | null,
   "order": ["<first>", "<second>"] | null,
   "polarity": "require"|"prefer"|"avoid"|"prohibit"
 }}
or {"skeleton": null} when the message establishes no durable delivery rule.
Report only what the message says — never guess a number that is not there."""

STYLE_SYSTEM = """Rate how much this chat message sounds like a real person quickly typing to their AI assistant (not documentation, not a spec, not marketing).
5 = indistinguishable from a real user; 1 = obviously synthetic/formal.
Output exactly: {"score": <1-5>, "why": "<one short phrase>"}"""


def readback_gate(utterance: str, skeleton: dict) -> tuple[bool, str]:
    """Blind reconstruction, field comparison. threshold/polarity must match
    exactly; object matches on token overlap (surface wording varies)."""
    got = flash_json(READBACK_SYSTEM,
                     f"Message:\n{utterance}\n\nJSON:", max_tokens=300)
    if not isinstance(got, dict):
        return False, "readback unparseable"
    rb = got.get("skeleton")
    if not rb:
        return False, "readback found no rule"
    want_th = skeleton.get("threshold")
    got_th = rb.get("threshold")
    if bool(want_th) != bool(got_th):
        return False, "threshold presence mismatch"
    if want_th and got_th:
        try:
            if float(got_th.get("value")) != float(want_th.get("value")):
                return False, (f"threshold value {got_th.get('value')} != "
                               f"{want_th.get('value')}")
        except (TypeError, ValueError):
            return False, "threshold not numeric in readback"
    if not want_th and rb.get("polarity") != skeleton.get("polarity"):
        # Polarity sign only carries information when there is NO threshold
        # ("limit to at most 55" ≡ "don't exceed 55" — the number equality
        # above already pinned the demand), AND the readback landed on the
        # SAME object. A require-rule is routinely uttered as a prohibition
        # of its complement (「必须小写」 ↔ 「别大写」) — same demand, flipped
        # surface, different object word. Only same-object sign flips are
        # real infidelity ("use bullets" vs "don't use bullets").
        pos = ("require", "prefer")
        sign_flip = (rb.get("polarity") in pos) != \
            (skeleton.get("polarity") in pos)
        obj_sk = set(_WORD.findall(_s(skeleton.get("object")).lower()))
        obj_rb = set(_WORD.findall(_s(rb.get("object")).lower()))
        same_object = bool(obj_sk and obj_rb) and \
            len(obj_sk & obj_rb) / len(obj_sk | obj_rb) >= 0.5
        if sign_flip and same_object:
            return False, (f"polarity sign flipped on the same object: "
                           f"{rb.get('polarity')} vs "
                           f"{skeleton.get('polarity')}")
    if skeleton.get("order"):
        if not isinstance(rb.get("order"), (list, tuple)) or not rb["order"]:
            return False, "order lost"
        if [_s(x).lower() for x in rb["order"]] != \
                [_s(x).lower() for x in skeleton["order"]]:
            return False, "order reversed or mangled"
    return True, ""


_WORD = re.compile(r"[a-zA-Z]{3,}|[一-鿿]")


def _s(x) -> str:
    """Coerce a model-provided field to a string. Skeleton fields come back
    from a flash model and are occasionally a list where the schema says
    string; calling .lower() on that killed five episode builds mid-fleet."""
    if isinstance(x, str):
        return x
    if isinstance(x, (list, tuple)):
        return " ".join(_s(i) for i in x)
    return "" if x is None else str(x)


def _ngrams(text: str, n: int = 5) -> set:
    words = _WORD.findall(text.lower())
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def _lcs_len(a: str, b: str) -> int:
    """Longest common substring, O(len(a)*len(b)) — strings are short."""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


def licence_gate(utterance: str, source_raw, allowed: tuple = ()) \
        -> tuple[bool, str]:
    """Zero-token: no shared content-word 5-gram, LCS bounded. The LCS limit
    follows the SOURCE's script (12 for a latin source, 6 for a CJK source):
    what the gate bounds is verbatim copying FROM the source, and a Chinese
    utterance embedding a single English technical term (`exception`) is not
    a copy — a 12+ character run is. Named objects, digits, and the
    skeleton's own content words are exempt via `allowed`."""
    stripped_src = _s(source_raw)
    stripped_utt = _s(utterance)
    for a in allowed:
        if a:
            stripped_src = stripped_src.replace(a, " ")
            stripped_utt = stripped_utt.replace(a, " ")
    if _ngrams(stripped_utt) & _ngrams(stripped_src):
        return False, "shared content 5-gram with source"
    lcs = _lcs_len(stripped_utt.lower(), stripped_src.lower())
    src_cjk = len(re.findall(r"[一-鿿]", stripped_src))
    limit = 6 if src_cjk > max(1, len(stripped_src)) / 3 else 12
    if lcs > limit:
        return False, f"LCS {lcs} > {limit}"
    return True, ""


def style_gate(utterance: str) -> tuple[bool, str]:
    got = flash_json(STYLE_SYSTEM, f"Message:\n{utterance}\n\nJSON:",
                     max_tokens=100)
    if not isinstance(got, dict) or not isinstance(got.get("score"),
                                                   (int, float)):
        return False, "style rating unparseable"
    return got["score"] >= 4, f"style {got['score']}"


DELIVERY_SYSTEM = """You decide whether a stored rule belongs in a DELIVERY-REQUIREMENT memory.
It belongs (answer yes) when it constrains HOW work is produced or delivered: format, length, structure, ordering, wording, register, language, method, workflow.
It does NOT belong (answer no) when it is any of:
- a content, topic, opinion or recommendation preference ("prefer open-source tools")
- a safety / values / harm rule ("never write anything offensive", "stay positive")
- a persona or role instruction ("don't roleplay as a character")
- vacuous or unactionable ("be professional", "do a good job") — an assistant could not tell whether it complied
- a one-off step for a single task rather than a durable rule
Output exactly: {"delivery": true|false, "why": "<short phrase>"}"""


def delivery_gate(clause: str, votes: int = 2) -> tuple[bool, str]:
    """Admission control against the classes that leaked into the first fleet
    audit: safety/values rows (PRISM is ~64% of them), persona instructions,
    and vacuous rules. Conservative by construction — both votes must say
    yes, because a content rule in the catalogue is worse than a missing one:
    the product is designed NOT to store it, so the suite would be grading a
    behaviour it forbids."""
    if not clause.strip():
        return False, "empty"
    for _ in range(votes):
        got = flash_json(DELIVERY_SYSTEM, f"Rule:\n{clause}\n\nJSON:",
                         max_tokens=120)
        if not isinstance(got, dict) or got.get("delivery") is not True:
            why = (got or {}).get("why", "unparseable") if isinstance(
                got, dict) else "unparseable"
            return False, f"not a delivery rule: {why}"
    return True, ""


PLAUSIBILITY_SYSTEM = """You judge whether a rule could belong to a specific person's work at all.
Answer NO only for a clear non-sequitur: the rule is about subject matter this person does not work with (rock descriptions for a site-reliability engineer, legal citations for a backend developer, recipe steps for a product manager).
Answer YES otherwise — including for small, fussy, or low-stakes rules. People state fussy rules about their own work all the time; that is not implausible, it is normal.
Output exactly: {"plausible": true|false, "why": "<short phrase>"}"""


def plausibility_gate(clause: str, persona: dict) -> tuple[bool, str]:
    """Would THIS user have said this? The corpus is partitioned across
    personas by stride, so without this an SRE's memory ends up holding a
    rule about how to describe rocks — the audit found exactly that. A gold
    entry the user would never have stated is not a memory test, it is a
    non-sequitur, and the product is right to ignore it."""
    got = flash_json(PLAUSIBILITY_SYSTEM,
                     f"Person:\n{json.dumps(persona, ensure_ascii=False)}\n\n"
                     f"Rule:\n{clause}\n\nJSON:", max_tokens=120)
    if not isinstance(got, dict):
        return False, "unparseable"
    return bool(got.get("plausible")), got.get("why", "")


def contamination_gate(distinctive: str) -> tuple[bool, str]:
    """The distinctive token must not exist anywhere in src/ — otherwise the
    'memory' being tested is sitting in the product prompt."""
    if not distinctive:
        return True, ""
    for p in SRC.rglob("*.py"):
        if distinctive in p.read_text():
            return False, f"distinctive {distinctive!r} found in {p.name}"
    return True, ""


def run_gates(utterance: str, skeleton: dict, source_raw: str,
              distinctive: str = "") -> tuple[bool, list[str]]:
    """All four; collects every failure rather than stopping at the first,
    so a dropped atom's record says everything that was wrong with it."""
    fails = []
    ok, why = readback_gate(utterance, skeleton)
    if not ok:
        fails.append(f"readback: {why}")
    num = skeleton.get("threshold") or {}
    allowed = tuple(str(x) for x in (
        num.get("value"), skeleton.get("object"), skeleton.get("against"),
        *(skeleton.get("order") or ())) if x)
    ok, why = licence_gate(utterance, source_raw, allowed)
    if not ok:
        fails.append(f"licence: {why}")
    ok, why = style_gate(utterance)
    if not ok:
        fails.append(f"style: {why}")
    ok, why = contamination_gate(distinctive)
    if not ok:
        fails.append(f"contamination: {why}")
    return not fails, fails
