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

"""pytest-triage plugin: option registration, hooks, and failure collection."""

from __future__ import annotations

import pytest

from pytest_triage import _hookspecs
from pytest_triage.config import Config
from pytest_triage.context import FailureContext, build_context, safe_message


def pytest_addhooks(pluginmanager: pytest.PytestPluginManager) -> None:
    pluginmanager.add_hookspecs(_hookspecs)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("pytest-triage", "AI failure triage")
    group.addoption(
        "--ai-triage",
        dest="ai_triage",
        choices=("off", "on"),
        default=None,
        help="Enable AI triage of failures (default: off).",
    )
    parser.addini("ai_triage", "Enable AI triage of failures (off|on).", default="off")
    group.addoption(
        "--ai-report",
        dest="ai_report",
        metavar="PATH",
        default=None,
        help="Write the machine-readable failure report to PATH.",
    )
    parser.addini(
        "ai_report", "Path for the machine-readable failure report.", default=""
    )
    group.addoption(
        "--ai-provider",
        dest="ai_provider",
        metavar="NAME",
        default=None,
        help="Triage provider name or import string.",
    )
    parser.addini("ai_provider", "Triage provider name or import string.", default="")
    group.addoption(
        "--ai-budget",
        dest="ai_budget",
        metavar="N",
        type=int,
        default=None,
        help="Max triage calls per run (default: 10).",
    )
    parser.addini("ai_budget", "Max triage calls per run.", default="10")
    group.addoption(
        "--ai-timeout",
        dest="ai_timeout",
        metavar="SEC",
        type=float,
        default=None,
        help="Wall-clock cap for triage in seconds (default: 30).",
    )
    parser.addini("ai_timeout", "Wall-clock cap for triage in seconds.", default="30")
    group.addoption(
        "--ai-redact",
        dest="ai_redact",
        choices=("strict", "off"),
        default=None,
        help="Secret redaction mode (default: strict).",
    )
    parser.addini("ai_redact", "Secret redaction mode (strict|off).", default="strict")


def pytest_configure(config: pytest.Config) -> None:
    plugin = _TriagePlugin(Config.from_config(config))
    config.pluginmanager.register(plugin, name="pytest_triage_run")


class _TriagePlugin:
    """Private: per-run collector. Holds all mutable state (no module globals).

    The factory (`pytest_configure`) resolves and injects the Config, so the
    collector itself is unit-testable without a live pytest session.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._failures: list[FailureContext] = []

    def pytest_exception_interact(
        self,
        call: pytest.CallInfo[object],
        report: pytest.TestReport | pytest.CollectReport,
    ) -> None:
        # Fires after the failing phase with both the report and the live
        # excinfo. logreport runs earlier and cannot give the exception type,
        # so collection happens here.
        if not isinstance(report, pytest.TestReport) or not report.failed:
            return
        excinfo = call.excinfo
        exc_type = excinfo.type.__name__ if excinfo is not None else None
        exc_message = safe_message(excinfo.value) if excinfo is not None else None
        self._failures.append(
            build_context(
                report,
                exc_type=exc_type,
                exc_message=exc_message,
                redact_mode=self._config.redact,
            )
        )

    def pytest_sessionfinish(self, session: pytest.Session) -> None:
        if hasattr(session.config, "workerinput"):
            return  # xdist worker: the controller aggregates and reports
        session.config.hook.pytest_triage_report(
            failures=list(self._failures),
            triage_config=self._config,
        )
