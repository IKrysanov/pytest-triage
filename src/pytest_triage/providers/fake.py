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

"""Deterministic fakes (no network): references for tests and pipelines."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from pytest_triage.providers.base import BaseTriageClient
from pytest_triage.verdict import Category, Verdict

if TYPE_CHECKING:
    from pytest_triage.context import FailureContext

_RULES: dict[str, Category] = {
    "AssertionError": "test_bug",
    "ConnectionError": "env",
    "TimeoutError": "env",
    "OSError": "env",
}


class FakeTriageClient(BaseTriageClient):
    """Deterministic verdict keyed off the exception type. No network."""

    def analyze(self, ctx: FailureContext) -> Verdict:
        category = _RULES.get(ctx.exc_type or "", "regression")
        return Verdict(
            category=category,
            hypothesis=f"{ctx.exc_type or 'failure'} in {ctx.nodeid}",
            confidence="low",
        )


class OAuthFakeClient(BaseTriageClient):
    """Fake OAuth token with a TTL, refreshed lazily inside `analyze`. No network.

    Exists to probe whether the interface needs explicit lifecycle hooks: it does
    not. The token refreshes on the fly and `close` clears it. The clock is
    injectable so tests need not sleep.
    """

    def __init__(
        self, ttl: float = 2.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._ttl = ttl
        self._clock = clock
        self._token: str | None = None
        self._acquired_at = 0.0
        self.refresh_count = 0

    def analyze(self, ctx: FailureContext) -> Verdict:
        self._ensure_token()
        return Verdict(
            category="unknown",
            hypothesis=f"authenticated as {self._token}",
            confidence="low",
        )

    def close(self) -> None:
        self._token = None

    def _ensure_token(self) -> None:
        if self._token is None or self._clock() - self._acquired_at >= self._ttl:
            self.refresh_count += 1
            self._token = f"fake-token-{self.refresh_count}"
            self._acquired_at = self._clock()
