from __future__ import annotations

import time


_rate_state: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_ts)


def token_bucket_allow(key: str, refill_per_min: float, burst: float, cost: float = 1.0) -> bool:
    now = time.time()
    tokens, last = _rate_state.get(key, (burst, now))
    refill_per_sec = refill_per_min / 60.0
    tokens = min(burst, tokens + (now - last) * refill_per_sec)
    if tokens < cost:
        _rate_state[key] = (tokens, now)
        return False
    tokens -= cost
    _rate_state[key] = (tokens, now)
    return True

