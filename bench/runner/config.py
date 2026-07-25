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
GATE_OVERALL = 0.80
GATE_PER_SUITE = 0.70                # 拍板点 1 决议：加下限
WEIGHTS = {"T": 0.4, "L": 0.3, "E": 0.3}
