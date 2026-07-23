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

"""Collection: FailureContext captured from a real failing run."""

from __future__ import annotations

import pytest

from tests.support import run_triage


def test_collects_only_failures(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        def test_ok():
            assert True

        def test_boom():
            value = 41
            assert value == 42
        """
    )
    spy, result = run_triage(pytester, "--ai-redact=off")
    result.assert_outcomes(passed=1, failed=1)

    assert len(spy.failures) == 1
    ctx = spy.failures[0]
    assert ctx.nodeid.endswith("::test_boom")
    assert ctx.phase == "call"
    assert ctx.outcome == "failed"
    assert ctx.exc_type == "AssertionError"
    assert ctx.duration >= 0.0
    assert "assert" in ctx.traceback

    print("\n--- collected FailureContext (visible under -s) ---")
    print(ctx)


def test_captures_message_and_output(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        def test_boom():
            print("MARKER_OUT")
            raise ValueError("explicit message")
        """
    )
    spy, _ = run_triage(pytester, "--ai-redact=off")

    assert len(spy.failures) == 1
    ctx = spy.failures[0]
    assert ctx.exc_type == "ValueError"
    assert ctx.exc_message == "explicit message"
    assert "MARKER_OUT" in ctx.stdout_tail
