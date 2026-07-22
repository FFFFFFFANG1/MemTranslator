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
