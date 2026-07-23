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

"""Test support: capture the internal pytest_triage_report hook payload."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_triage.context import FailureContext

if TYPE_CHECKING:
    from _pytest.pytester import Pytester, RunResult

    from pytest_triage.config import Config
    from pytest_triage.verdict import Verdict


class TriageSpy:
    """Records the failures, verdicts, and config handed to the report hook."""

    def __init__(self) -> None:
        self.failures: list[FailureContext] = []
        self.verdicts: list[Verdict | None] = []
        self.triage_config: Config | None = None

    @pytest.hookimpl(optionalhook=True)
    def pytest_triage_report(
        self,
        failures: list[FailureContext],
        verdicts: list[Verdict | None],
        triage_config: Config,
    ) -> None:
        self.failures = list(failures)
        self.verdicts = list(verdicts)
        self.triage_config = triage_config


def run_triage(pytester: Pytester, *args: str) -> tuple[TriageSpy, RunResult]:
    """Run pytester in-process with a spy attached; return (spy, result).

    Collection is scoped to the pytester tmp dir so an inprocess run can never
    pick up the outer project's own tests (rootdir / testpaths inheritance).
    """
    spy = TriageSpy()
    result = pytester.runpytest_inprocess(str(pytester.path), *args, plugins=[spy])
    return spy, result
