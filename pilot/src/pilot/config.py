"""Single point of definition for models, paths, and constants (pilot plan §1.4).

Everything cost- or reproducibility-sensitive lives here; no other module
hardcodes a model ID or a data path.
"""

from __future__ import annotations

from pathlib import Path

PILOT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA = PILOT_ROOT / "data"
DATA_RAW = DATA / "raw"
INSTANCES = DATA / "instances"
RUNS = PILOT_ROOT / "runs"
CACHE_DIR = RUNS / "llm_cache"
RESULTS = RUNS / "results"

PREFEVAL_DIR = DATA_RAW / "PrefEval" / "benchmark_dataset" / "explicit_preference"
LONGMEMEVAL_ORACLE = DATA_RAW / "LongMemEval" / "data" / "longmemeval_oracle.json"

# --- models (pilot plan §1.4) ---
MODELS = {
    "downstream_strong": "claude-opus-4-8",
    "downstream_weak": "claude-haiku-4-5",
    "translator": "claude-haiku-4-5",
    "judge": "claude-opus-4-8",
}
DOWNSTREAM_TIERS = ["downstream_strong", "downstream_weak"]

# --- arms ---
ARMS = ["A0_none", "A1_system", "A2_inject", "A3_translator"]
BASELINE_ARMS = ["B1_mem0", "B2_graphiti"]  # opt-in via --with-baselines

# --- baseline internals (frozen in docs/baseline-b0-memo.md) ---
MEM0_INTERNAL_LLM = "claude-haiku-4-5-20251001"   # anthropic provider works
GRAPHITI_INTERNAL_LLM = "gpt-4.1-mini"             # anthropic client trial pending (B1)
EMBEDDING_MODEL = "text-embedding-3-small"         # openai, used by both baselines

# --- experiment shape (pilot plan §1.3) ---
N_POS = 150
N_NEG = 100
N_LONGDOC = 30
K_DISTRACTORS = 7            # store size = K_DISTRACTORS + 1
MEMORY_STORE_SIZE = K_DISTRACTORS + 1
RECALL_K = 8

SEED = 20260721
