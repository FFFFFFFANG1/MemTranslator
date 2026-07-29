"""Bench-side config. The judge is NOT a product path, so anchor §5's
flash-only rule does not apply; per the 2026-07-24 sign-off it runs on
deepseek-v4-pro over the OpenAI-compatible channel configured in the
repo-root .env (currently Volcano Ark; swap channel or model here)."""
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
METRIC_VERSION = 3


def _load_env(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE reader for the repo-root .env; os.environ wins."""
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    for k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        if k in os.environ:
            out[k] = os.environ[k]
    return out


_ENV = _load_env(REPO_ROOT / ".env")
LLM_BASE_URL = _ENV.get("LLM_BASE_URL", "https://api.deepseek.com")
LLM_API_KEY = _ENV.get("LLM_API_KEY", os.environ.get("DEEPSEEK_API_KEY", ""))

JUDGE_MODEL = "deepseek-v4-pro"      # 拍板点 2 决议（2026-07-24）
GEN_MODEL = "deepseek-v4-flash"      # case 扩展生成用（同通道）
JUDGE_MAX_TOKENS = 300
E2E_SECOND_HALF_FROM = 9             # rounds 9..16 count toward the score
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
