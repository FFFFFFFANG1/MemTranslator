"""Single point of definition for models, paths, and constants (pilot plan §1.4).

Everything cost- or reproducibility-sensitive lives here; no other module
hardcodes a model ID or a data path.
"""

from __future__ import annotations

from pathlib import Path

PILOT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_RAW = PILOT_ROOT / "data" / "raw"
DATA_INSTANCES = PILOT_ROOT / "data" / "instances"
RUNS = PILOT_ROOT / "runs"

PREFEVAL_DIR = DATA_RAW / "PrefEval" / "benchmark_dataset" / "explicit_preference"
LONGMEMEVAL_ORACLE = DATA_RAW / "LongMemEval" / "data" / "longmemeval_oracle.json"

# --- models (pilot plan §1.4) ---
DOWNSTREAM_STRONG = "claude-opus-4-8"
DOWNSTREAM_WEAK = "claude-haiku-4-5"
TRANSLATOR_MODEL = "claude-haiku-4-5"
JUDGE_MODEL = "claude-opus-4-8"

# --- baseline internals (B0 memo: config definitively smoked) ---
MEM0_INTERNAL_LLM = "claude-haiku-4-5-20251001"   # anthropic provider works
GRAPHITI_INTERNAL_LLM = "gpt-4.1-mini"             # anthropic client trial pending (B1)
EMBEDDING_MODEL = "text-embedding-3-small"         # openai, used by both baselines

# --- experiment shape (pilot plan §1.3) ---
N_POSITIVE = 150
N_NEGATIVE = 100
N_LONGDOC = 30
MEMORY_STORE_SIZE = 8   # entries visible per instance (top-k for injection arms)
RECALL_K = 8

SEED = 20260721
