# Copyright 2026 the pytest-triage contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Cross-cutting decorators over TriageClient: budget, breaker, cache, timeout.

A third-party provider (~80 lines of transport) gets all of them for free by
being wrapped here. Composition order is
Caching(CircuitBreaker(Budgeted(TimedOut(provider)))): cache hits cost neither
budget nor time, and a tripped breaker costs neither either.
"""

from __future__ import annotations

import hashlib
import re
import threading
from typing import TYPE_CHECKING

from pytest_triage.redact import redact
from pytest_triage.registry import resolve_provider
from pytest_triage.verdict import Verdict

if TYPE_CHECKING:
    from pytest_triage.config import Config
    from pytest_triage.context import FailureContext
    from pytest_triage.providers.base import TriageClient

# Stable prefixes stamped on a degraded verdict's hypothesis so both the report
# and the terminal can explain why triage did not produce a real verdict.
_PROVIDER_ERROR = "triage provider error"
_TIMEOUT_REASON = "triage timed out"
_BUDGET_REASON = "triage budget exhausted"
_BREAKER_REASON = "triage stopped: the provider kept failing"
_MAX_ERROR_DETAIL = 200

# A provider that is down stays down for the rest of a run. Without a breaker a
# 30 s timeout times a 10-call budget is five minutes of a hung suite, with up
# to ten abandoned requests still being billed. One timeout, or two consecutive
# errors, is enough evidence to stop paying for the rest.
_MAX_CONSECUTIVE_ERRORS = 2


def _unknown(reason: str) -> Verdict:
    return Verdict(category="unknown", hypothesis=reason, confidence="low")


def _provider_error(exc: Exception) -> Verdict:
    # Surface the actual cause (a bad API key raises here) instead of a silent
    # unknown. Redacted and capped: a provider's message may carry a secret.
    detail = redact(f"{type(exc).__name__}: {exc}").strip()
    if len(detail) > _MAX_ERROR_DETAIL:
        detail = detail[:_MAX_ERROR_DETAIL] + "..."
    return _unknown(f"{_PROVIDER_ERROR}: {detail}")


def degraded_reason(verdict: Verdict) -> str | None:
    """Why triage could not produce a real verdict, or None if it did.

    Budget exhaustion is an expected, configured limit, not an error to surface.
    """
    hypothesis = verdict.hypothesis
    if verdict.category == "unknown" and (
        hypothesis.startswith(_PROVIDER_ERROR)
        or hypothesis in (_TIMEOUT_REASON, _BREAKER_REASON)
    ):
        return hypothesis
    return None


class TimedOutClient:
    """Hard wall-clock cap. A slow or raising provider never breaks the run."""

    def __init__(self, inner: TriageClient, timeout: float) -> None:
        self._inner = inner
        self._timeout = timeout

    def analyze(self, ctx: FailureContext) -> Verdict:
        result: list[Verdict] = []

        def _run() -> None:
            try:
                result.append(self._inner.analyze(ctx))
            except Exception as exc:  # invariant 1: never propagate; surface it
                result.append(_provider_error(exc))

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(self._timeout)
        if thread.is_alive():  # abandoned; a daemon thread won't block exit
            return _unknown(_TIMEOUT_REASON)
        return result[0]

    def close(self) -> None:
        self._inner.close()


class BudgetedClient:
    """Cap the number of provider calls per run. `calls` is what was spent."""

    def __init__(self, inner: TriageClient, budget: int) -> None:
        self._inner = inner
        self._remaining = budget
        self.calls = 0

    def analyze(self, ctx: FailureContext) -> Verdict:
        if self._remaining <= 0:
            return _unknown(_BUDGET_REASON)
        self._remaining -= 1
        self.calls += 1
        return self._inner.analyze(ctx)

    def close(self) -> None:
        self._inner.close()


class CircuitBreakerClient:
    """Stop calling a provider that has proven it is not going to answer.

    Trips on the first timeout, or on `_MAX_CONSECUTIVE_ERRORS` errors in a row.
    Sits above the budget so a tripped breaker spends nothing at all.
    """

    def __init__(self, inner: TriageClient) -> None:
        self._inner = inner
        self._consecutive_errors = 0
        self.tripped = False

    def analyze(self, ctx: FailureContext) -> Verdict:
        if self.tripped:
            return _unknown(_BREAKER_REASON)
        verdict = self._inner.analyze(ctx)
        if verdict.hypothesis == _TIMEOUT_REASON:
            self.tripped = True  # a hung provider costs the full cap every call
        elif verdict.hypothesis.startswith(_PROVIDER_ERROR):
            self._consecutive_errors += 1
            self.tripped = self._consecutive_errors >= _MAX_CONSECUTIVE_ERRORS
        else:
            self._consecutive_errors = 0
        return verdict

    def close(self) -> None:
        self._inner.close()


class CachingClient:
    """Deduplicate identical failures; in-memory for one run. `hits` counts the
    calls it saved."""

    def __init__(self, inner: TriageClient) -> None:
        self._inner = inner
        self._cache: dict[str, Verdict] = {}
        self.hits = 0

    def analyze(self, ctx: FailureContext) -> Verdict:
        key = _cache_key(ctx)
        cached = self._cache.get(key)
        if cached is not None:
            self.hits += 1
            return cached
        verdict = self._inner.analyze(ctx)
        self._cache[key] = verdict
        return verdict

    def close(self) -> None:
        self._inner.close()


_HEX = re.compile(r"0x[0-9a-fA-F]+")
_WHITESPACE = re.compile(r"\s+")


def _cache_key(ctx: FailureContext) -> str:
    # Normalize away volatile bits so identical failures share a verdict.
    normalized = _WHITESPACE.sub(" ", _HEX.sub("0xADDR", ctx.traceback)).strip()
    # A failure can arrive without a traceback (a broken longrepr, redaction
    # that scrubbed everything). Falling back to the nodeid keeps distinct
    # failures apart instead of collapsing them all onto one verdict.
    identity = normalized or f"{ctx.nodeid}\n{ctx.exc_message or ''}"
    payload = f"{ctx.exc_type or ''}\n{identity}"
    return hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()


def call_stats(client: TriageClient) -> tuple[int, int]:
    """(provider calls spent, verdicts served from cache) over a wrapper chain.

    Walks the decorators built by `build_triage_client`; zeros for a bare
    provider. What a run actually cost, for the terminal summary.
    """
    calls = hits = 0
    node: object | None = client
    while node is not None:
        if isinstance(node, BudgetedClient):
            calls = node.calls
        elif isinstance(node, CachingClient):
            hits = node.hits
        node = getattr(node, "_inner", None)
    return calls, hits


def build_triage_client(config: Config) -> TriageClient | None:
    """Resolve the provider and wrap it, or None when triage is off.

    Raises a clear error (from the registry) if the provider cannot be resolved
    or built; the caller decides whether that disables triage or aborts.
    """
    if not config.triage or config.provider is None:
        return None
    provider = resolve_provider(config.provider)()
    return CachingClient(
        CircuitBreakerClient(
            BudgetedClient(TimedOutClient(provider, config.timeout), config.budget)
        )
    )
