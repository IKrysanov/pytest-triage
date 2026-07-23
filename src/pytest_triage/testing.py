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

"""Public conformance kit for TriageClient provider authors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pytest_triage.context import FailureContext
from pytest_triage.verdict import CATEGORIES, CONFIDENCES, Verdict

if TYPE_CHECKING:
    from pytest_triage.providers.base import TriageClient


def assert_conforms(client: TriageClient) -> None:
    """Assert a TriageClient satisfies the pytest-triage provider contract.

    Call it against a fresh client: `analyze` must return a flat, valid Verdict
    for both a normal and a degenerate FailureContext, and `close` must be safe
    to call.
    """
    for ctx in (_sample_context(), _degenerate_context()):
        verdict = client.analyze(ctx)
        assert isinstance(verdict, Verdict), "analyze must return a Verdict"
        assert verdict.category in CATEGORIES, f"bad category: {verdict.category!r}"
        assert verdict.confidence in CONFIDENCES, (
            f"bad confidence: {verdict.confidence!r}"
        )
        assert isinstance(verdict.hypothesis, str), "hypothesis must be a string"
        assert verdict.suggested_fix is None or isinstance(verdict.suggested_fix, str)
    client.close()


def _sample_context() -> FailureContext:
    return FailureContext(
        nodeid="tests/test_login.py::test_ok",
        phase="call",
        outcome="failed",
        exc_type="AssertionError",
        exc_message="assert 401 == 200",
        traceback="assert 401 == 200",
        duration=0.01,
    )


def _degenerate_context() -> FailureContext:
    return FailureContext(nodeid="", phase="call", outcome="failed")
