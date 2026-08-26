"""Bench-side config. The judge is NOT a product path, so anchor §5's
flash-only rule does not apply. It runs over the OpenAI-compatible channel
configured in the repo-root .env (currently Volcano Ark); JUDGE_MODEL may
override the audited default."""
import os
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BENCH_ROOT.parent
CASES = BENCH_ROOT / "cases"
RESULTS = BENCH_ROOT / "results"

# High-frequency run state (checkpoints, per-shard stores) lives OUTSIDE the
# repo. The repo once sat in an iCloud directory that silently hid files
# (config history records it), and hundreds of small appended files do not
# belong in a synced tree in any case. Snapshots still land in RESULTS.
import tempfile  # noqa: E402  (kept local to this block on purpose)

RUN_DIR = Path(os.environ.get("BENCH_RUN_DIR")
               or Path(tempfile.gettempdir()) / "memtranslator-bench")

# Version of the scoring semantics. Bumped whenever a change makes numbers
# incomparable with previous snapshots (e.g. v2: suite headline became
# min(micro, macro) and shard-completeness gating landed; v3: T's
# AUTO_NO_INVENTION went ternary per the 2026-07-29 owner ruling — entailed
# specialization of a stored requirement now passes, so v2 T scores read
# strictly lower on the same behavior). The gate refuses to aggregate
# snapshots whose metric_version differs from the current one.
METRIC_VERSION = 12  # E1 applicability pairs + oracle attributes audited


def _load_env(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE reader for the repo-root .env; os.environ wins."""
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    for k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "JUDGE_MODEL",
              "STATE_JUDGE_MODEL"):
        if k in os.environ:
            out[k] = os.environ[k]
    return out


_ENV = _load_env(REPO_ROOT / ".env")
LLM_BASE_URL = _ENV.get("LLM_BASE_URL", "https://api.deepseek.com")
LLM_API_KEY = _ENV.get("LLM_API_KEY", os.environ.get("DEEPSEEK_API_KEY", ""))

JUDGE_MODEL = _ENV.get("JUDGE_MODEL", "glm-5.3")
GEN_MODEL = "deepseek-v4-flash"      # case 扩展生成用（同通道）
# GLM-5.x spends completion tokens on mandatory reasoning before its short
# JSON answer. Full oracle-v4 runs produced 13 empty finals at 2048 and 10 at
# 4096 among roughly 110 CARRY pairs. 8192 plus one parse retry in judge.py
# substantially reduces mandatory-thinking truncation while keeping any
# residual parse failures visible in the snapshot.
JUDGE_MAX_TOKENS = (8192 if JUDGE_MODEL.lower().startswith("glm-5") else 300)
STATE_JUDGE_MODEL = _ENV.get("STATE_JUDGE_MODEL", "deepseek-v4-pro")
STATE_JUDGE_MAX_TOKENS = (
    2048 if STATE_JUDGE_MODEL.lower().startswith("glm-5") else 300)
E2E_SEED_ROUNDS = 5                  # first N finals absorbed as message history
E2E_SECOND_HALF_FROM = 6             # rounds 6..16 count toward the score
E2E_PASS_THRESHOLD = 0.8             # persona-level pass, now REPORTING ONLY
E2E_PERSONA_COUNT = 8                # nominal suite size; fewer = hard error
E2E_REPEATS = 3                      # runs averaged per persona (variance control)
                                     # (iCloud can transiently hide a file —
                                     # a silently smaller suite skews scores)
# Owner ruling 2026-07-28: no weighted overall, no gate verdict. Suites
# report their own numbers and decisions read the parts. The old constants
# (GATE_OVERALL 0.80 / GATE_PER_SUITE 0.70 / WEIGHTS {T .4, L .3, E .3})
# are retired with the ruling recorded here so nobody reinvents them from
# git history without seeing why they left.
