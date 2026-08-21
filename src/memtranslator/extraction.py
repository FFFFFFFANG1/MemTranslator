"""Route A candidate extraction and route B attributed-edit extraction.

Route A: CANDIDATE_EXTRACTION_SYSTEM + parse_candidate_output (no Store texts).
Route B: B_EXTRACTION_SYSTEM + parse_feedback_ops (entries the patch used).

The candidate-first CASE consolidator lives in consolidate.py.
The archived GROUPS tidy pass lives in consolidate_tidy_backup.py.
parse_ops / _index_block remain for that archive only.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from memtranslator import llm
from memtranslator.config import (A_MESSAGE_MAX_TOKENS, GEN_TEMPERATURE,
                                  INDEX_ROW_TOKENS, MODELS, SALIENCE_MIN)
from memtranslator.schema import (BUCKETS, POLARITIES, WORK_KIND_ANY,
                                  WORK_KINDS, Requirement)
from memtranslator.scopes import normalize_kind, normalize_scope
from memtranslator.signals import compact_message

POTENTIAL_NEW = "potential_new"
POTENTIAL_CHANGE = "potential_change"
CANDIDATE_KINDS = (POTENTIAL_NEW, POTENTIAL_CHANGE)
CHANGE_REPLACE = "replace"
CHANGE_WITHDRAW = "withdraw"
CHANGE_MODES = (CHANGE_REPLACE, CHANGE_WITHDRAW)
DISCARD_REASONS = ("temporary", "unclear", "not_requirement")
TOP_K = 3


@dataclass
class CandidateItem:
    text: str
    bucket: str
    scope_mode: str = "scoped"
    applies_when: str = ""
    work_kinds: list[str] = field(default_factory=list)
    key: str = ""
    # Display-only 0-10 score. Never gates admission or lifecycle.
    confidence: int = 0


@dataclass
class MemoryCandidate:
    id: str
    kind: str
    item: CandidateItem | None
    change_candidate: str | None
    source_signal_ids: list[int]
    # Original signal texts resolved from source_signal_ids. Persisted by
    # rule; never shown to consolidator or other LLM calls.
    source_texts: list[str]
    ordinal: int
    # A pure withdrawal has no successor item. These fields preserve the
    # extractor's applicability hints for relation judgement in that case.
    bucket: str = ""
    scope_mode: str = "scoped"
    applies_when: str = ""
    work_kinds: list[str] = field(default_factory=list)
    key: str = ""
    confidence: int = 0
    # Explicit lifecycle intent. Previously item=None implicitly carried
    # "withdraw", which made one malformed field flip a revoke into reaffirm.
    change_mode: str | None = None

    @property
    def retrieval_query(self) -> str:
        if self.kind == POTENTIAL_CHANGE:
            return self.change_candidate or ""
        return self.item.text if self.item else ""


@dataclass
class CandidateDiscard:
    """Auditable Extractor-A abstention; never reaches retrieval or memory."""
    reason: str
    source_signal_ids: list[int]
    source_texts: list[str]



CANDIDATE_EXTRACTION_SYSTEM = """Extract atomic, durable requirements that the
user personally adopts for future agent work. Input is a batch of user
messages. [truncated] marks omitted middle text and is never evidence.

For each plausible clause, output candidate or discard.

Admission:
- Focus only on the user's own requirements. Rules merely attributed to a boss,
  client, team, or another person are not the user's unless the user personally
  adopts them. Personal facts, tastes, dietary restrictions, selection
  criteria, and other facts about WHAT to choose → discard not_requirement.
- The current task is temporary by default. Task-local format, tone, length,
  sections, method, and one-time exceptions are not memory merely because the
  task names a reusable work class. Admit only an explicit future/default rule,
  a correction of prior agent behavior not limited to this artifact/run, or the
  same atomic requirement independently repeated in more than two follow-ups.
  Unclear durability → discard unclear; explicit current-run/restored-default
  behavior → discard temporary.
- Store reusable HOW requirements, including durable execution and delivery
  policy, not a one-shot subject or objective. Split independently enforceable
  requirements; merge equivalent batch evidence and keep all source numbers.

Lifecycle:
- potential_new: no evidence that the user is revising an older rule. item is
  the new rule; target_query must be null.
- potential_change + replace: the user gives a durable successor to an old
  facet. item is the successor; target_query describes the OLD rule/facet.
- potential_change + withdraw: the user removes an old rule without a concrete
  successor. item must be null; target_query describes the OLD rule/facet.
  Withdrawal language dominates quoted old limits/formats. Returning to
  normal/default without a concrete replacement is withdraw.
- A bare reference such as "that rule" is targetable only when its antecedent
  occurs in this batch; otherwise discard unclear.

Applicability:
- work_kinds is a non-empty list of English slugs for recurring artifacts or
  activities. Prefer the supplied inventory; otherwise invent a narrow slug.
  Never output agent_response.
- Applicability is an injection-routing contract. Choose exactly one lane:
  1. ALWAYS-IN-CONTEXT means the rule remains relevant and enforceable for
     every possible future agent output, even if the request were replaced by
     unrelated code, email, image, or analysis work. Its ONE legal expression
     is scope_mode="global" + work_kinds=["all"] + applies_when=null.
  2. RETRIEVAL-ONLY means relevance depends on the task or on a condition. Its
     declaration always starts with scope_mode="scoped". It has exactly two
     legal forms:
     a) one or more concrete work_kinds, with applies_when=null or a narrower
        condition within those kinds; or
     b) work_kinds=["all"] with a non-empty applies_when that says when the
        otherwise cross-kind rule becomes relevant.
  Any other combination is invalid. Never use all as an unknown-kind fallback.
- Test global counterfactually: if any ordinary task can make the rule
  irrelevant, it is RETRIEVAL-ONLY. Words like always, every, future, responses,
  or 以后 do not by themselves choose the global lane; interpret what the user
  actually made universal. Classify the rule from its own clause; never inherit
  work kinds from unrelated tasks or rules elsewhere in the same batch.
- Conversely, a rule about the form of every answer, with no task or semantic
  condition in the rule itself, is ALWAYS-IN-CONTEXT even when all supporting
  messages happen to ask technical questions. Do not invent `code`, `report`,
  or another work kind from those examples. Common cases are a universal
  answer-length cap, never using bullets/emoji/Markdown, and never restating
  the user's question.
- "Every output must obey it" does not mean every negative sentence is
  ALWAYS-IN-CONTEXT. A prohibition tied to optional content is relevant only
  when that content appears: units, dates, abbreviations, quoted terms,
  pros/cons, links, citations, named entities, and similar facets use
  scope_mode="scoped" + work_kinds=["all"] + a non-empty applies_when. Reserve
  global for whole-response presentation or voice that must be injected into
  an otherwise unrelated request (overall length, no bullets/emoji/Markdown,
  tone, point of view, not restating the question).
- applies_when is a short natural-language trigger, not a keyword list,
  key:value object, or a copy of the requirement. It must distinguish cases within the same work kind. If it merely restates a concrete kind ("when writing code/reports") or item.text, use null.
- For changes, derive a narrow work kind from the old facet named by the user;
  inability to see the Store is not a reason to use all.

Other fields:
- item.text: one reusable English requirement sentence; preserve quoted names,
  formats, and code terms verbatim.
- bucket: exactly one of task_goal (objective), reasoning_policy (method or
  evidence), deliverables (required content/artifact), output_contract
  (rendering/order/length/structure/language), communication_style
  (tone/register/voice), execution_policy (tools/workflow/input/channel).
- key: stable English facet label containing a dot, e.g. length.max or
  tone.register. confidence: integer 0-10, display-only. sources: supporting
  1-based signal numbers. target_query is one short English sentence.

Minimal examples:
- "For today's export use CSV, then restore JSON." → discard temporary.
- "My boss requires their weekly reports to use bullets." → discard
  not_requirement.
- "Do not use emojis in any response, regardless of the task." →
  ALWAYS-IN-CONTEXT, scope_mode=global, work_kinds=["all"], applies_when=null.
- "Never use markup formatting in any future response." →
  ALWAYS-IN-CONTEXT, scope_mode=global, work_kinds=["all"], applies_when=null.
- "For every answer: keep it short, do not use bullets, and do not restate my
  question." → one compound ALWAYS-IN-CONTEXT candidate only when the three
  clauses were repeatedly stated together; scope_mode=global,
  work_kinds=["all"], applies_when=null. Technical source tasks do not make it
  a `code` rule.
- "Do not use emojis in emails." → RETRIEVAL-ONLY, scope_mode=scoped,
  work_kinds=["email"], applies_when=null.
- "For future reports, when figures are preliminary, label every estimate." →
  scoped, work_kinds=["report"], applies_when="when figures are preliminary".
- "Whenever an abbreviation appears, write its full form first." → scoped,
  work_kinds=["all"], applies_when="when abbreviations appear".
- "Never write calendar dates as digits." → scoped, work_kinds=["all"],
  applies_when="when calendar dates appear"; this is not global merely because
  it says never.
- "Keep every drawback to one short sentence." → scoped,
  work_kinds=["all"], applies_when="when listing drawbacks".
- "Future alerts switch from SMS to a webhook" → potential_change replace,
  scoped, work_kinds=["notification"], applies_when=null; item is the successor
  and target_query names the old delivery-channel rule.
- "The weekday-only meeting restriction now permits weekends" →
  potential_change replace, scoped, work_kinds=["meeting"], applies_when=null;
  item is the successor and target_query names the old scheduling rule.
- "For international invoices, withdraw the mandatory greeting." →
  potential_change withdraw, item=null, work_kinds=["invoice"],
  applies_when="when the invoice is international",
  target_query="international invoice greeting requirement".

FINAL ROUTING CHECK — validate every candidate before returning it:
- global + ["all"] + null is the only ALWAYS-IN-CONTEXT shape.
- scoped + concrete work_kinds + null is work-kind retrieval.
- scoped + concrete work_kinds + condition, or scoped + ["all"] + condition,
  is conditional retrieval.
- scoped + ["all"] + null is NEVER legal. For replace/withdraw, name the
  recurring facet's concrete activity (for example meeting or notification)
  instead of using all. Do not change the candidate into a discard to evade
  this check.

Output STRICTLY one JSON array, possibly empty:
[{
  "decision":"discard","reason":"temporary|unclear|not_requirement",
  "sources":[1]
}, {
  "decision":"candidate",
  "kind":"potential_new|potential_change",
  "change_mode":"replace|withdraw"|null,
  "item":{"text":"...","bucket":"<six buckets>",
          "scope_mode":"global|scoped","applies_when":"..."|null,
          "work_kinds":["all"]|["slug",...],
          "key":"facet.attribute","confidence":0}|null,
  "target_query":"retrieval description or null",
  "bucket":"only needed when item is null",
  "scope_mode":"global|scoped","applies_when":"..."|null,
  "work_kinds":["all"]|["slug",...],"key":"facet.attribute",
  "confidence":0,
  "sources":[1]}]"""



def known_work_kinds(existing: list[Requirement]) -> list[str]:
    """Seed ∪ kinds on active requirements, normalised and sorted."""
    # ``all`` is a reserved coverage declaration, not a suggested class.
    # Showing it beside concrete inventory values primes small models to use
    # it as the fallback whenever they need to invent a new slug.
    found: set[str] = set(WORK_KINDS)
    for req in existing:
        if req.status != "active" or req.kind != "requirement":
            continue
        for kind in req.kinds or []:
            if isinstance(kind, str) and kind.strip():
                normalised = normalize_kind(kind)
                if normalised not in {WORK_KIND_ANY, "agent_response"}:
                    found.add(normalised)
    return sorted(found)


def build_candidate_user_prompt(signals: list[str],
                                known_kinds: list[str] | None = None) -> str:
    block = [{"signal": idx,
              "text": compact_message(
                  text, max_tokens=A_MESSAGE_MAX_TOKENS)}
             for idx, text in enumerate(signals, 1)]
    kinds = known_kinds if known_kinds is not None else list(WORK_KINDS)
    shown_kinds = [kind for kind in kinds
                   if kind not in {WORK_KIND_ANY, "agent_response"}]
    return (
        "SIGNALS-A:\n"
        + json.dumps(block, ensure_ascii=False, indent=2)
        + "\n\nKnown work_kinds (prefer these; invent a new English slug "
        "only when none fit):\n"
        + json.dumps(list(dict.fromkeys(shown_kinds)), ensure_ascii=False)
        + "\n\nJSON:"
    )


def _normalize_work_kinds(value: object) -> list[str] | None:
    if not isinstance(value, list) or not value:
        return None
    out = []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            return None
        normalised = normalize_kind(entry)
        if normalised == "all":
            normalised = WORK_KIND_ANY
        if normalised == "agent_response":
            return None
        out.append(normalised)
    out = list(dict.fromkeys(out))
    if WORK_KIND_ANY in out and len(out) != 1:
        return None
    return out or None


_FACET_KEY = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


def _applicability_declaration(
        applies_when: object, mode: object, work_kinds: list[str], *,
        legacy_scope_present: bool = False
        ) -> tuple[str | None, str | None, str | None]:
    """Validate the explicit always-on-vs-retrieved declaration."""
    if legacy_scope_present:
        return (None, None,
                "scope object is no longer supported; use applies_when")
    if mode not in {"global", "scoped"}:
        return None, None, "missing or malformed scope_mode"
    if applies_when is None:
        condition = ""
    elif isinstance(applies_when, str):
        condition = " ".join(applies_when.split())
    else:
        return None, None, "applies_when must be a string or null"
    if len(condition) > 160:
        return None, None, "applies_when must be at most 160 characters"
    broad = work_kinds == [WORK_KIND_ANY]
    if mode == "global" and (not broad or condition):
        return (None, None,
                "global requires work_kinds all and empty applies_when")
    if mode == "scoped" and broad and not condition:
        return (None, None,
                "scoped with work_kinds all requires non-empty applies_when")
    return condition, str(mode), None


def _facet_key(value: object, work_kinds: list[str]
               ) -> tuple[str | None, str | None]:
    """Require a stable facet key, separate from work-kind applicability."""
    if not isinstance(value, str) or not _FACET_KEY.fullmatch(value.strip()):
        return None, "missing or malformed facet key"
    key = value.strip()
    root = key.split(".", 1)[0]
    if root in {"all", "any", "agent_response", "global"}:
        return None, "facet key must not repeat work_kind or global scope"
    return key, None


def _array(raw: str) -> list | None:
    start, end = raw.find("["), raw.rfind("]")
    if start < 0 or end <= start:
        return None
    fragment = raw[start:end + 1]
    try:
        value = json.loads(fragment)
    except json.JSONDecodeError:
        # Repair unescaped quotes inside values, matching the observed writer
        # failure mode without accepting arbitrary almost-JSON.
        out, in_string, escaped = [], False, False
        for idx, char in enumerate(fragment):
            if char == '"' and not escaped:
                if not in_string:
                    in_string = True
                    out.append(char)
                else:
                    rest = fragment[idx + 1:].lstrip()
                    if rest.startswith((",", ":", "}", "]")):
                        in_string = False
                        out.append(char)
                    else:
                        out.append('\\"')
            else:
                out.append(char)
            escaped = char == "\\" and not escaped
            if char != "\\":
                escaped = False
        try:
            value = json.loads("".join(out))
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, list) else None


def _confidence(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, min(10, value))


def _item(value: object) -> tuple[CandidateItem | None, str | None]:
    if value is None:
        return None, None
    if not isinstance(value, dict):
        return None, "item is not an object"
    text = value.get("text")
    bucket = value.get("bucket")
    if not isinstance(text, str) or not text.strip():
        return None, "item text is empty"
    if bucket not in BUCKETS:
        return None, f"unknown bucket: {bucket!r}"
    work_kinds = _normalize_work_kinds(value.get("work_kinds"))
    if work_kinds is None:
        return None, "missing or malformed work_kinds"
    applies_when, scope_mode, error = _applicability_declaration(
        value.get("applies_when"), value.get("scope_mode"), work_kinds,
        legacy_scope_present="scope" in value)
    if error:
        return None, error
    key, error = _facet_key(value.get("key"), work_kinds)
    if error:
        return None, error
    return CandidateItem(
        text=text.strip(), bucket=bucket, scope_mode=scope_mode,
        applies_when=applies_when, work_kinds=work_kinds, key=key,
        confidence=_confidence(value.get("confidence", 0))), None


def _source_ids(value: dict, signals: list[str]) -> list[int] | None:
    sources = value.get("sources")
    if (not isinstance(sources, list) or not sources
            or any(not isinstance(source, int)
                   or not 1 <= source <= len(signals)
                   for source in sources)):
        return None
    return list(dict.fromkeys(sources))


def parse_candidate_decisions(raw: str, signals: list[str]
                              ) -> tuple[list[MemoryCandidate],
                                         list[CandidateDiscard], list[str]]:
    """Parse explicit discard/candidate decisions from Extractor-A.

    Discards are returned for audit but never become MemoryCandidates, so they
    cannot reach retrieval or the Store. Candidate decisions are strict: a
    missing lifecycle field fails closed instead of reviving the old implicit
    item=None contract.
    """
    values = _array(raw)
    if values is None:
        return [], [], ["candidate output unparseable"]
    candidates, discards, flags = [], [], []
    for output_idx, value in enumerate(values, 1):
        if not isinstance(value, dict):
            flags.append(f"candidate {output_idx}: not an object")
            continue
        decision = value.get("decision")
        if decision == "discard":
            reason = value.get("reason")
            sources = _source_ids(value, signals)
            if reason not in DISCARD_REASONS:
                flags.append(
                    f"discard {output_idx}: unknown reason {reason!r}")
                continue
            if sources is None:
                flags.append(f"discard {output_idx}: invalid sources")
                continue
            discards.append(CandidateDiscard(
                reason=reason, source_signal_ids=sources,
                source_texts=[signals[source - 1] for source in sources]))
            continue
        if decision != "candidate":
            flags.append(
                f"candidate {output_idx}: unknown decision {decision!r}")
            continue
        kind = value.get("kind")
        if kind not in CANDIDATE_KINDS:
            flags.append(f"candidate {output_idx}: unknown kind {kind!r}")
            continue
        item, error = _item(value.get("item"))
        if error:
            flags.append(f"candidate {output_idx}: {error}")
            continue
        change = value.get("target_query", value.get("change_candidate"))
        change = change.strip() if isinstance(change, str) else None
        change_mode = value.get("change_mode")
        if (kind == POTENTIAL_NEW
                and (item is None or change_mode is not None)):
            flags.append(f"candidate {output_idx}: potential_new invariant")
            continue
        if kind == POTENTIAL_NEW and change is not None:
            flags.append(
                f"candidate {output_idx}: potential_new target_query must be null")
            continue
        if (kind == POTENTIAL_CHANGE
                and (not change or change_mode not in CHANGE_MODES)):
            flags.append(f"candidate {output_idx}: potential_change invariant")
            continue
        if (kind == POTENTIAL_CHANGE
                and ((change_mode == CHANGE_WITHDRAW and item is not None)
                     or (change_mode == CHANGE_REPLACE and item is None))):
            flags.append(
                f"candidate {output_idx}: inconsistent {change_mode} item")
            continue
        root_bucket = value.get("bucket") or ""
        root_scope_mode = value.get("scope_mode")
        root_applies_when = value.get("applies_when")
        root_work_kinds = value.get("work_kinds")
        root_confidence = _confidence(value.get("confidence", 0))
        if change_mode == CHANGE_WITHDRAW:
            if root_bucket not in BUCKETS:
                flags.append(
                    f"candidate {output_idx}: withdrawal needs a bucket")
                continue
            root_work_kinds = _normalize_work_kinds(root_work_kinds)
            if root_work_kinds is None:
                flags.append(
                    f"candidate {output_idx}: withdrawal has missing or malformed work_kinds")
                continue
            root_applies_when, root_scope_mode, error = \
                _applicability_declaration(
                    root_applies_when, root_scope_mode, root_work_kinds,
                    legacy_scope_present="scope" in value)
            if error:
                flags.append(f"candidate {output_idx}: withdrawal {error}")
                continue
            root_key, error = _facet_key(value.get("key"), root_work_kinds)
            if error:
                flags.append(f"candidate {output_idx}: withdrawal {error}")
                continue
        else:
            root_work_kinds = item.work_kinds
            root_scope_mode = item.scope_mode
            root_applies_when = item.applies_when
            root_key = item.key
        sources = _source_ids(value, signals)
        if sources is None:
            flags.append(f"candidate {output_idx}: invalid sources")
            continue
        source_texts = [signals[source - 1] for source in sources]
        candidates.append(MemoryCandidate(
            id=f"C{len(candidates) + 1}", kind=kind, item=item,
            change_candidate=change, source_signal_ids=sources,
            source_texts=source_texts, ordinal=len(candidates) + 1,
            bucket=item.bucket if item else root_bucket,
            scope_mode=(item.scope_mode if item else root_scope_mode),
            applies_when=(item.applies_when if item else root_applies_when),
            work_kinds=(item.work_kinds if item
                        else list(dict.fromkeys(root_work_kinds))),
            key=item.key if item else root_key,
            confidence=(item.confidence if item else root_confidence),
            change_mode=change_mode))
    return candidates, discards, flags


def parse_candidate_output(raw: str, signals: list[str]
                           ) -> tuple[list[MemoryCandidate], list[str]]:
    """Compatibility wrapper for callers that only consume candidates."""
    candidates, _discards, flags = parse_candidate_decisions(raw, signals)
    return candidates, flags


A_EXTRACTION_SYSTEM = CANDIDATE_EXTRACTION_SYSTEM
EXTRACTION_SYSTEM = A_EXTRACTION_SYSTEM


B_EXTRACTION_SYSTEM = """You decide whether a stored memory entry should be updated or deleted, from a user's edit.

During user-agent interaction, user's preferred requirements for certain tasks are stored in memory.
The translator weaves applicable entries into the current task description.
The user then edits that polished request before sending it.
Based on these edits, you decide if the entries used need update, retire, or none.

Each SIGNAL has:
- ENTRIES: the exact stored requirements the translator wove into that request, numbered locally.
- DIFF: apply_patch hunks of the user's edit, each
  {"translator_output": "<verbatim span from the patched request>",
   "user_edition": "<what they changed it to>"}.
  translator_output is a span from the translator's patched request — including
  the wording the entry caused. user_edition is what the user changed that
  span to. A hunk that drops the woven constraint with no replacement is
  evidence the entry no longer holds. The user may also edit a place the
  translator did not change; that is none for the entry, not update or retire.
  Long sentences may include [truncated], which is not user wording.

Your job is to judge each entry from the diff: keep it (none), revise it (update), or remove it (retire). You do not create new memories.

Operations definition:
- update: the hunk directly refines, narrows, widens, or changes that entry.
  Return the complete revised durable requirement in ENGLISH, not the
  one-off request; do not merely explain what changed.
- retire: the hunk directly removes or rejects the behavior required by that
  entry and supplies no replacement. This is one negative vote; storage
  retires an entry only after two votes.
- none: the user edited somewhere the translator did not change for this
  entry, or the edit is unrelated, only changes task content or phrasing,
  preserves the entry, adds a one-off constraint, or is ambiguous.

Judge each entry independently. First identify the facet governed by the
entry (length, format, language, tone, method, and so on), then the facet
changed from translator_output to user_edition.

Strict attribution rules:
- If the entry's original behavior remains unchanged and the user merely adds
  a second, independently satisfiable constraint, emit none. Never append an
  orthogonal addition to the stored entry.
- update is allowed only when the hunk changes the same facet, value, or scope
  as the entry. A changed cap, alternative rendering, opposite language or
  tone, or a new exception to the same rule is a replacement/refinement and
  MUST be update, never retire.
- retire is allowed only when the hunk removes or rejects the entry's
  behavior and supplies no replacement on that facet.
- When the edit is not at the location the translator wove this entry, or
  attribution or facet identity is uncertain, emit none.

Never create a new memory, reinforce an entry, infer a style rule, or target
an entry outside the signal. Untouched agent-written text is not user
evidence. A replacement is update, not retire. Emit exactly one judgement
per signal-entry pair.

Output STRICTLY a JSON array, nothing else:
[{"signal": <signal number>, "entry": <entry number>,
  "op": "update"|"retire"|"none", "text": "<required for update>"}]"""



def _index_block(existing: list[Requirement]) -> str:
    rows = []
    for n, r in enumerate(existing, 1):
        text = r.text if len(r.text) <= INDEX_ROW_TOKENS * 4 \
            else r.text[:INDEX_ROW_TOKENS * 4] + "…"
        tag = "/".join(x for x in (r.bucket, r.key) if x) or "unclassified"
        rows.append(f"[{n}] ({tag}) {text}")
    return "\n".join(rows) or "(store is empty)"


def _escape_inner_quotes(s: str) -> str:
    """Repair the one JSON defect flash actually produces: the user's
    curly quotes (“我建议”) echoed back as ASCII double quotes INSIDE a
    string value, which invalidates the whole array and silently threw
    away entire op batches (found live: a batch whose ops were all
    correct — two durable rules extracted, a task spec rightly refused —
    died as "unparseable"). Inside a string, a quote whose next
    non-whitespace character is not a JSON delimiter is content, not a
    terminator — escape it."""
    out, in_str, i = [], False, 0
    while i < len(s):
        ch = s[i]
        if not in_str:
            if ch == '"':
                in_str = True
            out.append(ch)
        elif ch == "\\":
            out.append(s[i:i + 2])
            i += 1
        elif ch == '"':
            j = i + 1
            while j < len(s) and s[j] in " \t\r\n":
                j += 1
            if j < len(s) and s[j] in ",:]}":
                in_str = False
                out.append(ch)
            else:
                out.append('\\"')
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def parse_ops(raw: str, existing: list[Requirement]) -> tuple[list[dict], list[str]]:
    """LLM output → store ops. Numbers become ids here; anything malformed
    is dropped with a flag, never guessed."""
    s = raw.strip()
    start, end = s.find("["), s.rfind("]")
    if start < 0 or end <= start:
        return [], ["unparseable"]
    try:
        items = json.loads(s[start:end + 1])
    except json.JSONDecodeError:
        try:
            items = json.loads(_escape_inner_quotes(s[start:end + 1]))
        except json.JSONDecodeError:
            return [], ["unparseable"]

    ops, flags = [], []
    for it in items:
        if not isinstance(it, dict):
            continue
        op = it.get("op")
        salience = it.get("salience", 0)
        if not isinstance(salience, int) or salience < SALIENCE_MIN:
            continue
        target_id = None
        if it.get("target") is not None:
            t = it["target"]
            if not isinstance(t, int) or not (1 <= t <= len(existing)):
                flags.append(f"target out of range: {t!r}")
                continue
            target_id = existing[t - 1].id

        bucket = it.get("bucket") or ""
        if bucket and bucket not in BUCKETS:
            flags.append(f"unknown bucket: {bucket!r}")
            continue
        polarity = it.get("polarity") or ""
        if polarity and polarity not in POLARITIES:
            polarity = ""            # a bad polarity is droppable metadata,
                                     # unlike a bad bucket which mis-files
        meta = {"bucket": bucket, "polarity": polarity,
                "evidence_id": it.get("evidence_id") or ""}

        if op == "new" and isinstance(it.get("text"), str):
            ops.append({"kind": "new", "text": it["text"],
                        "key": it.get("key", ""),
                        "scope": normalize_scope(it.get("scope")), "salience": salience,
                        **meta})
        elif op == "style_rule" and isinstance(it.get("text"), str):
            ops.append({"kind": "new", "text": it["text"], "key": "",
                        "scope": {}, "salience": salience,
                        "rkind": "style_rule", **meta})
        elif op == "reinforce" and target_id:
            ops.append({"kind": "reinforce", "target_id": target_id})
        elif op == "contradict" and target_id and isinstance(it.get("text"), str):
            ops.append({"kind": "contradict", "target_id": target_id,
                        "text": it["text"], "key": it.get("key", ""),
                        "scope": normalize_scope(it.get("scope")), "salience": salience,
                        **meta})
        elif op == "retire" and target_id:
            ops.append({"kind": "retire", "target_id": target_id})
        elif op == "merge":
            ts = it.get("targets")
            if (isinstance(ts, list) and len(ts) >= 2
                    and all(isinstance(t, int) and 1 <= t <= len(existing)
                            for t in ts)
                    and isinstance(it.get("text"), str)):
                ops.append({"kind": "merge",
                            "target_ids": [existing[t - 1].id for t in ts],
                            "text": it["text"], "key": it.get("key", ""),
                            "scope": normalize_scope(it.get("scope")),
                            "salience": salience, **meta})
            else:
                flags.append(f"malformed merge: {ts!r}")
        else:
            flags.append(f"malformed op: {op!r}")
    return ops, flags


def build_b_user_prompt(candidates: list[dict]) -> str:
    """Route-B input is entry snapshots plus apply_patch hunks — no store
    index. The entries are the ones the patch actually used, recorded at
    translate time, so there is nothing for the model to search for."""
    signals = []
    for signal_n, candidate in enumerate(candidates, 1):
        entries = []
        for entry_n, entry in enumerate(candidate.get("entries", []), 1):
            entries.append({
                "entry": entry_n,
                "text": entry.get("text", ""),
                "key": entry.get("key", ""),
                "scope": entry.get("scope") or None,
                "bucket": entry.get("bucket", ""),
                "kinds": entry.get("kinds") or [],
            })
        shown_diff = []
        for hunk in candidate.get("diff") or []:
            if not isinstance(hunk, dict):
                continue
            shown_diff.append({
                "translator_output": hunk.get(
                    "translator_output", hunk.get("old", "")),
                "user_edition": hunk.get(
                    "user_edition", hunk.get("new", "")),
            })
        signals.append({"signal": signal_n, "entries": entries,
                        "diff": shown_diff})
    return ("SIGNALS:\n" + json.dumps(signals, ensure_ascii=False, indent=2)
            + "\n\nJSON:")



def parse_feedback_ops(raw: str, candidates: list[dict]
                       ) -> tuple[list[dict], list[str]]:
    """Parse route-B judgements and bind them mechanically to the recorded
    entry ids. The model names a (signal, entry) pair, never an id: it can
    only ever act on an entry the patch really used."""
    s = raw.strip()
    start, end = s.find("["), s.rfind("]")
    if start < 0 or end <= start:
        return [], ["unparseable"]
    try:
        items = json.loads(s[start:end + 1])
    except json.JSONDecodeError:
        try:
            items = json.loads(_escape_inner_quotes(s[start:end + 1]))
        except json.JSONDecodeError:
            return [], ["unparseable"]
    if not isinstance(items, list):
        return [], ["unparseable"]

    by_pair, flags, seen = {}, [], set()
    for item in items:
        if not isinstance(item, dict):
            flags.append("malformed feedback judgement")
            continue
        signal_n, entry_n = item.get("signal"), item.get("entry")
        if not isinstance(signal_n, int) \
                or not (1 <= signal_n <= len(candidates)):
            flags.append(f"feedback signal out of range: {signal_n!r}")
            continue
        entries = candidates[signal_n - 1].get("entries", [])
        if not isinstance(entry_n, int) or not (1 <= entry_n <= len(entries)):
            flags.append(f"feedback entry out of range: {entry_n!r}")
            continue
        pair = (signal_n, entry_n)
        if pair in seen:
            flags.append(f"duplicate feedback judgement: {pair!r}")
            continue
        seen.add(pair)
        entry = entries[entry_n - 1]
        target_id = entry.get("id")
        if not target_id:
            flags.append(f"feedback entry missing id: {pair!r}")
            continue

        kind = item.get("op")
        if kind == "none":
            by_pair[pair] = None
            continue
        if kind == "retire":
            by_pair[pair] = {"kind": "retire", "target_id": target_id}
            continue
        if kind == "update":
            text = item.get("text")
            if not isinstance(text, str) or not text.strip():
                flags.append(f"feedback update missing text: {pair!r}")
                continue
            text = text.strip()
            if text == (entry.get("text") or "").strip():
                flags.append(f"feedback update unchanged: {pair!r}")
                continue
            by_pair[pair] = {"kind": "update", "target_id": target_id,
                             "text": text}
            continue
        flags.append(f"unsupported feedback op: {kind!r}")

    expected = sum(len(c.get("entries", [])) for c in candidates)
    if len(seen) < expected:
        flags.append(f"missing feedback judgements: {expected - len(seen)}")
    # Model array order is not trusted. Apply feedback in buffer chronology so
    # a later refinement can reset earlier negative evidence, not vice versa.
    ops = [by_pair[p] for p in sorted(by_pair) if by_pair[p] is not None]
    return ops, flags



def run_a_extraction(a_candidates: list[str],
                     existing: list[Requirement]) -> dict:
    """Route A: candidate extraction + per-candidate retrieval + reconcile."""
    from memtranslator.memory_write import run_memory_write
    return run_memory_write(a_candidates, existing)


def run_b_extraction(candidates: list[dict]) -> dict:
    """Route B: one call over a batch of {entries, diff} signals."""
    user = build_b_user_prompt(candidates)
    writer = MODELS.get("writer") or MODELS["translator"]
    raw = llm.complete(writer, B_EXTRACTION_SYSTEM, user,
                       max_tokens=llm.budget_for(writer, 900),
                       temperature=GEN_TEMPERATURE)
    ops, flags = parse_feedback_ops(raw, candidates)
    return {"ops": ops, "flags": flags,
            "trace": {"input_signals": candidates,
                      "model_visible_prompt": user,
                      "raw_output": raw,
                      "ops": list(ops), "flags": list(flags)}}


def run_extraction(a_candidates: list[str], b_candidates: list[dict],
                   existing: list[Requirement]) -> dict:
    """Compatibility entry point for route A only."""
    if b_candidates:
        raise ValueError("route B must use run_b_extraction")
    return run_a_extraction(a_candidates, existing)
