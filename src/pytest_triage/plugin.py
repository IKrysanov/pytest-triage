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

import contextlib
from collections import Counter
from typing import TYPE_CHECKING

import pytest

from pytest_triage import _hookspecs
from pytest_triage.config import Config
from pytest_triage.context import FailureContext, build_context, safe_message
from pytest_triage.report import _ReportWriter
from pytest_triage.verdict import Verdict
from pytest_triage.wrappers import build_triage_client, degraded_reason

if TYPE_CHECKING:
    from pytest_triage.providers.base import TriageClient


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
        help="Write the failure report to PATH (triage on defaults to .triage.json).",
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
    resolved = Config.from_config(config)
    _warn_if_triage_misconfigured(config, resolved)
    client = _build_triage_client_or_warn(config, resolved)
    config.pluginmanager.register(
        _TriagePlugin(resolved, client), name="pytest_triage_run"
    )
    if resolved.report is not None:
        _warn_if_report_incomplete_under_xdist(config)
        config.pluginmanager.register(
            _ReportWriter(resolved.report), name="pytest_triage_report_writer"
        )


def _warn_if_triage_misconfigured(config: pytest.Config, resolved: Config) -> None:
    """Warn on a triage/provider combination that silently produces no verdicts."""
    if resolved.triage and resolved.provider is None:
        config.issue_config_time_warning(
            pytest.PytestConfigWarning(
                "pytest-triage: --ai-triage=on but no --ai-provider is set; "
                "no verdicts will be produced."
            ),
            stacklevel=2,
        )
    elif resolved.provider is not None and not resolved.triage:
        config.issue_config_time_warning(
            pytest.PytestConfigWarning(
                f"pytest-triage: provider {resolved.provider!r} is configured but "
                "triage is off; pass --ai-triage=on to run it."
            ),
            stacklevel=2,
        )


def _build_triage_client_or_warn(
    config: pytest.Config, resolved: Config
) -> TriageClient | None:
    """Build the triage client; on failure warn and disable triage, never abort
    (invariant 1)."""
    try:
        return build_triage_client(resolved)
    except Exception as exc:
        config.issue_config_time_warning(
            pytest.PytestConfigWarning(f"pytest-triage: triage disabled: {exc}"),
            stacklevel=2,
        )
        return None


def _warn_if_report_incomplete_under_xdist(config: pytest.Config) -> None:
    """Warn on an xdist controller: worker failures aren't aggregated (0.1.0)."""
    if hasattr(config, "workerinput") or not config.getoption("numprocesses", None):
        return
    config.issue_config_time_warning(
        pytest.PytestConfigWarning(
            "pytest-triage: the failure report does not aggregate xdist worker "
            "failures and will be empty under -n; run triage without xdist."
        ),
        stacklevel=2,
    )


class _TriagePlugin:
    """Private: per-run collector holding all mutable state (no module globals)."""

    def __init__(self, config: Config, client: TriageClient | None) -> None:
        self._config = config
        self._client = client
        self._failures: list[FailureContext] = []
        self._summary_counts: Counter[str] = Counter()
        self._triage_errors: list[str] = []

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
        verdicts = self._triage()
        session.config.hook.pytest_triage_report(
            failures=list(self._failures),
            verdicts=verdicts,
            triage_config=self._config,
        )

    def _triage(self) -> list[Verdict | None]:
        """Analyze every failure; always returns len(failures).

        Every call is fenced (wrappers + the inner try) so nothing escapes to
        change the run (invariant 1). The client is closed once, best-effort.
        """
        client = self._client
        if client is None:
            return [None] * len(self._failures)
        verdicts: list[Verdict | None] = []
        counts: Counter[str] = Counter()
        errors: list[str] = []
        try:
            for failure in self._failures:
                try:
                    verdict = client.analyze(failure)
                except Exception:  # guards a failure in the wrappers (invariant 1)
                    verdict = Verdict(
                        category="unknown",
                        hypothesis="triage failed",
                        confidence="low",
                    )
                    errors.append(verdict.hypothesis)
                verdicts.append(verdict)
                counts[verdict.category] += 1
                reason = degraded_reason(verdict)
                if reason is not None:
                    errors.append(reason)
        finally:
            with contextlib.suppress(Exception):
                client.close()
        self._summary_counts = counts
        self._triage_errors = errors
        return verdicts

    def pytest_terminal_summary(
        self, terminalreporter: pytest.TerminalReporter
    ) -> None:
        if self._summary_counts:
            summary = ", ".join(
                f"{count} {category}"
                for category, count in sorted(self._summary_counts.items())
            )
            terminalreporter.write_line(f"pytest-triage: {summary}")
        # Explain any degraded verdict (e.g. a bad key); deduplicated, non-fatal.
        for reason in dict.fromkeys(self._triage_errors):
            terminalreporter.write_line(f"pytest-triage: {reason}", yellow=True)
