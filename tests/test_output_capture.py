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

"""End to end: stdout, stderr and logging reach the report, redacted."""

from __future__ import annotations

import json

import pytest

from tests.support import run_triage


def test_all_output_streams_are_captured_redacted_and_reported(
    pytester: pytest.Pytester,
) -> None:
    report = pytester.path / "triage.json"
    pytester.makepyfile(
        test_output="""
        import logging
        import sys

        def test_boom():
            print("checkout stdout sk-live0000000000000000abcd")
            print("checkout stderr glpat-00000000000000000000", file=sys.stderr)
            logging.getLogger("srv").error(
                "db auth failed ghp_000000000000000000000000000000000000"
            )
            assert False
        """
    )
    _, result = run_triage(pytester, f"--ai-report={report}")
    result.assert_outcomes(failed=1)

    row = json.loads(report.read_text(encoding="utf-8"))["failures"][0]
    # every stream reached the report
    assert "checkout stdout" in row["stdout_tail"]
    assert "checkout stderr" in row["stderr_tail"]
    assert "db auth failed" in row["log_tail"]
    # and every secret was scrubbed on the way (strict is the default)
    assert "sk-live" not in row["stdout_tail"]
    assert "glpat-" not in row["stderr_tail"]
    assert "ghp_" not in row["log_tail"]
    assert "[REDACTED]" in row["stdout_tail"]


def test_logging_is_not_redacted_when_redaction_is_off(
    pytester: pytest.Pytester,
) -> None:
    report = pytester.path / "triage.json"
    pytester.makepyfile(
        test_output="""
        import logging

        def test_boom():
            logging.getLogger("srv").warning("cache miss for key user:42")
            assert False
        """
    )
    _, result = run_triage(pytester, f"--ai-report={report}", "--ai-redact=off")
    result.assert_outcomes(failed=1)

    row = json.loads(report.read_text(encoding="utf-8"))["failures"][0]
    assert "cache miss for key user:42" in row["log_tail"]
