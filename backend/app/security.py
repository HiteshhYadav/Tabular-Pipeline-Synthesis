"""Access tokens and per-client rate limits.

Not prompt surface.

Two FastAPI dependencies, applied in the router layer:

  require_token  When API_TOKENS is set, every dataset route needs
                 `Authorization: Bearer <token>`. When it is not set the app
                 is open, which config.py permits only for
                 DEPLOYMENT_ENV=local. /health is never protected, because
                 the frontend reads it to learn whether to ask for a token.

  limit(bucket)  A sliding-window budget per client per bucket. The client is
                 the token when there is one - so a team sharing one office
                 IP is not one client - and the peer IP otherwise.

What this is not: user accounts, per-user data isolation, or a substitute for
TLS. A token holder can read any dataset id they learn. Tokens are compared in
constant time and never logged or echoed back.

The limiter is in-process memory, which is correct for the single-worker
deployment this app runs as and resets on restart. Several workers behind a
load balancer would each keep their own windows; that deployment would need a
shared store, and is out of scope with the rest of multi-node operation.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Request

from app.config import settings
from app.errors import AppError, ErrorCode


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def _token_matches(presented: str, tokens: list[str]) -> bool:
    # Compared against every configured token, not short-circuited on the
    # first match, so timing does not reveal which slot a token occupies.
    matched = False
    for token in tokens:
        matched |= hmac.compare_digest(presented.encode(), token.encode())
    return matched


def require_token(request: Request) -> None:
    """Router dependency. A no-op when no tokens are configured."""
    tokens = settings.api_token_list
    if not tokens:
        return
    presented = _bearer(request)
    if presented is None or not _token_matches(presented, tokens):
        raise AppError(
            ErrorCode.UNAUTHORIZED,
            "This server requires an access token. Enter the token your "
            "administrator gave you."
            if presented is None
            else "That access token is not valid for this server.",
        )


def client_key(request: Request) -> str:
    """Who a request counts against. A hash, so raw tokens are never held as
    dictionary keys in a long-lived process."""
    presented = _bearer(request)
    if presented is not None and settings.api_token_list:
        return "token:" + hashlib.sha256(presented.encode()).hexdigest()[:16]
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


@dataclass(frozen=True)
class Budget:
    limit: int
    window_s: int
    describe: str


def _budgets() -> dict[str, Budget]:
    """Read from settings on each call so a test or an operator changing the
    numbers takes effect without rebuilding the limiter."""
    return {
        "generate": Budget(
            settings.rate_limit_generations_per_hour, 3600, "pipeline generations per hour"
        ),
        "upload": Budget(settings.rate_limit_uploads_per_hour, 3600, "uploads per hour"),
        "execute": Budget(
            settings.rate_limit_executions_per_hour, 3600, "pipeline runs per hour"
        ),
        "default": Budget(settings.rate_limit_requests_per_minute, 60, "requests per minute"),
    }


class RateLimiter:
    """Sliding-window counters keyed by (client, bucket).

    One instance per app, held on app.state, so every TestClient starts with
    clean windows rather than sharing a process-wide counter across tests.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def hit(self, client: str, bucket: str) -> None:
        budget = _budgets()[bucket]
        now = self._clock()
        with self._lock:
            hits = self._hits[(client, bucket)]
            while hits and hits[0] <= now - budget.window_s:
                hits.popleft()
            if len(hits) >= budget.limit:
                retry_after = max(1, math.ceil(hits[0] + budget.window_s - now))
                raise AppError(
                    ErrorCode.RATE_LIMITED,
                    f"Too many requests: the limit is {budget.limit} {budget.describe}. "
                    f"Try again in {retry_after} seconds.",
                    {"bucket": bucket, "retry_after_s": str(retry_after)},
                )
            hits.append(now)


def limit(bucket: str) -> Callable[[Request], None]:
    """Route dependency charging one request to `bucket`."""

    def dependency(request: Request) -> None:
        limiter: RateLimiter = request.app.state.rate_limiter
        limiter.hit(client_key(request), bucket)

    dependency.__name__ = f"rate_limit_{bucket}"
    return dependency
