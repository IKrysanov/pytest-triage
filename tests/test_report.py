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

"""JSON report artifact: schema validity, rerun fidelity, and write safety."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest

from pytest_triage.config import Config
from pytest_triage.context import FailureContext
from pytest_triage.report import _ReportWriter, build_report, write_report

if TYPE_CHECKING:
    from pathlib import Path


def test_build_report_shape_and_dedup() -> None:
    fc = FailureContext(
        nodeid="t.py::a",
        phase="call",
        outcome="failed",
        exc_type="ValueError",
        exc_message="x",
        traceback="tb",
        duration=0.1,
    )
    report = build_report([fc, fc])  # same nodeid twice
    assert report["schema_version"] == 1
    assert report["created_at"].endswith("Z")
    assert report["pytest_args"] == ["t.py::a"]  # deduped
    assert len(report["failures"]) == 2
    first = report["failures"][0]
    assert first["nodeid"] == "t.py::a"
    assert first["pytest_args"] == ["t.py::a"]
    assert first["exc_type"] == "ValueError"
    assert first["verdict"] is None


def test_write_report_is_atomic_and_creates_parents(tmp_path: Path) -> None:
    fc = FailureContext(nodeid="t.py::a", phase="call", outcome="failed")
    path = tmp_path / "nested" / "report.json"  # parent does not exist yet
    write_report(path, [fc])
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert list(tmp_path.glob("**/*.tmp")) == []  # temp file replaced, not left


def test_report_writer_swallows_write_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file", encoding="utf-8")
    # The target's parent is a regular file, so mkdir/write fails.
    writer = _ReportWriter(blocker / "report.json")
    writer.pytest_triage_report(failures=[], triage_config=Config())  # must not raise
    assert "failed to write report" in capsys.readouterr().err


def test_report_written_and_valid(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        def test_pass():
            assert True

        def test_fail():
            assert 1 == 2
        """
    )
    result = pytester.runpytest_inprocess("--ai-report=report.json")
    result.assert_outcomes(passed=1, failed=1)

    data = json.loads((pytester.path / "report.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert len(data["failures"]) == 1
    failure = data["failures"][0]
    assert failure["nodeid"].endswith("::test_fail")
    assert failure["verdict"] is None
    assert data["pytest_args"] == [failure["nodeid"]]


def test_pytest_args_rerun_exactly_the_failures(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        def test_a():
            assert True

        def test_b():
            assert False

        def test_c():
            assert True

        def test_d():
            raise ValueError("boom")
        """
    )
    pytester.runpytest_inprocess("--ai-report=report.json")
    data = json.loads((pytester.path / "report.json").read_text(encoding="utf-8"))
    rerun_args = data["pytest_args"]
    assert len(rerun_args) == 2

    result = pytester.runpytest_inprocess(*rerun_args)
    outcomes = result.parseoutcomes()
    assert outcomes.get("failed") == 2
    assert outcomes.get("passed", 0) == 0  # only the two failures reran


@pytest.mark.skipif(os.name != "posix", reason="POSIX file mode")
def test_report_file_is_owner_only(tmp_path: Path) -> None:
    fc = FailureContext(nodeid="t.py::a", phase="call", outcome="failed")
    path = tmp_path / "report.json"
    write_report(path, [fc])
    assert (path.stat().st_mode & 0o777) == 0o600
