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

# Injection pre-screen (2026-07-29): above this many candidates, recall ranks
# and injects only the top slice. Measured motivation: at 32 flat-injected
# rules the flash translator refused 5/5 on a task with two squarely
# applicable rules, while the same task over 2 injected rules applied 3/3 —
# the failure is selection difficulty across competing conditional rules,
# not context length (32 rules ≈ 1.1k tokens). Every current scenario needs
# at most 3 rules woven simultaneously (E1 probe max should_fire), so 8
# keeps 2.5x headroom.
INJECT_CAP = 8

# v1 pipeline knobs (design 2026-07-24 R5 — proposal defaults, single point)
BATCH_N = 8               # extraction fires at N queued candidates...
FLUSH_IDLE_S = 30 * 60    # ...or 30min after the oldest one
SALIENCE_MIN = 3          # extraction ops below this are dropped
# Tightened 2026-07-29: at 48/16 the ACTIVE branch never fired in practice
# (11/12 episodes) and stores accumulated visible triplicates ("只囤不并").
# Dedup and conflict elimination are the WRITE path's job — the rewrite
# model's newest-wins rule is a last line of defense, not the mechanism.
CONSOLIDATE_ACTIVE = 24   # consolidation fires above this many active reqs...
CONSOLIDATE_ADDS = 8      # ...or after this many ADDs since the last pass
STYLE_RULE_CAP = 10       # style_rule entries kept after curation
INDEX_ROW_TOKENS = 20     # per-entry text budget in numbered indexes

# A rewrite only adds: at least this share of the user's original text must
# survive verbatim in the polished request, or the patch is discarded as a
# replacement rather than a rewrite (translate.preserves_request). Set just
# below 1.0 to tolerate ordinary connective rewording ("催修暖气" → "催他尽快
# 修暖气") while still catching deletion of user content.
PRESERVE_MIN_RATIO = 0.85

# Read-path wire format (2026-07-30, phase ③ latency tier). "edits": the
# model emits INSERTIONS ONLY ({"after": snippet, "insert": text} /
# {"append": text}) and the product splices mechanically — output tokens
# then scale with the constraints woven in, not with the request length the
# legacy "full" mode had to echo back verbatim. The rewrite contract is
# add-only, so insertions express every legal rewrite; a splice that fails
# (anchor missing/ambiguous) degrades to noop like every other error path.
# "full" = legacy full-text polished; instant rollback switch.
#
# Routing (2026-07-30): edits wire engages only ABOVE a request-size floor.
# Measured: the win is entirely on long inputs (2437→1123ms on a ~500-char
# paste) while short requests echo cheaply in full mode (0.85-1.5s) — and
# the injection family showed edits mode is "braver" next to short
# attack-shaped tasks where full mode's cautious noop is the banked 46/46
# behavior. Below the floor nothing changes; above it, protected-zone
# splicing guards pasted material. One prompt-patch attempt at the caution
# gap was spent without effect — this routing is the mechanical resolution,
# not a third patch.
TRANSLATE_WIRE = "edits"
EDITS_MIN_TOKENS = 200     # request size (est. tokens) below which full wire is used
EDITS_OUTPUT_TOKENS = 700  # flat budget: inserts are short by construction

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
