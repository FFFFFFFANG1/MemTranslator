"""Tests for the user_edit diff signal and the default-profile fallback."""

import json

from memtranslator import FakeLLM, MemoryEntry, MemoryStore, Scope
from memtranslator.extract import extract
from memtranslator.transcript import format_transcript, render_edit_note

# --- edit-note rendering ---------------------------------------------------

EDITED_TURN = {
    "role": "user",
    "text": "帮我看看 Zep 这篇论文，请批判性分析其新颖性。另外单独说说 bi-temporal 设计值不值得借鉴。",
    "final": "帮我看看 Zep 这篇论文，请批判性分析其新颖性。另外单独说说 bi-temporal 设计值不值得借鉴。",
    "original": "帮我看看 Zep 这篇论文",
    "polished": "帮我看看 Zep 这篇论文，请批判性分析其新颖性。",
}


def test_edit_note_rendered_when_user_modified_draft():
    note = render_edit_note(EDITED_TURN)
    assert note is not None
    assert "system draft" in note
    assert "帮我看看 Zep 这篇论文，请批判性分析其新颖性。" in note
    rendered = format_transcript([EDITED_TURN])
    assert "[EDIT NOTE" in rendered


def test_no_edit_note_when_sent_verbatim():
    turn = dict(EDITED_TURN, final=EDITED_TURN["polished"], text=EDITED_TURN["polished"])
    assert render_edit_note(turn) is None
    assert "[EDIT NOTE" not in format_transcript([turn])


def test_no_edit_note_without_translation():
    turn = {"role": "user", "text": "随便聊聊", "final": "随便聊聊", "polished": ""}
    assert render_edit_note(turn) is None


# --- user_edit extraction signal -------------------------------------------

def test_user_edit_candidate_accepted_with_quote_from_user_text(tmp_path):
    store = MemoryStore(tmp_path / "m.jsonl")
    resp = json.dumps({"candidates": [{
        "requirement": "When reviewing memory-system papers, separately assess design decisions worth adopting.",
        "polarity": "do",
        "scope_condition": "the user asks to review a memory-system paper",
        "task_type": "research.paper-review",
        "keywords": ["paper", "adopt", "design"],
        "signal": "user_edit",
        "quote": "另外单独说说 bi-temporal 设计值不值得借鉴",
        "turn": 0,
        "expires_hint": None,
    }]}, ensure_ascii=False)
    got = extract(FakeLLM([resp]), format_transcript([EDITED_TURN]), store)
    assert len(got) == 1 and got[0].signal == "user_edit"


# --- default profile --------------------------------------------------------

def default_entries():
    return [MemoryEntry(requirement="Stay focused on what was asked.",
                        scope=Scope(condition="any request", keywords=["focus"]))]


def test_seed_defaults_idempotent(tmp_path):
    store = MemoryStore(tmp_path / "m.jsonl")
    assert store.seed_defaults(default_entries()) == 1
    assert store.seed_defaults(default_entries()) == 0
    reloaded = MemoryStore(tmp_path / "m.jsonl")
    assert sum(1 for e in reloaded.all() if e.source == "default") == 1


def test_seed_respects_retired_default(tmp_path):
    store = MemoryStore(tmp_path / "m.jsonl")
    store.seed_defaults(default_entries())
    mid = store.active()[0].mid
    store.retire(mid)
    assert store.seed_defaults(default_entries()) == 0  # stays retired, no re-seed
    assert store.active() == []


def test_learned_outranks_default_at_equal_relevance(tmp_path):
    store = MemoryStore(tmp_path / "m.jsonl")
    store.seed_defaults([MemoryEntry(requirement="Default about papers.",
                                     scope=Scope(condition="any", keywords=["paper"]))])
    learned = store.add(MemoryEntry(requirement="Learned about papers.",
                                    scope=Scope(condition="papers", keywords=["paper"])))
    got = store.recall("review this paper", k=2)
    assert got[0].mid == learned.mid


def test_default_can_be_superseded_by_learned(tmp_path):
    store = MemoryStore(tmp_path / "m.jsonl")
    store.seed_defaults(default_entries())
    default = store.active()[0]
    new = store.supersede(default.mid, MemoryEntry(
        requirement="Give exhaustive detail on every request.",
        scope=Scope(condition="any request")))
    assert store.get(default.mid).status == "superseded"
    assert [e.mid for e in store.active()] == [new.mid]
    assert new.source == "learned"
