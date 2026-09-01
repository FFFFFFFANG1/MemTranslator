"""Performance suite — thin entry into the fused E1+perf lifecycle run.

One chained write pass yields owner metrics (per-task / per-memory) and the
scale/safety instruments (canary carry@alive, spurious kills, noop, latency).
Prefer ``python -m bench.suites.run_episodes --episodes …`` for the full
flag surface; this module keeps the historical ``python -m bench.perf``
command.

    uv run python -m bench.perf --episodes e-01,e-03,e-05,e-09
"""
from bench.suites.run_episodes import main as lifecycle_main


def main():
    import sys
    # Historical defaults: multi-episode, real arm only, canary on, size buckets.
    argv = sys.argv[1:]
    if not any(a == "--episodes" or a.startswith("--episodes=") for a in argv):
        argv = ["--episodes", "e-01,e-03,e-05,e-09", *argv]
    if not any(a == "--arms" or a.startswith("--arms=") for a in argv):
        argv = ["--arms", "real", *argv]
    if "--no-canary" not in argv and "--canary" not in argv:
        argv = ["--canary", *argv]
    if not any(a == "--sizes" or a.startswith("--sizes=") for a in argv):
        argv = ["--sizes", "4,8,16,24,32", *argv]
    lifecycle_main(argv)


if __name__ == "__main__":
    main()
