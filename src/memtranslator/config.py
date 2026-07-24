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
