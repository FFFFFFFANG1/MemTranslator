"""Single source of truth for models, paths, and budgets."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
STORE_FILE = DATA / "store.jsonl"
EVENTS_FILE = DATA / "events.jsonl"
WEB_DIR = ROOT / "web"

MODELS = {
    # anchor §5: translator (and the future write path) run on flash-tier only
    "translator": "claude-haiku-4-5",
    # stand-in for the user's real downstream agent; swappable, any strong model
    "downstream": "claude-opus-4-8",
}

# anchor §4 context budget: only the newest N active requirements reach the prompt
RECALL_CAP = 32

# v1 pipeline knobs (design 2026-07-24 R5 — proposal defaults, single point)
BATCH_N = 8               # extraction fires at N queued candidates...
FLUSH_IDLE_S = 30 * 60    # ...or 30min after the oldest one
SALIENCE_MIN = 3          # extraction ops below this are dropped
CONSOLIDATE_ACTIVE = 48   # consolidation fires above this many active reqs...
CONSOLIDATE_ADDS = 16     # ...or after this many ADDs since the last pass
STYLE_RULE_CAP = 10       # style_rule entries kept after curation
INDEX_ROW_TOKENS = 20     # per-entry text budget in numbered indexes

# A rewrite only adds: at least this share of the user's original text must
# survive verbatim in the polished request, or the patch is discarded as a
# replacement rather than a rewrite (translate.preserves_request). Set just
# below 1.0 to tolerate ordinary connective rewording ("催修暖气" → "催他尽快
# 修暖气") while still catching deletion of user content.
PRESERVE_MIN_RATIO = 0.85

# Every product generative call is pinned to greedy decoding. anchor §5 ranks
# "predictable rewrite magnitude" above peak accuracy: the same request with
# the same store should produce the same rewrite, or the hotkey stops feeling
# like a tool and starts feeling like a dice roll. It also removes the
# dominant source of run-to-run noise in the write path (the SDK default is
# temperature 1.0, which was measured as the largest variance term in suite E).
GEN_TEMPERATURE = 0.0

# The rewrite is additive, so its length tracks the request's. A fixed cap
# truncates long pastes mid-payload and the hotkey silently does nothing;
# translate.output_budget() scales within these bounds. The ceiling exists so
# a pathological paste cannot bill an unbounded completion.
MIN_OUTPUT_TOKENS = 1024
MAX_OUTPUT_TOKENS = 8192
