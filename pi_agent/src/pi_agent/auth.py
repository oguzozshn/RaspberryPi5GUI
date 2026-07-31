from __future__ import annotations

import hmac
import time
from collections import defaultdict

from pi_agent.config import AgentConfig

_FAILURE_WINDOW_SECONDS = 30
_MAX_FAILURES = 5

_failures: dict[str, list[float]] = defaultdict(list)


def token_matches(config: AgentConfig, candidate: str) -> bool:
    return hmac.compare_digest(config.auth.token, candidate)


def is_rate_limited(source_ip: str) -> bool:
    now = time.time()
    recent = [t for t in _failures[source_ip] if now - t < _FAILURE_WINDOW_SECONDS]
    _failures[source_ip] = recent
    return len(recent) >= _MAX_FAILURES


def record_failure(source_ip: str) -> None:
    _failures[source_ip].append(time.time())
