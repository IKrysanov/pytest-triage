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

"""JSON failure-report artifact: schema, serialization, and atomic writing."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_triage.config import Config
    from pytest_triage.context import FailureContext

# Versioned from day one; evolve additively only.
SCHEMA_VERSION = 1


def build_report(failures: list[FailureContext]) -> dict[str, Any]:
    """Assemble the machine-readable report payload."""
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        # Ready-to-run selectors that rerun every failure in one command.
        "pytest_args": _dedup([failure.nodeid for failure in failures]),
        "failures": [_failure_to_dict(failure) for failure in failures],
    }


def write_report(path: Path, failures: list[FailureContext]) -> None:
    """Serialize the report and write it atomically (temp file + os.replace).

    The file is created owner-only (0o600 on POSIX): even after redaction it may
    hold residual sensitive output and must not be world-readable on a shared CI
    host.
    """
    text = json.dumps(build_report(failures), indent=2, ensure_ascii=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


def _failure_to_dict(failure: FailureContext) -> dict[str, Any]:
    return {
        "nodeid": failure.nodeid,
        "pytest_args": [failure.nodeid],
        "phase": failure.phase,
        "outcome": failure.outcome,
        "exc_type": failure.exc_type,
        "exc_message": failure.exc_message,
        "traceback": failure.traceback,
        "duration": failure.duration,
        "stdout_tail": failure.stdout_tail,
        "stderr_tail": failure.stderr_tail,
        # Filled by the triage layer in a later milestone; null until then.
        "verdict": None,
    }


def _dedup(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


class _ReportWriter:
    """Private: writes the JSON report when `--ai-report` is set.

    Implements the internal `pytest_triage_report` hook. A write failure must
    never change the run's outcome (invariant 1), so all errors are swallowed
    with a warning to stderr.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def pytest_triage_report(
        self, failures: list[FailureContext], triage_config: Config
    ) -> None:
        try:
            write_report(self._path, failures)
        except Exception as exc:  # never let reporting affect the test run
            print(
                f"pytest-triage: failed to write report to {self._path}: {exc}",
                file=sys.stderr,
            )
