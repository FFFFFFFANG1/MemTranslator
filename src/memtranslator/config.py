"""Single source of truth for models, paths, and budgets."""
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_project_env(path: Path) -> None:
    """Load simple KEY=VALUE entries without overriding the launch shell.

    The product keeps provider credentials in the gitignored project `.env`.
    `uvicorn` and the menu-bar process do not source that file themselves, so
    loading it here keeps every entry point on the same configuration path.
    """
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_project_env(ROOT / ".env")

DATA = ROOT / "data"
STORE_FILE = DATA / "store.jsonl"
EVENTS_FILE = DATA / "events.jsonl"
VOCAB_FILE = DATA / "vocabulary.jsonl"
WEB_DIR = ROOT / "web"


def project_env(name: str, default: str = "") -> str:
    """Read one setting from process env, then the repo-root ``.env``.

    Product and bench previously loaded the same endpoint credentials through
    different paths, so activating the project venv still left product calls
    without a key. Keep the tiny loader dependency-free and make process env
    win for deployments and one-off experiments.
    """
    if name in os.environ:
        return os.environ[name]
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == name:
                return value.strip()
    return default

# Candidate retrieval may fuse BM25 with a local multilingual embedding
# model. The default points at an explicitly provisioned ONNX export and is
# never downloaded at runtime. ONNX CPU execution is the compatibility floor;
# alternative local backends may use an integrated GPU, but a discrete GPU or
# remote embedding API must not be required for memory correctness.
EMBED_MODEL_DIR = Path(os.environ.get(
    "MT_EMBED_MODEL_DIR", ROOT / "models" / "multilingual-e5-small"))
EMBED_ONNX_FILE = os.environ.get("MT_EMBED_ONNX_FILE", "onnx/model_O4.onnx")

MODELS = {
    # anchor §5: flash tier. 2026-07-31 owner ruling: main model is
    # deepseek-v4-flash over Ark ("ark:" prefix routes the channel, ":think"
    # suffix enables reasoning — llm.py); the read path never thinks
    # (latency-bound). qwen/ling are auxiliary verification backbones.
    "translator": "ark:deepseek-v4-flash",
    # write path (extraction/consolidation/kind tagging): may think — it is
    # asynchronous, its latency is free. MT_WRITER env overrides for A/B
    # runs without touching this file (parallel experiments must not race
    # on config edits). Absent → falls back to translator.
    "writer": os.environ.get("MT_WRITER", "ark:deepseek-v4-flash"),
    # Stand-in for the user's real downstream agent. Prefer the same
    # OpenAI-compatible model declared by the project `.env`; MT_DOWNSTREAM
    # remains the explicit override for testing another channel.
    "downstream": os.environ.get(
        "MT_DOWNSTREAM",
        f"ark:{os.environ.get('LLM_MODEL', 'deepseek-v4-flash')}"),
}

# Translator recall has two independent prompt budgets. Explicitly broad
# rules never compete with task-scoped rules: global requirements share a
# 2048-token prompt budget, while structured applicability + retrieval
# chooses up to sixteen scoped requirements. There is intentionally no fixed
# total item cap: short global rules should not be discarded merely because
# ten other short rules exist.
GLOBAL_RECALL_MAX_TOKENS = 2048
SCOPED_RECALL_CAP = 16
# Optional two-stage read-path experiment. Zero preserves text-first recall;
# a positive value first admits this many scoped rules using only work_kinds +
# applies_when, then body BM25+dense selects SCOPED_RECALL_CAP prompt entries.
SCOPED_ATTRIBUTE_POOL_CAP = int(os.environ.get(
    "MT_SCOPED_ATTRIBUTE_POOL_CAP", "0"))

# v1 pipeline knobs (design 2026-07-24 R5 — proposal defaults, single point).
# The two write channels batch independently: route A waits for enough
# screened statements to be worth a call, route B fires far sooner because a
# diff is scarce, already attributed, and stale feedback is worth less — the
# entry it judges may have moved on.
A_BATCH_N = 8             # extraction fires at N queued candidates...
B_BATCH_N = 3             # ...route B at three attributed diffs
BATCH_N = A_BATCH_N       # historical name for callers that know only route A
FLUSH_IDLE_S = 30 * 60    # ...or 30min after the oldest one, either channel
SALIENCE_MIN = 3          # extraction ops below this are dropped

# Route B sends the changed sentence as an apply_patch {old, new} hunk.
# Longer run-on sentences retain a symmetric 56-token window on each side:
# enough local syntax for attribution, with one threshold shared by code
# and tests. The prompt only sees old/new, not the token policy.
B_DIFF_SENTENCE_TOKENS = 128
B_DIFF_CONTEXT_TOKENS = 56
B_DIFF_CHANGE_TOKENS = 64
B_DIFF_MERGE_GAP_TOKENS = 3

# Raw-message views shown to generative calls. Over budget, both paths keep
# the beginning and end and mark the hidden middle with [truncated]. Route A
# is deliberately tight because up to A_BATCH_N messages share one call;
# translator gets a larger single-message window.
A_MESSAGE_MAX_TOKENS = 600
TRANSLATOR_MESSAGE_MAX_TOKENS = 4096
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

# Translator emits apply_patch hunks ({old, new}); the product splices them
# against the original request. Output is short by construction, so the
# budget is flat — no length routing between a full echo and a patch.
# Sixteen scoped entries plus the global lane make the per-entry verdict JSON
# materially larger than the former top-8 protocol.  Keep enough room for one
# evidence string per applied/already-satisfied entry and the patch hunks.
PATCH_OUTPUT_TOKENS = 2000

# Every product generative call is pinned to greedy decoding. anchor §5 ranks
# "predictable rewrite magnitude" above peak accuracy: the same request with
# the same store should produce the same rewrite, or the hotkey stops feeling
# like a tool and starts feeling like a dice roll. It also removes the
# dominant source of run-to-run noise in the write path (the SDK default is
# temperature 1.0, which was measured as the largest variance term in suite E).
GEN_TEMPERATURE = 0.0

# Async write-path budget switches. Tested 2026-07-31 under the owner's
# bar (+0.5 amortized calls must buy ≥0.1 owner-metric): three pooled
# 4-episode runs per arm, ~130 points each — ON scored 0.402/0.397 vs OFF
# 0.515/0.514, non-overlapping run ranges. The coverage recheck mostly
# re-admits ops the first pass had CORRECTLY ignored; behind the current
# gate stack the binding constraint is store churn, not under-extraction.
# Defaults stay OFF; the machinery and env switches remain for re-testing
# after the write path changes shape again.
WRITE_RECHECK = os.environ.get("MT_RECHECK", "0") == "1"
WRITE_VERIFY = os.environ.get("MT_VERIFY", "0") == "1"

# The rewrite is additive, so its length tracks the request's. A fixed cap
# truncates long pastes mid-payload and the hotkey silently does nothing;
# translate.output_budget() scales within these bounds. The ceiling exists so
# a pathological paste cannot bill an unbounded completion.
MIN_OUTPUT_TOKENS = 1024
MAX_OUTPUT_TOKENS = 8192
