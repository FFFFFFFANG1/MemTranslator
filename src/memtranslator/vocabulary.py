"""Small, explicit spelling ledger for the desktop input loop.

Vocabulary is deliberately separate from requirement memory.  A vocabulary
entry only preserves the exact spelling of a name, acronym, or project term;
it never says how an agent should perform a task.  Semantic edits continue to
flow through the existing route-B requirement writer.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path


STATUSES = {"active", "retired"}
_IDENTIFIER = r"[A-Za-z](?:[A-Za-z0-9]|[._+\-/](?=[A-Za-z0-9]))*"
_TOKEN = re.compile(_IDENTIFIER + r"|[\u3400-\u9fff]+|\d+|[^\w\s]",
                    re.UNICODE)
_LATIN_TERM = re.compile(_IDENTIFIER)
_CJK_TERM = re.compile(r"[\u3400-\u9fff]{2,12}")


@dataclass
class VocabularyEntry:
    term: str
    alias: str = ""
    source: str = "manual"
    app_bundle_id: str = ""
    status: str = "active"
    id: str = field(default_factory=lambda: f"voc-{uuid.uuid4().hex[:10]}")
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    observations: int = 1

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "VocabularyEntry":
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in raw.items() if k in allowed})


class VocabularyStore:
    """Append-only JSONL vocabulary store, matching the requirement ledger."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._items: dict[str, VocabularyEntry] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text().splitlines():
            if not line.strip():
                continue
            entry = VocabularyEntry.from_dict(json.loads(line))
            self._items[entry.id] = entry

    def _append(self, entry: VocabularyEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as handle:
            handle.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

    def upsert(self, term: str, *, alias: str = "", source: str = "manual",
               app_bundle_id: str = "") -> tuple[VocabularyEntry, bool]:
        term, alias = term.strip(), alias.strip()
        if not term:
            raise ValueError("vocabulary term is empty")
        match = next((item for item in self._items.values()
                      if item.term.casefold() == term.casefold()
                      and item.alias.casefold() == alias.casefold()), None)
        if match is not None:
            match.term = term
            match.status = "active"
            match.updated_at = time.time()
            match.observations += 1
            if app_bundle_id:
                match.app_bundle_id = app_bundle_id
            self._append(match)
            return match, False
        entry = VocabularyEntry(term=term, alias=alias, source=source,
                                app_bundle_id=app_bundle_id)
        self._items[entry.id] = entry
        self._append(entry)
        return entry, True

    def update(self, entry_id: str, *, term: str | None = None,
               status: str | None = None) -> VocabularyEntry:
        entry = self._items[entry_id]
        if term is not None:
            term = term.strip()
            if not term:
                raise ValueError("vocabulary term is empty")
            entry.term = term
        if status is not None:
            if status not in STATUSES:
                raise ValueError(f"unknown status: {status}")
            entry.status = status
        entry.updated_at = time.time()
        self._append(entry)
        return entry

    def list(self, *, include_retired: bool = True) -> list[VocabularyEntry]:
        entries = sorted(self._items.values(), key=lambda item: item.created_at)
        if include_retired:
            return entries
        return [item for item in entries if item.status == "active"]

    def get(self, entry_id: str) -> VocabularyEntry:
        return self._items[entry_id]


def _tokens(text: str) -> list[tuple[str, int, int]]:
    return [(match.group(0), match.start(), match.end())
            for match in _TOKEN.finditer(text)]


def _looks_like_term(value: str) -> bool:
    return bool(_LATIN_TERM.fullmatch(value) or _CJK_TERM.fullmatch(value))


def vocabulary_replacements(polished: str, final: str,
                            limit: int = 3) -> list[dict]:
    """Return conservative one-token spelling replacements.

    This intentionally does not turn arbitrary prose edits into vocabulary.
    Each candidate must be a one-token replacement whose before/after forms
    remain lexically similar, or whose final form is visibly identifier-like.
    """
    before, after = _tokens(polished), _tokens(final)
    matcher = SequenceMatcher(None, [token[0] for token in before],
                              [token[0] for token in after], autojunk=False)
    candidates = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace" or i2 - i1 != 1 or j2 - j1 != 1:
            continue
        alias, term = before[i1][0], after[j1][0]
        if not (_looks_like_term(alias) and _looks_like_term(term)):
            continue
        similarity = SequenceMatcher(None, alias.casefold(),
                                     term.casefold()).ratio()
        identifier_like = bool(re.search(r"[A-Z0-9._+\-/]", term[1:]))
        if similarity < 0.45 and not identifier_like:
            continue
        candidates.append({"term": term, "alias": alias,
                           "similarity": round(similarity, 3)})
        if len(candidates) >= limit:
            break
    return candidates


def apply_vocabulary(text: str,
                     entries: list[VocabularyEntry]) -> tuple[str, list[str]]:
    """Apply confirmed alias → term spellings to complete tokens only.

    This is a deterministic local pre-pass, not requirement recall and not an
    LLM prompt. The most recently updated active entry wins if two aliases
    conflict. Substrings are never replaced (``Sirius`` must not alter
    ``SiriusXM``).
    """
    aliases: dict[str, VocabularyEntry] = {}
    for entry in sorted(entries, key=lambda item: item.updated_at):
        if entry.status == "active" and entry.alias:
            aliases[entry.alias.casefold()] = entry
    if not aliases:
        return text, []
    pieces, cursor, applied = [], 0, []
    for token, start, end in _tokens(text):
        entry = aliases.get(token.casefold())
        if entry is None or token == entry.term:
            continue
        pieces.extend((text[cursor:start], entry.term))
        cursor = end
        if entry.id not in applied:
            applied.append(entry.id)
    if not pieces:
        return text, []
    pieces.append(text[cursor:])
    return "".join(pieces), applied
