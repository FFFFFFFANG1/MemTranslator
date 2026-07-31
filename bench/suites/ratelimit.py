"""AIMD token bucket for the judge channel.

Per-call backoff cannot protect a shared endpoint: when W workers each back
off independently, a 429 slows only the worker that saw it, so the aggregate
request rate drops by 1/W and the channel keeps tripping — the mechanism's
effectiveness falls exactly as concurrency rises. parallel.py already recorded
the motivating fact: the judge channel returned 429 at SERIAL pace.

One process-wide bucket in front of every judge call fixes the aggregate rate
directly. AIMD (halve on 429, creep up on success) converges on whatever the
channel actually sustains without hardcoding a number that would rot when the
provider changes limits.
"""
import threading
import time


class AIMDBucket:
    def __init__(self, rate: float = 3.0, burst: float = 6.0,
                 floor: float = 0.25, ceiling: float = 12.0):
        self.rate = rate                  # tokens (requests) per second
        self.burst = burst
        self.floor, self.ceiling = floor, ceiling
        self._tokens = burst
        self._last = time.monotonic()
        self._lock = threading.Lock()
        self._successes = 0
        self.rate_limits_seen = 0         # snapshot telemetry

    def acquire(self) -> None:
        """Block until a token is available."""
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(self.burst,
                                   self._tokens + (now - self._last) * self.rate)
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self.rate
            time.sleep(wait)

    def on_success(self) -> None:
        """Additive increase: +0.1 req/s every 20 clean calls."""
        with self._lock:
            self._successes += 1
            if self._successes >= 20:
                self._successes = 0
                self.rate = min(self.ceiling, self.rate + 0.1)

    def on_rate_limit(self) -> None:
        """Multiplicative decrease, and drain the bucket so the next call
        waits a full token instead of riding the burst."""
        with self._lock:
            self.rate = max(self.floor, self.rate / 2)
            self._tokens = 0.0
            self._successes = 0
            self.rate_limits_seen += 1


# One bucket per channel, process-wide. The judge channel is the measured
# bottleneck; the product channel has not tripped and gets no bucket yet.
JUDGE_BUCKET = AIMDBucket()


class CrossProcessSpacer:
    """Global minimum spacing between judge calls ACROSS processes.

    The AIMD bucket above is process-wide only; N parallel runner processes
    each carry their own bucket, so the aggregate rate scales with N and the
    channel trips collectively (measured 2026-07-31: six concurrent episode
    runs killed every sibling with judge 429s after per-process retries were
    exhausted). A file-lock timestamp gives all processes one shared clock:
    each call waits until at least `min_interval` has passed since ANY
    process's last call. flock is advisory but every caller goes through
    this class, and a crashed holder releases the lock with its fd."""

    def __init__(self, path: str, min_interval: float):
        self.path = path
        self.min_interval = min_interval

    def acquire(self) -> None:
        import fcntl
        import os
        with open(self.path, "a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                st = os.fstat(f.fileno())
                wait = self.min_interval - (time.time() - st.st_mtime)
                if wait > 0:
                    time.sleep(wait)
                os.utime(self.path, None)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)


# 150ms global spacing ≈ 6-7 judge QPS total, regardless of process count —
# roughly what one 4-worker process generated when the channel was healthy.
JUDGE_SPACER = CrossProcessSpacer("/tmp/memtranslator-judge.lock", 0.15)
